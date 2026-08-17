import React, { useEffect, useState } from "react";
import {
  AssistantInfo,
  AssistantsResponse,
  getAssistants,
  getHealth,
  HealthResponse,
} from "./api";
import { ChatWindow } from "./components/ChatWindow";

/**
 * Top-level layout: sidebar (assistant switcher + status) + chat panel.
 *
 * Currently only one assistant is registered server-side (Azure DevOps),
 * but the sidebar is built generically against `GET /api/assistants` so a
 * second assistant becomes a backend-only addition.
 */
const App: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [assistantsRes, setAssistantsRes] = useState<AssistantsResponse | null>(null);
  const [selectedAssistant, setSelectedAssistant] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [h, a] = await Promise.all([getHealth(), getAssistants()]);
        if (cancelled) return;
        setHealth(h);
        setAssistantsRes(a);
        setSelectedAssistant(a.default);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const activeAssistant: AssistantInfo | undefined = assistantsRes?.assistants.find(
    (a) => a.name === selectedAssistant,
  );

  const statusDot = (ok: boolean | undefined): string =>
    ok === undefined ? "bg-slate-400" : ok ? "bg-emerald-500" : "bg-rose-500";

  return (
    <div className="flex h-screen w-screen bg-white text-slate-900">
      {/* Sidebar */}
      <aside className="w-64 border-r border-slate-200 bg-slate-100 flex flex-col">
        <div className="px-4 py-3 border-b border-slate-200">
          <h1 className="text-lg font-semibold">
            {health?.app_name ?? assistantsRes?.current_name ?? "Assistant"}
          </h1>
          <div className="text-xs text-slate-500 mt-0.5">LAN-hosted LLM assistant</div>
        </div>

        <div className="px-4 py-3 border-b border-slate-200">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Status</div>
          <div className="flex items-center gap-2 text-sm">
            <span className={`inline-block w-2 h-2 rounded-full ${statusDot(health?.openai)}`} />
            <span>OpenAI</span>
          </div>
          <div className="flex items-center gap-2 text-sm mt-1">
            <span className={`inline-block w-2 h-2 rounded-full ${statusDot(health?.ado)}`} />
            <span>Azure DevOps</span>
          </div>
          {health && !health.openai ? (
            <div className="text-[11px] text-rose-700 mt-1">Add OPENAI_API_KEY to .env</div>
          ) : null}
          {health && !health.ado ? (
            <div className="text-[11px] text-rose-700 mt-1">Configure Azure DevOps in .env</div>
          ) : null}
        </div>

        <div className="px-4 py-3 flex-1 overflow-y-auto">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Assistants</div>
          {assistantsRes?.assistants.map((a) => (
            <button
              key={a.name}
              type="button"
              onClick={() => setSelectedAssistant(a.name)}
              className={[
                "block w-full text-left px-2 py-1 rounded text-sm mb-1 border",
                a.name === selectedAssistant
                  ? "bg-blue-600 border-blue-600 text-white"
                  : "bg-white border-transparent text-slate-800 hover:border-slate-300",
              ].join(" ")}
            >
              <span className="font-medium">{a.title}</span>
              <span className="block text-xs opacity-80">{a.description}</span>
            </button>
          ))}
        </div>

        <div className="px-4 py-2 border-t border-slate-200 text-xs text-slate-500">
          v0.1 · MVP
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col">
        {error ? (
          <div className="flex items-center justify-center h-full text-rose-700">
            Backend unreachable: {error}
          </div>
        ) : !activeAssistant ? (
          <div className="flex items-center justify-center h-full text-slate-500">Loading…</div>
        ) : (
          <>
            <div className="px-4 py-2 border-b border-slate-200 text-sm">
              <span className="font-medium">{activeAssistant.title}</span>
              <span className="text-slate-400"> · {activeAssistant.description}</span>
            </div>
            <div className="flex-1 overflow-hidden">
              <ChatWindow assistant={activeAssistant} onError={(e) => setError(e)} />
            </div>
          </>
        )}
      </main>
    </div>
  );
};

export default App;
