import { Badge } from "@/components/ui/badge";
import type { AIStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const STYLES: Record<AIStatus, string> = {
  ANSWERED: "bg-emerald-100 text-emerald-700",
  SUCCESS: "bg-emerald-100 text-emerald-700",
  NO_ANSWER: "bg-slate-100 text-slate-600",
  NEEDS_INPUT: "bg-sky-100 text-sky-700",
  CONFIRMATION_REQUIRED: "bg-amber-100 text-amber-800",
  DENIED: "bg-rose-100 text-rose-700",
  BLOCKED: "bg-rose-100 text-rose-700",
  FAILED: "bg-orange-100 text-orange-700",
};

const LABELS: Record<AIStatus, string> = {
  ANSWERED: "Answered",
  SUCCESS: "Done",
  NO_ANSWER: "No answer",
  NEEDS_INPUT: "Needs input",
  CONFIRMATION_REQUIRED: "Confirm",
  DENIED: "Not permitted",
  BLOCKED: "Blocked",
  FAILED: "Failed",
};

export function StatusBadge({ status }: { status: string }) {
  const known = status as AIStatus;
  return <Badge className={cn(STYLES[known] ?? "bg-slate-100 text-slate-600")}>{LABELS[known] ?? status}</Badge>;
}
