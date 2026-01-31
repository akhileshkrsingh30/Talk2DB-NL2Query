from fastapi import FastAPI, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime

from config import settings
from routers import database, queries, sharing
from services.database import DatabaseService
from services.llm import LLMService
from services.sharing import SharingService
from services.billing.billing_service import BillingService
from services.registry import service_registry
from schemas import HealthCheck

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize services
    print("Initializing services...")
    
    db_service = DatabaseService()
    llm_service = LLMService()
    sharing_service = SharingService()
    billing_service = BillingService()
    
    # Register services in the registry
    service_registry.set_db_service(db_service)
    service_registry.set_llm_service(llm_service)
    service_registry.set_sharing_service(sharing_service)
    service_registry.set_billing_service(billing_service)
    
    # Try to configure LLM from environment variables
    if settings.krutim_cloud_api_key and settings.krutim_cloud_api_key.strip():
        try:
            print("Configuring LLM from environment variables (Krutim)...")
            llm_service.configure(
                api_key=settings.krutim_cloud_api_key,
                base_url=settings.openai_api_base,
                model=settings.llm_model_name
            )
            print("LLM configured successfully from environment variables")
        except Exception as e:
            print(f"LLM configuration failed: {e}")
            print("LLM can be configured later using the /database/configure-llm endpoint")
    elif settings.openai_api_key and settings.openai_api_key.strip():
        try:
            print("Configuring LLM from environment variables (OpenAI)...")
            llm_service.configure(
                api_key=settings.openai_api_key,
                base_url=settings.openai_api_base,
                model=settings.llm_model_name
            )
            print("LLM configured successfully from environment variables")
        except Exception as e:
            print(f"LLM configuration failed: {e}")
            print("LLM can be configured later using the /database/configure-llm endpoint")
    else:
        print("No API key found in environment. LLM can be configured using the /database/configure-llm endpoint")
    
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(database.router)
app.include_router(queries.router)
app.include_router(sharing.router)

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "Database Query API", "version": settings.app_version}

@app.get("/health", response_model=HealthCheck, tags=["health"])
async def health_check():
    """Health check endpoint"""
    try:
        db_service = service_registry.get_db_service()
        llm_service = service_registry.get_llm_service()
        
        return HealthCheck(
            status="healthy",
            database_connected=db_service.is_connected(),
            llm_configured=llm_service.is_configured(),
            timestamp=datetime.now()
        )
    except Exception:
        return HealthCheck(
            status="unhealthy",
            database_connected=False,
            llm_configured=False,
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)