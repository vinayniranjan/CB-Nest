"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Bot, Loader2, SendHorizonal, User } from "lucide-react";

import { ActionResultCard } from "@/components/ai/action-result-card";
import { SourceList } from "@/components/ai/source-list";
import { SqlResultTable } from "@/components/ai/sql-result-table";
import { StatusBadge } from "@/components/ai/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { AIChatResponse, AIEndpoint, sendAIMessage } from "@/lib/api";

type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
  response?: AIChatResponse;
  error?: boolean;
  confirmation?: "pending" | "confirmed" | "cancelled" | null;
};

const INTENT_LABELS: Record<string, string> = {
  POLICY_QA: "HR Policy",
  SQL_QUERY: "People & Projects",
  HR_ACTION: "HR Task",
  UNKNOWN: "Guardrail",
};

const PLACEHOLDERS: Record<AIEndpoint, string> = {
  router: "Ask anything — policies, people & projects, or an HR task…",
  policy: "e.g. How many sick leaves can I take?",
  sql: "e.g. Which employees know Python and FastAPI?",
  actions: "e.g. Create a high-priority IT ticket for VPN not working",
};

function errorMessage(status: number, body: unknown): string {
  if (status === 429) return "You're sending requests too quickly. Please wait a minute.";
  const detail = (body as { detail?: { error?: { message?: string } } })?.detail;
  if (detail && typeof detail === "object" && detail.error?.message) return detail.error.message;
  if (status === 422) return "Please enter a message between 1 and 2000 characters.";
  return "The copilot is unavailable right now. Please try again.";
}

export function ChatPanel({
  token,
  endpoint,
  suggestions,
  onUnauthorized,
  onActivity,
}: {
  token: string;
  endpoint: AIEndpoint;
  suggestions: string[];
  onUnauthorized: () => void;
  onActivity: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const nextId = useRef(1);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  const push = (message: Omit<ChatMessage, "id">) => {
    const id = nextId.current++;
    setMessages((prev) => [...prev, { ...message, id }]);
    return id;
  };

  const send = async (text: string, target: AIEndpoint, confirmationToken?: string) => {
    setLoading(true);
    try {
      const result = await sendAIMessage(token, target, text, confirmationToken);
      if (result.status === 401) return onUnauthorized();
      if (!result.ok || !("success" in result.body) || !result.body.success) {
        push({ role: "assistant", text: errorMessage(result.status, result.body), error: true });
        return;
      }
      const response = result.body.data;
      push({
        role: "assistant",
        text: response.answer,
        response,
        confirmation: response.status === "CONFIRMATION_REQUIRED" ? "pending" : null,
      });
      onActivity();
    } catch {
      push({ role: "assistant", text: "Network error — check your connection and try again.", error: true });
    } finally {
      setLoading(false);
    }
  };

  const onSubmit = async (event?: FormEvent) => {
    event?.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    push({ role: "user", text });
    await send(text, endpoint);
  };

  const setConfirmation = (id: number, state: "confirmed" | "cancelled") =>
    setMessages((prev) => prev.map((message) => (message.id === id ? { ...message, confirmation: state } : message)));

  const onConfirm = async (message: ChatMessage) => {
    const token = message.response?.confirmation?.token;
    if (!token || loading) return;
    setConfirmation(message.id, "confirmed");
    push({ role: "user", text: "Confirm" });
    await send("confirm", "actions", token);
  };

  const onCancel = (message: ChatMessage) => {
    setConfirmation(message.id, "cancelled");
    push({ role: "assistant", text: "Okay, I cancelled that. Nothing was changed." });
  };

  return (
    <div className="flex h-[640px] flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto rounded-md border border-border bg-slate-50/50 p-4" aria-live="polite">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
            <Bot className="h-10 w-10 text-indigo-400" />
            <p className="max-w-md text-sm text-slate-500">
              Answers come only from the HR policy library and the HR data you are allowed to see. Actions run through
              the HRMS with your permissions.
            </p>
            <div className="flex max-w-2xl flex-wrap justify-center gap-2">
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="rounded-full border border-border bg-white px-3 py-1.5 text-xs text-slate-600 hover:border-indigo-300 hover:text-indigo-700"
                  onClick={() => setInput(suggestion)}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {messages.map((message) => (
          <div
            key={message.id}
            className={message.role === "user" ? "flex justify-end" : "flex justify-start"}
            data-testid={`ai-message-${message.role}`}
            data-status={message.response?.status ?? (message.error ? "ERROR" : "")}
            data-intent={message.response?.intent ?? ""}
          >
            <div
              className={
                message.role === "user"
                  ? "flex max-w-[80%] items-start gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-sm text-white"
                  : `max-w-[90%] rounded-xl border px-4 py-3 text-sm ${message.error ? "border-rose-200 bg-rose-50 text-rose-800" : "border-border bg-white text-slate-800"}`
              }
            >
              {message.role === "user" ? (
                <>
                  <span className="whitespace-pre-wrap">{message.text}</span>
                  <User className="mt-0.5 h-4 w-4 shrink-0 opacity-70" />
                </>
              ) : (
                <>
                  {message.response ? (
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <StatusBadge status={message.response.status} />
                      <span>{INTENT_LABELS[message.response.intent] ?? message.response.intent}</span>
                      <span>· {message.response.latency_ms} ms</span>
                    </div>
                  ) : null}
                  <p className="whitespace-pre-wrap leading-relaxed">{message.text}</p>
                  {message.response?.intent === "POLICY_QA" && message.response.sources ? (
                    <SourceList sources={message.response.sources} />
                  ) : null}
                  {message.response?.intent === "SQL_QUERY" && message.response.status === "ANSWERED" ? (
                    <SqlResultTable
                      columns={message.response.columns ?? []}
                      rows={message.response.rows ?? []}
                      truncated={message.response.truncated}
                      sql={message.response.sql}
                    />
                  ) : null}
                  {message.response?.intent === "HR_ACTION" ? (
                    <ActionResultCard
                      response={message.response}
                      confirmationState={message.confirmation ?? null}
                      onConfirm={() => onConfirm(message)}
                      onCancel={() => onCancel(message)}
                    />
                  ) : null}
                </>
              )}
            </div>
          </div>
        ))}

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-slate-500" data-testid="ai-loading">
            <Loader2 className="h-4 w-4 animate-spin" /> Checking permissions and working on it…
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>

      <form className="mt-3 flex gap-2" onSubmit={onSubmit}>
        <Input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={PLACEHOLDERS[endpoint]}
          maxLength={2000}
          disabled={loading}
          aria-label="Message the HR copilot"
        />
        <Button type="submit" disabled={loading || !input.trim()}>
          <SendHorizonal className="mr-1.5 h-4 w-4" /> Send
        </Button>
      </form>
    </div>
  );
}
