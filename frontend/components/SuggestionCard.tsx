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
  repName,
}: {
  s: Suggestion;
  onPropose?: (action: Action) => void | Promise<void>;
  repName?: string;
}) {
  const meta = intentMeta(s.intent_type);
  const pct = Math.round(s.confidence * 100);
  const [proposed, setProposed] = useState<Record<number, boolean>>({});
  const [showTrust, setShowTrust] = useState(false);
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
  const grounded = s.grounded !== false;
  const userScope = s.access_scope === "user";

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
        <div className="trust-row">
          <span className={`trust ${grounded ? "ok" : "warn"}`}>
            {grounded ? "✓ Grounded · cited" : "⚠ Will confirm — not in your sources"}
          </span>
          <span
            className={`trust ${userScope ? "scope" : "demo"}`}
            title={
              userScope
                ? "Retrieved live through your own connected tools, scoped to your permissions — the copilot can't see anything you can't."
                : "Demo/seeded data. Connect your tools to answer from your own permission-scoped sources."
            }
          >
            {userScope ? "🔒 Answered as you · your access only" : "🗂️ demo data"}
          </span>
          <button className="trust-why" onClick={() => setShowTrust((v) => !v)}>
            {showTrust ? "hide" : "why can I trust this?"}
          </button>
        </div>

        {showTrust && (
          <div className="trust-detail">
            <div className="td-title">Why you can trust this answer</div>
            <ul className="td-list">
              <li>
                <b>Engine</b> — {liveAgent ? "Claude live agent over your tools" : fastPhase ? "Instant local retrieval" : "Offline composer"}
                {s.latency_ms ? ` · ${s.latency_ms}ms to first answer` : ""}
                {s.deep_latency_ms ? ` · +${(s.deep_latency_ms / 1000).toFixed(0)}s deep` : ""}
              </li>
              <li>
                <b>Grounding</b> —{" "}
                {grounded
                  ? "every claim is drawn from the sources below — nothing invented."
                  : "not found in your sources, so the copilot abstained instead of guessing."}
              </li>
              <li>
                <b>Access</b> —{" "}
                {userScope
                  ? `retrieved as ${repName || "you"} through your own connected tools. Only data you can access was read — nothing outside your permissions was touched.`
                  : "seeded demo data. Connect your tools on the Connections page to answer from your own permission-scoped sources."}
              </li>
              <li><b>Confidence</b> — {pct}%</li>
            </ul>
            {s.sources?.length > 0 && (
              <>
                <div className="td-sub">Sources consulted ({s.sources.length})</div>
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
          </div>
        )}
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
