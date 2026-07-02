import sys
import io
import logging

# Force UTF-8 encoding for Windows terminals to prevent 'charmap' codec errors
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Configure logging EARLY (before any other imports that may call logging)
# Direct all logs to stdout so they appear alongside print() in the terminal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] %(message)s',
    stream=sys.stdout,
    force=True  # Override any handlers set by imported libraries
)

from fastapi import FastAPI, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime

from config import settings
from routers import database, queries, sharing, llm_config, rbac, memories
from services.database import DatabaseService
from services.llm import LLMService
from services.sharing import SharingService
from services.billing.billing_service import BillingService
from services.mongodb import MongoDBService
from services.mem0_service import Mem0Service
from services.registry import service_registry
from schemas import HealthCheck
from dependencies import verify_token
# logging is already configured at the top of this file

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize services
    print("Initializing services...")
    
    db_service = DatabaseService()
    llm_service = LLMService()
    sharing_service = SharingService()
    billing_service = BillingService()
    mongodb_service = MongoDBService()
    mem0_service = Mem0Service()
    
    # Register services in the registry
    service_registry.set_db_service(db_service)
    service_registry.set_llm_service(llm_service)
    service_registry.set_sharing_service(sharing_service)
    service_registry.set_billing_service(billing_service)
    service_registry.set_mongodb_service(mongodb_service)
    service_registry.set_mem0_service(mem0_service)
    
    # Initialize Mem0
    try:
        mem0_service.initialize()
    except Exception as e:
        print(f"Mem0 initialization warning/error: {e}")

    # 2. Try to auto-connect to database
    if all([settings.db_host, settings.db_port, settings.db_name, settings.db_user]):
        try:
            print(f"Connecting to database {settings.db_name} at {settings.db_host}...")
            db_service.connect({
                "host": settings.db_host,
                "port": settings.db_port,
                "database": settings.db_name,
                "user": settings.db_user,
                "password": settings.db_password,
                "db_type": settings.db_type
            })
            print("Database connected successfully")
        except Exception as e:
            print(f"Database auto-connection failed: {e}")

    # Try to configure LLM from environment variables
    import os
    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
    
    if api_key and api_key.strip():
        try:
            print(f"Auto-Configuring LLM (Primary key detected: {api_key[:10]}...)")
            # Use direct configuration to avoid the overhead/latency of the test-ping during startup
            llm_service.configure(
                api_key=api_key,
                base_url=settings.openai_api_base or os.getenv("OPENAI_API_BASE"),
                model=settings.llm_model_name,
                validate_key=False  # Bypass validation for instant startup
            )
            print(f"✓ LLM configured successfully (Model: {settings.llm_model_name})")
        except Exception as e:
            print(f"✗ LLM auto-configuration failed: {e}")
    else:
        print("✗ No OpenAI API key found in environment variables or .env file.")
    
    print("Services initialized successfully")
    yield
    
    # Shutdown: Clean up resources
    print("Shutting down services...")
    service_registry.cleanup()
    print("Services shut down successfully")

app = FastAPI(
    title=settings.app_title,
    description=settings.app_description,
    version=settings.app_version,
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers with token verification
app.include_router(database.router, dependencies=[Depends(verify_token)])
app.include_router(queries.router, dependencies=[Depends(verify_token)])
app.include_router(sharing.router, dependencies=[Depends(verify_token)])
app.include_router(llm_config.router, dependencies=[Depends(verify_token)])
app.include_router(rbac.router, dependencies=[Depends(verify_token)])
app.include_router(memories.router, dependencies=[Depends(verify_token)])

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Database Query API", "version": settings.app_version}

@app.get("/health", response_model=HealthCheck, tags=["health"])
async def health_check():
    """Health check endpoint"""
    try:
        db_service = service_registry.get_db_service()
        llm_service = service_registry.get_llm_service()
        mongodb_service = service_registry.get_mongodb_service()
        
        return HealthCheck(
            status="healthy",
            database_connected=db_service.is_connected(),
            llm_configured=llm_service.is_configured(),
            mongodb_connected=mongodb_service.is_connected(),
            timestamp=datetime.now()
        )
    except Exception:
        return HealthCheck(
            status="unhealthy",
            database_connected=False,
            llm_configured=False,
            mongodb_connected=False,
            timestamp=datetime.now()
        )

@app.get("/config", tags=["config"])
async def get_configuration():
    """Get current configuration (without sensitive data)"""
    try:
        db_service = service_registry.get_db_service()
        llm_service = service_registry.get_llm_service()
        return {
            "db_host": settings.db_host,
            "db_port": settings.db_port,
            "db_name": settings.db_name,
            "db_user": settings.db_user,
            "openai_api_base": settings.openai_api_base,
            "model_name": settings.llm_model_name,
            "db_connected": db_service.is_connected(),
            "llm_configured": llm_service.is_configured()
        }
    except Exception:
        return {
            "db_host": settings.db_host,
            "db_port": settings.db_port,
            "db_name": settings.db_name,
            "db_user": settings.db_user,
            "openai_api_base": settings.openai_api_base,
            "model_name": settings.llm_model_name,
            "db_connected": False,
            "llm_configured": False
        }

def load_page_to_tables() -> dict:
    import os
    import json
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        json_path = os.path.join(base_dir, "page_to_tables.json")
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to load page_to_tables.json: {e}")
        return {}

PAGE_TO_TABLES = load_page_to_tables()

def resolve_allowed_tables(allowed_pages: list) -> list:
    if "ALL_ACCESS" in allowed_pages:
        return ["*"]
    tables = set()
    for page in allowed_pages:
        tables.update(PAGE_TO_TABLES.get(page, []))
    return sorted(tables)

@app.api_route("/push-db-roles", methods=["GET", "POST"], tags=["rbac"])
async def push_db_roles():
    mem0_service = service_registry.get_mem0_service()
    if not mem0_service or not mem0_service.is_ready():
        return {"status": "error", "message": "Mem0 not ready"}
        
    try:
        mem0_service.invalidate_cache()
        return {
            "status": "success",
            "message": "RBAC cache invalidated. Permissions will be resolved dynamically from the database."
        }
    except Exception as err:
        return {"status": "error", "message": f"Cache invalidation failed: {str(err)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)