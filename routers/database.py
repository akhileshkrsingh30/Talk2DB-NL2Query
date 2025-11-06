from fastapi import APIRouter, Depends, HTTPException, status
from typing import Annotated
from pydantic import BaseModel, Field
from typing import Optional, Dict
from datetime import datetime
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from schemas import DatabaseConnection, ConnectionResponse, DatabaseSchema, ErrorResponse, SQLBatchRequest, SQLBatchResult
from services.database import DatabaseService, convert_realdict_to_dict
from services.llm import LLMService
from dependencies import get_db_service, get_llm_service

router = APIRouter(prefix="/database", tags=["database"])

class LLMConfigRequest(BaseModel):
    api_key: str = Field(..., description="API key for LLM service")
    api_base: str = Field("https://cloud.olakrutrim.com/v1", description="API base URL")
    model: str = Field("Llama-3.3-70B-Instruct", description="Model name")
    headers: Optional[Dict[str, str]] = Field(None, description="Optional extra headers to send to the provider")

@router.post("/connect", response_model=ConnectionResponse, responses={400: {"model": ErrorResponse}})
async def connect_to_database(
    connection: DatabaseConnection,
    db_service: Annotated[DatabaseService, Depends(get_db_service)]
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
            return ConnectionResponse(
                status="success",
                message="Connected to database successfully",
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
    db_service: Annotated[DatabaseService, Depends(get_db_service)]
):
    """Disconnect from database"""
    db_service.disconnect()
    return {"message": "Disconnected from database"}

@router.get("/schema", response_model=DatabaseSchema, responses={400: {"model": ErrorResponse}})
async def get_database_schema(
    db_service: Annotated[DatabaseService, Depends(get_db_service)]
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
    db_service: Annotated[DatabaseService, Depends(get_db_service)]
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
            message="Database is not connected"
        )

@router.post("/test-llm-connection", response_model=dict)
async def test_llm_connection(
    config: LLMConfigRequest,
    llm_service: Annotated[LLMService, Depends(get_llm_service)]
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
    llm_service: Annotated[LLMService, Depends(get_llm_service)]
):
    """Configure the LLM service"""
    try:
        # Reset any existing configuration first
        llm_service.reset_configuration()
        
        success = llm_service.configure(
            api_key=config.api_key,
            base_url=config.api_base,
            model=config.model,
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
    llm_service: Annotated[LLMService, Depends(get_llm_service)]
):
    """Get current LLM configuration status"""
    return {
        "configured": llm_service.is_configured(),
        "config_details": llm_service.get_config_details(),
        "status": "configured" if llm_service.is_configured() else "not_configured"
    }

@router.post("/execute-sql-batch", response_model=SQLBatchResult, responses={400: {"model": ErrorResponse}})
async def execute_sql_batch(
    batch: SQLBatchRequest,
    db_service: Annotated[DatabaseService, Depends(get_db_service)]
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