"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { TeamCoaching, TeamRep, TeamMember } from "@/lib/types";

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

function fmtDate(d: string): string {
  if (!d) return "";
  const t = new Date(d);
  return isNaN(t.getTime()) ? "" : t.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function MemberCard({ m }: { m: TeamMember }) {
  const [open, setOpen] = useState(m.meeting_count > 0 && m.meeting_count <= 4);
  const teamLabel = m.team === "tech" ? "Tech" : m.team === "ops" ? "Ops" : "Sales";
  return (
    <div className="card pad" style={{ marginBottom: 12 }}>
      <div
        style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", cursor: m.meeting_count ? "pointer" : "default" }}
        onClick={() => m.meeting_count && setOpen(!open)}
      >
        <span style={{ width: 42, height: 42, borderRadius: "50%", display: "grid", placeItems: "center", fontWeight: 800, fontSize: 16, background: "var(--surface-2)", color: "var(--muted)" }}>
          {(m.name || "?").charAt(0).toUpperCase()}
        </span>
        <div style={{ flex: 1, minWidth: 180 }}>
          <div style={{ fontWeight: 700 }}>
            {m.name} <span className="badge">{teamLabel}</span> <span className="badge">{m.role}</span>
          </div>
          <div style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 2 }}>
            {m.email} · {m.meeting_count} meeting{m.meeting_count === 1 ? "" : "s"}
            {m.avg_score != null ? <> · <span style={{ color: scoreColor(m.avg_score), fontWeight: 700 }}>avg {m.avg_score}</span></> : null}
          </div>
        </div>
        {m.meeting_count > 0 && <span style={{ color: "var(--faint)" }}>{open ? "▾" : "▸"}</span>}
      </div>

      {open && (
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
          {m.meetings.map((mt) => (
            <Link key={mt.id} href={`/meeting/${mt.id}`} style={{ textDecoration: "none", color: "inherit" }}>
              <div className="card" style={{ padding: "10px 12px", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: 180 }}>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{mt.title}</div>
                  <div style={{ color: "var(--muted)", fontSize: 12 }}>
                    {fmtDate(mt.date)} · {mt.status}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", fontSize: 11.5, alignItems: "center" }}>
                  <span className="badge">{mt.persona === "tech" ? "Tech" : "Sales"}</span>
                  {mt.has_transcript && <span className="source-chip">📄 Transcript</span>}
                  {mt.suggestions > 0 && <span className="source-chip">💡 {mt.suggestions} live answers</span>}
                  {mt.has_summary && <span className="source-chip">📝 Summary</span>}
                  {mt.has_recording && <span className="source-chip">🎥 Recording</span>}
                  {mt.score != null && <span className="source-chip" style={{ fontWeight: 700, color: scoreColor(mt.score) }}>⭐ {mt.score}</span>}
                </div>
              </div>
            </Link>
          ))}
          {m.meeting_count === 0 && <div style={{ color: "var(--faint)", fontSize: 13 }}>No meetings yet.</div>}
        </div>
      )}
    </div>
  );
}

export default function TeamPage() {
  const [data, setData] = useState<TeamCoaching | null>(null);
  const [members, setMembers] = useState<TeamMember[] | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    api.teamCoaching().then(setData).catch(() => setErr(true));
    api.teamMembers().then((d) => setMembers(d.members)).catch(() => {});
  }, []);

  return (
    <main className="container">
      <h1 className="page-title">Team coaching</h1>
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

      {members && members.length > 0 && (
        <section style={{ marginTop: 32 }}>
          <h2 style={{ fontSize: 20, letterSpacing: "-0.02em", margin: "0 0 4px" }}>Team members &amp; meetings</h2>
          <p style={{ color: "var(--muted)", fontSize: 13.5, marginTop: 0, marginBottom: 14 }}>
            Everyone you can see, with their meetings. Open any meeting for its transcript, live answers,
            summary and recording.
          </p>
          {members.map((m) => <MemberCard key={m.id} m={m} />)}
        </section>
      )}
    </main>
  );
}
