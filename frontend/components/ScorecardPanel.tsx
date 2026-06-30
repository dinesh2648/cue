"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { Scorecard } from "@/lib/types";

function scoreColor(n: number): string {
  if (n >= 75) return "var(--green, #34d399)";
  if (n >= 50) return "#fbbf24";
  return "var(--red, #f87171)";
}

const METRIC_LABELS: Record<string, string> = {
  talk_ratio_pct: "Talk ratio",
  rep_questions: "Questions asked",
  customer_questions: "Customer questions",
  longest_monologue_words: "Longest monologue",
  filler_count: "Filler words",
};

export default function ScorecardPanel({ meetingId }: { meetingId: string }) {
  const [sc, setSc] = useState<Scorecard | null>(null);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = async (refresh = false) => {
    setLoading(true);
    setMsg(null);
    try {
      const d = await api.scorecard(meetingId, refresh);
      if (d.status && d.status !== "ready") {
        setMsg(d.status === "no_transcript" ? "No transcript captured — nothing to coach on yet." : "Couldn't generate a scorecard for this call.");
      } else {
        setSc(d);
      }
    } catch {
      setMsg("Couldn't load the scorecard.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="summary-panel" style={{ marginTop: 26 }}>
      <h2 className="section-title">🎯 Rep coaching scorecard</h2>

      {!sc ? (
        <div className="card pad">
          <p style={{ color: "var(--muted)", marginTop: 0, lineHeight: 1.6 }}>
            Analyze how the rep handled this call — scored across discovery, listening, objection
            handling, answer quality, rapport and closing, with specific, quote-backed coaching tips.
          </p>
          <button className="btn primary" disabled={loading} onClick={() => load()}>
            {loading ? "Analyzing the call…" : "🎯 Score this call"}
          </button>
          {msg && <div style={{ color: "var(--muted)", marginTop: 12 }}>{msg}</div>}
        </div>
      ) : (
        <div className="card pad">
          <div style={{ display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
            <div
              style={{
                width: 76, height: 76, borderRadius: "50%", display: "grid", placeItems: "center",
                fontSize: 26, fontWeight: 800, color: scoreColor(sc.overall_score),
                border: `4px solid ${scoreColor(sc.overall_score)}`,
              }}
            >
              {sc.overall_score}
            </div>
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ fontWeight: 700, fontSize: 15 }}>{sc.rep_name}</div>
              <div style={{ color: "var(--muted)", lineHeight: 1.5, marginTop: 4 }}>{sc.headline}</div>
            </div>
          </div>

          {/* Objective metrics */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 16 }}>
            {Object.entries(METRIC_LABELS).map(([k, label]) =>
              sc.metrics[k] !== undefined ? (
                <span key={k} className="source-chip">
                  {label}: <b>{sc.metrics[k]}{k === "talk_ratio_pct" ? "%" : ""}</b>
                </span>
              ) : null
            )}
          </div>

          {/* Dimension bars */}
          <div style={{ marginTop: 18, display: "grid", gap: 10 }}>
            {sc.dimensions.map((d) => (
              <div key={d.name}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 4 }}>
                  <span>{d.name}</span>
                  <span style={{ color: scoreColor(d.score), fontWeight: 700 }}>{d.score}</span>
                </div>
                <div style={{ height: 6, borderRadius: 4, background: "var(--surface-2)", overflow: "hidden" }}>
                  <div style={{ width: `${d.score}%`, height: "100%", background: scoreColor(d.score) }} />
                </div>
                {d.comment && <div style={{ color: "var(--faint)", fontSize: 12.5, marginTop: 4, lineHeight: 1.5 }}>{d.comment}</div>}
              </div>
            ))}
          </div>

          <div className="score-cols" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, marginTop: 20 }}>
            <div>
              <div className="kicker" style={{ color: "var(--green, #34d399)" }}>✓ Strengths</div>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18, lineHeight: 1.6, fontSize: 13.5 }}>
                {sc.strengths.map((s, i) => <li key={i}>{s}</li>)}
              </ul>
            </div>
            <div>
              <div className="kicker" style={{ color: "#fbbf24" }}>△ To improve</div>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18, lineHeight: 1.6, fontSize: 13.5 }}>
                {sc.improvements.map((s, i) => <li key={i}>{s}</li>)}
              </ul>
            </div>
          </div>

          {sc.coaching_tips.length > 0 && (
            <div style={{ marginTop: 18 }}>
              <div className="kicker">Coaching tips</div>
              <div style={{ display: "grid", gap: 10, marginTop: 8 }}>
                {sc.coaching_tips.map((t, i) => (
                  <div key={i} style={{ background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: 10, padding: "10px 13px" }}>
                    <div style={{ fontSize: 13.5, fontWeight: 600 }}>{t.tip}</div>
                    {t.example && <div style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 4, fontStyle: "italic" }}>e.g. “{t.example}”</div>}
                  </div>
                ))}
              </div>
            </div>
          )}

          <button className="btn ghost sm" style={{ marginTop: 16 }} disabled={loading} onClick={() => load(true)}>
            {loading ? "Re-scoring…" : "↻ Re-score"}
          </button>
        </div>
      )}
    </div>
  );
}
