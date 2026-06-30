"use client";

import { useState } from "react";
import type { ProposedAction } from "@/lib/types";

const KIND_ICON: Record<string, string> = {
  note: "📝",
  task: "✅",
  email: "✉️",
  jira_ticket: "🎫",
  notion_doc: "📑",
  reminder: "⏰",
  document: "📎",
  workflow: "⚙️",
  ticket: "🎫",
  pr: "🔀",
};

// kind → the payload field the rep can edit before approving
const EDITABLE: Record<string, string> = {
  email: "draft", note: "body", task: "title",
  notion_doc: "body", jira_ticket: "description",
};

function originalValue(a: ProposedAction): string {
  const p = (a.payload || {}) as Record<string, unknown>;
  if (a.kind === "email") return String(p.draft || p.body || a.title || "");
  const f = EDITABLE[a.kind];
  return f ? String(p[f] || a.title || "") : "";
}

export default function ApprovalsPanel({
  actions,
  onApprove,
  onReject,
  onApproveAll,
}: {
  actions: ProposedAction[];
  onApprove: (id: string, payload?: Record<string, unknown>) => Promise<void>;
  onReject: (id: string) => Promise<void>;
  onApproveAll: () => Promise<void>;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});
  const pending = actions.filter((a) => a.status === "proposed");

  const wrap = (id: string, fn: () => Promise<void>) => async () => {
    setBusy(id);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  };
  const toggle = (id: string) => setOpen((o) => ({ ...o, [id]: !o[id] }));

  const approve = (a: ProposedAction) => {
    const field = EDITABLE[a.kind];
    let payload: Record<string, unknown> | undefined;
    if (field) {
      const val = edits[a.id] ?? originalValue(a);
      payload = { [field]: val };
    }
    return onApprove(a.id, payload);
  };

  const detail = (a: ProposedAction) => {
    const editable = EDITABLE[a.kind] && a.status === "proposed";
    const value = edits[a.id] ?? originalValue(a);
    const result = a.result as Record<string, unknown> | undefined;
    return (
      <div className="approval-detail">
        {EDITABLE[a.kind] ? (
          editable ? (
            <>
              <textarea
                className="approval-edit"
                value={value}
                rows={Math.min(18, Math.max(4, value.split("\n").length + 1))}
                onChange={(e) => setEdits((m) => ({ ...m, [a.id]: e.target.value }))}
              />
              <div className="ak-edit-hint">Edit before approving — your changes are what gets written.</div>
            </>
          ) : (
            <pre className="approval-body">{value}</pre>
          )
        ) : (
          (() => {
            const p = (a.payload || {}) as Record<string, unknown>;
            const entries = Object.entries(p).filter(([, v]) => v !== "" && v != null);
            return entries.length ? (
              <div className="approval-body">
                {entries.map(([k, v]) => (
                  <div key={k} style={{ marginBottom: 4 }}>
                    <b style={{ color: "var(--muted)" }}>{k}:</b>{" "}
                    {typeof v === "string" ? v : JSON.stringify(v)}
                  </div>
                ))}
              </div>
            ) : (
              <div className="approval-body" style={{ color: "var(--faint)" }}>No additional details.</div>
            );
          })()
        )}
        {a.status === "executed" && result && Boolean(result.crm_id || result.url || result.status) && (
          <div style={{ marginTop: 8, fontSize: 12, color: "var(--green, #34d399)" }}>
            ✓ {result.status ? String(result.status) : "written"}
            {result.crm_id ? ` · id ${String(result.crm_id)}` : ""}
            {result.url ? <> · <a href={String(result.url)} target="_blank" rel="noreferrer">open</a></> : null}
          </div>
        )}
        {a.status === "failed" && a.error && (
          <div style={{ marginTop: 8, fontSize: 12, color: "var(--red, #f87171)" }}>✗ {a.error}</div>
        )}
      </div>
    );
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
        Nothing is written until you approve. Click any item to review — and edit — the full content
        first. Each action runs as you, via your own connection.
      </p>

      <div className="approvals">
        {actions.map((a) => (
          <div key={a.id} className={`approval ${a.status}`}>
            <div className="approval-row">
              <button className="approval-head" onClick={() => toggle(a.id)} aria-expanded={!!open[a.id]} title="Show details">
                <span className="ak-chevron">{open[a.id] ? "▾" : "▸"}</span>
                <span className="ak-icon">{KIND_ICON[a.kind] ?? "•"}</span>
                <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                  <span className="ak-title">{a.title}</span>
                  <span className="ak-meta">
                    {a.kind} · {a.write ? "write" : "read"}
                    {EDITABLE[a.kind] && a.status === "proposed" && <span> · editable</span>}
                    {a.status === "executed" && <span className="ak-done"> · ✓ done</span>}
                    {a.status === "rejected" && <span className="ak-rej"> · rejected</span>}
                    {a.status === "failed" && <span className="ak-rej"> · failed</span>}
                  </span>
                </span>
              </button>
              {a.status === "proposed" ? (
                <div style={{ display: "flex", gap: 8 }}>
                  <button className="btn primary sm" disabled={busy === a.id} onClick={wrap(a.id, () => approve(a))}>
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
            {open[a.id] && detail(a)}
          </div>
        ))}
      </div>
    </div>
  );
}
