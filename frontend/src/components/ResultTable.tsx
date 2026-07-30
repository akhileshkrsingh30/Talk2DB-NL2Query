import type { QueryResultRow } from "../api/types";

interface ResultTableProps {
  rows: QueryResultRow[];
  maxRows?: number;
}

export function ResultTable({ rows, maxRows = 200 }: ResultTableProps) {
  if (!rows || rows.length === 0) {
    return <p className="text-sm italic text-slate-500 dark:text-slate-400">No rows returned.</p>;
  }

  const columns = Array.from(
    rows.slice(0, 50).reduce((set, row) => {
      Object.keys(row ?? {}).forEach((k) => set.add(k));
      return set;
    }, new Set<string>()),
  );

  const shown = rows.slice(0, maxRows);

  return (
    <div className="overflow-auto rounded-lg border border-slate-200 dark:border-slate-700">
      <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-700">
        <thead className="sticky top-0 bg-slate-50 dark:bg-slate-800">
          <tr>
            {columns.map((col) => (
              <th
                key={col}
                className="whitespace-nowrap px-3 py-2 text-left font-semibold text-slate-600 dark:text-slate-300"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-900">
          {shown.map((row, i) => (
            <tr key={i} className="hover:bg-slate-50 dark:hover:bg-slate-800/60">
              {columns.map((col) => (
                <td
                  key={col}
                  className="max-w-xs truncate whitespace-nowrap px-3 py-2 text-slate-700 dark:text-slate-300"
                >
                  {formatCell(row?.[col])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > maxRows && (
        <div className="border-t border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400">
          Showing {maxRows} of {rows.length} rows
        </div>
      )}
    </div>
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
