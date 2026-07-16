"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CostReport } from "@/lib/types";

const usd = (n: number) =>
  n >= 1 ? `$${n.toFixed(2)}` : n > 0 ? `$${n.toFixed(4)}` : "$0";
const compactUsd = (n: number) =>
  n >= 1000 ? `$${(n / 1000).toFixed(1)}k` : n >= 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(3)}`;
const fmt = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(1)}k` : `${n}`;

const CALL_TYPE_LABEL: Record<string, string> = {
  deep_answer: "Live deep answers",
  triage: "Triage (routing)",
  meeting_context: "Meeting context refresh",
  insights: "Proactive insights",
  summary: "Post-meeting summary",
  scorecard: "Rep scorecard",
  planner: "Action planner",
  planner_doc: "Action drafts",
  prep_research: "Prep — live research",
  prep_compose: "Prep — compose",
  answer_polish: "Fast-answer polish",
  advisory_envelope: "Answer envelope",
  ask: "Ask Cue",
  other: "Other",
};

function Bar({ label, sub, cost, max }: { label: string; sub?: string; cost: number; max: number }) {
  const pct = max > 0 ? Math.max(2, Math.round((cost / max) * 100)) : 0;
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4, gap: 10 }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {label}
          {sub && <span style={{ color: "var(--faint)" }}> · {sub}</span>}
        </span>
        <b style={{ fontVariantNumeric: "tabular-nums", flex: "none" }}>{usd(cost)}</b>
      </div>
      <div style={{ height: 8, borderRadius: 5, background: "var(--surface-2, #eef1f9)", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: "var(--accent)", borderRadius: 5 }} />
      </div>
    </div>
  );
}

export default function CostsPage() {
  const [report, setReport] = useState<CostReport | null>(null);
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);

  const load = useCallback((d: number) => {
    setLoading(true);
    api
      .costs(d)
      .then((r) => { setReport(r); setDenied(false); })
      .catch((e) => { if (String(e?.message || e).includes("403")) setDenied(true); })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(days); }, [days, load]);

  const t = report?.totals;
  const maxCall = Math.max(1e-9, ...(report?.by_call_type ?? []).map((r) => r.cost_usd));
  const maxModel = Math.max(1e-9, ...(report?.by_model ?? []).map((r) => r.cost_usd));
  const maxDay = Math.max(1e-9, ...(report?.by_day ?? []).map((r) => r.cost_usd));

  return (
    <main className="container">
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <h1 className="page-title" style={{ marginBottom: 2 }}>💸 Costs</h1>
          <p style={{ color: "var(--muted)", marginTop: 4, fontSize: 13.5, maxWidth: "60ch" }}>
            LLM token usage &amp; estimated cost across the workspace, computed from per-call token
            counts × model pricing. Owner/Admin only.
          </p>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              className={`btn sm ${days === d ? "primary" : "ghost"}`}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {denied ? (
        <div className="card pad" style={{ marginTop: 20 }}>
          Only an <b>owner or admin</b> can view workspace costs.
        </div>
      ) : loading && !report ? (
        <div className="card pad" style={{ marginTop: 20, color: "var(--muted)" }}>Loading cost data…</div>
      ) : !report || (t && t.calls === 0) ? (
        <div className="card pad" style={{ marginTop: 20, color: "var(--muted)" }}>
          No LLM usage recorded in the last {days} days yet. Cost accounting starts capturing on the
          next meeting/answer/prep once this build is deployed.
        </div>
      ) : (
        <>
          <div className="meta-strip" style={{ marginTop: 18, marginBottom: 18 }}>
            <div className="metric">
              <div className="v good">{usd(t!.cost_usd)}</div>
              <div className="l">Total cost · {days}d</div>
            </div>
            <div className="metric">
              <div className="v">{fmt(t!.calls)}</div>
              <div className="l">API calls</div>
            </div>
            <div className="metric">
              <div className="v">{fmt(t!.input_tokens)}</div>
              <div className="l">Input tokens</div>
            </div>
            <div className="metric">
              <div className="v">{fmt(t!.output_tokens)}</div>
              <div className="l">Output tokens</div>
            </div>
            <div className="metric">
              <div className="v">{fmt(t!.cache_read_tokens)}</div>
              <div className="l">Cache-read tokens</div>
            </div>
          </div>

          {report.by_day.length > 1 && (
            <div className="card pad" style={{ marginBottom: 18 }}>
              <div className="section-title" style={{ marginBottom: 12 }}>Daily spend</div>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 120 }}>
                {report.by_day.map((d) => (
                  <div key={d.date} title={`${d.date}: ${usd(d.cost_usd)} · ${d.calls} calls`}
                       style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-end", height: "100%" }}>
                    <div style={{
                      height: `${Math.max(2, Math.round((d.cost_usd / maxDay) * 100))}%`,
                      background: "var(--accent)", borderRadius: "4px 4px 0 0", minHeight: 2,
                    }} />
                  </div>
                ))}
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", color: "var(--faint)", fontSize: 11, marginTop: 6 }}>
                <span>{report.by_day[0]?.date}</span>
                <span>{report.by_day[report.by_day.length - 1]?.date}</span>
              </div>
            </div>
          )}

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, marginBottom: 18 }} className="costs-cols">
            <div className="card pad">
              <div className="section-title" style={{ marginBottom: 14 }}>Cost by call type</div>
              {report.by_call_type.map((r) => (
                <Bar key={r.call_type} label={CALL_TYPE_LABEL[r.call_type] || r.call_type}
                     sub={`${fmt(r.calls)} calls`} cost={r.cost_usd} max={maxCall} />
              ))}
            </div>
            <div className="card pad">
              <div className="section-title" style={{ marginBottom: 14 }}>Cost by model</div>
              {report.by_model.map((r) => (
                <Bar key={r.model} label={r.model} sub={`${fmt(r.calls)} calls`} cost={r.cost_usd} max={maxModel} />
              ))}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }} className="costs-cols">
            <div className="card pad">
              <div className="section-title" style={{ marginBottom: 10 }}>By person</div>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
                <tbody>
                  {report.by_user.map((r) => (
                    <tr key={r.user_id} style={{ borderTop: "1px solid var(--border)" }}>
                      <td style={{ padding: "8px 0" }}>{r.name || r.user_id || "Unattributed"}</td>
                      <td style={{ padding: "8px 0", textAlign: "right", color: "var(--faint)" }}>{fmt(r.calls)} calls</td>
                      <td style={{ padding: "8px 0", textAlign: "right", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{usd(r.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="card pad">
              <div className="section-title" style={{ marginBottom: 10 }}>Top meetings by cost</div>
              {report.top_meetings.length === 0 ? (
                <div style={{ color: "var(--muted)", fontSize: 13 }}>No meeting-attributed spend yet.</div>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
                  <tbody>
                    {report.top_meetings.map((r) => (
                      <tr key={r.meeting_id} style={{ borderTop: "1px solid var(--border)" }}>
                        <td style={{ padding: "8px 0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 220 }}>{r.title || "Meeting"}</td>
                        <td style={{ padding: "8px 0", textAlign: "right", fontWeight: 700, fontVariantNumeric: "tabular-nums" }}>{usd(r.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          <p style={{ color: "var(--faint)", fontSize: 11.5, marginTop: 16 }}>
            Cost is estimated from token counts × list pricing (Sonnet ${compactUsd(3)}/$15, Haiku
            $1/$5 per 1M in/out; cache-read ~10% of input). Not a billing figure.
          </p>
        </>
      )}
    </main>
  );
}
