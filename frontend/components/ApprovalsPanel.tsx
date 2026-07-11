"use client";

import { useState } from "react";
import { api } from "@/lib/api";
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
  onUndo,
  engineering = false,
  capabilities = {},
}: {
  actions: ProposedAction[];
  onApprove: (id: string, payload?: Record<string, unknown>) => Promise<void>;
  onReject: (id: string) => Promise<void>;
  onApproveAll: () => Promise<void>;
  onUndo?: (id: string) => Promise<void>;
  engineering?: boolean; // tech-team meeting → notes/tasks file into Jira, not the CRM
  capabilities?: Record<string, boolean>;
}) {
  const cap = (k: string) => capabilities[k] !== false; // default-on if unknown
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [jiraProjects, setJiraProjects] = useState<{ key: string; name: string }[] | null>(null);
  const [jiraProj, setJiraProj] = useState<Record<string, string>>({});
  const pending = actions.filter((a) => a.status === "proposed");

  // Which actions actually write to Jira (and so should offer a project picker):
  // an explicit Jira ticket always; a note/task only when this is an engineering meeting.
  const routesToJira = (a: ProposedAction) =>
    a.kind === "jira_ticket" || (engineering && (a.kind === "task" || a.kind === "note"));

  const loadJiraProjects = () => {
    if (jiraProjects !== null) return;
    setJiraProjects([]);
    api.jiraProjects().then(setJiraProjects).catch(() => setJiraProjects([]));
  };

  const wrap = (id: string, fn: () => Promise<void>) => async () => {
    setBusy(id);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  };
  const toggle = (id: string) => {
    setOpen((o) => ({ ...o, [id]: !o[id] }));
    const a = actions.find((x) => x.id === id);
    if (a && routesToJira(a)) loadJiraProjects();
  };

  const approve = (a: ProposedAction, mode?: string) => {
    const field = EDITABLE[a.kind];
    const payload: Record<string, unknown> = {};
    if (field) payload[field] = edits[a.id] ?? originalValue(a);
    if (a.kind === "email" && mode) payload.mode = mode;
    if (routesToJira(a) && jiraProj[a.id]) payload.project_key = jiraProj[a.id];
    return onApprove(a.id, Object.keys(payload).length ? payload : undefined);
  };

  const detail = (a: ProposedAction) => {
    const editable = EDITABLE[a.kind] && a.status === "proposed";
    const value = edits[a.id] ?? originalValue(a);
    const result = a.result as Record<string, unknown> | undefined;
    const jiraPicker =
      routesToJira(a) && a.status === "proposed" ? (
        <div style={{ marginBottom: 10 }}>
          <div className="ak-edit-hint" style={{ marginTop: 0, marginBottom: 4 }}>File into Jira project</div>
          <select
            className="member-select"
            value={jiraProj[a.id] ?? String(((a.payload || {}) as Record<string, unknown>).project_key || "")}
            onChange={(e) => setJiraProj((m) => ({ ...m, [a.id]: e.target.value }))}
          >
            <option value="">
              {jiraProjects === null ? "Loading…" : jiraProjects.length ? "First available project" : "No projects — connect/authorize Jira"}
            </option>
            {(jiraProjects || []).map((pr) => (
              <option key={pr.key} value={pr.key}>{pr.key} · {pr.name}</option>
            ))}
          </select>
        </div>
      ) : null;
    return (
      <div className="approval-detail">
        {jiraPicker}
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
        {a.status === "executed" && cap("action_confirmations") && result && Boolean(result.crm_id || result.url || result.status) && (
          <div style={{ marginTop: 8, fontSize: 12, color: "var(--green, #34d399)" }}>
            ✓ {result.status ? String(result.status) : "written"}
            {result.crm_id ? ` · id ${String(result.crm_id)}` : ""}
            {result.url ? <> · <a href={String(result.url)} target="_blank" rel="noreferrer">open</a></> : null}
          </div>
        )}
        {a.status === "undone" && (
          <div style={{ marginTop: 8, fontSize: 12, color: "var(--muted)" }}>
            ↩ {result?.status ? String(result.status) : "Undone — reversed the write."}
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
                    {a.status === "undone" && <span className="ak-rej"> · undone</span>}
                    {a.status === "failed" && <span className="ak-rej"> · failed</span>}
                  </span>
                </span>
              </button>
              {a.status === "proposed" ? (
                <div style={{ display: "flex", gap: 8 }}>
                  {a.kind === "email" ? (
                    <>
                      <button className="btn sm" disabled={busy === a.id} onClick={wrap(a.id, () => approve(a, "draft"))} title="Save as a draft in your Gmail (or locally)">
                        Save draft
                      </button>
                      <button className="btn primary sm" disabled={busy === a.id} onClick={wrap(a.id, () => approve(a, "send"))} title="Send the email now via your Gmail">
                        Send
                      </button>
                    </>
                  ) : (
                    <button className="btn primary sm" disabled={busy === a.id} onClick={wrap(a.id, () => approve(a))}>
                      Approve
                    </button>
                  )}
                  <button className="btn sm" disabled={busy === a.id} onClick={wrap(a.id, () => onReject(a.id))}>
                    Reject
                  </button>
                </div>
              ) : (
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <span className={`pill ${a.status === "executed" ? "live" : ""}`}>
                    {a.status === "executed" ? "approved" : a.status}
                  </span>
                  {a.status === "executed" && a.undoable && onUndo && cap("action_undo") && (
                    <button
                      className="btn sm"
                      disabled={busy === a.id}
                      onClick={wrap(a.id, () => onUndo(a.id))}
                      title="Reverse this — delete/archive what was created"
                    >
                      {busy === a.id ? "Undoing…" : "Undo"}
                    </button>
                  )}
                </div>
              )}
            </div>
            {open[a.id] && detail(a)}
          </div>
        ))}
      </div>
    </div>
  );
}
