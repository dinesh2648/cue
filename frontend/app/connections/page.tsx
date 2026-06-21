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
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(() => {
    api.connectors().then(setConnectors).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const q = new URLSearchParams(window.location.search);
    if (q.get("connected")) {
      setToast(`✓ Connected ${q.get("connected")}`);
      window.history.replaceState({}, "", "/connections");
      setTimeout(() => setToast(null), 2600);
    } else if (q.get("error")) {
      setToast(`Connection failed: ${q.get("error")}`);
      window.history.replaceState({}, "", "/connections");
      setTimeout(() => setToast(null), 3200);
    }
  }, [load]);

  const flash = (m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 2600);
  };

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

  const oauth = async (provider: string) => {
    setBusy(provider);
    try {
      const { authorize_url } = await api.connectUrl(provider);
      window.location.href = authorize_url;
    } catch {
      flash("OAuth isn't set up for this provider on the server.");
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

  return (
    <main className="container">
      <h1 style={{ fontSize: 28, letterSpacing: "-0.025em", margin: "4px 0 6px" }}>Your connections</h1>
      <p style={{ color: "var(--muted)", maxWidth: 680, lineHeight: 1.6, marginTop: 0 }}>
        Connect the tools <b>you</b> use with your <b>own</b> access token or key — nothing is configured
        for you. The copilot reads them live during meetings using your access, so it can only ever see
        what you can see. Tokens are encrypted and used only on your behalf; disconnect anytime.
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
              {c.status === "connected" ? (
                <span className="pill live"><span className="led" />connected</span>
              ) : c.status === "error" ? (
                <span className="pill" style={{ color: "var(--red)" }}><span className="led" />error</span>
              ) : (
                <span className="pill"><span className="led" />not connected</span>
              )}
            </div>

            <p className="conn-desc">{c.description}</p>

            <div className="conn-meta">
              {c.account_label && c.status === "connected" && (
                <span className="source-chip">👤 {c.account_label}</span>
              )}
              {c.has_mcp ? (
                <span className="source-chip">🔌 MCP ready</span>
              ) : (
                <span className="source-chip" title="Provide an MCP server URL when connecting">🔌 MCP: add URL</span>
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
                    {busy === c.provider ? "Connecting…" : "Connect"}
                  </button>
                  <button className="btn sm" onClick={() => setOpen(null)}>Cancel</button>
                  {c.oauth_available && (
                    <button className="btn ghost sm" onClick={() => oauth(c.provider)}>
                      or use OAuth
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
                {c.status === "connected" ? (
                  <button className="btn sm" disabled={busy === c.provider} onClick={() => disconnect(c.provider)}>
                    Disconnect
                  </button>
                ) : (
                  <>
                    <button className="btn primary sm" onClick={() => openForm(c)}>Connect</button>
                    {c.oauth_available && (
                      <button className="btn ghost sm" disabled={busy === c.provider} onClick={() => oauth(c.provider)}>
                        OAuth
                      </button>
                    )}
                  </>
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
