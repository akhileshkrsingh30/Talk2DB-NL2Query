import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { ShareChannelLinks } from "../components/ShareChannelLinks";
import { SqlResultSets } from "../components/SqlResultSets";
import type { SharedResult } from "../api/types";

export function SharedResultPage() {
  const { shareId } = useParams<{ shareId: string }>();
  const [data, setData] = useState<SharedResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!shareId) return;
    setLoading(true);
    api.sharing
      .get(shareId)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load shared result"))
      .finally(() => setLoading(false));
  }, [shareId]);

  return (
    <div className="mx-auto min-h-screen max-w-3xl bg-white px-6 py-10 dark:bg-slate-950">
      <Link to="/" className="text-sm font-medium text-blue-600 hover:underline dark:text-blue-400">
        &larr; Talk2DB
      </Link>

      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        {loading && <p className="text-sm text-slate-400">Loading…</p>}
        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        {data && (
          <div className="space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100">{data.result.query}</h1>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Shared {new Date(data.metadata.created_at).toLocaleString()} · Expires{" "}
                  {new Date(data.metadata.expires_at).toLocaleString()} · {data.metadata.access_count} view
                  {data.metadata.access_count === 1 ? "" : "s"}
                </p>
              </div>
              <ShareChannelLinks url={typeof window !== "undefined" ? window.location.href : ""} text={data.result.query} />
            </div>
            <SqlResultSets sqlQueries={data.result.sql_queries} results={data.result.results} />
            {data.result.explanation && (
              <p className="whitespace-pre-wrap text-sm text-slate-700 dark:text-slate-300">{data.result.explanation}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
