"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { Meeting, Metrics } from "@/lib/types";

const PIPELINE = [
  { icon: "🎧", title: "Listen", sub: "Live Google Meet transcript" },
  { icon: "🎯", title: "Detect intent", sub: "Pricing · contract · security · support…" },
  { icon: "🔎", title: "Retrieve", sub: "HubSpot CRM + enterprise docs" },
  { icon: "💡", title: "Suggest", sub: "Grounded answer · sources · confidence" },
  { icon: "🔄", title: "Automate", sub: "CRM notes, tasks & follow-up email" },
];

export default function Home() {
  const router = useRouter();
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [health, setHealth] = useState<{ llm_provider: string; agent_engine: string; knowledge_backend: string } | null>(null);
  const [starting, setStarting] = useState(false);
  const [recallEnabled, setRecallEnabled] = useState(false);
  const [meetUrl, setMeetUrl] = useState("");
  const [joining, setJoining] = useState(false);
  const [limitMsg, setLimitMsg] = useState<string | null>(null);

  useEffect(() => {
    api.listMeetings().then(setMeetings).catch(() => {});
    api.metrics().then(setMetrics).catch(() => {});
    api.health().then(setHealth).catch(() => {});
    api.authConfig().then((c) => setRecallEnabled(c.recall_enabled)).catch(() => {});
  }, []);

  const joinLive = async () => {
    if (!meetUrl.trim()) return;
    setJoining(true);
    try {
      const m = await api.joinLive(meetUrl.trim());
      router.push(`/meeting/${m.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) setLimitMsg(e.detail);
      setJoining(false);
    }
  };

  const startDemo = async () => {
    setStarting(true);
    setLimitMsg(null);
    try {
      const m = await api.createDemo();
      router.push(`/meeting/${m.id}?autostart=1`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) setLimitMsg(e.detail);
      setStarting(false);
    }
  };

  return (
    <main className="container">
      <section className="hero">
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--accent)", marginBottom: 12 }}>
            Sales pack
          </div>
          <h1>
            Your real-time <span className="grad">AI Sales Engineer</span>, on every call.
          </h1>
          <p>
            The copilot joins your customer meeting, follows the conversation, and the moment a
            question comes up — about the contract, security, tickets, pricing — it surfaces a
            grounded answer from your CRM and enterprise docs, with sources and a confidence score.
            Then it writes the recap back to your CRM for you.
          </p>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <button className="btn primary" onClick={startDemo} disabled={starting}>
              {starting ? "Starting…" : "▶  Start demo meeting"}
            </button>
            <Link href="/connections" className="btn ghost">
              🔌 Connect your tools
            </Link>
            {health && (
              <span className="btn ghost" style={{ cursor: "default" }}>
                <span className="pill live" style={{ border: "none", background: "transparent", padding: 0 }}>
                  <span className="led" />
                </span>
                Agent: {health.agent_engine} · retrieval: {health.knowledge_backend}
              </span>
            )}
          </div>

          {limitMsg && (
            <div className="crm-banner" style={{ background: "rgba(251,191,36,0.10)", borderColor: "#5c4a1f", color: "#fcd34d", marginTop: 16 }}>
              <span style={{ fontSize: 18 }}>⚡</span>
              <div>
                {limitMsg}{" "}
                <Link href="/settings" style={{ textDecoration: "underline", fontWeight: 700 }}>Upgrade →</Link>
              </div>
            </div>
          )}

          {metrics && (
            <div className="meta-strip">
              <div className="metric">
                <div className="v good">&lt; {Math.round(metrics.response_sla_ms / 1000)}s</div>
                <div className="l">Response SLA</div>
              </div>
              <div className="metric">
                <div className="v">{metrics.suggestions}</div>
                <div className="l">Answers surfaced</div>
              </div>
              <div className="metric">
                <div className="v good">{metrics.sla_compliance_pct}%</div>
                <div className="l">Within SLA</div>
              </div>
              <div className="metric">
                <div className="v">{metrics.meetings}</div>
                <div className="l">Meetings</div>
              </div>
            </div>
          )}
        </div>

        <div className="card pad">
          <div className="section-title">How it works</div>
          <div className="pipeline">
            {PIPELINE.map((p, i) => (
              <div key={p.title}>
                <div className="step">
                  <span className="dot">{p.icon}</span>
                  <div>
                    <b>{p.title}</b>
                    <br />
                    <span>{p.sub}</span>
                  </div>
                </div>
                {i < PIPELINE.length - 1 && <div className="arrow">↓</div>}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section style={{ marginBottom: 30 }}>
        <div className="section-title">Bring the copilot to a real call</div>
        <div className="card pad" style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <input
            className="meet-input"
            placeholder="Paste a Google Meet / Zoom / Teams link…"
            value={meetUrl}
            onChange={(e) => setMeetUrl(e.target.value)}
            disabled={!recallEnabled}
          />
          <button className="btn primary" onClick={joinLive} disabled={!recallEnabled || joining || !meetUrl.trim()}>
            {joining ? "Dispatching bot…" : "🤖 Send copilot to meeting"}
          </button>
          {!recallEnabled && (
            <span style={{ color: "var(--faint)", fontSize: 12.5 }}>
              Set <code>RECALL_API_KEY</code> to enable live meeting capture. The demo meeting works without it.
            </span>
          )}
        </div>
      </section>

      <section>
        <div className="section-title">Recent meetings</div>
        {meetings.length === 0 ? (
          <div className="card empty">
            No meetings yet. Hit <b>Start demo meeting</b> to watch the copilot work a live
            Northwind Trading expansion call.
          </div>
        ) : (
          <div className="meeting-list">
            {meetings.map((m) => (
              <Link key={m.id} href={`/meeting/${m.id}`} className="meeting-row">
                <span style={{ fontSize: 20 }}>{m.platform === "google_meet" ? "📹" : "💬"}</span>
                <div style={{ flex: 1 }}>
                  <div className="title">{m.title}</div>
                  <div className="sub">
                    {m.customer_company || "—"} · {new Date(m.created_at).toLocaleString()}
                  </div>
                </div>
                <span className={`pill ${m.status}`}>
                  <span className="led" />
                  {m.status}
                </span>
              </Link>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
