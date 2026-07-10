"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { AskResult, Segment } from "@/lib/types";

const SUGGESTED = [
  "Summarize the discussion so far",
  "What did we decide?",
  "What are the open action items?",
  "What are the risks?",
  "What should I say next?",
];

// Live "Ask AI" during a meeting — grounded in the whole conversation, earlier answers, and the
// asker's connected tools. Tag transcript lines to ask about them specifically.
export default function MeetingAsk({
  meetingId,
  tagged = [],
  onUntag,
  onClearTags,
}: {
  meetingId: string;
  tagged?: Segment[];
  onUntag?: (id: string) => void;
  onClearTags?: () => void;
}) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AskResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const ask = async (query: string) => {
    const text = query.trim();
    if (!text || busy) return;
    setBusy(true);
    setErr(null);
    try {
      const selection = tagged.map((t) => `${t.speaker}: ${t.text}`);
      setRes(await api.ask(text, "", meetingId, selection));
    } catch {
      setErr("Couldn't reach the advisor. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="meeting-ask">
      {tagged.length > 0 && (
        <div className="ma-tags">
          <span className="ma-tags-label">Asking about {tagged.length} tagged line{tagged.length > 1 ? "s" : ""}:</span>
          {tagged.map((t) => (
            <span key={t.id} className="ma-tag" title={t.text}>
              <b>{t.speaker}:</b> {t.text.length > 48 ? t.text.slice(0, 48) + "…" : t.text}
              <button className="ma-tag-x" onClick={() => onUntag?.(t.id)} title="Remove">✕</button>
            </span>
          ))}
          <button className="ma-tags-clear" onClick={() => onClearTags?.()}>clear all</button>
        </div>
      )}
      <div className="ma-row">
        <input
          className="ma-input"
          value={q}
          placeholder="Ask the advisor about this meeting…"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask(q)}
          disabled={busy}
        />
        <button className="btn primary sm" disabled={busy || !q.trim()} onClick={() => ask(q)}>
          {busy ? "…" : "Ask"}
        </button>
      </div>
      <div className="ma-chips">
        {SUGGESTED.map((s) => (
          <button key={s} className="ma-chip" disabled={busy} onClick={() => { setQ(s); ask(s); }}>{s}</button>
        ))}
      </div>

      {err && <div className="ma-err">{err}</div>}
      {res && (
        <div className="ma-answer">
          <div className="ma-text">{res.answer}</div>
          {(res.next_actions?.length || res.risks?.length || res.assumptions?.length) ? (
            <div className="envelope">
              {res.next_actions?.length ? (
                <div className="env-block"><div className="kicker">▸ Next actions</div>
                  <ul className="env-list">{res.next_actions.map((x, i) => <li key={i}>{x}</li>)}</ul></div>
              ) : null}
              {res.risks?.length ? (
                <div className="env-block"><div className="kicker">⚠ Risks</div>
                  <ul className="env-list warn">{res.risks.map((x, i) => <li key={i}>{x}</li>)}</ul></div>
              ) : null}
              {res.assumptions?.length ? (
                <div className="env-block"><div className="kicker">◇ Assumptions</div>
                  <ul className="env-list muted">{res.assumptions.map((x, i) => <li key={i}>{x}</li>)}</ul></div>
              ) : null}
            </div>
          ) : null}
          {res.sources?.length > 0 && (
            <div className="sources" style={{ marginTop: 8 }}>
              {res.sources.map((s, i) => (
                <span key={i} className="source-chip" title={s.detail}>
                  {s.url ? <a href={s.url} target="_blank" rel="noreferrer" style={{ color: "inherit" }}>{s.label}</a> : s.label}
                </span>
              ))}
            </div>
          )}
          <div className="ma-meta">
            {res.grounded ? "✓ grounded" : "⚠ will confirm"} · {Math.round(res.confidence * 100)}% ·{" "}
            {res.connected.length ? `searched: ${res.connected.join(", ")}` : "internal knowledge"}
          </div>
        </div>
      )}
    </div>
  );
}
