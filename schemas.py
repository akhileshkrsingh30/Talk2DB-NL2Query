from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Union
from datetime import datetime

class DatabaseConnection(BaseModel):
    host: str = Field(..., description="Database host address")
    port: str = Field(..., description="Database port")
    database: Optional[str] = Field(None, description="Database name (optional)")
    user: Optional[str] = Field(None, description="Database username")
    password: Optional[str] = Field(None, description="Database password")
    db_type: Optional[str] = Field("postgresql", description="Database type (postgresql, mysql, mariadb, mssql, oracle, mongodb)")
    auth_source: Optional[str] = Field("admin", description="MongoDB authentication database (default: admin)")
    auth_mechanism: Optional[str] = Field(None, description="MongoDB authentication mechanism (optional)")

class DatabaseSelect(BaseModel):
    database: Optional[str] = Field(None, description="Database name to switch to")
    collection: Optional[str] = Field(None, description="Collection name to switch to (MongoDB only)")

class ConnectionResponse(BaseModel):
    status: str = Field(..., description="Connection status")
    message: str = Field(..., description="Detailed message")
    version: Optional[str] = Field(None, description="Database version if connected")
    details: Optional[Dict[str, str]] = Field(None, description="Connection details")

from uuid import uuid4

class QueryRequest(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique session identifier")
    message_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique message identifier")
    company_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique company identifier")
    query: str = Field(..., description="Natural language query")
    max_tokens: Optional[int] = Field(1024, description="Maximum tokens for LLM response")
    temperature: Optional[float] = Field(0.0, description="Temperature for LLM generation")
    user_id: Optional[str] = Field(None, description="Optional user identifier")
    task_id: Optional[int] = Field(None, description="Optional task ID to restrict query execution to the tables mapped to this task")
    explain: Optional[bool] = Field(True, description="Whether to generate a natural language explanation of results")

class SQLQuery(BaseModel):
    sql: str = Field(..., description="Generated SQL query")
    order: int = Field(..., description="Execution order")

class QueryResult(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    message_id: str = Field(..., description="Unique message identifier")
    company_id: str = Field(..., description="Unique company identifier")
    query: str = Field(..., description="Original natural language query")
    sql_queries: Optional[List[SQLQuery]] = Field(None, description="Generated SQL queries")
    mongo_query: Optional[Dict[str, Any]] = Field(None, description="Generated MongoDB query")
    results: List[Union[List[Dict[str, Any]], Dict[str, Any]]] = Field(..., description="Query execution results")
    explanation: Optional[str] = Field(None, description="Natural language explanation of results")
    timestamp: datetime = Field(..., description="When the query was executed")
    execution_time: Optional[float] = Field(None, description="Execution time in seconds")
    input_tokens: Optional[int] = Field(None, description="Number of input tokens")
    output_tokens: Optional[int] = Field(None, description="Number of output tokens")
    total_tokens: Optional[int] = Field(None, description="Total number of tokens used")
    billing: Optional[Dict[str, Any]] = Field(None, description="Billing and cost information")
    user_id: Optional[str] = Field(None, description="User identifier from request")
    task_id: Optional[int] = Field(None, description="Optional task ID associated with the query")
    
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
    task_id: Optional[int] = Field(None, description="Optional top-level task ID to apply to all queries in the batch")

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

# ============================================================================
# MongoDB Schemas
# ============================================================================

class MongoDBConnection(BaseModel):
    host: str = Field(..., description="MongoDB host address")
    port: str = Field("27017", description="MongoDB port (default: 27017)")
    database: Optional[str] = Field(None, description="Database name (optional, defaults to 'admin' if not provided)")
    username: Optional[str] = Field(None, description="MongoDB username (optional)")
    password: Optional[str] = Field(None, description="MongoDB password (optional)")
    auth_source: Optional[str] = Field("admin", description="Authentication database (default: admin)")
    auth_mechanism: Optional[str] = Field(None, description="Authentication mechanism (e.g., SCRAM-SHA-256)")

class MongoDBSelect(BaseModel):
    database: str = Field(..., description="Database name to switch to")

class MongoDBCollectionSelect(BaseModel):
    collection: str = Field(..., description="Collection name to switch to")

class MongoDBConnectionResponse(BaseModel):
    status: str = Field(..., description="Connection status")
    message: str = Field(..., description="Detailed message")
    server_info: Optional[Dict[str, Any]] = Field(None, description="MongoDB server information")
    details: Optional[Dict[str, str]] = Field(None, description="Connection details")

class MongoDBDatabaseList(BaseModel):
    status: str = Field(..., description="Status of the operation")
    databases: List[str] = Field(..., description="List of database names")
    count: int = Field(..., description="Number of databases")

class MongoDBCollectionList(BaseModel):
    status: str = Field(..., description="Status of the operation")
    collections: List[str] = Field(..., description="List of collection names")
    count: int = Field(..., description="Number of collections")
    database: str = Field(..., description="Current database name")

class MongoDBQueryRequest(BaseModel):
    query: str = Field(..., description="Natural language query for MongoDB")
    max_tokens: Optional[int] = Field(1024, description="Maximum tokens for LLM response")
    temperature: Optional[float] = Field(0.0, description="Temperature for LLM generation")
    session_id: Optional[str] = Field(None, description="Optional session identifier")
    explain: Optional[bool] = Field(True, description="Whether to return a natural language explanation alongside the results")

class MongoDBQueryResult(BaseModel):
    query: str = Field(..., description="Original natural language query")
    mongo_query: Dict[str, Any] = Field(..., description="Generated MongoDB query")
    results: List[Dict[str, Any]] = Field(..., description="Query execution results")
    result_count: int = Field(..., description="Number of results returned")
    explanation: Optional[str] = Field(None, description="Natural language explanation of results")
    collection: str = Field(..., description="Collection queried")
    database: str = Field(..., description="Database queried")
    timestamp: datetime = Field(..., description="When the query was executed")
    execution_time: Optional[float] = Field(None, description="Execution time in seconds")
    input_tokens: Optional[int] = Field(None, description="Number of input tokens")
    output_tokens: Optional[int] = Field(None, description="Number of output tokens")
    total_tokens: Optional[int] = Field(None, description="Total number of tokens used")
    user_id: Optional[str] = Field(None, description="User identifier")
    session_id: Optional[str] = Field(None, description="Session identifier")

    class Config:
        extra = "allow"
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

# ============================================================================
# RBAC Schemas
# ============================================================================

class UserPolicyRequest(BaseModel):
    username: str = Field(..., description="Target user identifier (email/username)")
    role: str = Field("standard", description="User role (standard, manager, admin)")
    department: str = Field(..., description="User department")
    restricted_tables: List[str] = Field(default_factory=list, description="List of table names user is restricted from querying")

class UserPolicyRawRequest(BaseModel):
    username: Optional[str] = Field(None, description="Target user identifier (optional if agent_id is provided)")
    agent_id: Optional[str] = Field(None, description="Target agent identifier (optional if username is provided)")
    memory: str = Field(..., description="Raw natural language policy memory to store")

class UserPolicyResponse(BaseModel):
    username: str = Field(..., description="Target user identifier")
    resolved_permissions: Dict[str, Any] = Field(..., description="Parsed permissions rules currently active for the user")

class MemoryStoreRequest(BaseModel):
    content: str = Field(..., description="The content/text data to store in memory")
    user_id: Optional[str] = Field(None, description="The user identifier to associate the memory with")
    agent_id: Optional[str] = Field(None, description="The agent identifier to associate the memory with")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional key-value metadata to store with the memory")

class MemoriesRequest(BaseModel):
    task_id: int = Field(..., description="The ID of the task")
    tables: List[str] = Field(..., description="List of tables associated with the task")