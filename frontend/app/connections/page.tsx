"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Connector } from "@/lib/types";

interface FormState {
  token: string;
  mcp: string;
  label: string;
}

export default function ConnectionsPage() {
  const [connectors, setConnectors] = useState<Connector[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>({ token: "", mcp: "", label: "" });
  const [busy, setBusy] = useState<string | null>(null);
  const [checking, setChecking] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(() => {
    api.connectors().then(setConnectors).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const q = new URLSearchParams(window.location.search);
    if (q.get("connected")) {
      setToast(`✓ Connected ${q.get("connected")}`);
      window.history.replaceState({}, "", window.location.pathname);
      setTimeout(() => setToast(null), 2600);
    } else if (q.get("error")) {
      const e = q.get("error");
      setToast(e === "denied" ? "Authorization cancelled" : `Connection failed: ${e}`);
      window.history.replaceState({}, "", window.location.pathname);
      setTimeout(() => setToast(null), 3200);
    }
  }, [load]);

  const flash = (m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 2600);
  };

  // Primary flow: OAuth click-through — redirect to the provider's consent page.
  const connect = async (provider: string) => {
    setBusy(provider);
    try {
      const { authorize_url } = await api.connectUrl(provider);
      window.location.href = authorize_url;
    } catch {
      flash("Couldn't start authorization.");
      setBusy(null);
    }
  };

  // Secondary flow: paste a token (power users / providers without an OAuth app).
  const openForm = (c: Connector) => {
    setOpen(c.provider);
    setForm({ token: "", mcp: c.mcp_default || "", label: "" });
  };

  const submitToken = async (provider: string) => {
    if (!form.token.trim()) return;
    setBusy(provider);
    try {
      await api.connectToken(provider, form.token, form.mcp, form.label);
      setOpen(null);
      load();
      flash("✓ Connected");
    } catch {
      flash("Couldn't connect — check the token / MCP URL.");
    } finally {
      setBusy(null);
    }
  };

  const disconnect = async (provider: string) => {
    setBusy(provider);
    try {
      await api.disconnect(provider);
      load();
    } finally {
      setBusy(null);
    }
  };

  // Actively test a connection so "connected but silently broken" becomes visible + fixable.
  const test = async (provider: string) => {
    setChecking(provider);
    try {
      const r = await api.checkConnector(provider);
      flash((r.ok ? "✓ " : "⚠ ") + (r.reason || (r.ok ? "Working" : "Not working")));
      load();
    } catch {
      flash("Couldn't run the test.");
    } finally {
      setChecking(null);
    }
  };

  // Health → chip color + label. Amber = works but degraded (reconnect to fix), red = broken.
  const AMBER = "#c77a00";
  const healthChip = (c: Connector): { label: string; color?: string; live: boolean } => {
    if (c.status !== "connected")
      return c.status === "error"
        ? { label: "error", color: "var(--red)", live: false }
        : { label: "not connected", live: false };
    const h = c.health || "healthy";
    if (h === "healthy") return { label: "connected", live: true };
    if (h === "error" || h === "expired") return { label: h, color: "var(--red)", live: false };
    if (h === "demo") return { label: "demo", color: "var(--muted)", live: false };
    return { label: h, color: AMBER, live: false }; // limited
  };

  return (
    <main className="container">
      <h1 className="page-title">Your connections</h1>
      <p style={{ color: "var(--muted)", maxWidth: 680, lineHeight: 1.6, marginTop: 0 }}>
        Click <b>Connect</b> and approve on the provider&apos;s own page — no keys to paste. You authorize
        with <b>your own</b> account, so the copilot only ever sees what you can. Tokens are encrypted and
        used only on your behalf; disconnect anytime.
      </p>

      <div className="conn-grid">
        {connectors.map((c) => (
          <div key={c.provider} className={`conn-card ${c.status === "connected" ? "on" : ""}`}>
            <div className="conn-top">
              <span className="conn-icon">{c.icon}</span>
              <div style={{ flex: 1 }}>
                <div className="conn-name">{c.name}</div>
                <div className="conn-cat">{c.category}</div>
              </div>
              {(() => {
                const chip = healthChip(c);
                return (
                  <span
                    className={`pill ${chip.live ? "live" : ""}`}
                    style={chip.color ? { color: chip.color } : undefined}
                    title={c.health_reason || undefined}
                  >
                    <span className="led" />{chip.label}
                  </span>
                );
              })()}
            </div>

            <p className="conn-desc">{c.description}</p>

            {c.status === "connected" && c.health && c.health !== "healthy" && c.health_reason && (
              <div style={{ fontSize: 12.5, color: c.health === "error" || c.health === "expired" ? "var(--red)" : "#c77a00", marginTop: 2, marginBottom: 2, lineHeight: 1.5 }}>
                ⚠ {c.health_reason}
              </div>
            )}

            <div className="conn-meta">
              {c.account_label && c.status === "connected" && (
                <span className="source-chip">👤 {c.account_label}</span>
              )}
              {c.has_mcp ? (
                <span className="source-chip">🔌 MCP ready</span>
              ) : (
                <span className="source-chip" title="Provide an MCP server URL when connecting">🔌 MCP: add URL</span>
              )}
              {c.status !== "connected" && c.oauth_mode === "live" && (
                <span className="source-chip" title="A real provider OAuth app is configured">🔒 OAuth</span>
              )}
            </div>

            {open === c.provider && c.status !== "connected" ? (
              <div className="conn-form">
                <input
                  className="conn-input"
                  type="password"
                  placeholder="Your access token / API key"
                  value={form.token}
                  onChange={(e) => setForm({ ...form, token: e.target.value })}
                  autoFocus
                />
                <input
                  className="conn-input"
                  placeholder={c.mcp_default ? "MCP server URL" : "MCP server URL (optional)"}
                  value={form.mcp}
                  onChange={(e) => setForm({ ...form, mcp: e.target.value })}
                />
                <input
                  className="conn-input"
                  placeholder="Label (optional, e.g. your email)"
                  value={form.label}
                  onChange={(e) => setForm({ ...form, label: e.target.value })}
                />
                <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                  <button
                    className="btn primary sm"
                    disabled={busy === c.provider || !form.token.trim()}
                    onClick={() => submitToken(c.provider)}
                  >
                    {busy === c.provider ? "Connecting…" : "Save token"}
                  </button>
                  <button className="btn sm" onClick={() => setOpen(null)}>Cancel</button>
                </div>
              </div>
            ) : (
              <div style={{ marginTop: 14 }}>
                {c.status === "connected" ? (
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="btn sm" disabled={checking === c.provider} onClick={() => test(c.provider)} title="Run a live check that this connection still works">
                      {checking === c.provider ? "Testing…" : "Test"}
                    </button>
                    <button className="btn sm" disabled={busy === c.provider} onClick={() => disconnect(c.provider)}>
                      Disconnect
                    </button>
                  </div>
                ) : (
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <button className="btn primary sm" disabled={busy === c.provider} onClick={() => connect(c.provider)}>
                      {busy === c.provider ? "Opening…" : `Connect ${c.name}`}
                    </button>
                    <button
                      className="linklike"
                      onClick={() => openForm(c)}
                      title="Advanced: connect with your own access token instead"
                    >
                      use a token
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {toast && <div className="toast">{toast}</div>}
    </main>
  );
}
