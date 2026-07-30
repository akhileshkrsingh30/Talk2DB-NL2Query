import type { QueryResultRow, SQLQuery } from "../api/types";
import { ResultTable } from "./ResultTable";

interface SqlResultSetsProps {
  sqlQueries?: SQLQuery[];
  results?: (QueryResultRow[] | QueryResultRow)[];
}

/**
 * A long/complex question can be broken into multiple SQL statements, each with its own
 * result set (a list of rows, or a single status dict for non-SELECT statements). Rendering
 * one query paired with its own table — instead of flattening every statement's rows into a
 * single table — avoids mixing columns from unrelated result sets together.
 */
export function SqlResultSets({ sqlQueries, results }: SqlResultSetsProps) {
  const queries = sqlQueries ?? [];
  const sets = results ?? [];
  const count = Math.max(queries.length, sets.length);

  if (count === 0) return null;

  return (
    <div className="space-y-4">
      {Array.from({ length: count }, (_, i) => {
        const query = queries[i];
        const resultSet = sets[i];
        const rows = resultSet == null ? undefined : Array.isArray(resultSet) ? resultSet : [resultSet];
        return (
          <div key={i} className="space-y-2">
            {count > 1 && (
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Query {i + 1}
              </p>
            )}
            {query && (
              <pre className="overflow-auto rounded-xl bg-slate-900 p-3 text-xs text-slate-100">{query.sql}</pre>
            )}
            {rows && <ResultTable rows={rows} />}
          </div>
        );
      })}
    </div>
  );
}
