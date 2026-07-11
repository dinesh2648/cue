"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { MeetingHealth } from "@/lib/types";

const STATUS: Record<string, { label: string; color: string; bg: string }> = {
  good: { label: "Grounded", color: "#12946a", bg: "rgba(18,148,106,.12)" },
  fair: { label: "Partly grounded", color: "#c77a00", bg: "rgba(199,122,0,.12)" },
  poor: { label: "Needs attention", color: "#ce4257", bg: "rgba(206,66,87,.12)" },
};

/**
 * Answer-quality + connection health for this meeting, from the caller's own suggestions.
 * A compact pill that expands into the concrete numbers + fix-it recommendations — so a
 * degraded meeting is visible and actionable instead of a vague "it felt off".
 */
export default function MeetingHealthBadge({ meetingId, live }: { meetingId: string; live?: boolean }) {
  const [h, setH] = useState<MeetingHealth | null>(null);
  const [open, setOpen] = useState(false);

  const load = useCallback(() => {
    api.meetingHealth(meetingId).then(setH).catch(() => {});
  }, [meetingId]);

  useEffect(() => {
    load();
    if (!live) return;
    const t = setInterval(load, 15000); // refresh while the meeting is live
    return () => clearInterval(t);
  }, [load, live]);

  if (!h || h.turns === 0) return null;
  const s = STATUS[h.status] ?? STATUS.fair;

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        title="Answer quality & connection health for this meeting"
        style={{
          display: "inline-flex", alignItems: "center", gap: 7, cursor: "pointer",
          border: `1px solid ${s.color}33`, background: s.bg, color: s.color,
          borderRadius: 999, padding: "5px 11px", fontSize: 12.5, fontWeight: 650,
        }}
      >
        <span style={{ width: 7, height: 7, borderRadius: "50%", background: s.color }} />
        {s.label} · {h.grounded_pct}% grounded
        <span style={{ opacity: 0.6, fontWeight: 400 }}>{open ? "▴" : "▾"}</span>
      </button>

      {open && (
        <div
          style={{
            position: "absolute", top: "calc(100% + 8px)", right: 0, zIndex: 20, width: 320,
            background: "var(--surface, #fff)", color: "var(--ink, #10132e)",
            border: "1px solid var(--line, #e3e7f2)", borderRadius: 12,
            boxShadow: "0 10px 34px rgba(16,19,46,.14)", padding: 16, fontSize: 13,
          }}
        >
          <div style={{ fontWeight: 700, marginBottom: 10 }}>Meeting health · your answers</div>

          <Row label="Answers" value={`${h.turns}`} />
          <Row label="Grounded in a real source" value={`${h.grounded}/${h.turns} · ${h.grounded_pct}%`} />
          <Row label="From your connected tools" value={`${h.scope_pct.user ?? 0}%`} />
          {(h.scope_pct.web ?? 0) > 0 && <Row label="From live web research" value={`${h.scope_pct.web}%`} />}
          {(h.scope_pct.demo ?? 0) > 0 && <Row label="Sample/demo data" value={`${h.scope_pct.demo}%`} />}
          {h.abstained > 0 && <Row label="Abstained (no data)" value={`${h.abstained}`} warn />}
          <Row label="Deep answers" value={`${h.deep_turns}/${h.turns}`} />
          {h.avg_latency_ms > 0 && <Row label="Avg first answer" value={`${h.avg_latency_ms}ms`} />}
          <Row
            label="Connectors healthy"
            value={`${h.connectors.healthy}/${h.connectors.connected}`}
            warn={h.connectors.healthy < h.connectors.connected}
          />

          {h.recommendations.length > 0 && (
            <div style={{ marginTop: 12, borderTop: "1px solid var(--line, #e3e7f2)", paddingTop: 10 }}>
              <div style={{ fontWeight: 700, fontSize: 12, color: "var(--muted, #666c90)", marginBottom: 6 }}>
                To improve
              </div>
              <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 5 }}>
                {h.recommendations.map((r, i) => (
                  <li key={i} style={{ color: "var(--ink-soft, #363b5e)", lineHeight: 1.5 }}>{r}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, value, warn }: { label: string; value: string; warn?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, padding: "3px 0" }}>
      <span style={{ color: "var(--muted, #666c90)" }}>{label}</span>
      <span style={{ fontWeight: 650, fontVariantNumeric: "tabular-nums", color: warn ? "#c77a00" : "inherit" }}>
        {value}
      </span>
    </div>
  );
}
