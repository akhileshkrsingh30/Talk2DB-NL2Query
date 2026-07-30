import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { ShareChannelLinks } from "../components/ShareChannelLinks";
import type { SharedResultMetadata } from "../api/types";

export function SharingPage() {
  const [items, setItems] = useState<SharedResultMetadata[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  function load() {
    setLoading(true);
    setError(null);
    api.sharing
      .list()
      .then(setItems)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load shared results"))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function handleDelete(id: string) {
    await api.sharing.delete(id);
    load();
  }

  function handleCopy(id: string) {
    const url = `${window.location.origin}/share/${id}`;
    navigator.clipboard.writeText(url).catch(() => {});
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 1500);
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4 p-6">
      <div>
        <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">Shared results</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Links generated from the chat or history pages, valid until they expire.
        </p>
      </div>

      {loading && <p className="text-sm text-slate-400">Loading…</p>}
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {!loading && !error && items.length === 0 && (
        <p className="text-sm text-slate-400 dark:text-slate-500">No shared results yet.</p>
      )}

      <div className="space-y-2">
        {items.map((item) => (
          <div
            key={item.id}
            className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-900"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">{item.query}</p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Created {new Date(item.created_at).toLocaleString()} · Expires {new Date(item.expires_at).toLocaleString()} ·{" "}
                {item.access_count} view{item.access_count === 1 ? "" : "s"}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <ShareChannelLinks url={`${window.location.origin}/share/${item.id}`} text={item.query} />
              <Link
                to={`/share/${item.id}`}
                className="rounded-lg border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                Open
              </Link>
              <button
                onClick={() => handleCopy(item.id)}
                className="rounded-lg border border-slate-300 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                {copiedId === item.id ? "Copied!" : "Copy link"}
              </button>
              <button
                onClick={() => handleDelete(item.id)}
                className="rounded-lg border border-red-200 px-3 py-1 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950"
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
