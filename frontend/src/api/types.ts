// Shared API types for the Talk2DB frontend.
// NOTE: frontend/src/lib/localHistory.ts already imports QueryResult/QueryResultRow/SQLQuery
// from this path but the file didn't exist in this workspace — added here so it resolves.
// Mirrors schemas.py::QueryRequest / QueryResult on the backend.

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
  /** If true, backend includes a condensed summary of prior turns in this session_id. */
  use_chat_history?: boolean;
  /** How many prior turns to consider when use_chat_history is true (1-10). */
  history_limit?: number;
  /** If false, backend skips natural-language explanation generation to save tokens. */
  include_explanation?: boolean;
}
