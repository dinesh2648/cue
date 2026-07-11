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

const teamLabelOf = (t: string) =>
  ({ tech: "Tech", ops: "Ops", finance: "Finance", hr: "HR", marketing: "Marketing", cs: "CS" } as Record<string, string>)[t] || "Sales";

function actionStatusColor(s: string): string {
  if (s === "executed") return "var(--green, #12946a)";
  if (s === "failed") return "var(--red, #ce4257)";
  if (s === "proposed") return "#c77a00";
  return "var(--muted, #666c90)"; // undone / rejected
}

function TeamRow({ m, days }: { m: TeamMember; days: number }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"meetings" | "activity">("meetings");
  const status = m.meeting_count > 0 ? "active" : "idle";
  const cutoff = days > 0 ? Date.now() - days * 86400000 : 0;
  const inRange = (iso: string) => !cutoff || (!!iso && new Date(iso).getTime() >= cutoff);
  const meetings = m.meetings.filter((mt) => inRange(mt.date));
  const acts = (m.recent_actions || []).filter((a) => inRange(a.when));
  const activity = m.activity;
  const hasDetail = m.meeting_count > 0 || (m.recent_actions?.length || 0) > 0;

  return (
    <>
      <div className="tt-row" onClick={() => hasDetail && setOpen(!open)}>
        <div className="tt-member">
          <span className="tt-avatar">{(m.name || m.email || "?").charAt(0).toUpperCase()}</span>
          <div style={{ minWidth: 0 }}>
            <div className="tt-name">{m.name || m.email}</div>
            <div className="tt-email">
              {m.email}
              {activity && activity.total > 0 && (
                <span style={{ color: "var(--faint)" }}> · 🗂 {activity.total} action{activity.total === 1 ? "" : "s"}</span>
              )}
            </div>
          </div>
        </div>
        <span className="tt-cell" style={{ textTransform: "capitalize" }}>{m.role} · {teamLabelOf(m.team)}</span>
        <span className="tt-cell">{m.meeting_count}</span>
        <span className="tt-score" style={{ color: m.avg_score != null ? scoreColor(m.avg_score) : "var(--faint)" }}>{m.avg_score ?? "—"}</span>
        <span className={`tt-status ${status}`}>{status === "active" ? "Active" : "No calls"}</span>
      </div>
      {open && (
        <div className="tt-expand">
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <button className={`btn sm ${tab === "meetings" ? "primary" : ""}`} onClick={() => setTab("meetings")}>
              Meetings ({meetings.length})
            </button>
            <button className={`btn sm ${tab === "activity" ? "primary" : ""}`} onClick={() => setTab("activity")}>
              Activity ({acts.length})
            </button>
          </div>

          {tab === "meetings" && (
            <>
              {meetings.map((mt) => (
                <Link key={mt.id} href={`/meeting/${mt.id}`} style={{ textDecoration: "none", color: "inherit" }}>
                  <div className="card" style={{ padding: "10px 12px", display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
                    <div style={{ flex: 1, minWidth: 180 }}>
                      <div style={{ fontWeight: 600, fontSize: 14 }}>{mt.title}</div>
                      <div style={{ color: "var(--muted)", fontSize: 12 }}>
                        {mt.customer ? `${mt.customer} · ` : ""}{fmtDate(mt.date)} · {mt.status}
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap", fontSize: 11.5, alignItems: "center" }}>
                      <span className="badge">{mt.persona === "tech" ? "Tech" : "Sales"}</span>
                      {mt.has_transcript && <span className="source-chip">📄 Transcript</span>}
                      {mt.suggestions > 0 && <span className="source-chip">💡 {mt.suggestions} live answers</span>}
                      {mt.has_summary && <span className="source-chip">📝 Summary</span>}
                      {mt.has_recording && <span className="source-chip">🎥 Recording</span>}
                      {mt.actions > 0 && <span className="source-chip">✅ {mt.actions_done}/{mt.actions} actions</span>}
                      {mt.score != null && <span className="source-chip" style={{ fontWeight: 700, color: scoreColor(mt.score) }}>⭐ {mt.score}</span>}
                    </div>
                  </div>
                </Link>
              ))}
              {meetings.length === 0 && <div style={{ color: "var(--faint)", fontSize: 13 }}>{days ? "No meetings in this range." : "No meetings yet."}</div>}
            </>
          )}

          {tab === "activity" && (
            <>
              {activity && activity.total > 0 && (
                <div style={{ display: "flex", gap: 14, flexWrap: "wrap", fontSize: 12.5, color: "var(--muted)", marginBottom: 8 }}>
                  <span>✅ {activity.executed} done</span>
                  {activity.proposed > 0 && <span style={{ color: "#c77a00" }}>◷ {activity.proposed} awaiting approval</span>}
                  {activity.undone > 0 && <span>↩ {activity.undone} undone</span>}
                  {activity.failed > 0 && <span style={{ color: "var(--red, #ce4257)" }}>✗ {activity.failed} failed</span>}
                </div>
              )}
              {acts.map((a) => (
                <div key={a.id} className="card" style={{ padding: "8px 12px", display: "flex", gap: 10, alignItems: "center", marginBottom: 6 }}>
                  <span style={{ fontSize: 16 }}>{a.icon}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13.5, fontWeight: 600, textDecoration: a.status === "undone" ? "line-through" : "none" }}>{a.title}</div>
                    <div style={{ color: "var(--muted)", fontSize: 12 }}>
                      <Link href={`/meeting/${a.meeting_id}`} style={{ color: "var(--muted)" }}>{a.meeting_title}</Link>
                      {" · "}{a.kind}{a.when ? ` · ${fmtDate(a.when)}` : ""}
                      {a.result_status ? ` · ${a.result_status}` : ""}
                    </div>
                  </div>
                  <span style={{ fontSize: 11.5, fontWeight: 700, color: actionStatusColor(a.status), textTransform: "capitalize" }}>{a.status}</span>
                  {a.url && a.status !== "undone" && (
                    <a href={a.url} target="_blank" rel="noreferrer" className="btn ghost sm">open</a>
                  )}
                </div>
              ))}
              {acts.length === 0 && <div style={{ color: "var(--faint)", fontSize: 13 }}>{days ? "No actions in this range." : "No actions taken yet."}</div>}
            </>
          )}
        </div>
      )}
    </>
  );
}

