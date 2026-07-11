"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

/**
 * Meeting-recording player. Fetches a fresh presigned URL and plays it inline (View),
 * with a Download button and an Open-in-new-tab fallback. Handles the still-processing
 * and no-recording states so the user always knows what's going on.
 */
export default function RecordingModal({ meetingId, onClose }: { meetingId: string; onClose: () => void }) {
  const [state, setState] = useState<{ status: string; url: string | null } | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let alive = true;
    api.recording(meetingId).then((r) => alive && setState(r)).catch(() => alive && setErr(true));
    return () => { alive = false; };
  }, [meetingId]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(10,13,30,0.62)", display: "grid", placeItems: "center", zIndex: 100, padding: 20 }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="card"
        style={{ width: "min(900px, 96vw)", padding: 0, overflow: "hidden", background: "var(--surface)" }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
          <span style={{ fontWeight: 700 }}>📹 Meeting recording</span>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            {state?.url && (
              <>
                <a className="btn primary sm" href={state.url} download="meeting-recording.mp4" target="_blank" rel="noreferrer" title="Download the recording">
                  ⬇ Download
                </a>
                <a className="btn ghost sm" href={state.url} target="_blank" rel="noreferrer" title="Open in a new tab">
                  Open ↗
                </a>
              </>
            )}
            <button className="btn ghost sm" onClick={onClose} aria-label="Close">✕</button>
          </div>
        </div>

        <div style={{ background: "#000", minHeight: 220, display: "grid", placeItems: "center" }}>
          {err ? (
            <div style={{ color: "#fff", padding: 44, textAlign: "center" }}>Couldn&apos;t load the recording. Try again shortly.</div>
          ) : state === null ? (
            <div style={{ color: "#fff", padding: 44 }}>Loading recording…</div>
          ) : state.url ? (
            <video
              src={state.url}
              controls
              autoPlay
              style={{ width: "100%", maxHeight: "72vh", display: "block", background: "#000" }}
            />
          ) : (
            <div style={{ color: "#fff", padding: 44, textAlign: "center", lineHeight: 1.6 }}>
              {state.status === "processing"
                ? "Recording is still processing — check back in a few minutes."
                : "No recording available for this meeting."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
