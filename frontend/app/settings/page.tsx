"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { BillingInfo, OrgInfo } from "@/lib/types";

const lim = (v: number | null) => (v == null ? "∞" : v);
const pct = (used: number, limit: number | null) =>
  limit == null ? 8 : Math.min(100, Math.round((100 * used) / limit));

export default function SettingsPage() {
  const [billing, setBilling] = useState<BillingInfo | null>(null);
  const [org, setOrg] = useState<OrgInfo | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const load = useCallback(() => {
    api.billing().then(setBilling).catch(() => {});
    api.org().then(setOrg).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const q = new URLSearchParams(window.location.search);
    if (q.get("upgraded")) {
      setToast(`✓ Upgraded to ${q.get("upgraded")}`);
      window.history.replaceState({}, "", "/settings");
      setTimeout(() => setToast(null), 2600);
      setTimeout(load, 300);
    }
  }, [load]);

  const upgrade = async (plan: string) => {
    setBusy(plan);
    try {
      const r = await api.checkout(plan);
      if (r.live) window.location.href = r.url;
      else {
        setToast(`✓ Upgraded to ${plan}`);
        setTimeout(() => setToast(null), 2600);
        load();
        setBusy(null);
      }
    } catch {
      setToast("Couldn't start checkout.");
      setBusy(null);
    }
  };

  const manage = async () => {
    setBusy("portal");
    try {
      const r = await api.portal();
      window.location.href = r.url;
    } catch {
      setToast("Billing portal unavailable in this environment.");
      setBusy(null);
    }
  };

  const u = billing?.usage;

  return (
    <main className="container">
      <h1 style={{ fontSize: 28, letterSpacing: "-0.025em", margin: "4px 0 18px" }}>Settings &amp; billing</h1>

      {u && billing && (
        <div className="card pad" style={{ marginBottom: 22 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <div style={{ flex: 1 }}>
              <div className="section-title" style={{ marginBottom: 4 }}>Current plan</div>
              <div style={{ fontSize: 22, fontWeight: 800 }}>
                {u.plan_name}
                {!u.billing_enabled && (
                  <span className="pill" style={{ marginLeft: 10, fontSize: 11 }}>dev billing</span>
                )}
              </div>
            </div>
            {billing.org.plan !== "free" && (
              <button className="btn sm" disabled={busy === "portal"} onClick={manage}>
                Manage billing
              </button>
            )}
          </div>

          <div className="usage-grid">
            <div>
              <div className="usage-label">
                <span>Meetings this month</span>
                <b>{u.meetings_used} / {lim(u.meetings_limit)}</b>
              </div>
              <div className="usage-bar"><span style={{ width: `${pct(u.meetings_used, u.meetings_limit)}%` }} /></div>
            </div>
            <div>
              <div className="usage-label">
                <span>Connectors</span>
                <b>{u.connectors_used} / {lim(u.connectors_limit)}</b>
              </div>
              <div className="usage-bar"><span style={{ width: `${pct(u.connectors_used, u.connectors_limit)}%` }} /></div>
            </div>
          </div>
        </div>
      )}

      <div className="section-title">Plans</div>
      <div className="plan-grid">
        {billing?.plans.map((p) => {
          const current = billing.org.plan === p.key;
          return (
            <div key={p.key} className={`plan-card ${current ? "current" : ""}`}>
              <div className="plan-name">{p.name}</div>
              <div className="plan-price">
                {p.price_monthly == null ? "Custom" : p.price_monthly === 0 ? "Free" : `$${p.price_monthly}`}
                {p.price_monthly ? <span>/mo</span> : null}
              </div>
              <p className="plan-blurb">{p.blurb}</p>
              <ul className="plan-feats">
                <li>{p.meetings_per_month == null ? "Unlimited" : p.meetings_per_month} meetings / mo</li>
                <li>{p.max_connectors == null ? "All" : p.max_connectors} connectors</li>
                <li className={p.recall ? "on" : "off"}>{p.recall ? "✓" : "—"} Real meeting bots (Recall.ai)</li>
                <li className={p.sso ? "on" : "off"}>{p.sso ? "✓" : "—"} SSO &amp; custom limits</li>
              </ul>
              {current ? (
                <button className="btn sm" disabled style={{ width: "100%" }}>Current plan</button>
              ) : p.key === "free" ? (
                <span />
              ) : (
                <button className="btn primary sm" style={{ width: "100%" }} disabled={busy === p.key} onClick={() => upgrade(p.key)}>
                  {busy === p.key ? "…" : p.key === "enterprise" ? "Contact sales / Upgrade" : "Upgrade"}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {org && (
        <>
          <div className="section-title" style={{ marginTop: 28 }}>Team · {org.name}</div>
          <div className="card pad">
            <div className="team-list">
              {org.members.map((m) => (
                <div key={m.id} className="team-row">
                  <span className="team-avatar">{(m.name || m.email || "?")[0].toUpperCase()}</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{m.name || m.email || m.id}</div>
                    <div style={{ color: "var(--faint)", fontSize: 12.5 }}>{m.email}</div>
                  </div>
                  <span className="badge fam-product" style={{ textTransform: "capitalize" }}>{m.role}</span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {toast && <div className="toast">{toast}</div>}
    </main>
  );
}
