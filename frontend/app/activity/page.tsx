"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { ActionHistoryItem } from "@/lib/types";

const ICON: Record<string, string> = {
  note: "📝", task: "✅", email: "✉️", jira_ticket: "🎫", notion_doc: "📑",
  reminder: "⏰", document: "📎", workflow: "⚙️", ticket: "🎫", pr: "🔀",
};

const STATUS: Record<string, { label: string; color: string }> = {
  executed: { label: "written", color: "var(--green, #12946a)" },
  undone: { label: "undone", color: "var(--muted, #666c90)" },
  failed: { label: "failed", color: "var(--red, #ce4257)" },
};

/**
 * Activity — the audit/history of everything the copilot has written across the meetings you
 * can see. Every write is here (executed, undone, failed) with a link back to the artifact and
 * a one-click Undo where the write can still be reversed.
 */
export default function ActivityPage() {
  const [items, setItems] = useState<ActionHistoryItem[]>([]);
  const [caps, setCaps] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(() => {
    api.actionHistory().then((r) => { setItems(r.items); setLoaded(true); }).catch(() => setLoaded(true));
    api.me().then((m) => setCaps(m.capabilities || {})).catch(() => {});
  }, []);

  useEffect(() => { load(); }, [load]);

  const undo = async (id: string) => {
    setBusy(id);
    try {
      await api.undoAction(id);
      setToast("✓ Undone — the write was reversed");
      load();
    } catch {
      setToast("Couldn't undo that.");
    } finally {
      setBusy(null);
      setTimeout(() => setToast(null), 2400);
    }
  };

  const fmt = (iso: string | null) => {
    if (!iso) return "";
    try { return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }); }
    catch { return ""; }
  };

  return (
    <main className="container">
      <h1 className="page-title">Activity</h1>
      <p style={{ color: "var(--muted)", maxWidth: 680, lineHeight: 1.6, marginTop: 0 }}>
        Everything the copilot has written on your behalf — across the meetings you can see. Each item links
        back to what was created; reverse anything still undoable in one click.
      </p>

      {loaded && items.length === 0 && (
        <div className="card pad" style={{ color: "var(--muted)" }}>
          Nothing written yet. Approve an action in a meeting and it shows up here.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {items.map((a) => {
          const st = STATUS[a.status] ?? STATUS.executed;
          return (
            <div key={a.id} className="card pad" style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <span style={{ fontSize: 20 }}>{ICON[a.kind] ?? "•"}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: 14, textDecoration: a.status === "undone" ? "line-through" : "none" }}>
                  {a.title}
                </div>
                <div style={{ color: "var(--muted)", fontSize: 12.5, marginTop: 2 }}>
                  <Link href={`/meeting/${a.meeting_id}`} style={{ color: "var(--muted)" }}>{a.meeting_title}</Link>
                  {" · "}{a.kind}{a.decided_at ? ` · ${fmt(a.decided_at)}` : ""}
                  {a.status === "failed" && a.error ? ` · ${a.error}` : a.result_status ? ` · ${a.result_status}` : ""}
                </div>
              </div>
              <span className="pill" style={{ color: st.color }}><span className="led" />{st.label}</span>
              {a.url && a.status !== "undone" && (
                <a href={a.url} target="_blank" rel="noreferrer" className="btn ghost sm">open</a>
              )}
              {a.undoable && caps.action_undo !== false && (
                <button className="btn sm" disabled={busy === a.id} onClick={() => undo(a.id)} title="Reverse this write">
                  {busy === a.id ? "Undoing…" : "Undo"}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {toast && <div className="toast">{toast}</div>}
    </main>
  );
}
