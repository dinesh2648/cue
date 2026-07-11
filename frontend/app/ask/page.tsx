"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { AskResult, AskThreadSummary } from "@/lib/types";

type Msg = { role: "user"; text: string } | { role: "assistant"; text: string; meta: AskResult };

const EXAMPLES = [
  "What are my open GitHub pull requests?",
  "Summarize the latest Jira issues assigned to me",
  "What's the status of our biggest deal in HubSpot?",
  "Find recent decisions in my Slack / Drive / email about the roadmap",
];

const pct = (n: number) => `${Math.round((n || 0) * 100)}%`;

/** Live research progress: cycles through the real phases, shows elapsed time + the sources
 *  being searched, so a slow deep answer reads as "working" instead of "stuck". */
function ResearchProgress({ sources }: { sources: string[] }) {
  const phases = [
    "Understanding your question",
    sources.length ? `Searching your ${sources.length} connected source${sources.length > 1 ? "s" : ""}` : "Searching your connected sources",
    "Reading and cross-checking results",
    "Composing a grounded, cited answer",
  ];
  const [i, setI] = useState(0);
  const [sec, setSec] = useState(0);
  useEffect(() => {
    const p = setInterval(() => setI((x) => (x + 1 < phases.length ? x + 1 : x)), 3200);
    const s = setInterval(() => setSec((x) => x + 1), 1000);
    return () => { clearInterval(p); clearInterval(s); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="card" style={{ alignSelf: "flex-start", maxWidth: "88%", minWidth: 300, padding: "14px 16px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 9 }}>
        <span style={{ fontWeight: 600, fontSize: 14 }}>{phases[i]}…</span>
        <span style={{ color: "var(--muted)", fontSize: 12, fontVariantNumeric: "tabular-nums" }}>{sec}s</span>
      </div>
      <div className="cue-prog" />
      {sources.length > 0 && (
        <div style={{ marginTop: 10, color: "var(--muted)", fontSize: 12 }}>Searching: {sources.join(" · ")}</div>
      )}
      <div style={{ marginTop: 6, color: "var(--faint)", fontSize: 11.5 }}>
        Deep research across your tools can take up to a minute for the first grounded answer.
      </div>
    </div>
  );
}

function AssistantBubble({ meta, text }: { meta: AskResult; text: string }) {
  return (
    <div className="card" style={{ alignSelf: "flex-start", maxWidth: "88%", padding: "14px 16px" }}>
      <div style={{ whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{text}</div>

      {(meta.next_actions?.length || meta.risks?.length || meta.assumptions?.length) ? (
        <div className="envelope">
          {meta.next_actions?.length ? (
            <div className="env-block"><div className="kicker">▸ Recommended next actions</div>
              <ul className="env-list">{meta.next_actions.map((x, j) => <li key={j}>{x}</li>)}</ul></div>
          ) : null}
          {meta.risks?.length ? (
            <div className="env-block"><div className="kicker">⚠ Risks &amp; caveats</div>
              <ul className="env-list warn">{meta.risks.map((x, j) => <li key={j}>{x}</li>)}</ul></div>
          ) : null}
          {meta.assumptions?.length ? (
            <div className="env-block"><div className="kicker">◇ Assumptions</div>
              <ul className="env-list muted">{meta.assumptions.map((x, j) => <li key={j}>{x}</li>)}</ul></div>
          ) : null}
        </div>
      ) : null}

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12, alignItems: "center" }}>
        <span className="engine-badge">{meta.engine}</span>
        <span className="badge">{meta.persona}</span>
        <span className="badge">{meta.intent}</span>
        <span style={{ color: "var(--muted)", fontSize: 12 }}>· {pct(meta.confidence)} confidence · {meta.latency_ms}ms</span>
      </div>

      {(meta.sources?.length ?? 0) > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
          {meta.sources.map((s, j) => (
            <span key={j} className="source-chip" title={s.detail}>
              {s.url ? <a href={s.url} target="_blank" rel="noreferrer" style={{ color: "inherit" }}>{s.label}</a> : s.label}
            </span>
          ))}
        </div>
      )}

      {(meta.evidence?.length ?? 0) > 0 && (
        <details style={{ marginTop: 10 }}>
          <summary style={{ cursor: "pointer", color: "var(--muted)", fontSize: 13 }}>Evidence ({meta.evidence.length})</summary>
          <ul className="evidence" style={{ marginTop: 8 }}>
            {meta.evidence.map((e, j) => <li key={j}>{e}</li>)}
          </ul>
        </details>
      )}

      <div style={{ marginTop: 10, color: "var(--muted)", fontSize: 11.5 }}>
        {meta.deep_ran
          ? `Searched: ${meta.connected?.length ? meta.connected.join(", ") : "connected sources"}`
          : "Answered from internal knowledge (no live connectors used — connect tools for deeper answers)."}
      </div>
    </div>
  );
}

export default function AskPage() {
  const [threads, setThreads] = useState<AskThreadSummary[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameText, setRenameText] = useState("");
  const [connectedSources, setConnectedSources] = useState<string[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  const loadThreads = useCallback(() => api.askThreads().then((r) => setThreads(r.threads)).catch(() => {}), []);

  // On mount: load the thread list and open the most recent conversation (if any).
  useEffect(() => {
    let alive = true;
    api.askThreads().then((r) => {
      if (!alive) return;
      setThreads(r.threads);
      if (r.threads.length > 0) openThread(r.threads[0].id);
    }).catch(() => {});
    api.connectors()
      .then((cs) => alive && setConnectedSources(cs.filter((c) => c.status === "connected").map((c) => c.name)))
      .catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [turns, busy]);

  const openThread = async (id: string) => {
    setCurrentId(id);
    setError(null);
    try {
      const t = await api.getAskThread(id);
      setTurns(
        t.messages.map((m) =>
          m.role === "assistant"
            ? { role: "assistant", text: m.content, meta: (m.meta || {}) as AskResult }
            : { role: "user", text: m.content }
        )
      );
    } catch {
      setTurns([]);
    }
  };

  const newChat = () => {
    setCurrentId(null);
    setTurns([]);
    setError(null);
    setInput("");
  };

  const send = async (q: string) => {
    const query = q.trim();
    if (!query || busy) return;
    setError(null);
    setInput("");
    const context = turns.slice(-6).map((t) => `${t.role === "user" ? "You" : "Copilot"}: ${t.text}`).join("\n");
    setTurns((t) => [...t, { role: "user", text: query }]);
    setBusy(true);
    try {
      const res = await api.ask(query, context, undefined, undefined, currentId);
      setTurns((t) => [...t, { role: "assistant", text: res.answer, meta: res }]);
      if (res.thread_id && res.thread_id !== currentId) setCurrentId(res.thread_id);
      loadThreads(); // reflect the (possibly new / retitled) thread in the sidebar
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  const saveRename = async (id: string) => {
    const title = renameText.trim();
    setRenamingId(null);
    if (!title) return;
    try {
      await api.renameAskThread(id, title);
      loadThreads();
    } catch { /* ignore */ }
  };

  const del = async (id: string) => {
    try {
      await api.deleteAskThread(id);
      if (id === currentId) newChat();
      loadThreads();
    } catch { /* ignore */ }
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); }
  };

  return (
    <main className="container" style={{ display: "flex", gap: 20, alignItems: "stretch", minHeight: "calc(100vh - 80px)" }}>
      {/* Thread sidebar */}
      <aside style={{ width: 248, flex: "0 0 248px", display: "flex", flexDirection: "column", gap: 10 }} className="ask-threads">
        <button className="btn primary" onClick={newChat} style={{ width: "100%" }}>＋ New chat</button>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, overflowY: "auto", flex: 1 }}>
          {threads.length === 0 && (
            <div style={{ color: "var(--faint)", fontSize: 12.5, padding: "8px 6px", lineHeight: 1.5 }}>
              Your conversations will show up here.
            </div>
          )}
          {threads.map((t) => (
            <div
              key={t.id}
              className="card"
              style={{
                padding: "8px 10px", display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
                borderColor: t.id === currentId ? "var(--accent)" : "var(--border)",
                background: t.id === currentId ? "var(--surface-2)" : "var(--surface)",
              }}
              onClick={() => renamingId !== t.id && openThread(t.id)}
            >
              {renamingId === t.id ? (
                <input
                  autoFocus
                  className="meet-input"
                  style={{ flex: 1, padding: "4px 8px", fontSize: 13 }}
                  value={renameText}
                  onChange={(e) => setRenameText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") saveRename(t.id); if (e.key === "Escape") setRenamingId(null); }}
                  onBlur={() => saveRename(t.id)}
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <>
                  <span style={{ flex: 1, minWidth: 0, fontSize: 13, fontWeight: t.id === currentId ? 700 : 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={t.title}>
                    {t.title}
                  </span>
                  <button
                    className="linklike" title="Rename" style={{ fontSize: 12, opacity: 0.7 }}
                    onClick={(e) => { e.stopPropagation(); setRenamingId(t.id); setRenameText(t.title); }}
                  >✎</button>
                  <button
                    className="linklike" title="Delete" style={{ fontSize: 12, opacity: 0.7 }}
                    onClick={(e) => { e.stopPropagation(); del(t.id); }}
                  >🗑</button>
                </>
              )}
            </div>
          ))}
        </div>
      </aside>

      {/* Conversation */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <h1 style={{ fontSize: 24, letterSpacing: "-0.025em", margin: "4px 0 4px" }}>Ask the copilot</h1>
        <p style={{ color: "var(--muted)", maxWidth: 720, lineHeight: 1.55, marginTop: 0, marginBottom: 12, fontSize: 13.5 }}>
          Researches across <b>your</b> connected sources with your own access — every question and answer is saved.
          Start a <b>New chat</b> for a separate thread, and rename threads to find them later.
        </p>

        {turns.length === 0 && !busy && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "4px 0 20px" }}>
            {EXAMPLES.map((ex) => (
              <button key={ex} className="btn ghost sm" onClick={() => send(ex)} disabled={busy}>{ex}</button>
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
              <AssistantBubble key={i} meta={t.meta} text={t.text} />
            )
          )}
          {busy && <ResearchProgress sources={connectedSources} />}
          {error && (
            <div className="card" style={{ alignSelf: "flex-start", padding: "12px 16px", color: "var(--red, #e5484d)" }}>{error}</div>
          )}
          <div ref={endRef} />
        </div>

        <div style={{ position: "sticky", bottom: 0, background: "var(--bg, #EEF3FF)", paddingBottom: 16, display: "flex", gap: 10 }}>
          <textarea
            className="meet-input"
            style={{ flex: 1, minHeight: 52, resize: "vertical", fontFamily: "inherit" }}
            placeholder="Ask anything about your work — Enter to send, Shift+Enter for a new line"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKey}
            disabled={busy}
          />
          <button className="btn" onClick={() => send(input)} disabled={busy || !input.trim()}>{busy ? "…" : "Ask"}</button>
        </div>
      </div>
    </main>
  );
}
