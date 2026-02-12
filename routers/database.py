from fastapi import APIRouter, Depends, HTTPException, status
from typing import Annotated
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import settings
from schemas import DatabaseConnection, DatabaseSelect, ConnectionResponse, DatabaseSchema, ErrorResponse, SQLBatchRequest, SQLBatchResult
from services.database import DatabaseService, convert_realdict_to_dict
from services.llm import LLMService
from dependencies import get_db_service, get_llm_service, verify_token

router = APIRouter(prefix="/database", tags=["database"])

class LLMConfigRequest(BaseModel):
    api_key: Optional[str] = Field(None, description="API key for LLM service (falls back to .env if not provided)")
    api_base: Optional[str] = Field(None, description="API base URL (falls back to .env if not provided)")
    model: Optional[str] = Field(None, description="Model name (falls back to .env if not provided)")
    headers: Optional[Dict[str, str]] = Field(None, description="Optional extra headers to send to the provider")

@router.post("/connect", response_model=ConnectionResponse, responses={400: {"model": ErrorResponse}})
async def connect_to_database(
    connection: DatabaseConnection,
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Connect to a PostgreSQL database"""
    try:
        connection_params = {
            "host": connection.host,
            "port": connection.port,
            "database": connection.database,
            "user": connection.user,
            "password": connection.password
        }
        
        success = db_service.connect(connection_params)
        
        if success:
            # When database connects, also ensure LLM is configured if it isn't already
            if not llm_service.is_configured():
                api_key = settings.krutim_cloud_api_key or settings.openai_api_key
                if api_key and api_key.strip():
                    try:
                        llm_service.configure(
                            api_key=api_key,
                            base_url=settings.openai_api_base or (None if settings.openai_api_key else "https://api.krutim.ai/v1"),
                            model=settings.llm_model_name,
                            validate_key=False
                        )
                    except Exception as e:
                        print(f"Automatic LLM configuration failed during DB connect: {e}")

            return ConnectionResponse(
                status="success",
                message="Connected to database successfully (and LLM configured)",
                version=db_service.get_db_version(),
                details={
                    "host": connection.host,
                    "database": connection.database,
                    "user": connection.user
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to connect to database"
            )
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/disconnect", response_model=dict)
async def disconnect_database(
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Disconnect from database"""
    db_service.disconnect()
    return {"message": "Disconnected from database"}

@router.get("/list", response_model=Dict[str, Any])
async def list_databases(
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """List all databases available on the server"""
    try:
        databases = db_service.get_databases()
        return {
            "status": "success",
            "databases": databases
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/select", response_model=ConnectionResponse)
async def select_database(
    selection: DatabaseSelect,
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Switch to a specific database after listing them"""
    try:
        success = db_service.select_database(selection.database)
        if success:
            params = db_service.get_connection_params()
            return ConnectionResponse(
                status="success",
                message=f"Switched to database '{selection.database}' successfully",
                version=db_service.get_db_version(),
                details={
                    "host": params["host"],
                    "database": params["database"],
                    "user": params["user"]
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to switch to database '{selection.database}'"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.get("/schema", response_model=DatabaseSchema, responses={400: {"model": ErrorResponse}})
async def get_database_schema(
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Get database schema information"""
    try:
        if not db_service.is_connected():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Database not connected"
            )
        
        db = db_service.get_langchain_db()
        schema_info = db.get_table_info()
        
        return DatabaseSchema(schema_info=schema_info)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to get schema: {str(e)}"
        )

@router.get("/status", response_model=ConnectionResponse)
async def get_database_status(
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Get current database connection status"""
    if db_service.is_connected():
        params = db_service.get_connection_params()
        return ConnectionResponse(
            status="connected",
            message="Database is connected",
            version=db_service.get_db_version(),
            details={
                "host": params["host"],
                "port": params["port"],
                "database": params["database"],
                "user": params["user"]
            } if params else None
        )
    else:
        return ConnectionResponse(
            status="disconnected",
            message=f"Database is not connected. (Configured for {settings.db_host or 'none'})"
        )

@router.post("/test-llm-connection", response_model=dict)
async def test_llm_connection(
    config: LLMConfigRequest,
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Test LLM connection without configuring the service"""
    try:
        # Test the API key
        is_valid = llm_service.test_api_key(config.api_key, config.api_base, config.headers)
        
        if is_valid:
            return {
                "status": "success",
                "message": "API key is valid and connection successful",
                "api_base": config.api_base,
                "model": config.model,
                "details": llm_service.last_error
            }
        else:
            return {
                "status": "failed",
                "message": "API key is invalid or connection failed",
                "api_base": config.api_base,
                "model": config.model,
                "details": llm_service.last_error
            }
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connection test failed: {str(e)}"
        )

@router.post("/configure-llm", response_model=dict)
async def configure_llm(
    config: LLMConfigRequest,
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Configure the LLM service"""
    try:
        # Reset any existing configuration first
        llm_service.reset_configuration()
        
        # Use provided value or fall back to settings
        api_key = config.api_key or settings.krutim_cloud_api_key or settings.openai_api_key
        api_base = config.api_base or settings.openai_api_base
        model = config.model or settings.llm_model_name
        
        success = llm_service.configure(
            api_key=api_key,
            base_url=api_base,
            model=model,
            headers=config.headers
        )
        
        if success:
            return {
                "status": "success",
                "message": "LLM configured successfully",
                "model": config.model,
                "api_base": config.api_base,
                "configured": llm_service.is_configured(),
                "config_details": llm_service.get_config_details()
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to configure LLM"
            )
    except ValueError as e:
        if "Invalid API key" in str(e):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Authentication failed: {str(e)}"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Configuration error: {str(e)}"
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"LLM configuration failed: {str(e)}"
        )

@router.get("/llm-status", response_model=dict)
async def get_llm_status(
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Get current LLM configuration status"""
    details = llm_service.get_config_details() or {}
    return {
        "configured": llm_service.is_configured(),
        "config_details": details,
        "model": details.get("model", settings.llm_model_name),
        "status": "configured" if llm_service.is_configured() else "not_configured"
    }

@router.post("/execute-sql-batch", response_model=SQLBatchResult, responses={400: {"model": ErrorResponse}})
async def execute_sql_batch(
    batch: SQLBatchRequest,
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    try:
        if not db_service.is_connected():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Database not connected"
            )

        start_time = time.time()

        if batch.transaction:
            items = []
            # Single transaction: sequential execution
            try:
                with db_service.create_connection() as conn:
                    with conn.cursor() as cursor:
                        for idx, sql in enumerate(batch.queries):
                            try:
                                cursor.execute(sql)
                                if sql.strip().lower().startswith("select"):
                                    rows = cursor.fetchall()
                                    result = convert_realdict_to_dict(rows)
                                else:
                                    result = {
                                        "status": "Command executed successfully",
                                        "rows_affected": cursor.rowcount,
                                        "query": sql.strip()
                                    }
                                items.append({
                                    "sql": sql,
                                    "order": idx,
                                    "result": result,
                                    "error": None
                                })
                            except Exception as e:
                                conn.rollback()
                                items.append({
                                    "sql": sql,
                                    "order": idx,
                                    "result": {},
                                    "error": str(e)
                                })
                                break
                        else:
                            conn.commit()
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"SQL batch execution (transaction) failed: {str(e)}"
                )
        else:
            if batch.parallel:
                max_workers = batch.max_concurrency or 5
                results = [None] * len(batch.queries)

                def run_sql(index: int, sql: str):
                    try:
                        res = db_service.execute_query(sql)
                        return {
                            "sql": sql,
                            "order": index,
                            "result": res,
                            "error": None
                        }
                    except Exception as e:
                        return {
                            "sql": sql,
                            "order": index,
                            "result": {},
                            "error": str(e)
                        }

                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_map = {
                        executor.submit(run_sql, idx, sql): idx
                        for idx, sql in enumerate(batch.queries)
                    }
                    for future in as_completed(future_map):
                        idx = future_map[future]
                        results[idx] = future.result()
                items = results
            else:
                items = []
                for idx, sql in enumerate(batch.queries):
                    try:
                        result = db_service.execute_query(sql)
                        items.append({
                            "sql": sql,
                            "order": idx,
                            "result": result,
                            "error": None
                        })
                    except Exception as e:
                        items.append({
                            "sql": sql,
                            "order": idx,
                            "result": {},
                            "error": str(e)
                        })

        total_time = time.time() - start_time
        return SQLBatchResult(
            results=items,
            timestamp=datetime.now(),
            execution_time=total_time
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"SQL batch execution failed: {str(e)}"
        )