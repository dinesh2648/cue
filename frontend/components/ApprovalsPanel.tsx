"use client";

import { useState } from "react";
import type { ProposedAction } from "@/lib/types";

const KIND_ICON: Record<string, string> = {
  note: "📝",
  task: "✅",
  email: "✉️",
  document: "📎",
  workflow: "⚙️",
  ticket: "🎫",
  pr: "🔀",
};

export default function ApprovalsPanel({
  actions,
  onApprove,
  onReject,
  onApproveAll,
}: {
  actions: ProposedAction[];
  onApprove: (id: string) => Promise<void>;
  onReject: (id: string) => Promise<void>;
  onApproveAll: () => Promise<void>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const pending = actions.filter((a) => a.status === "proposed");

  const wrap = (id: string, fn: () => Promise<void>) => async () => {
    setBusy(id);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ marginTop: 26 }}>
      <h2 className="section-title" style={{ display: "flex", alignItems: "center", gap: 10 }}>
        ✅ Approvals — approve-then-act
        {pending.length > 0 && (
          <button className="btn primary sm" disabled={busy === "all"} onClick={wrap("all", onApproveAll)}>
            {busy === "all" ? "Approving…" : `Approve all (${pending.length})`}
          </button>
        )}
      </h2>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -6, marginBottom: 14, maxWidth: 680, lineHeight: 1.6 }}>
        Nothing is written to your systems until you approve it. Each action runs as you, via your
        own connection.
      </p>

      <div className="approvals">
        {actions.map((a) => (
          <div key={a.id} className={`approval ${a.status}`}>
            <span className="ak-icon">{KIND_ICON[a.kind] ?? "•"}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="ak-title">{a.title}</div>
              <div className="ak-meta">
                {a.kind} · {a.write ? "write" : "read"}
                {a.status === "executed" && <span className="ak-done"> · ✓ done</span>}
                {a.status === "rejected" && <span className="ak-rej"> · rejected</span>}
                {a.status === "failed" && <span className="ak-rej"> · failed</span>}
              </div>
            </div>
            {a.status === "proposed" ? (
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn primary sm" disabled={busy === a.id} onClick={wrap(a.id, () => onApprove(a.id))}>
                  Approve
                </button>
                <button className="btn sm" disabled={busy === a.id} onClick={wrap(a.id, () => onReject(a.id))}>
                  Reject
                </button>
              </div>
            ) : (
              <span className={`pill ${a.status === "executed" ? "live" : ""}`}>
                {a.status === "executed" ? "approved" : a.status}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
