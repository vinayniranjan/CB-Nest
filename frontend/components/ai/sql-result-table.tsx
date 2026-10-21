"use client";

import { useState } from "react";

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function formatHeader(column: string): string {
  return column.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function SqlResultTable({
  columns,
  rows,
  truncated,
  sql,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
  truncated?: boolean;
  sql?: string | null;
}) {
  const [showSql, setShowSql] = useState(false);
  return (
    <div className="mt-3 space-y-2">
      {rows.length > 0 ? (
        <div className="max-h-80 overflow-auto rounded-md border border-border">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-slate-100 text-slate-600">
              <tr>
                {columns.map((column) => (
                  <th key={column} className="whitespace-nowrap px-3 py-2 font-semibold">
                    {formatHeader(column)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index} className="border-t border-border odd:bg-white even:bg-slate-50/60">
                  {columns.map((column) => (
                    <td key={column} className="max-w-xs truncate px-3 py-1.5 text-slate-700" title={formatCell(row[column])}>
                      {formatCell(row[column])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500">
        <span>
          {rows.length} row{rows.length === 1 ? "" : "s"}
          {truncated ? " (limited — refine your question to narrow results)" : ""}
        </span>
        {sql ? (
          <button type="button" className="text-indigo-600 hover:underline" onClick={() => setShowSql((prev) => !prev)}>
            {showSql ? "Hide SQL" : "View SQL"}
          </button>
        ) : null}
      </div>
      {sql && showSql ? (
        <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-slate-900 p-3 text-xs text-slate-100">{sql}</pre>
      ) : null}
    </div>
  );
}
