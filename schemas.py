from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from datetime import datetime

class DatabaseConnection(BaseModel):
    host: str = Field(..., description="Database host address")
    port: str = Field(..., description="Database port")
    database: Optional[str] = Field(None, description="Database name")
    user: str = Field(..., description="Database username")
    password: str = Field(..., description="Database password")

class DatabaseSelect(BaseModel):
    database: str = Field(..., description="Database name to switch to")

class ConnectionResponse(BaseModel):
    status: str = Field(..., description="Connection status")
    message: str = Field(..., description="Detailed message")
    version: Optional[str] = Field(None, description="Database version if connected")
    details: Optional[Dict[str, str]] = Field(None, description="Connection details")

class QueryRequest(BaseModel):
    query: str = Field(..., description="Natural language query")
    max_tokens: Optional[int] = Field(1024, description="Maximum tokens for LLM response")
    temperature: Optional[float] = Field(0.0, description="Temperature for LLM generation")
    user_id: Optional[str] = Field(None, description="Optional user identifier")
    session_id: Optional[str] = Field(None, description="Optional session identifier")

class SQLQuery(BaseModel):
    sql: str = Field(..., description="Generated SQL query")
    order: int = Field(..., description="Execution order")

class QueryResult(BaseModel):
    query: str = Field(..., description="Original natural language query")
    sql_queries: List[SQLQuery] = Field(..., description="Generated SQL queries")
    results: List[Union[List[Dict[str, Any]], Dict[str, Any]]] = Field(..., description="Query execution results")
    explanation: str = Field(..., description="Natural language explanation of results")
    timestamp: datetime = Field(..., description="When the query was executed")
    execution_time: Optional[float] = Field(None, description="Execution time in seconds")
    input_tokens: Optional[int] = Field(None, description="Number of input tokens")
    output_tokens: Optional[int] = Field(None, description="Number of output tokens")
    total_tokens: Optional[int] = Field(None, description="Total number of tokens used")
    billing: Optional[Dict[str, Any]] = Field(None, description="Billing and cost information")
    user_id: Optional[str] = Field(None, description="User identifier from request")
    session_id: Optional[str] = Field(None, description="Session identifier from request")
    
    class Config:
        # Allow any additional fields that might come from the database
        extra = "allow"
        # Custom JSON encoder for datetime and other types
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

class ErrorResponse(BaseModel):
    error: str = Field(..., description="Error message")
    details: Optional[str] = Field(None, description="Detailed error information")

class DatabaseSchema(BaseModel):
    schema_info: str = Field(..., description="Database schema information")

class HealthCheck(BaseModel):
    status: str = Field(..., description="API status")
    database_connected: bool = Field(..., description="Database connection status")
    llm_configured: bool = Field(..., description="LLM configuration status")
    mongodb_connected: bool = Field(..., description="MongoDB connection status")
    timestamp: datetime = Field(..., description="Check timestamp")

class ShareRequest(BaseModel):
    expiry_hours: Optional[int] = Field(24, description="Hours until the shared result expires", ge=1, le=168)

class ShareResponse(BaseModel):
    share_id: str = Field(..., description="Unique identifier for the shared result")
    share_url: str = Field(..., description="URL to access the shared result")
    expires_at: datetime = Field(..., description="When the shared result expires")

class SharedResultMetadata(BaseModel):
    id: str = Field(..., description="Share ID")
    created_at: datetime = Field(..., description="When the result was shared")
    expires_at: datetime = Field(..., description="When the share expires")
    access_count: int = Field(..., description="Number of times accessed")
    last_accessed: Optional[datetime] = Field(None, description="Last access time")
    query: str = Field(..., description="Original query")
    sql_queries_count: int = Field(..., description="Number of SQL queries")

class SharedResult(BaseModel):
    metadata: SharedResultMetadata = Field(..., description="Metadata about the shared result")
    result: QueryResult = Field(..., description="The actual query result")

class BatchQueryRequest(BaseModel):
    queries: List[QueryRequest]
    parallel: Optional[bool] = Field(False, description="Execute multiple natural language queries in parallel")
    max_concurrency: Optional[int] = Field(5, description="Maximum parallel workers", ge=1, le=32)

class BatchQueryResult(BaseModel):
    results: List[QueryResult]
    timestamp: datetime
    execution_time: Optional[float] = None

class SQLBatchRequest(BaseModel):
    queries: List[str]
    parallel: Optional[bool] = Field(True, description="Execute SQL queries in parallel when not using transaction")
    max_concurrency: Optional[int] = Field(5, description="Maximum parallel workers", ge=1, le=32)
    transaction: Optional[bool] = Field(False, description="Execute all queries sequentially in a single transaction")

class SQLBatchItem(BaseModel):
    sql: str
    order: int
    result: Union[List[Dict[str, Any]], Dict[str, Any]]
    error: Optional[str] = None

class SQLBatchResult(BaseModel):
    results: List[SQLBatchItem]
    timestamp: datetime
    execution_time: Optional[float] = None