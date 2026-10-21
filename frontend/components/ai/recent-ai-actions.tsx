import { StatusBadge } from "@/components/ai/status-badge";
import type { AIAuditItem } from "@/lib/api";

export function RecentAIActions({ items }: { items: AIAuditItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No AI activity yet.</p>;
  }
  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li key={item.id} className="rounded-md border border-border bg-white p-3">
          <div className="flex items-center justify-between gap-2">
            <StatusBadge status={item.action_status ?? "UNKNOWN"} />
            <span className="text-[11px] text-slate-400">
              {item.created_at ? new Date(item.created_at.endsWith("Z") ? item.created_at : `${item.created_at}Z`).toLocaleString() : ""}
            </span>
          </div>
          <p className="mt-1.5 line-clamp-2 text-xs text-slate-700">{item.message}</p>
          <p className="mt-1 text-[11px] text-slate-400">
            {item.intent ?? "—"}
            {item.tool_name ? ` · ${item.tool_name}` : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}
