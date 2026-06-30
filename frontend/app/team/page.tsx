"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { TeamCoaching, TeamRep } from "@/lib/types";

function scoreColor(n: number): string {
  if (n >= 75) return "var(--green, #34d399)";
  if (n >= 50) return "#fbbf24";
  return "var(--red, #f87171)";
}

function Sparkline({ points }: { points: { score: number }[] }) {
  if (points.length < 2) return <span style={{ color: "var(--faint)", fontSize: 12 }}>—</span>;
  const w = 90, h = 26, pad = 2;
  const xs = points.map((_, i) => pad + (i * (w - 2 * pad)) / (points.length - 1));
  const ys = points.map((p) => h - pad - (Math.max(0, Math.min(100, p.score)) / 100) * (h - 2 * pad));
  const d = xs.map((x, i) => `${i ? "L" : "M"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
  const last = points[points.length - 1].score;
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <path d={d} fill="none" stroke={scoreColor(last)} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={xs[xs.length - 1]} cy={ys[ys.length - 1]} r="2.4" fill={scoreColor(last)} />
    </svg>
  );
}

function RepCard({ rep, rank }: { rep: TeamRep; rank: number }) {
  return (
    <div className="card pad" style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <span style={{ color: "var(--faint)", fontWeight: 800, fontSize: 16, width: 26 }}>#{rank}</span>
        <span
          style={{
            width: 48, height: 48, borderRadius: "50%", display: "grid", placeItems: "center",
            fontWeight: 800, fontSize: 18, color: scoreColor(rep.avg_score), border: `3px solid ${scoreColor(rep.avg_score)}`,
          }}
        >
          {rep.avg_score}
        </span>
        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={{ fontWeight: 700 }}>{rep.rep_name}</div>
          <div style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 2 }}>
            {rep.calls} call{rep.calls === 1 ? "" : "s"} scored ·{" "}
            <span style={{ color: rep.trend > 0 ? "var(--green, #34d399)" : rep.trend < 0 ? "var(--red, #f87171)" : "var(--faint)" }}>
              {rep.trend > 0 ? `▲ +${rep.trend}` : rep.trend < 0 ? `▼ ${rep.trend}` : "no change"} trend
            </span>
          </div>
        </div>
        <Sparkline points={rep.recent} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10, marginTop: 16 }}>
        {rep.dimensions.map((d) => (
          <div key={d.name}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, marginBottom: 3 }}>
              <span style={{ color: "var(--muted)" }}>{d.name}</span>
              <span style={{ color: scoreColor(d.score), fontWeight: 700 }}>{d.score}</span>
            </div>
            <div style={{ height: 5, borderRadius: 3, background: "var(--surface-2)", overflow: "hidden" }}>
              <div style={{ width: `${d.score}%`, height: "100%", background: scoreColor(d.score) }} />
            </div>
          </div>
        ))}
      </div>

      {rep.top_improvements.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <div className="kicker" style={{ color: "#fbbf24" }}>Top areas to coach</div>
          <ul style={{ margin: "6px 0 0", paddingLeft: 18, lineHeight: 1.6, fontSize: 13 }}>
            {rep.top_improvements.map((s, i) => <li key={i}>{s}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function TeamPage() {
  const [data, setData] = useState<TeamCoaching | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.teamCoaching().then(setData).catch(() => setErr(true));
  }, []);

  return (
    <main className="container">
      <h1 style={{ fontSize: 28, letterSpacing: "-0.025em", margin: "4px 0 6px" }}>Team coaching</h1>
      <p style={{ color: "var(--muted)", maxWidth: 680, lineHeight: 1.6, marginTop: 0 }}>
        How the team is handling calls — average scores across every analyzed meeting, trends over
        time, and the most common areas to coach. Score more calls from each meeting&apos;s coaching panel.
      </p>

      {err ? (
        <div className="card empty">Couldn&apos;t load team data.</div>
      ) : !data ? (
        <div className="card empty">Loading…</div>
      ) : data.reps.length === 0 ? (
        <div className="card empty">
          No scored calls yet. Open a finished meeting and hit <b>🎯 Score this call</b> — reps appear here once they have scored calls.
        </div>
      ) : (
        <>
          <div className="meta-strip" style={{ marginTop: 0, marginBottom: 18 }}>
            <div className="metric"><div className="v">{data.reps.length}</div><div className="l">Reps</div></div>
            <div className="metric"><div className="v">{data.scored_calls}</div><div className="l">Calls scored</div></div>
            <div className="metric">
              <div className="v good">{Math.round(data.reps.reduce((a, r) => a + r.avg_score, 0) / data.reps.length)}</div>
              <div className="l">Team avg</div>
            </div>
          </div>
          {data.reps.map((rep, i) => <RepCard key={rep.rep_name} rep={rep} rank={i + 1} />)}
        </>
      )}
    </main>
  );
}
