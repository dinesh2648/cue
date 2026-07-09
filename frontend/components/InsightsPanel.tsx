"use client";

import { useState } from "react";
import type { Insight } from "@/lib/types";

const ICON: Record<string, string> = {
  decision_without_owner: "🧭",
  unassigned_action: "📌",
  open_question: "❓",
  risk: "⚠️",
  contradiction: "🔀",
  deadline: "⏰",
  missing_stakeholder: "👤",
  follow_up: "↩️",
};
const LABEL: Record<string, string> = {
  decision_without_owner: "Decision needs an owner",
  unassigned_action: "Unassigned action",
  open_question: "Open question",
  risk: "Risk",
  contradiction: "Contradiction",
  deadline: "Deadline",
  missing_stakeholder: "Missing stakeholder",
  follow_up: "Follow-up",
};

// Proactive insights the advisor surfaces during the meeting — non-intrusive, dismissible.
export default function InsightsPanel({ insights }: { insights: Insight[] }) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const key = (i: Insight, idx: number) => `${i.type}:${i.text}:${idx}`;
  const shown = insights.filter((i, idx) => !dismissed.has(key(i, idx)));
  if (shown.length === 0) return null;

  return (
    <div className="insights-panel">
      <div className="insights-head">
        <span>💡 Proactive insights</span>
        <span className="insights-count">{shown.length}</span>
      </div>
      <div className="insights-list">
        {insights.map((i, idx) => {
          const k = key(i, idx);
          if (dismissed.has(k)) return null;
          return (
            <div key={k} className={`insight-card sev-${i.severity}`}>
              <span className="insight-ic" aria-hidden="true">{ICON[i.type] ?? "💡"}</span>
              <div className="insight-body">
                <div className="insight-label">{LABEL[i.type] ?? "Insight"}</div>
                <div className="insight-text">{i.text}</div>
              </div>
              <button
                className="insight-dismiss"
                title="Dismiss"
                onClick={() => setDismissed((prev) => new Set(prev).add(k))}
              >
                ✕
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
