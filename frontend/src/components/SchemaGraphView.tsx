import { useMemo, useState } from "react";
import type { SchemaTable } from "../api/types";

const BOX_WIDTH = 220;
const GAP_X = 90;
const GAP_Y = 70;
const HEADER_H = 30;
const ROW_H = 18;
const MAX_ROWS_SHOWN = 8;
const PADDING = 40;

interface Positioned {
  table: SchemaTable;
  x: number;
  y: number;
  width: number;
  height: number;
}

function tableHeight(t: SchemaTable): number {
  const shown = Math.min(t.columns.length, MAX_ROWS_SHOWN);
  const extra = t.columns.length > MAX_ROWS_SHOWN ? 1 : 0;
  return HEADER_H + (shown + extra) * ROW_H + 10;
}

function layout(tables: SchemaTable[]) {
  const cols = Math.max(1, Math.ceil(Math.sqrt(tables.length)));
  const positions: Positioned[] = [];
  let col = 0;
  let x = PADDING;
  let y = PADDING;
  let rowMaxHeight = 0;

  for (const table of tables) {
    const height = tableHeight(table);
    positions.push({ table, x, y, width: BOX_WIDTH, height });
    rowMaxHeight = Math.max(rowMaxHeight, height);
    col++;
    if (col >= cols) {
      col = 0;
      x = PADDING;
      y += rowMaxHeight + GAP_Y;
      rowMaxHeight = 0;
    } else {
      x += BOX_WIDTH + GAP_X;
    }
  }

  const width = cols * BOX_WIDTH + (cols - 1) * GAP_X + PADDING * 2;
  const height = y + rowMaxHeight + PADDING;
  return { positions, width, height: Math.max(height, PADDING * 2 + tableHeight(tables[0] ?? { columns: [] } as unknown as SchemaTable)) };
}

export function SchemaGraphView({ tables }: { tables: SchemaTable[] }) {
  const [hovered, setHovered] = useState<string | null>(null);
  const { positions, width, height } = useMemo(() => layout(tables), [tables]);

  const byName = useMemo(() => {
    const map = new Map<string, Positioned>();
    for (const p of positions) map.set(p.table.name.toLowerCase(), p);
    return map;
  }, [positions]);

  if (tables.length === 0) {
    return <p className="text-sm text-slate-400 dark:text-slate-500">No tables to display.</p>;
  }

  const edges: { key: string; x1: number; y1: number; x2: number; y2: number; label: string; from: string; to: string }[] = [];
  for (const p of positions) {
    for (const fk of p.table.foreign_keys) {
      const target = byName.get(fk.referred_table.toLowerCase());
      if (!target || target === p) continue;
      const x1 = p.x + p.width / 2;
      const y1 = p.y + p.height / 2;
      const x2 = target.x + target.width / 2;
      const y2 = target.y + target.height / 2;
      edges.push({
        key: `${p.table.name}.${fk.column}->${fk.referred_table}`,
        x1,
        y1,
        x2,
        y2,
        label: fk.column,
        from: p.table.name,
        to: target.table.name,
      });
    }
  }

  return (
    <div className="overflow-auto rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <svg width={width} height={height} className="block">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="fill-slate-400 dark:fill-slate-500" />
          </marker>
        </defs>

        {edges.map((e) => {
          const active = hovered === e.from || hovered === e.to;
          return (
            <g key={e.key}>
              <line
                x1={e.x1}
                y1={e.y1}
                x2={e.x2}
                y2={e.y2}
                strokeWidth={active ? 2 : 1}
                markerEnd="url(#arrow)"
                className={active ? "stroke-blue-500" : "stroke-slate-300 dark:stroke-slate-700"}
              />
              <title>
                {e.from}.{e.label} → {e.to}
              </title>
            </g>
          );
        })}

        {positions.map((p) => {
          const shown = p.table.columns.slice(0, MAX_ROWS_SHOWN);
          const overflowCount = p.table.columns.length - shown.length;
          const isHovered = hovered === p.table.name;
          return (
            <g
              key={p.table.name}
              onMouseEnter={() => setHovered(p.table.name)}
              onMouseLeave={() => setHovered(null)}
              className="cursor-default"
            >
              <rect
                x={p.x}
                y={p.y}
                width={p.width}
                height={p.height}
                rx={8}
                className={
                  isHovered
                    ? "fill-blue-50 stroke-blue-500 dark:fill-slate-800 dark:stroke-blue-400"
                    : "fill-slate-50 stroke-slate-300 dark:fill-slate-800 dark:stroke-slate-700"
                }
                strokeWidth={isHovered ? 2 : 1}
              />
              <rect x={p.x} y={p.y} width={p.width} height={HEADER_H} rx={8} className="fill-slate-200 dark:fill-slate-700" />
              <rect x={p.x} y={p.y + HEADER_H / 2} width={p.width} height={HEADER_H / 2} className="fill-slate-200 dark:fill-slate-700" />
              <text
                x={p.x + 10}
                y={p.y + HEADER_H / 2 + 4}
                className="fill-slate-800 text-[12px] font-semibold dark:fill-slate-100"
              >
                {p.table.name}
              </text>
              <text
                x={p.x + p.width - 10}
                y={p.y + HEADER_H / 2 + 4}
                textAnchor="end"
                className="fill-slate-500 text-[10px] dark:fill-slate-400"
              >
                {p.table.estimated_rows.toLocaleString()} rows
              </text>
              {shown.map((col, i) => (
                <text
                  key={col.name}
                  x={p.x + 12}
                  y={p.y + HEADER_H + (i + 1) * ROW_H - 5}
                  className="fill-slate-600 text-[11px] dark:fill-slate-300"
                >
                  {col.is_primary_key ? "🔑 " : ""}
                  {col.name}
                  <tspan className="fill-slate-400 dark:fill-slate-500"> · {col.type}</tspan>
                </text>
              ))}
              {overflowCount > 0 && (
                <text
                  x={p.x + 12}
                  y={p.y + HEADER_H + (shown.length + 1) * ROW_H - 5}
                  className="fill-slate-400 text-[10px] italic dark:fill-slate-500"
                >
                  +{overflowCount} more
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
