import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api/client";
import { ResultTable } from "../components/ResultTable";
import { ShareChannelLinks } from "../components/ShareChannelLinks";
import { SqlResultSets } from "../components/SqlResultSets";
import { clearLocalHistory, getLocalHistory, removeLocalHistoryEntry, type LocalHistoryEntry } from "../lib/localHistory";
import type { QueryResult, QueryResultRow } from "../api/types";

const LIMIT_OPTIONS = [10, 20, 50, 100] as const;
type ViewMode = "table" | "nl" | "both";

function flattenResults(raw: QueryResult["results"]): QueryResultRow[] {
  const out: QueryResultRow[] = [];
  for (const item of raw ?? []) {
    if (Array.isArray(item)) out.push(...item);
    else if (item) out.push(item);
  }
  return out;
}

function mergeHistory(local: LocalHistoryEntry[], backend: QueryResult[]): LocalHistoryEntry[] {
  const byMessageId = new Map<string, LocalHistoryEntry>();
  for (const entry of local) byMessageId.set(entry.message_id, entry);
  for (const item of backend) {
    if (!byMessageId.has(item.message_id)) {
      byMessageId.set(item.message_id, { ...item, mode: "sql" });
    }
  }
  return Array.from(byMessageId.values()).sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
  );
}

export function HistoryPage() {
  const [limit, setLimit] = useState<number>(20);
  const [backendItems, setBackendItems] = useState<QueryResult[]>([]);
  const [backendNote, setBackendNote] = useState<string | null>(null);
  const [localItems, setLocalItems] = useState<LocalHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [shareResult, setShareResult] = useState<{ id: string; url?: string; error?: string } | null>(null);
  const [itemModes, setItemModes] = useState<Record<string, ViewMode>>({});

  function load() {
    setLoading(true);
    setLocalItems(getLocalHistory());
    api.queries
      .history({ limit: 200 })
      .then((items) => {
        setBackendItems(items);
        setBackendNote(null);
      })
      .catch((err) =>
        setBackendNote(
          err instanceof ApiError
            ? `Server-side history unavailable (${err.message}) — showing this browser's local history only.`
            : "Server-side history unavailable — showing this browser's local history only.",
        ),
      )
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  const merged = useMemo(() => mergeHistory(localItems, backendItems).slice(0, limit), [localItems, backendItems, limit]);

  async function handleClear() {
    clearLocalHistory();
    setLocalItems([]);
    try {
      await api.queries.clearHistory();
    } catch {
      // best-effort; server-side history may be unreachable
    }
    load();
  }

  function handleRemoveOne(messageId: string) {
    removeLocalHistoryEntry(messageId);
    setLocalItems(getLocalHistory());
    setBackendItems((items) => items.filter((i) => i.message_id !== messageId));
  }

  async function handleShare(entry: LocalHistoryEntry) {
    setShareResult(null);
    try {
      const res = await api.sharing.create(entry, 24);
      setShareResult({ id: entry.message_id, url: res.share_url });
    } catch (err) {
      setShareResult({ id: entry.message_id, error: err instanceof ApiError ? err.message : "Failed to share" });
    }
  }

  function setViewMode(id: string, mode: ViewMode) {
    setItemModes((prev) => ({ ...prev, [id]: mode }));
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4 p-6">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">Query history</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Recent natural language queries and their results, kept in this browser so it works even without a
            server-side history store.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <label className="text-sm text-slate-500 dark:text-slate-400">
            Show last{" "}
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100"
            >
              {LIMIT_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={handleClear}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Clear history
          </button>
        </div>
      </div>

      {loading && <p className="text-sm text-slate-400">Loading…</p>}
      {backendNote && <p className="text-xs text-amber-600 dark:text-amber-400">{backendNote}</p>}
      {!loading && merged.length === 0 && (
        <p className="text-sm text-slate-400 dark:text-slate-500">
          No history yet — questions you ask on the Chat page will show up here.
        </p>
      )}

      <div className="space-y-2">
        {merged.map((item) => {
          const id = item.message_id;
          const isOpen = expanded === id;
          const share = shareResult?.id === id ? shareResult : null;
          const currentMode = itemModes[id] ?? "table";

          return (
            <div
              key={id}
              className="rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
            >
              <button
                onClick={() => setExpanded(isOpen ? null : id)}
                className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium uppercase text-slate-500 dark:bg-slate-800 dark:text-slate-400">
                      {item.mode}
                    </span>
                    <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{item.query}</p>
                  </div>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {new Date(item.timestamp).toLocaleString()}
                    {item.execution_time != null && ` · ${item.execution_time.toFixed(2)}s`}
                    {item.total_tokens != null && ` · ${item.total_tokens} tokens`}
                  </p>
                </div>
                <span className="text-xs font-medium text-slate-500 dark:text-slate-400">{isOpen ? "Hide" : "Show"}</span>
              </button>
              {isOpen && (
                <div className="space-y-3.5 border-t border-slate-100 px-4 py-3.5 dark:border-slate-800">
                  {/* View Mode Toggle Switch */}
                  <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1 dark:border-slate-800 dark:bg-slate-950/60 w-fit">
                    <button
                      onClick={() => setViewMode(id, "table")}
                      className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-all ${
                        currentMode === "table"
                          ? "bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-slate-100"
                          : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
                      }`}
                    >
                      <span>📊</span> Table Response
                    </button>
                    <button
                      onClick={() => setViewMode(id, "nl")}
                      className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-all ${
                        currentMode === "nl"
                          ? "bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-slate-100"
                          : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
                      }`}
                    >
                      <span>💬</span> Natural Language Response
                    </button>
                    <button
                      onClick={() => setViewMode(id, "both")}
                      className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium transition-all ${
                        currentMode === "both"
                          ? "bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-slate-100"
                          : "text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"
                      }`}
                    >
                      <span>👁️</span> Both
                    </button>
                  </div>

                  {/* Render Table Content */}
                  {(currentMode === "table" || currentMode === "both") && (
                    <div className="space-y-2">
                      {item.mode === "mongo" ? (
                        <>
                          {item.mongo_query && (
                            <pre className="overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
                              {JSON.stringify(item.mongo_query, null, 2)}
                            </pre>
                          )}
                          <ResultTable rows={flattenResults(item.results)} />
                        </>
                      ) : (
                        <SqlResultSets sqlQueries={item.sql_queries} results={item.results} />
                      )}
                    </div>
                  )}

                  {/* Render Natural Language Explanation */}
                  {(currentMode === "nl" || currentMode === "both") && (
                    <div className="rounded-xl border border-slate-200/80 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-850/60">
                      <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1.5">
                        Natural Language Summary
                      </h4>
                      {item.explanation ? (
                        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800 dark:text-slate-200">
                          {item.explanation}
                        </p>
                      ) : (
                        <p className="text-xs italic text-slate-400 dark:text-slate-500">
                          No natural language response recorded for this query.
                        </p>
                      )}
                    </div>
                  )}

                  {/* Action Bar */}
                  <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-slate-100 dark:border-slate-800">
                    <button
                      onClick={() => handleShare(item)}
                      className="rounded-lg border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                    >
                      Share this result
                    </button>
                    <button
                      onClick={() => handleRemoveOne(id)}
                      className="rounded-lg border border-red-200 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950"
                    >
                      Remove
                    </button>
                    {share?.url && (
                      <>
                        <span className="truncate text-xs text-slate-500 dark:text-slate-400">{share.url}</span>
                        <ShareChannelLinks url={share.url} text={item.query} />
                      </>
                    )}
                    {share?.error && <span className="text-xs text-red-500 dark:text-red-400">{share.error}</span>}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
