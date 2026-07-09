"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { AskResult } from "@/lib/types";

type Turn = { role: "user"; text: string } | { role: "assistant"; text: string; meta: AskResult };

const EXAMPLES = [
  "What are my open GitHub pull requests?",
  "Summarize the latest Jira issues assigned to me",
  "What's the status of our biggest deal in HubSpot?",
  "Find recent decisions in my Slack / Drive / email about the roadmap",
];

function pct(n: number) {
  return `${Math.round((n || 0) * 100)}%`;
}

export default function AskPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, busy]);

  const send = async (q: string) => {
    const query = q.trim();
    if (!query || busy) return;
    setError(null);
    setInput("");
    // Thread the recent conversation so follow-ups ("what about that repo?") resolve.
    const context = turns
      .slice(-6)
      .map((t) => `${t.role === "user" ? "You" : "Copilot"}: ${t.text}`)
      .join("\n");
    setTurns((t) => [...t, { role: "user", text: query }]);
    setBusy(true);
    try {
      const res = await api.ask(query, context);
      setTurns((t) => [...t, { role: "assistant", text: res.answer, meta: res }]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(input);
    }
  };

  return (
    <main className="container" style={{ display: "flex", flexDirection: "column", minHeight: "calc(100vh - 80px)" }}>
      <h1 style={{ fontSize: 28, letterSpacing: "-0.025em", margin: "4px 0 6px" }}>Ask the copilot</h1>
      <p style={{ color: "var(--muted)", maxWidth: 720, lineHeight: 1.6, marginTop: 0 }}>
        Ask anything — it researches across <b>your</b> connected sources (GitHub, Jira, HubSpot, Slack,
        Drive, Gmail, Notion) with your own access, exactly like the live meeting copilot. Great for a quick
        query, or to test that a connector is returning data.
      </p>

      {turns.length === 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "12px 0 20px" }}>
          {EXAMPLES.map((ex) => (
            <button key={ex} className="btn ghost sm" onClick={() => send(ex)} disabled={busy}>
              {ex}
            </button>
          ))}
        </div>
      )}

      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 14, marginBottom: 16 }}>
        {turns.map((t, i) =>
          t.role === "user" ? (
            <div key={i} style={{ alignSelf: "flex-end", maxWidth: "78%", background: "var(--accent, #6d7cff)", color: "#fff", padding: "10px 14px", borderRadius: "14px 14px 4px 14px", lineHeight: 1.5 }}>
              {t.text}
            </div>
          ) : (
            <div key={i} className="card" style={{ alignSelf: "flex-start", maxWidth: "88%", padding: "14px 16px" }}>
              <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{t.text}</div>

              {(t.meta.next_actions?.length || t.meta.risks?.length || t.meta.assumptions?.length) ? (
                <div className="envelope">
                  {t.meta.next_actions?.length ? (
                    <div className="env-block"><div className="kicker">▸ Recommended next actions</div>
                      <ul className="env-list">{t.meta.next_actions.map((x, j) => <li key={j}>{x}</li>)}</ul></div>
                  ) : null}
                  {t.meta.risks?.length ? (
                    <div className="env-block"><div className="kicker">⚠ Risks &amp; caveats</div>
                      <ul className="env-list warn">{t.meta.risks.map((x, j) => <li key={j}>{x}</li>)}</ul></div>
                  ) : null}
                  {t.meta.assumptions?.length ? (
                    <div className="env-block"><div className="kicker">◇ Assumptions</div>
                      <ul className="env-list muted">{t.meta.assumptions.map((x, j) => <li key={j}>{x}</li>)}</ul></div>
                  ) : null}
                </div>
              ) : null}

              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12, alignItems: "center" }}>
                <span className="engine-badge">{t.meta.engine}</span>
                <span className="badge">{t.meta.persona}</span>
                <span className="badge">{t.meta.intent}</span>
                <span style={{ color: "var(--muted)", fontSize: 12 }}>· {pct(t.meta.confidence)} confidence · {t.meta.latency_ms}ms</span>
              </div>

              {t.meta.sources.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
                  {t.meta.sources.map((s, j) => (
                    <span key={j} className="source-chip" title={s.detail}>
                      {s.url ? <a href={s.url} target="_blank" rel="noreferrer" style={{ color: "inherit" }}>{s.label}</a> : s.label}
                    </span>
                  ))}
                </div>
              )}

              {t.meta.evidence.length > 0 && (
                <details style={{ marginTop: 10 }}>
                  <summary style={{ cursor: "pointer", color: "var(--muted)", fontSize: 13 }}>
                    Evidence ({t.meta.evidence.length})
                  </summary>
                  <ul className="evidence" style={{ marginTop: 8 }}>
                    {t.meta.evidence.map((e, j) => (
                      <li key={j}>{e}</li>
                    ))}
                  </ul>
                </details>
              )}

              {/* Test-bench signal: which sources were reachable, and whether the deep tier ran. */}
              <div style={{ marginTop: 10, color: "var(--muted)", fontSize: 11.5 }}>
                {t.meta.deep_ran
                  ? `Searched: ${t.meta.connected.length ? t.meta.connected.join(", ") : "connected sources"}`
                  : "Answered from internal knowledge (no live connectors used — connect tools for deeper answers)."}
              </div>
            </div>
          )
        )}

        {busy && (
          <div className="card" style={{ alignSelf: "flex-start", padding: "12px 16px", color: "var(--muted)" }}>
            Researching across your connected sources…
          </div>
        )}
        {error && (
          <div className="card" style={{ alignSelf: "flex-start", padding: "12px 16px", color: "var(--red, #e5484d)" }}>
            {error}
          </div>
        )}
        <div ref={endRef} />
      </div>

      <div style={{ position: "sticky", bottom: 0, background: "var(--bg, #0b0f1a)", paddingBottom: 16, display: "flex", gap: 10 }}>
        <textarea
          className="meet-input"
          style={{ flex: 1, minHeight: 52, resize: "vertical", fontFamily: "inherit" }}
          placeholder="Ask anything about your work — Enter to send, Shift+Enter for a new line"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          disabled={busy}
        />
        <button className="btn" onClick={() => send(input)} disabled={busy || !input.trim()}>
          {busy ? "…" : "Ask"}
        </button>
      </div>
    </main>
  );
}
