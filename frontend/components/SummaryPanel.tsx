"use client";

import { useState } from "react";
import type { Summary } from "@/lib/types";

export default function SummaryPanel({ summary }: { summary: Summary }) {
  const [copied, setCopied] = useState(false);

  const copyEmail = async () => {
    try {
      await navigator.clipboard.writeText(summary.follow_up_email);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable */
    }
  };

  return (
    <div className="summary-panel" style={{ marginTop: 26 }}>
      <h2 className="section-title">📋 Post-meeting recap &amp; automation</h2>

      <div className="card pad">
        <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 12 }}>
          <span style={{ fontSize: 18 }}>✦</span>
          <span style={{ fontFamily: "var(--font-display)", fontWeight: 800, fontSize: 17, color: "var(--text)" }}>AI summary</span>
        </div>
        <p style={{ margin: 0, color: "var(--muted)", lineHeight: 1.65, fontSize: 14.5 }}>
          {summary.executive_summary}
        </p>
      </div>

      <div className="summary-grid">
        <div className="card pad sum-card">
          <h4>✅ Key decisions</h4>
          <ul className="sum-list">
            {summary.key_decisions.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </div>
        <div className="card pad sum-card">
          <h4>⚠️ Risks</h4>
          <ul className="sum-list risk">
            {summary.risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
        <div className="card pad sum-card">
          <h4>📌 Action items</h4>
          <ul className="sum-list">
            {summary.action_items.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
        <div className="card pad sum-card">
          <h4>🗣️ Customer concerns</h4>
          <ul className="sum-list">
            {summary.customer_concerns.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      </div>

      <div className="crm-banner">
        <span style={{ fontSize: 18 }}>🔄</span>
        <div>
          <b>CRM updates ready for approval</b> — a recap note, follow-up tasks, and a follow-up email were
          drafted and queued in <b>Approvals</b> above. Nothing is written to your CRM until you approve it.
        </div>
      </div>

      <div className="card pad" style={{ marginTop: 16 }}>
        <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
          <h4 style={{ margin: 0, fontSize: 14 }}>✉️ Follow-up email draft</h4>
          <span className="spacer" style={{ flex: 1 }} />
          <button className="btn sm" onClick={copyEmail}>
            {copied ? "✓ Copied" : "Copy"}
          </button>
        </div>
        <div className="email-box">{summary.follow_up_email}</div>
      </div>
    </div>
  );
}
