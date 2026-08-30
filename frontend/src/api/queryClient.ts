import type { QueryRequest, QueryResult } from "./types";
import { applyQuerySettings } from "../lib/querySettings";

// See frontend/.env — VITE_API_URL defaults to "/api" (dev-server proxy to the backend).
const API_BASE = import.meta.env.VITE_API_URL ?? "/api";

/**
 * Submit a natural language query, merging in the current session's
 * chat-history / history-depth / explanation settings (see QueryHistorySettings.tsx).
 * Replace the auth header wiring below with whatever this app already uses.
 */
export async function runQuery(
  base: Omit<QueryRequest, "use_chat_history" | "history_limit" | "include_explanation">,
  authToken: string
): Promise<QueryResult> {
  const sessionId = base.session_id ?? crypto.randomUUID();
  const body = applyQuerySettings(sessionId, { ...base, session_id: sessionId });

  const response = await fetch(`${API_BASE}/queries/process`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${authToken}`,
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => response.statusText);
    throw new Error(`Query failed (${response.status}): ${detail}`);
  }

  return response.json() as Promise<QueryResult>;
}
