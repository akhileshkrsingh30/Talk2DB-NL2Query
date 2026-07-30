// Types mirroring backend/schemas.py

export type DbType = "postgresql" | "mysql" | "mariadb" | "mssql" | "oracle" | "sqlserver";

export interface DatabaseConnectionRequest {
  host: string;
  port: string;
  database?: string;
  user: string;
  password: string;
  db_type?: string;
}

export interface ConnectionResponse {
  status: string;
  message: string;
  version?: string | null;
  details?: Record<string, string> | null;
}

export interface DatabaseSchema {
  schema_info: string;
}

export interface SchemaColumn {
  name: string;
  type: string;
  nullable: boolean;
  is_primary_key: boolean;
}

export interface SchemaForeignKey {
  column: string;
  referred_table: string;
  referred_schema: string;
}

export interface SchemaTable {
  name: string;
  schema: string;
  columns: SchemaColumn[];
  foreign_keys: SchemaForeignKey[];
  estimated_rows: number;
}

export interface SchemaGraph {
  database: string;
  tables: SchemaTable[];
  error?: string;
}

export interface HealthCheck {
  status: string;
  database_connected: boolean;
  llm_configured: boolean;
  mongodb_connected: boolean;
  timestamp: string;
  database_name?: string | null;
  db_type?: string | null;
  db_host?: string | null;
  llm_model?: string | null;
}

export interface SQLQuery {
  sql: string;
  order: number;
}

export type QueryResultRow = Record<string, unknown>;

export interface QueryResult {
  session_id: string;
  message_id: string;
  company_id: string;
  query: string;
  sql_queries: SQLQuery[];
  results: (QueryResultRow[] | QueryResultRow)[];
  explanation: string;
  timestamp: string;
  execution_time?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
  billing?: Record<string, unknown> | null;
  user_id?: string | null;
  task_id?: number | null;
}

export interface QueryRequest {
  session_id?: string;
  message_id?: string;
  company_id?: string;
  query: string;
  max_tokens?: number;
  temperature?: number;
  user_id?: string;
  task_id?: number;
}

export interface ShareRequest {
  expiry_hours?: number;
}

export interface ShareResponse {
  share_id: string;
  share_url: string;
  expires_at: string;
}

export interface SharedResultMetadata {
  id: string;
  created_at: string;
  expires_at: string;
  access_count: number;
  last_accessed?: string | null;
  query: string;
  sql_queries_count: number;
}

export interface SharedResult {
  metadata: SharedResultMetadata;
  result: QueryResult;
}

// MongoDB

export interface MongoDBConnectionRequest {
  host: string;
  port?: string;
  database?: string;
  username?: string;
  password?: string;
  auth_source?: string;
  auth_mechanism?: string;
}

export interface MongoDBConnectionResponse {
  status: string;
  message: string;
  server_info?: Record<string, unknown> | null;
  details?: Record<string, string> | null;
}

export interface MongoDBDatabaseList {
  status: string;
  databases: string[];
  count: number;
}

export interface MongoDBCollectionList {
  status: string;
  collections: string[];
  count: number;
  database: string;
}

export interface MongoDBQueryResult {
  query: string;
  mongo_query: Record<string, unknown>;
  results: QueryResultRow[];
  result_count: number;
  explanation: string;
  collection: string;
  database: string;
  timestamp: string;
  execution_time?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
  user_id?: string | null;
  session_id?: string | null;
}

// LLM config

export interface LLMConfigRequest {
  api_key?: string;
  api_base?: string;
  model?: string;
}

export interface LLMConfigResponse {
  status: string;
  message: string;
  model: string;
}

// Streaming (NDJSON) events, shared shape for SQL + Mongo streams

export type StreamEvent =
  | { type: "status"; content: string }
  | { type: "sql"; content: SQLQuery[] }
  | { type: "mongo_query"; content: Record<string, unknown> }
  | { type: "results"; content: (QueryResultRow[] | QueryResultRow)[]; count?: number }
  | { type: "explanation_start" }
  | { type: "explanation_chunk"; content: string }
  | { type: "metadata"; [key: string]: unknown }
  | { type: "error"; content: string };

export interface ApiErrorBody {
  detail?: string;
  error?: string;
  details?: string;
}
