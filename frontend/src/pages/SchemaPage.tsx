import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { ResultTable } from "../components/ResultTable";
import { SchemaGraphView } from "../components/SchemaGraphView";
import type { QueryResultRow, SchemaTable } from "../api/types";

const PAGE_SIZE = 50;

export function SchemaPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [tables, setTables] = useState<string[]>([]);
  const [tablesError, setTablesError] = useState<string | null>(null);
  const [loadingTables, setLoadingTables] = useState(true);

  const [selectedTable, setSelectedTable] = useState<string | null>(searchParams.get("table"));
  const [rows, setRows] = useState<QueryResultRow[]>([]);
  const [offset, setOffset] = useState(0);
  const [rowCount, setRowCount] = useState(0);
  const [loadingRows, setLoadingRows] = useState(false);
  const [rowsError, setRowsError] = useState<string | null>(null);

  const [schemaText, setSchemaText] = useState<string | null>(null);
  const [showRawSchema, setShowRawSchema] = useState(false);

  const [view, setView] = useState<"list" | "graph">("list");
  const [graphTables, setGraphTables] = useState<SchemaTable[] | null>(null);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [loadingGraph, setLoadingGraph] = useState(false);

  useEffect(() => {
    setLoadingTables(true);
    api.database
      .tables()
      .then((res) => setTables(res.tables))
      .catch((err) => setTablesError(err instanceof ApiError ? err.message : "Failed to load tables"))
      .finally(() => setLoadingTables(false));
  }, []);

  useEffect(() => {
    if (!selectedTable) return;
    setLoadingRows(true);
    setRowsError(null);
    api.database
      .tableData(selectedTable, PAGE_SIZE, offset)
      .then((res) => {
        setRows(res.data);
        setRowCount(res.count);
      })
      .catch((err) => setRowsError(err instanceof ApiError ? err.message : "Failed to load table data"))
      .finally(() => setLoadingRows(false));
  }, [selectedTable, offset]);

  useEffect(() => {
    if (view !== "graph" || graphTables !== null) return;
    setLoadingGraph(true);
    setGraphError(null);
    api.database
      .schemaGraph()
      .then((res) => setGraphTables(res.tables))
      .catch((err) => setGraphError(err instanceof ApiError ? err.message : "Failed to load schema graph"))
      .finally(() => setLoadingGraph(false));
  }, [view, graphTables]);

  function selectTable(t: string) {
    setSelectedTable(t);
    setOffset(0);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("table", t);
      return next;
    });
  }

  function loadRawSchema() {
    setShowRawSchema(true);
    if (schemaText !== null) return;
    api.database
      .schema()
      .then((res) => setSchemaText(res.schema_info))
      .catch((err) => setSchemaText(err instanceof ApiError ? err.message : "Failed to load schema"));
  }

  return (
    <div className="flex h-full gap-6 p-6">
      <aside className="w-64 shrink-0 overflow-auto rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">Tables ({tables.length})</h2>
          <button onClick={loadRawSchema} className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400">
            Raw schema
          </button>
        </div>
        {loadingTables && <p className="text-sm text-slate-400">Loading…</p>}
        {tablesError && <p className="text-sm text-red-600 dark:text-red-400">{tablesError}</p>}
        <ul className="space-y-0.5">
          {tables.map((t) => (
            <li key={t}>
              <button
                onClick={() => selectTable(t)}
                className={`w-full truncate rounded-md px-2 py-1.5 text-left text-sm ${
                  selectedTable === t
                    ? "bg-blue-50 font-medium text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                    : "text-slate-600 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800"
                }`}
                title={t}
              >
                {t}
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <div className="flex-1 overflow-auto">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex rounded-lg border border-slate-300 bg-white p-1 text-sm dark:border-slate-700 dark:bg-slate-900">
            <button
              className={`rounded-md px-3 py-1 font-medium ${
                view === "list" ? "bg-blue-600 text-white" : "text-slate-600 dark:text-slate-300"
              }`}
              onClick={() => setView("list")}
            >
              List
            </button>
            <button
              className={`rounded-md px-3 py-1 font-medium ${
                view === "graph" ? "bg-blue-600 text-white" : "text-slate-600 dark:text-slate-300"
              }`}
              onClick={() => setView("graph")}
            >
              Graph
            </button>
          </div>
        </div>

        {showRawSchema && (
          <div className="mb-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">Raw schema</h2>
              <button
                onClick={() => setShowRawSchema(false)}
                className="text-xs text-slate-500 hover:underline dark:text-slate-400"
              >
                Close
              </button>
            </div>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
              {schemaText ?? "Loading…"}
            </pre>
          </div>
        )}

        {view === "graph" ? (
          <div>
            {loadingGraph && <p className="text-sm text-slate-400">Loading schema graph…</p>}
            {graphError && <p className="text-sm text-red-600 dark:text-red-400">{graphError}</p>}
            {graphTables && <SchemaGraphView tables={graphTables} />}
          </div>
        ) : !selectedTable ? (
          <p className="text-sm text-slate-400 dark:text-slate-500">Select a table on the left to preview its data.</p>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">{selectedTable}</h2>
              <div className="flex items-center gap-2 text-sm">
                <button
                  disabled={offset === 0 || loadingRows}
                  onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                  className="rounded-md border border-slate-300 px-2 py-1 disabled:opacity-40 dark:border-slate-700"
                >
                  Prev
                </button>
                <span className="text-slate-500 dark:text-slate-400">
                  {offset + 1}–{offset + rows.length} of {rowCount === PAGE_SIZE ? `${rowCount}+` : rowCount}
                </span>
                <button
                  disabled={rows.length < PAGE_SIZE || loadingRows}
                  onClick={() => setOffset((o) => o + PAGE_SIZE)}
                  className="rounded-md border border-slate-300 px-2 py-1 disabled:opacity-40 dark:border-slate-700"
                >
                  Next
                </button>
              </div>
            </div>
            {loadingRows && <p className="text-sm text-slate-400">Loading…</p>}
            {rowsError && <p className="text-sm text-red-600 dark:text-red-400">{rowsError}</p>}
            {!loadingRows && !rowsError && <ResultTable rows={rows} />}
          </div>
        )}
      </div>
    </div>
  );
}
