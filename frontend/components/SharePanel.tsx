"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ShareLink } from "@/lib/types";

const SCOPES: { key: string; label: string; icon: string }[] = [
  { key: "summary", label: "Executive summary", icon: "📋" },
  { key: "prep", label: "Prep notes", icon: "📝" },
  { key: "transcript", label: "Transcript", icon: "💬" },
  { key: "recording", label: "Recording", icon: "🎥" },
];

// Public share links for a meeting's artifacts — pick what to expose, copy the link, revoke anytime.
export default function SharePanel({ meetingId, onClose }: { meetingId: string; onClose: () => void }) {
  const [sel, setSel] = useState<Record<string, boolean>>({ summary: true, prep: true, transcript: true, recording: true });
  const [expires, setExpires] = useState<number | null>(30);
  const [links, setLinks] = useState<ShareLink[]>([]);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = () => api.listShares(meetingId).then(setLinks).catch(() => {});
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [meetingId]);

  const chosen = SCOPES.filter((s) => sel[s.key]).map((s) => s.key);
  const linkUrl = (l: ShareLink) =>
    typeof window !== "undefined" ? `${window.location.origin}${process.env.NEXT_PUBLIC_BASE_PATH || ""}/share/${l.token}` : l.url;

  const create = async () => {
    setBusy(true); setErr(null);
    try {
      await api.createShare(meetingId, chosen.length ? chosen : ["all"], expires);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Couldn't create link — owner/manager only.");
    } finally {
      setBusy(false);
    }
  };
  const copy = async (l: ShareLink) => {
    try { await navigator.clipboard.writeText(linkUrl(l)); setCopied(l.token); setTimeout(() => setCopied(null), 1500); } catch { /* ignore */ }
  };
  const revoke = async (token: string) => {
    try { await api.revokeShare(token); await load(); } catch { /* ignore */ }
  };

  const active = links.filter((l) => !l.revoked);

  return (
    <div className="share-overlay" onClick={onClose}>
      <div className="share-modal" onClick={(e) => e.stopPropagation()}>
        <div className="share-head">
          <span>🔗 Share meeting</span>
          <button className="share-close" onClick={onClose}>✕</button>
        </div>

        <p className="share-note">
          Creates a <b>public link</b> — anyone with it can view the selected items without signing in.
          Pick what to include, set an expiry, and revoke anytime.
        </p>

        <div className="share-scopes">
          {SCOPES.map((s) => (
            <label key={s.key} className={`share-scope ${sel[s.key] ? "on" : ""}`}>
              <input type="checkbox" checked={!!sel[s.key]} onChange={(e) => setSel({ ...sel, [s.key]: e.target.checked })} />
              <span>{s.icon} {s.label}</span>
            </label>
          ))}
        </div>

        <div className="share-row">
          <label style={{ fontSize: 12.5, color: "var(--muted)" }}>
            Expires:{" "}
            <select value={expires ?? "never"} onChange={(e) => setExpires(e.target.value === "never" ? null : Number(e.target.value))} className="member-select">
              <option value="7">in 7 days</option>
              <option value="30">in 30 days</option>
              <option value="90">in 90 days</option>
              <option value="never">never</option>
            </select>
          </label>
          <button className="btn primary sm" disabled={busy || chosen.length === 0} onClick={create}>
            {busy ? "Creating…" : "Create link"}
          </button>
        </div>
        {chosen.length === 0 && <div className="share-warn">Select at least one item to share.</div>}
        {err && <div className="share-warn">{err}</div>}

        {active.length > 0 && (
          <div className="share-list">
            <div className="kicker">Active links ({active.length})</div>
            {active.map((l) => (
              <div key={l.token} className="share-item">
                <div className="share-item-main">
                  <input readOnly value={linkUrl(l)} className="share-url" onFocus={(e) => e.currentTarget.select()} />
                  <div className="share-meta">
                    {(l.scopes || []).join(" · ") || "all"} · {l.view_count} view{l.view_count === 1 ? "" : "s"}
                    {l.expires_at ? ` · expires ${new Date(l.expires_at).toLocaleDateString()}` : " · no expiry"}
                  </div>
                </div>
                <button className="btn sm" onClick={() => copy(l)}>{copied === l.token ? "✓ copied" : "Copy"}</button>
                <button className="btn ghost sm" onClick={() => revoke(l.token)} title="Revoke">Revoke</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
