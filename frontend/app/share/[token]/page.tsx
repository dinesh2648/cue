"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import type { ShareBundle } from "@/lib/types";
import { Markdown } from "@/components/MeetingPrepPanel";

export default function SharePage() {
  const params = useParams();
  const token = String(params.token);
  const [bundle, setBundle] = useState<ShareBundle | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    api.publicShare(token)
      .then((b) => alive && setBundle(b))
      .catch((e) => alive && setError(e?.detail || "This link is not available."));
    return () => { alive = false; };
  }, [token]);

  if (error) {
    return (
      <main className="share-page">
        <div className="share-card share-empty">
          <div style={{ fontSize: 32 }}>🔗</div>
          <h2>Link unavailable</h2>
          <p>{error}</p>
        </div>
      </main>
    );
  }
  if (!bundle) return <main className="share-page"><div className="share-card">Loading…</div></main>;

  const { meeting, summary, prep, transcript, recording } = bundle;
  const date = meeting.date ? new Date(meeting.date).toLocaleString() : "";

  return (
    <main className="share-page">
      <div className="share-page-head">
        <span className="share-logo">🛰️ Cue</span>
        <span className="share-badge">Shared meeting</span>
      </div>

      <div className="share-card">
        <h1 className="share-title">{meeting.title || "Meeting"}</h1>
        <div className="share-sub">
          {meeting.customer_company ? `${meeting.customer_company} · ` : ""}{date}
        </div>
      </div>

      {summary && (
        <section className="share-card">
          <h2 className="share-h">📋 Executive summary</h2>
          <p className="share-para">{summary.executive_summary || "—"}</p>
          {summary.key_decisions?.length > 0 && (
            <>
              <h3 className="share-h3">Key decisions</h3>
              <ul className="share-list-ul">{summary.key_decisions.map((d, i) => <li key={i}>{d}</li>)}</ul>
            </>
          )}
          {summary.action_items?.length > 0 && (
            <>
              <h3 className="share-h3">Action items</h3>
              <ul className="share-list-ul">{summary.action_items.map((a, i) => <li key={i}>{a}</li>)}</ul>
            </>
          )}
          {summary.risks?.length > 0 && (
            <>
              <h3 className="share-h3">Risks</h3>
              <ul className="share-list-ul">{summary.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </>
          )}
          {summary.customer_concerns?.length > 0 && (
            <>
              <h3 className="share-h3">Concerns raised</h3>
              <ul className="share-list-ul">{summary.customer_concerns.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </>
          )}
          {summary.follow_up_email && (
            <>
              <h3 className="share-h3">Follow-up email</h3>
              <pre className="share-email">{summary.follow_up_email}</pre>
            </>
          )}
        </section>
      )}

      {prep && (
        <section className="share-card">
          <h2 className="share-h">📝 Prep notes</h2>
          <Markdown md={prep.markdown} />
        </section>
      )}

      {recording && (
        <section className="share-card">
          <h2 className="share-h">🎥 Recording</h2>
          {recording.url ? (
            <a className="btn primary sm" href={recording.url} target="_blank" rel="noreferrer">Open recording ↗</a>
          ) : (
            <p className="share-para" style={{ opacity: 0.7 }}>
              {recording.status === "processing" ? "Recording is still processing." : "No recording available."}
            </p>
          )}
        </section>
      )}

      {transcript && transcript.length > 0 && (
        <section className="share-card">
          <h2 className="share-h">💬 Transcript</h2>
          <div className="share-transcript">
            {transcript.map((s, i) => (
              <div key={i} className={`share-turn ${s.role}`}>
                <span className="share-who">{s.speaker}</span>
                <span className="share-text">{s.text}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="share-foot">Shared via Cue · read-only</div>
    </main>
  );
}
