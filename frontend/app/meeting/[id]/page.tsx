"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api, meetingSocket } from "@/lib/api";
import type { Meeting, Segment, Suggestion, Summary, WSEvent, ProposedAction, Action, MeetingPrepRecord } from "@/lib/types";
import SuggestionCard from "@/components/SuggestionCard";
import SummaryPanel from "@/components/SummaryPanel";
import ApprovalsPanel from "@/components/ApprovalsPanel";
import ScorecardPanel from "@/components/ScorecardPanel";
import { Markdown } from "@/components/MeetingPrepPanel";

export default function MeetingConsole() {
  const params = useParams();
  const id = String(params.id);

  const [meeting, setMeeting] = useState<Meeting | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [status, setStatus] = useState<string>("scheduled");
  const [summary, setSummary] = useState<Summary | null>(null);
  const [actions, setActions] = useState<ProposedAction[]>([]);
  const [thinking, setThinking] = useState(false);
  const [ending, setEnding] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [recBusy, setRecBusy] = useState(false);
  const [prep, setPrep] = useState<MeetingPrepRecord | null>(null);
  const [prepOpen, setPrepOpen] = useState(false);

  const flash = (m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 3000);
  };
  const openRecording = async () => {
    setRecBusy(true);
    try {
      const r = await api.recording(id);
      if (r.url) window.open(r.url, "_blank", "noopener");
      else flash(r.status === "processing" ? "Recording is still processing — try again shortly." : "No recording available for this meeting.");
    } catch {
      flash("Couldn't load the recording.");
    } finally {
      setRecBusy(false);
    }
  };
  const jumpTo = (sel: string) => document.querySelector(sel)?.scrollIntoView({ behavior: "smooth", block: "start" });

  const refreshActions = () => api.listActions(id).then(setActions).catch(() => {});
  const proposeAction = async (action: Action) => {
    await api.proposeAction(id, action);
    refreshActions();
  };
  const approveAction = async (aid: string, payload?: Record<string, unknown>) => {
    await api.approveAction(aid, payload);
    refreshActions();
  };
  const rejectAction = async (aid: string) => {
    await api.rejectAction(aid);
    refreshActions();
  };
  const approveAll = async () => {
    await api.approveAll(id);
    refreshActions();
  };

  const wsRef = useRef<WebSocket | null>(null);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const suggestRef = useRef<HTMLDivElement | null>(null);

  // Initial load + WebSocket
  useEffect(() => {
    let alive = true;
    (async () => {
      const m = await api.getMeeting(id);
      if (!alive) return;
      setMeeting(m);
      setStatus(m.status);
      const [t, s] = await Promise.all([api.transcript(id), api.suggestions(id)]);
      if (!alive) return;
      setSegments(t);
      setSuggestions(s);
      api.listActions(id).then((acts) => alive && setActions(acts)).catch(() => {});
      api.meetingPrepRecord(id).then((p) => alive && p.found && setPrep(p)).catch(() => {});
      if (m.status === "ended") {
        api.summary(id).then(setSummary).catch(() => {});
      }

      const ws = await meetingSocket(id);
      if (!alive) {
        ws.close();
        return;
      }
      wsRef.current = ws;
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data) as WSEvent;
        switch (msg.type) {
          case "transcript":
            setSegments((prev) => [...prev, msg.data]);
            if (msg.data.role === "customer") setThinking(true);
            break;
          case "intent":
            if (!msg.data.actionable) setThinking(false);
            break;
          case "suggestion":
            setSuggestions((prev) => [...prev, msg.data]);
            setThinking(false);
            break;
          case "suggestion_update":
            setSuggestions((prev) => prev.map((s) => (s.id === msg.data.id ? msg.data : s)));
            break;
          case "status":
            setStatus(msg.data.status);
            if (msg.data.status === "transcript_complete") setThinking(false);
            break;
          case "summary":
            setSummary(msg.data);
            break;
          case "error":
            setToast(msg.data.message);
            break;
        }
      };

      // Auto-start if navigated from the dashboard CTA
      const autostart = new URLSearchParams(window.location.search).get("autostart");
      if (autostart && m.status === "scheduled") {
        ws.onopen = () => api.start(id).catch(() => {});
      }
    })();

    return () => {
      alive = false;
      wsRef.current?.close();
    };
  }, [id]);

  // Auto-scroll
  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight, behavior: "smooth" });
  }, [segments, thinking]);
  useEffect(() => {
    suggestRef.current?.scrollTo({ top: suggestRef.current.scrollHeight, behavior: "smooth" });
  }, [suggestions]);

  const endMeeting = async () => {
    setEnding(true);
    try {
      const s = await api.end(id);
      setSummary(s);
      setStatus("ended");
      refreshActions();
      setToast("Meeting ended — review & approve the proposed updates below");
      setTimeout(() => setToast(null), 2800);
    } finally {
      setEnding(false);
    }
  };

  const avgConfidence =
    suggestions.length > 0
      ? Math.round((suggestions.reduce((a, s) => a + s.confidence, 0) / suggestions.length) * 100)
      : 0;

  return (
    <main className="container">
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 18, flexWrap: "wrap" }}>
        <Link href="/" className="btn ghost sm">
          ← Meetings
        </Link>
        <div style={{ flex: 1, minWidth: 200 }}>
          <h2 style={{ margin: 0, fontSize: 20, letterSpacing: "-0.02em" }}>
            {meeting?.title ?? "Meeting"}
          </h2>
          <div style={{ color: "var(--faint)", fontSize: 13, marginTop: 3 }}>
            {meeting?.customer_company} · {meeting?.customer_contact} · with {meeting?.rep_name}
            {meeting?.pack ? (
              <span style={{ textTransform: "capitalize" }}> · {meeting.pack} pack</span>
            ) : null}
          </div>
        </div>
        <span className={`pill ${status === "transcript_complete" ? "scheduled" : status}`}>
          <span className="led" />
          {status === "transcript_complete" ? "ready to wrap" : status}
        </span>
        {prep?.found && (
          <button
            className={`btn ghost sm ${prepOpen ? "active" : ""}`}
            onClick={() => setPrepOpen((v) => !v)}
            title="Preparation notes researched before this meeting"
          >
            {prepOpen ? "▾ Prep notes" : "📋 Prep notes"}
          </button>
        )}
        {meeting?.recall_bot_id && (
          <button className="btn ghost sm" onClick={openRecording} disabled={recBusy} title="Open the meeting recording">
            {recBusy ? "Opening…" : "📹 Recording"}
          </button>
        )}
        <button className="btn ghost sm" onClick={() => jumpTo(".transcript-body")} title="Jump to transcript">
          📄 Transcript
        </button>
        {summary && (
          <button className="btn ghost sm" onClick={() => jumpTo(".summary-panel")} title="Jump to notes / summary">
            📝 Notes
          </button>
        )}
        {status !== "ended" && (
          <button className="btn danger" onClick={endMeeting} disabled={ending}>
            {ending ? "Generating…" : "⏹  End & summarize"}
          </button>
        )}
      </div>

      {prep?.found && prepOpen && (
        <div className="prep-panel" style={{ borderRadius: 12, border: "1px solid var(--accent)", marginBottom: 18 }}>
          <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>
            📋 Prepared before this meeting{prep.customer ? ` · ${prep.customer}` : ""}
          </div>
          <Markdown md={prep.markdown || ""} />
          {(prep.sources?.length ?? 0) > 0 && (
            <div className="prep-sources" style={{ marginTop: 12, paddingTop: 10, borderTop: "1px solid var(--border)" }}>
              {prep.sources!.map((s, i) => (
                <span key={i} className="source-chip" title={s.detail}>{s.label}</span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="meta-strip" style={{ marginTop: 0, marginBottom: 18 }}>
        <div className="metric">
          <div className="v">{suggestions.length}</div>
          <div className="l">Answers surfaced</div>
        </div>
        <div className="metric">
          <div className="v good">{avgConfidence}%</div>
          <div className="l">Avg confidence</div>
        </div>
        <div className="metric">
          <div className="v">{segments.length}</div>
          <div className="l">Transcript turns</div>
        </div>
      </div>

      <div className="console">
        {/* Transcript */}
        <div className="panel">
          <div className="panel-head">
            <span style={{ fontSize: 16 }}>🎧</span>
            <h3>Live transcript</h3>
            <span className="spacer" style={{ flex: 1 }} />
            {status === "live" && (
              <span className="thinking" style={{ padding: 0 }}>
                <i />
                <i />
                <i />
              </span>
            )}
          </div>
          <div className="panel-body transcript-body" ref={transcriptRef}>
            {segments.length === 0 && (
              <div className="empty">Waiting for the meeting to start…</div>
            )}
            {segments.map((seg) => (
              <div key={seg.id} className={`turn ${seg.role}`}>
                <span className="who">{seg.speaker}</span>
                <div className="bubble">{seg.text}</div>
              </div>
            ))}
            {thinking && (
              <div className="turn customer">
                <span className="who">Copilot</span>
                <div className="bubble" style={{ background: "transparent", border: "none" }}>
                  <span className="thinking">
                    analyzing <i /> <i /> <i />
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Copilot suggestions */}
        <div className="panel">
          <div className="panel-head">
            <span style={{ fontSize: 16 }}>💡</span>
            <h3>Copilot suggestions</h3>
            <span className="spacer" style={{ flex: 1 }} />
            <span className="pill">{suggestions.length}</span>
          </div>
          <div className="panel-body suggest-body" ref={suggestRef}>
            {suggestions.length === 0 ? (
              <div className="empty">
                When the customer asks something, the copilot&apos;s grounded answer will appear
                here — with sources and a confidence score, in seconds.
              </div>
            ) : (
              suggestions.map((s) => (
                <SuggestionCard key={s.id} s={s} onPropose={proposeAction} repName={meeting?.rep_name} />
              ))
            )}
          </div>
        </div>
      </div>

      {actions.length > 0 && (
        <ApprovalsPanel
          actions={actions}
          onApprove={approveAction}
          onReject={rejectAction}
          onApproveAll={approveAll}
        />
      )}

      {summary && <SummaryPanel summary={summary} />}

      {status === "ended" && <ScorecardPanel meetingId={id} />}

      {toast && <div className="toast">{toast}</div>}
    </main>
  );
}
