"use client";

import { CheckCircle2, ShieldAlert, Wrench } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { AIChatResponse } from "@/lib/api";

function toolLabel(tool: string): string {
  return tool.replace(/_/g, " ").replace(/^\w/, (char) => char.toUpperCase());
}

export function ActionResultCard({
  response,
  confirmationState,
  onConfirm,
  onCancel,
}: {
  response: AIChatResponse;
  confirmationState: "pending" | "confirmed" | "cancelled" | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const needsConfirmation = response.status === "CONFIRMATION_REQUIRED" && response.confirmation;
  return (
    <div className="mt-3 rounded-md border border-border bg-slate-50 p-3 text-xs text-slate-700">
      {response.tool ? (
        <p className="flex items-center gap-1.5 font-medium text-slate-600">
          <Wrench className="h-3.5 w-3.5" />
          Backend API tool: {toolLabel(response.tool)}
        </p>
      ) : null}
      {response.status === "SUCCESS" ? (
        <p className="mt-1 flex items-center gap-1.5 text-emerald-700">
          <CheckCircle2 className="h-3.5 w-3.5" /> Completed through the HRMS API with your permissions.
        </p>
      ) : null}
      {response.status === "DENIED" ? (
        <p className="mt-1 flex items-center gap-1.5 text-rose-700">
          <ShieldAlert className="h-3.5 w-3.5" /> No action was taken.
        </p>
      ) : null}
      {response.notes && response.notes.length > 0 ? <p className="mt-1 text-slate-500">{response.notes.join(" ")}</p> : null}
      {needsConfirmation ? (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {confirmationState === "pending" || confirmationState === null ? (
            <>
              <Button size="sm" onClick={onConfirm}>
                Confirm
              </Button>
              <Button size="sm" variant="outline" onClick={onCancel}>
                Cancel
              </Button>
              <span className="text-slate-500">Expires in {Math.round((response.confirmation?.expires_in_seconds ?? 0) / 60)} min</span>
            </>
          ) : (
            <span className="text-slate-500">{confirmationState === "confirmed" ? "Confirmed." : "Cancelled — nothing was changed."}</span>
          )}
        </div>
      ) : null}
    </div>
  );
}
