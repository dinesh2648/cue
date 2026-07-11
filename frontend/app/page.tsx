"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { Meeting, Metrics, UpcomingMeetings, CalendarEvent } from "@/lib/types";
import MeetingPrepPanel from "@/components/MeetingPrepPanel";

const PIPELINE = [
  { icon: "🎧", title: "Listen", sub: "Live meeting transcript" },
  { icon: "🎯", title: "Detect intent", sub: "The real question — sales or technical" },
  { icon: "🔎", title: "Retrieve", sub: "CRM · docs · Jira · GitHub · Slack" },
  { icon: "💡", title: "Suggest", sub: "Grounded answer · sources · confidence" },
  { icon: "🔄", title: "Automate", sub: "Notes, tickets, tasks & follow-ups" },
];

const PAGE_SIZE = 8;

export default function Home() {
  const router = useRouter();
  const [recent, setRecent] = useState<{ items: Meeting[]; total: number }>({ items: [], total: 0 });
  const [live, setLive] = useState<Meeting[]>([]);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [starting, setStarting] = useState(false);
  const [recallEnabled, setRecallEnabled] = useState(false);
  const [meetUrl, setMeetUrl] = useState("");
  const [joining, setJoining] = useState(false);
  const [joiningId, setJoiningId] = useState<string | null>(null);
  const [limitMsg, setLimitMsg] = useState<string | null>(null);
  const [upcoming, setUpcoming] = useState<UpcomingMeetings | null>(null);
  const [recBusy, setRecBusy] = useState<string | null>(null);
  const [prepOpen, setPrepOpen] = useState<Record<string, boolean>>({});
  // Recent-meetings filters + pagination
  const [q, setQ] = useState("");
  const [days, setDays] = useState(0); // 0 = all time
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  // Upcoming-calendar range window
  const [calDays, setCalDays] = useState(30);
  // Dashboard meetings sub-menu: which list is shown
  const [tab, setTab] = useState<"upcoming" | "recent">("upcoming");

  const openRecording = async (mid: string) => {
    setRecBusy(mid);
    try {
      const r = await api.recording(mid);
      if (r.url) window.open(r.url, "_blank", "noopener");
      else alert(r.status === "processing" ? "Recording is still processing — try again shortly." : "No recording available for this meeting.");
    } catch {
      alert("Couldn't load the recording.");
    } finally {
      setRecBusy(null);
    }
  };

  useEffect(() => {
    api.metrics().then(setMetrics).catch(() => {});
    api.authConfig().then((c) => setRecallEnabled(c.recall_enabled)).catch(() => {});
  }, []);

  // Reset to the first page whenever a filter changes.
  useEffect(() => { setPage(0); }, [q, days, status]);

  // Load (and poll) the filtered recent list, live meetings, and the calendar window.
  useEffect(() => {
    let alive = true;
    const loadRecent = () =>
      api.listMeetings({ limit: PAGE_SIZE, offset: page * PAGE_SIZE, q, status, days })
        .then((r) => alive && setRecent(r)).catch(() => {});
    const loadLive = () =>
      api.listMeetings({ status: "live", limit: 20 }).then((r) => alive && setLive(r.items)).catch(() => {});
    const loadCal = () => api.upcomingMeetings(calDays).then((u) => alive && setUpcoming(u)).catch(() => {});

    const t = setTimeout(loadRecent, q ? 300 : 0); // small debounce while typing a search
    loadLive();
    loadCal();
    const poll = setInterval(() => { loadRecent(); loadLive(); loadCal(); }, 20000);
    return () => { alive = false; clearTimeout(t); clearInterval(poll); };
  }, [page, q, status, days, calDays]);

  const liveMeetings = live;

  const sendToEvent = async (ev: CalendarEvent) => {
    if (!ev.meeting_url) return;
    setJoiningId(ev.id);
    setLimitMsg(null);
    try {
      const m = await api.joinLive(ev.meeting_url, {
        title: ev.title,
        customer_contact: ev.attendees.find((a) => a !== ev.organizer) || "",
      });
      router.push(`/meeting/${m.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) setLimitMsg(e.detail);
      setJoiningId(null);
    }
  };

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

  const greeting = (() => {
    const h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  })();
  const today = new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" }).toUpperCase();

  return (
    <main className="container">
      <div className="dash-head">
        <div style={{ flex: 1, minWidth: 280 }}>
          <div className="dash-eyebrow">{today}</div>
          <h1 className="dash-title">{greeting}</h1>
          <div className="dash-sub">
            {liveMeetings.length > 0 ? (
              <><b>{liveMeetings.length}</b> live now · </>
            ) : null}
            Your real-time AI copilot, in every meeting.
          </div>
        </div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <button className="btn primary" onClick={startDemo} disabled={starting}>
            {starting ? "Starting…" : "▶  Start demo meeting"}
          </button>
          <Link href="/connections" className="btn ghost">🔌 Connect your tools</Link>
        </div>
      </div>

      {limitMsg && (
        <div className="crm-banner" style={{ background: "rgba(199,122,0,0.10)", borderColor: "#E0C084", color: "#8A5A00", marginBottom: 18 }}>
          <span style={{ fontSize: 18 }}>⚡</span>
          <div>
            {limitMsg}{" "}
            <Link href="/settings" style={{ textDecoration: "underline", fontWeight: 700 }}>Upgrade →</Link>
          </div>
        </div>
      )}

      {metrics && (
        <div className="kpi-grid">
          <div className="kpi-card">
            <div className="kpi-top"><span>Avg. response</span><span>⚡</span></div>
            <div className="kpi-val">{(metrics.avg_latency_ms / 1000).toFixed(1)}s</div>
            <div className="kpi-delta good">Within {Math.round(metrics.response_sla_ms / 1000)}s SLA · {metrics.sla_compliance_pct}%</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-top"><span>Grounded in sources</span><span>✓</span></div>
            <div className="kpi-val">{metrics.grounded_pct}%</div>
            <div className="kpi-delta good">cited, not invented</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-top"><span>Answers surfaced</span><span>💡</span></div>
            <div className="kpi-val">{metrics.suggestions}</div>
            <div className="kpi-delta mut">across your meetings</div>
          </div>
          <div className="kpi-card">
            <div className="kpi-top"><span>Meetings run</span><span>📹</span></div>
            <div className="kpi-val">{metrics.meetings}</div>
            <div className="kpi-delta mut">in this workspace</div>
          </div>
        </div>
      )}

      <section style={{ marginBottom: 18 }}>
        <div className="card pad" style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <input
            className="meet-input"
            placeholder="Paste a Google Meet / Zoom / Teams link to send the copilot…"
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

      {liveMeetings.length > 0 && (
        <section style={{ marginBottom: 30 }}>
          <div className="section-title">🔴 Live now</div>
          <div className="meeting-list">
            {liveMeetings.map((m) => (
              <div key={m.id} className="meeting-row" style={{ borderColor: "var(--accent)" }}>
                <span className="led" style={{ background: "var(--red, #f87171)" }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="title">{m.title}</div>
                  <div className="sub">
                    {m.customer_company || m.customer_contact || "in progress"}
                    {m.recall_bot_id ? " · 🤖 AL Copilot dispatched" : ""}
                  </div>
                </div>
                <Link href={`/meeting/${m.id}`} className="btn primary sm">
                  Open live transcript →
                </Link>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="dash-grid">
        <div>
          {/* Sub-menu: switch between the calendar and past meetings */}
          <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--border)", marginBottom: 16 }}>
            {([["upcoming", "📅 Upcoming meetings"], ["recent", "🕘 Recent meetings"]] as const).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setTab(k)}
                style={{
                  background: "none", border: "none", cursor: "pointer",
                  padding: "8px 4px", marginRight: 18, fontSize: 14,
                  fontWeight: 700, color: tab === k ? "var(--accent)" : "var(--muted)",
                  borderBottom: tab === k ? "2px solid var(--accent)" : "2px solid transparent",
                  marginBottom: -1,
                }}
              >
                {label}
                {k === "recent" && recent.total > 0 ? ` (${recent.total})` : ""}
              </button>
            ))}
          </div>

      {tab === "upcoming" && (
      <section style={{ marginBottom: 4 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap", marginBottom: 12 }}>
          <span style={{ color: "var(--muted)", fontSize: 13 }}>From your Google Calendar</span>
          <select
            className="meet-input"
            style={{ width: "auto", padding: "6px 12px", fontSize: 13 }}
            value={calDays}
            onChange={(e) => setCalDays(Number(e.target.value))}
            aria-label="Calendar range"
          >
            <option value={7}>Next 7 days</option>
            <option value={30}>Next 30 days</option>
            <option value={90}>Next 90 days</option>
          </select>
        </div>
        {upcoming === null ? (
          <div className="card empty">Loading your calendar…</div>
        ) : !upcoming.connected ? (
          <div className="card empty">
            <Link href="/connections" style={{ color: "var(--accent)", fontWeight: 700 }}>Connect Google Calendar</Link>{" "}
            to see your upcoming meetings here and send the copilot in one click.
          </div>
        ) : upcoming.error ? (
          <div className="card empty">
            {upcoming.error === "api_disabled" ? (
              <>
                Calendar connected, but the <b>Google Calendar API</b> isn&apos;t enabled in your Google Cloud
                project. Enable it (APIs &amp; Services → Library → Google Calendar API), then reload.
              </>
            ) : upcoming.error === "demo_connection" ? (
              <>This is a demo connection. Reconnect Google Calendar with your <b>real Google account</b> to see live events.</>
            ) : upcoming.error === "permission" ? (
              <>Calendar connected, but access was denied. Reconnect and grant calendar read permission.</>
            ) : (
              <>Couldn&apos;t load your calendar right now. Try reconnecting Google Calendar.</>
            )}
          </div>
        ) : upcoming.events.length === 0 ? (
          <div className="card empty">No meetings on your calendar in the next {upcoming.days ?? calDays} days.</div>
        ) : (
          <div className="meeting-list">
            {upcoming.events.map((ev) => (
              <div key={ev.id} className={`meeting-card ${prepOpen[ev.id] ? "open" : ""}`}>
                <div className="meeting-row">
                  <span style={{ fontSize: 20 }}>{ev.meeting_url ? "📹" : "📅"}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="title">{ev.title}</div>
                    <div className="sub">
                      {ev.start ? new Date(ev.start).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: ev.all_day ? undefined : "numeric", minute: ev.all_day ? undefined : "2-digit" }) : "—"}
                      {ev.attendees.length > 0 && ` · ${ev.attendees.length} attendee${ev.attendees.length > 1 ? "s" : ""}`}
                    </div>
                  </div>
                  <button
                    className={`btn sm ${prepOpen[ev.id] ? "primary" : ""}`}
                    title="Preparation notes — researched from your connected tools, docs, emails & prior meetings"
                    onClick={() => setPrepOpen((o) => ({ ...o, [ev.id]: !o[ev.id] }))}
                  >
                    {prepOpen[ev.id] ? "▾ Prep notes" : "📋 Prep notes"}
                  </button>
                  {ev.meeting_url ? (
                    <button
                      className="btn primary sm"
                      disabled={!recallEnabled || joiningId === ev.id}
                      title={recallEnabled ? "Send the copilot to this meeting" : "Set RECALL_API_KEY to enable live capture"}
                      onClick={() => sendToEvent(ev)}
                    >
                      {joiningId === ev.id ? "Dispatching…" : "🤖 Send copilot"}
                    </button>
                  ) : (
                    <span className="source-chip" title="No video link found on this event">no link</span>
                  )}
                </div>
                {prepOpen[ev.id] && <MeetingPrepPanel eventId={ev.id} />}
              </div>
            ))}
          </div>
        )}
      </section>
      )}

      {tab === "recent" && (
        <div className="list-card">
          <div className="list-card-head" style={{ flexWrap: "wrap", gap: 8 }}>
            <span className="t">Recent meetings</span>
            <span style={{ color: "var(--faint)", fontSize: 12, fontWeight: 400 }}>{recent.total} total</span>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", padding: "0 2px 12px" }}>
            <input
              className="meet-input"
              style={{ flex: 1, minWidth: 130, padding: "7px 11px", fontSize: 13 }}
              placeholder="Search title or customer…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
            <select className="meet-input" style={{ width: "auto", padding: "7px 10px", fontSize: 13 }} value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Date range">
              <option value={0}>All time</option>
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
            </select>
            <select className="meet-input" style={{ width: "auto", padding: "7px 10px", fontSize: 13 }} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
              <option value="">Any status</option>
              <option value="live">Live</option>
              <option value="ended">Ended</option>
              <option value="scheduled">Scheduled</option>
            </select>
          </div>
          {recent.total === 0 ? (
            <div className="empty">
              {q || status || days
                ? "No meetings match your filters."
                : <>No meetings yet. Hit <b>Start demo meeting</b> to watch the copilot work a live call.</>}
            </div>
          ) : (
            <>
              {recent.items.map((m) => {
                const label = (m.customer_company || m.title || "?").trim();
                const initials = label.split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
                return (
                  <div key={m.id} className="rm-row">
                    <span className="rm-avatar">{initials}</span>
                    <Link href={`/meeting/${m.id}`} className="rm-main" style={{ textDecoration: "none", color: "inherit" }}>
                      <div className="rm-title">{m.title}</div>
                      <div className="rm-sub">{m.customer_company || "—"} · {new Date(m.created_at).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</div>
                    </Link>
                    <span className={`pill ${m.status}`}><span className="led" />{m.status}</span>
                    {m.recall_bot_id && (
                      <button className="btn ghost sm" disabled={recBusy === m.id} onClick={() => openRecording(m.id)} title="Open recording">
                        {recBusy === m.id ? "…" : "📹"}
                      </button>
                    )}
                  </div>
                );
              })}
              {recent.total > PAGE_SIZE && (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginTop: 12, fontSize: 13 }}>
                  <button className="btn ghost sm" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>← Prev</button>
                  <span style={{ color: "var(--muted)" }}>
                    {page * PAGE_SIZE + 1}–{page * PAGE_SIZE + recent.items.length} of {recent.total}
                  </span>
                  <button className="btn ghost sm" disabled={(page + 1) * PAGE_SIZE >= recent.total} onClick={() => setPage((p) => p + 1)}>Next →</button>
                </div>
              )}
            </>
          )}
        </div>
      )}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div className="navy-card">
            <div className="nc-head">✦ How Cue works</div>
            {PIPELINE.map((p, i) => (
              <div className="nc-step" key={p.title}>
                <span className="nc-num">{i + 1}</span>
                <div><b>{p.title}</b> — {p.sub}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
