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

// Minimal, safe markdown for short answers: **bold**, [text](url), bare URLs, and
// line breaks. No raw HTML — React escapes all text nodes, so this can't inject markup.
const INLINE_RE = /\*\*(.+?)\*\*|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s)]+)/g;

function renderInline(line: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  let m: RegExpExecArray | null;
  INLINE_RE.lastIndex = 0;
  while ((m = INLINE_RE.exec(line)) !== null) {
    if (m.index > last) out.push(line.slice(last, m.index));
    if (m[1] !== undefined) {
      out.push(<strong key={key++}>{m[1]}</strong>);
    } else if (m[2] !== undefined) {
      out.push(<a key={key++} href={m[3]} target="_blank" rel="noreferrer">{m[2]}</a>);
    } else if (m[4] !== undefined) {
      const url = m[4];
      out.push(<a key={key++} href={url} target="_blank" rel="noreferrer">{url.replace(/^https?:\/\//, "")}</a>);
    }
    last = INLINE_RE.lastIndex;
  }
  if (last < line.length) out.push(line.slice(last));
  return out;
}

function renderRich(text: string): React.ReactNode {
  return text
    .split(/\n{2,}/)
    .filter((p) => p.trim())
    .map((para, i) => (
      <p key={i} style={{ margin: i ? "8px 0 0" : 0 }}>
        {para.split("\n").map((line, j) => (
          <span key={j}>
            {j > 0 && <br />}
            {renderInline(line)}
          </span>
        ))}
      </p>
    ));
}

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
  const webScope = s.access_scope === "web";

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
            className={`trust ${userScope || webScope ? "scope" : "demo"}`}
            title={
              userScope
                ? "Retrieved live through your own connected tools, scoped to your permissions — the copilot can't see anything you can't."
                : webScope
                ? "Researched live on the web — every claim is drawn from the sources below."
                : "Demo/seeded data. Connect your tools to answer from your own permission-scoped sources."
            }
          >
            {userScope
              ? "🔒 Answered as you · your access only"
              : webScope
              ? "🌐 Live web research"
              : "🗂️ demo data"}
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
                  : webScope
                  ? "researched live on the public web (this topic isn't in your connected sources). See the source links below."
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
        <div className="answer">{renderRich(s.answer)}</div>

        {s.envelope && (s.envelope.assumptions?.length || s.envelope.risks?.length || s.envelope.next_actions?.length) ? (
          <div className="envelope">
            {s.envelope.next_actions?.length ? (
              <div className="env-block">
                <div className="kicker">▸ Recommended next actions</div>
                <ul className="env-list">{s.envelope.next_actions.map((x, i) => <li key={i}>{x}</li>)}</ul>
              </div>
            ) : null}
            {s.envelope.risks?.length ? (
              <div className="env-block">
                <div className="kicker">⚠ Risks &amp; caveats</div>
                <ul className="env-list warn">{s.envelope.risks.map((x, i) => <li key={i}>{x}</li>)}</ul>
              </div>
            ) : null}
            {s.envelope.assumptions?.length ? (
              <div className="env-block">
                <div className="kicker">◇ Assumptions</div>
                <ul className="env-list muted">{s.envelope.assumptions.map((x, i) => <li key={i}>{x}</li>)}</ul>
              </div>
            ) : null}
          </div>
        ) : null}

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
