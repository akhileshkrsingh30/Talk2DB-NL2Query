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
from services.mongodb import MongoDBService
from dependencies import get_db_service, get_llm_service, verify_token, get_mongodb_service

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
    mongodb_service: Annotated[MongoDBService, Depends(get_mongodb_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Connect to a PostgreSQL database"""
    try:
        # Log the incoming connection request (without password)
        print(f"Connection request - Host: {connection.host}, Port: {connection.port}, "
              f"Database: {connection.database}, User: {connection.user}")
        
        connection_params = {
            "host": connection.host,
            "port": connection.port,
            "database": connection.database,
            "user": connection.user,
            "password": connection.password,
            "db_type": connection.db_type or settings.db_type
        }
        
        success = db_service.connect(connection_params)
        
        if success:
            # When database connects, also ensure LLM is configured if it isn't already
            if not llm_service.is_configured():
                api_key = settings.openai_api_key
                if api_key and api_key.strip():
                    try:
                        llm_service.configure(
                            api_key=api_key,
                            base_url=settings.openai_api_base,
                            model=settings.llm_model_name,
                            validate_key=False
                        )
                    except Exception as e:
                        print(f"Automatic LLM configuration failed during DB connect: {e}")

            # NEW: Push schema to MongoDB on successful connection
            try:
                schema_dict = db_service.get_schema_dict()
                mongodb_service.push_postgres_schema(schema_dict)
            except Exception as e:
                print(f"Failed to auto-push schema to MongoDB: {e}")


            return ConnectionResponse(
                status="success",
                message="Connected to database successfully (and LLM configured)",
                version=db_service.get_db_version(),
                details={
                    "host": connection.host,
                    "database": connection.database or "postgres",
                    "user": connection.user
                }
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to connect to database"
            )
            
    except ValueError as e:
        # Validation errors (missing fields, invalid port, etc.)
        print(f"Validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Validation error: {str(e)}"
        )
    except ConnectionError as e:
        # Database connection errors
        print(f"Connection error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Connection error: {str(e)}"
        )
    except Exception as e:
        # Other unexpected errors
        print(f"Unexpected error during connection: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error: {str(e)}"
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
        # Check if connected first
        if not db_service.is_connected():
            print("Error: Attempted to list databases without being connected")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Database not connected. Please connect first using /database/connect endpoint (you can omit the 'database' field to connect to the default 'postgres' database)."
            )
        
        databases = db_service.get_databases()
        print(f"Successfully listed {len(databases)} databases")
        return {
            "status": "success",
            "databases": databases,
            "count": len(databases)
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        print(f"Runtime error listing databases: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        print(f"Unexpected error listing databases: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list databases: {str(e)}"
        )

@router.post("/select", response_model=ConnectionResponse)
async def select_database(
    selection: DatabaseSelect,
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    mongodb_service: Annotated[MongoDBService, Depends(get_mongodb_service)],
    current_user: Annotated[str, Depends(verify_token)]
):
    """Switch to a specific database after listing them"""
    try:
        success = db_service.select_database(selection.database)
        if success:
            # NEW: Push schema to MongoDB on successful selection
            try:
                schema_dict = db_service.get_schema_dict()
                mongodb_service.push_postgres_schema(schema_dict)
            except Exception as e:
                print(f"Failed to auto-push schema to MongoDB: {e}")


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
        
        schema_info = db_service.get_simplified_schema()
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

@router.get("/tables", response_model=Dict[str, Any], responses={400: {"model": ErrorResponse}})
async def list_tables(
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    current_user: Annotated[str, Depends(verify_token)],
    task_id: Optional[int] = None
):
    """List all tables in the currently connected database"""
    try:
        if not db_service.is_connected():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Database not connected. Please connect first using /database/connect endpoint."
            )
        
        tables = db_service.get_tables()
        params = db_service.get_connection_params()
        return {
            "status": "success",
            "database": params.get("database") if params else None,
            "tables": tables,
            "count": len(tables)
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list tables: {str(e)}"
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
        api_key = config.api_key or settings.openai_api_key
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
                                if sql.strip().lower().startswith(("select", "with", "show", "describe", "explain")):
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

@router.get("/tables/{table_name}/data", responses={400: {"model": ErrorResponse}, 403: {"model": ErrorResponse}})
async def get_table_data(
    table_name: str,
    db_service: Annotated[DatabaseService, Depends(get_db_service)],
    current_user: Annotated[str, Depends(verify_token)],
    limit: int = 100,
    offset: int = 0,
    task_id: Optional[str] = None
):
    """
    Fetch records/data from a specific database table.
    """
    if not db_service.is_connected():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Database not connected."
        )

    # 1. Resolve tables and check existence
    try:
        db_tables = db_service.get_tables()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch database tables: {str(e)}"
        )

    # Case-insensitive match to find the actual table name
    safe_table = None
    for t in db_tables:
        if t.lower() == table_name.lower():
            safe_table = t
            break

    if not safe_table:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Table '{table_name}' does not exist in the connected database."
        )

    # 4. Construct Dialect-Aware Query (fully safe as table name comes from get_tables())
    try:
        limit = max(1, min(limit, 1000)) # clamp between 1 and 1000
        offset = max(0, offset)

        if db_service.db_type == "mssql":
            if offset > 0:
                query = f"SELECT * FROM {safe_table} ORDER BY (SELECT NULL) OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"
            else:
                query = f"SELECT TOP {limit} * FROM {safe_table}"
        elif db_service.db_type == "oracle":
            query = f"SELECT * FROM {safe_table} OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"
        else: # postgresql / mysql default
            query = f"SELECT * FROM {safe_table} LIMIT {limit} OFFSET {offset}"

        data = db_service.execute_query(query)
        return {
            "status": "success",
            "table": safe_table,
            "count": len(data),
            "limit": limit,
            "offset": offset,
            "data": data
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch data: {str(e)}"
        )