export default function TeamPage() {
  const [data, setData] = useState<TeamCoaching | null>(null);
  const [members, setMembers] = useState<TeamMember[] | null>(null);
  const [err, setErr] = useState(false);
  const [q, setQ] = useState("");
  const [days, setDays] = useState(0); // 0 = all time; filters each member's meetings + activity

  useEffect(() => {
    api.teamCoaching().then(setData).catch(() => setErr(true));
    api.teamMembers().then((d) => setMembers(d.members)).catch(() => {});
  }, []);

  const shown = (members || []).filter(
    (m) => !q.trim() || `${m.name} ${m.email}`.toLowerCase().includes(q.trim().toLowerCase())
  );

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
          <div className="kpi-grid">
            <div className="kpi-card"><div className="kpi-top"><span>Reps</span><span>◎</span></div><div className="kpi-val">{data.reps.length}</div><div className="kpi-delta mut">with scored calls</div></div>
            <div className="kpi-card"><div className="kpi-top"><span>Calls scored</span><span>✓</span></div><div className="kpi-val">{data.scored_calls}</div><div className="kpi-delta mut">across the team</div></div>
            <div className="kpi-card"><div className="kpi-top"><span>Team avg</span><span>⭐</span></div><div className="kpi-val">{Math.round(data.reps.reduce((a, r) => a + r.avg_score, 0) / data.reps.length)}</div><div className="kpi-delta good">out of 100</div></div>
            <div className="kpi-card" style={{ borderLeftColor: "var(--amber)" }}><div className="kpi-top"><span>Coaching flags</span><span>⚠</span></div><div className="kpi-val">{data.reps.filter((r) => r.avg_score < 65).length}</div><div className="kpi-delta mut">reps under 65</div></div>
          </div>
          {data.reps.map((rep, i) => <RepCard key={rep.rep_name} rep={rep} rank={i + 1} />)}
        </>
      )}

      {members && members.length > 0 && (
        <section style={{ marginTop: 32 }}>
          <h2 style={{ fontSize: 20, letterSpacing: "-0.02em", margin: "0 0 4px" }}>Team members &amp; meetings</h2>
          <p style={{ color: "var(--muted)", fontSize: 13.5, marginTop: 0, marginBottom: 14 }}>
            Everyone you can see. Click a row to open a member&apos;s <b>meetings</b> — each with its
            transcript, live answers, summary, recording and score — and their <b>activity</b>: every
            action the copilot took for them (tickets, notes, emails, docs) with its status.
          </p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
            <input
              className="meet-input"
              style={{ flex: 1, minWidth: 180, padding: "8px 12px", fontSize: 13.5 }}
              placeholder="Search a team member…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <select
              className="meet-input"
              style={{ width: "auto", padding: "8px 12px", fontSize: 13.5 }}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              aria-label="Date range for meetings & activity"
            >
              <option value={0}>All time</option>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
            </select>
          </div>
          <div className="team-table">
            <div className="tt-head"><span>Member</span><span>Role · team</span><span>Calls</span><span>Avg score</span><span>Status</span></div>
            {shown.map((m) => <TeamRow key={m.id} m={m} days={days} />)}
            {shown.length === 0 && (
              <div style={{ padding: "16px", color: "var(--faint)", fontSize: 13 }}>No members match &ldquo;{q}&rdquo;.</div>
            )}
          </div>
        </section>
      )}
    </main>
  );
}
