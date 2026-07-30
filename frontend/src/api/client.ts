import type {
  ApiErrorBody,
  ConnectionResponse,
  DatabaseConnectionRequest,
  DatabaseSchema,
  HealthCheck,
  LLMConfigRequest,
  LLMConfigResponse,
  MongoDBCollectionList,
  MongoDBConnectionRequest,
  MongoDBConnectionResponse,
  MongoDBDatabaseList,
  MongoDBQueryResult,
  QueryRequest,
  QueryResult,
  SchemaGraph,
  ShareRequest,
  ShareResponse,
  SharedResult,
  SharedResultMetadata,
} from "./types";

const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") || "/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("talk2db_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(init?.headers || {}),
    },
  });

  if (!res.ok) {
    let message = `Request failed with status ${res.status}`;
    try {
      const body = (await res.json()) as ApiErrorBody;
      message = body.detail || body.error || message;
    } catch {
      // response wasn't JSON; keep the default message
    }
    throw new ApiError(res.status, message);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

function get<T>(path: string): Promise<T> {
  return request<T>(path, { method: "GET" });
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
}

function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

export const api = {
  health: () => get<HealthCheck>("/health"),

  database: {
    connect: (payload: DatabaseConnectionRequest) => post<ConnectionResponse>("/database/connect", payload),
    disconnect: () => post<{ message: string }>("/database/disconnect"),
    list: () => get<{ status: string; databases: string[]; count: number }>("/database/list"),
    select: (database: string) => post<ConnectionResponse>("/database/select", { database }),
    status: () => get<ConnectionResponse>("/database/status"),
    schema: () => get<DatabaseSchema>("/database/schema"),
    schemaGraph: () => get<SchemaGraph>("/database/schema-graph"),
    tables: (taskId?: number) =>
      get<{ status: string; database: string | null; tables: string[]; count: number }>(
        `/database/tables${taskId != null ? `?task_id=${taskId}` : ""}`,
      ),
    tableData: (tableName: string, limit = 100, offset = 0) =>
      get<{ status: string; table: string; count: number; limit: number; offset: number; data: Record<string, unknown>[] }>(
        `/database/tables/${encodeURIComponent(tableName)}/data?limit=${limit}&offset=${offset}`,
      ),
  },

  mongodb: {
    connect: (payload: MongoDBConnectionRequest) => post<MongoDBConnectionResponse>("/mongodb/connect", payload),
    disconnect: () => post<{ message: string }>("/mongodb/disconnect"),
    list: () => get<MongoDBDatabaseList>("/mongodb/list"),
    select: (database: string) => post<MongoDBConnectionResponse>("/mongodb/select", { database }),
    collections: () => get<MongoDBCollectionList>("/mongodb/collections"),
    selectCollection: (collection: string) =>
      post<{ status: string; message: string; database: string; collection: string }>("/mongodb/select-collection", {
        collection,
      }),
    status: () => get<MongoDBConnectionResponse>("/mongodb/status"),
    schema: () => get<{ status: string; schema: unknown }>("/mongodb/schema"),
    process: (payload: { query: string; max_tokens?: number; temperature?: number; session_id?: string }) =>
      post<MongoDBQueryResult>("/mongodb/process", payload),
  },

  llm: {
    configure: (payload: LLMConfigRequest) => post<LLMConfigResponse>("/llm/configure", payload),
    status: () => get<LLMConfigResponse>("/llm/status"),
  },

  queries: {
    process: (payload: QueryRequest) => post<QueryResult>("/queries/process", payload),
    checkPrerequisites: () =>
      get<{
        status: string;
        database_connected: boolean;
        llm_configured: boolean;
        issues: string[];
        ready_for_queries: boolean;
      }>("/queries/check-prerequisites"),
    history: (params?: { limit?: number; session_id?: string; task_id?: number; user_id?: string }) => {
      const search = new URLSearchParams();
      if (params?.limit != null) search.set("limit", String(params.limit));
      if (params?.session_id) search.set("session_id", params.session_id);
      if (params?.task_id != null) search.set("task_id", String(params.task_id));
      if (params?.user_id) search.set("user_id", params.user_id);
      const qs = search.toString();
      return get<QueryResult[]>(`/queries/history${qs ? `?${qs}` : ""}`);
    },
    clearHistory: () => del<{ message: string }>("/queries/history"),
    shareByIndex: (index: number, payload: ShareRequest) =>
      post<ShareResponse>(`/queries/${index}/share`, payload),
  },

  sharing: {
    get: (shareId: string) => get<SharedResult>(`/sharing/${shareId}`),
    list: (limit = 50) => get<SharedResultMetadata[]>(`/sharing/?limit=${limit}`),
    delete: (shareId: string) => del<{ message: string }>(`/sharing/${shareId}`),
    create: (result: QueryResult, expiryHours = 24) =>
      post<ShareResponse>("/sharing/", { result, expiry_hours: expiryHours }),
  },
};

export function streamPath(mode: "sql" | "mongo") {
  return mode === "sql" ? "/queries/stream" : "/mongodb/stream";
}

export async function streamQuery(
  mode: "sql" | "mongo",
  payload: QueryRequest | { query: string; max_tokens?: number; temperature?: number; session_id?: string },
  onLine: (line: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE_URL}${streamPath(mode)}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
    },
    body: JSON.stringify(payload),
    signal,
  });

  if (!res.ok || !res.body) {
    let message = `Stream request failed with status ${res.status}`;
    try {
      const body = (await res.json()) as ApiErrorBody;
      message = body.detail || body.error || message;
    } catch {
      // ignore
    }
    throw new ApiError(res.status, message);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.trim()) onLine(line);
    }
  }
  if (buffer.trim()) onLine(buffer);
}
