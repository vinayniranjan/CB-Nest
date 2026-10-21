"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Database, ScrollText, Sparkles, Wand2 } from "lucide-react";

import { ChatPanel } from "@/components/ai/chat-panel";
import { RecentAIActions } from "@/components/ai/recent-ai-actions";
import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AIAuditItem, AICapabilities, AIEndpoint, fetchAIAudit, fetchAICapabilities, fetchProfile } from "@/lib/api";
import { cn } from "@/lib/utils";

const MODES: { endpoint: AIEndpoint; label: string; description: string; icon: typeof Sparkles }[] = [
  { endpoint: "router", label: "Ask Anything", description: "The copilot picks the right assistant for you.", icon: Sparkles },
  { endpoint: "policy", label: "Ask HR Policy", description: "Grounded answers from the HR policy library, with sources.", icon: ScrollText },
  { endpoint: "sql", label: "People & Projects", description: "Read-only answers from HR data you are allowed to see.", icon: Database },
  { endpoint: "actions", label: "Automate HR Task", description: "Apply leave, raise tickets and more through the HRMS.", icon: Wand2 },
];

export default function AICopilotPage() {
  const router = useRouter();
  const [name, setName] = useState("User");
  const [capabilities, setCapabilities] = useState<AICapabilities | null>(null);
  const [recent, setRecent] = useState<AIAuditItem[]>([]);
  const [endpoint, setEndpoint] = useState<AIEndpoint>("router");
  const [error, setError] = useState("");

  const token = useMemo(() => {
    if (typeof window === "undefined") return null;
    return localStorage.getItem("hrms_access_token");
  }, []);

  const clearAuthAndRedirect = useCallback(() => {
    localStorage.removeItem("hrms_access_token");
    document.cookie = "hrms_auth=; path=/; max-age=0; samesite=lax";
    router.push("/login");
  }, [router]);

  const loadRecent = useCallback(async () => {
    if (!token) return;
    const result = await fetchAIAudit(token, 8);
    if (result.ok && "success" in result.body && result.body.success) setRecent(result.body.data.items);
  }, [token]);

  useEffect(() => {
    if (!token) {
      clearAuthAndRedirect();
      return;
    }
    (async () => {
      try {
        const [profile, caps] = await Promise.all([fetchProfile(token), fetchAICapabilities(token)]);
        if (profile.status === 401 || caps.status === 401) return clearAuthAndRedirect();
        if (profile.ok && "success" in profile.body && profile.body.success) setName(profile.body.data.name);
        if (caps.ok && "success" in caps.body && caps.body.success) setCapabilities(caps.body.data);
        else setError("Failed to load copilot settings");
        await loadRecent();
      } catch {
        setError("Unable to reach the HRMS API");
      }
    })();
  }, [token, clearAuthAndRedirect, loadRecent]);

  const active = MODES.find((mode) => mode.endpoint === endpoint) ?? MODES[0];

  return (
    <main className="flex min-h-screen">
      <Sidebar />
      <section className="flex w-full flex-col">
        <Topbar name={name} title="AI Copilot" />
        <div className="grid gap-4 p-6 xl:grid-cols-[minmax(0,1fr)_320px]">
          <Card className="min-w-0">
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle className="flex items-center gap-2">
                    <Sparkles className="h-5 w-5 text-indigo-500" /> NovaWorks PeopleOps Copilot
                  </CardTitle>
                  <CardDescription>{active.description}</CardDescription>
                </div>
                {capabilities ? (
                  <span className="rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700 ring-1 ring-indigo-200">
                    {capabilities.mode}
                  </span>
                ) : null}
              </div>
              <div className="mt-3 flex flex-wrap gap-2" role="tablist">
                {MODES.map((mode) => (
                  <button
                    key={mode.endpoint}
                    type="button"
                    role="tab"
                    aria-selected={endpoint === mode.endpoint}
                    onClick={() => setEndpoint(mode.endpoint)}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition",
                      endpoint === mode.endpoint
                        ? "border-indigo-300 bg-indigo-50 text-indigo-700"
                        : "border-border bg-white text-slate-600 hover:bg-slate-50"
                    )}
                  >
                    <mode.icon className="h-4 w-4" /> {mode.label}
                  </button>
                ))}
              </div>
            </CardHeader>
            <CardContent>
              {error ? <p className="mb-3 text-sm text-red-600">{error}</p> : null}
              {token
                ? MODES.map((mode) => (
                    <div key={mode.endpoint} className={mode.endpoint === endpoint ? "block" : "hidden"}>
                      <ChatPanel
                        token={token}
                        endpoint={mode.endpoint}
                        suggestions={capabilities?.suggestions ?? []}
                        onUnauthorized={clearAuthAndRedirect}
                        onActivity={loadRecent}
                      />
                    </div>
                  ))
                : null}
            </CardContent>
          </Card>

          <div className="space-y-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Recent AI Actions</CardTitle>
                <CardDescription>Every copilot request is audited.</CardDescription>
              </CardHeader>
              <CardContent>
                <RecentAIActions items={recent} />
              </CardContent>
            </Card>
            {capabilities ? (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">What you can do</CardTitle>
                  <CardDescription>Based on your {capabilities.role.toLowerCase()} role.</CardDescription>
                </CardHeader>
                <CardContent>
                  <ul className="flex flex-wrap gap-1.5">
                    {capabilities.capabilities.map((capability) => (
                      <li key={capability} className="rounded bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
                        {capability.replace(/_/g, " ").toLowerCase()}
                      </li>
                    ))}
                  </ul>
                  <p className="mt-3 text-[11px] text-slate-400">Engine: {capabilities.provider}</p>
                </CardContent>
              </Card>
            ) : null}
          </div>
        </div>
      </section>
    </main>
  );
}
