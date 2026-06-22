"use client";

import { useState } from "react";
import type { Suggestion, Action } from "@/lib/types";
import { intentMeta, confidenceColor, ACTION_ICON } from "@/lib/intents";

const SOURCE_ICON: Record<string, string> = {
  crm: "🗂️",
  document: "📄",
  email: "✉️",
  connector: "🔌",
};

export default function SuggestionCard({
  s,
  onPropose,
}: {
  s: Suggestion;
  onPropose?: (action: Action) => void | Promise<void>;
}) {
  const meta = intentMeta(s.intent_type);
  const pct = Math.round(s.confidence * 100);
  const [proposed, setProposed] = useState<Record<number, boolean>>({});
  const liveAgent = s.engine === "claude+mcp";

  const propose = async (i: number, a: Action) => {
    if (proposed[i]) return;
    setProposed((p) => ({ ...p, [i]: true }));
    try {
      await onPropose?.(a);
    } catch {
      setProposed((p) => ({ ...p, [i]: false }));
    }
  };
  const fastPhase = s.engine === "fast";
  const refining = !!s.deep_pending && !liveAgent;

  return (
    <div className="suggestion">
      <div className="s-head">
        <div
          className="ring"
          style={
            {
              ["--p" as string]: pct,
              ["--ring-color" as string]: confidenceColor(s.confidence),
            } as React.CSSProperties
          }
          title={`Confidence ${pct}%`}
        >
          <span>{pct}</span>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <span className={`badge fam-${meta.family}`}>
            {meta.icon} {meta.label}
          </span>
          <div className="q" style={{ marginTop: 5 }}>
            “{s.query_text}”
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 5, alignItems: "flex-end" }}>
          <span className={`engine-badge ${liveAgent ? "claude" : fastPhase ? "fast" : "offline"}`}>
            {liveAgent ? "✦ Claude · live" : fastPhase ? "⚡ instant" : "offline"}
          </span>
          {refining ? (
            <span className="refining" title="Deepening with the Claude agent + MCP tools">
              ✦ deepening<i />
            </span>
          ) : (
            s.latency_ms > 0 && (
              <span className="pill" title="Time to first answer (SLA)">
                ⚡ {s.latency_ms}ms
                {liveAgent && s.deep_latency_ms ? ` · +${(s.deep_latency_ms / 1000).toFixed(0)}s deep` : ""}
              </span>
            )
          )}
        </div>
      </div>

      <div className="s-body">
        <div className="answer">{s.answer}</div>

        {s.evidence?.length > 0 && (
          <>
            <div className="kicker">Supporting evidence</div>
            <ul className="evidence">
              {s.evidence.map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          </>
        )}

        {s.sources?.length > 0 && (
          <>
            <div className="kicker">Sources</div>
            <div className="sources">
              {s.sources.map((src, i) =>
                src.url ? (
                  <a key={i} className={`source-chip ${src.type}`} href={src.url} target="_blank" rel="noreferrer">
                    <span className="ic">{SOURCE_ICON[src.type] ?? "📄"}</span>
                    {src.label}
                  </a>
                ) : (
                  <span key={i} className={`source-chip ${src.type}`}>
                    <span className="ic">{SOURCE_ICON[src.type] ?? "📄"}</span>
                    {src.label}
                  </span>
                )
              )}
            </div>
          </>
        )}

        {s.actions?.length > 0 && (
          <>
            <div className="kicker">Recommended actions</div>
            <div className="actions">
              {s.actions.map((a, i) => (
                <button
                  key={i}
                  className={`action-btn ${proposed[i] ? "done" : ""}`}
                  disabled={proposed[i]}
                  title={proposed[i] ? "Sent to Approvals" : "Propose for approval"}
                  onClick={() => propose(i, a)}
                >
                  {proposed[i] ? "✓ proposed" : `${ACTION_ICON[a.type] ?? "•"} ${a.label}`}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
