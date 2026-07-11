"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { BillingInfo, OrgInfo } from "@/lib/types";

const lim = (v: number | null) => (v == null ? "∞" : v);
const pct = (used: number, limit: number | null) =>
  limit == null ? 8 : Math.min(100, Math.round((100 * used) / limit));

const DEPARTMENTS: [string, string][] = [
  ["sales", "🟦 Sales"], ["tech", "🟩 Engineering"], ["ops", "⬜ Operations"],
  ["finance", "💰 Finance"], ["hr", "👥 People / HR"], ["marketing", "📣 Marketing"], ["cs", "🎧 Customer Success"],
];
const LANGUAGES: [string, string][] = [
  ["en", "English"], ["ar", "العربية (Arabic)"], ["fr", "Français"], ["es", "Español"],
  ["de", "Deutsch"], ["hi", "हिन्दी (Hindi)"], ["ur", "اردو (Urdu)"], ["pt", "Português"],
  ["zh", "中文 (Chinese)"], ["ja", "日本語 (Japanese)"], ["ru", "Русский"], ["tr", "Türkçe"],
];
const splitList = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
const emptyProfile = {
  team: "sales", language: "en", designation: "", manager_name: "", location: "", timezone: "", focus: "",
  responsibilities: "", decision_authority: "", working_style: "", preferred_output: "", custom_context: "",
};
const emptyCompany = { name: "", description: "", industry: "", locations: "", products: "", tech_stack: "", priorities: "" };
const inputStyle: React.CSSProperties = {
  width: "100%", padding: "8px 10px", borderRadius: 8, border: "1px solid var(--border)",
  background: "var(--card2, transparent)", color: "inherit", fontSize: 13.5,
};

function Label({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <div style={{ fontSize: 12.5, fontWeight: 600, marginBottom: 4 }}>
      {children}{hint && <span style={{ color: "var(--faint)", fontWeight: 400 }}> · {hint}</span>}
    </div>
  );
}

export default function SettingsPage() {
  const [billing, setBilling] = useState<BillingInfo | null>(null);
  const [org, setOrg] = useState<OrgInfo | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [autopilot, setAutopilot] = useState<boolean | null>(null);
  const [caps, setCaps] = useState<Record<string, boolean>>({});
  const [capCatalog, setCapCatalog] = useState<{ key: string; label: string; description: string; default: boolean }[]>([]);
  const [prof, setProf] = useState({ ...emptyProfile });
  const [company, setCompany] = useState({ ...emptyCompany });
  const [canManageCompany, setCanManageCompany] = useState(false);

  const load = useCallback(() => {
    api.billing().then(setBilling).catch(() => {});
    api.org().then(setOrg).catch(() => {});
    api.me().then((m) => {
      setAutopilot(!!m.autopilot);
      setCaps(m.capabilities || {});
      setCapCatalog(m.capability_catalog || []);
      const p = m.profile || {};
      setProf({
        team: m.team || "sales", language: m.language || "en", designation: p.designation || "", manager_name: p.manager_name || "",
        location: p.location || "", timezone: p.timezone || "", focus: p.focus || "",
        responsibilities: (p.responsibilities || []).join(", "), decision_authority: (p.decision_authority || []).join(", "),
        working_style: (p.working_style || []).join(", "), preferred_output: (p.preferred_output || []).join(", "),
        custom_context: m.custom_context || "",
      });
    }).catch(() => {});
    api.orgProfile().then((o) => {
      setCanManageCompany(o.can_manage);
      const p = o.profile || {};
      setCompany({
        name: o.name || "", description: o.description || "", industry: p.industry || "",
        locations: (p.locations || []).join(", "), products: (p.products || []).join(", "),
        tech_stack: (p.tech_stack || []).join(", "), priorities: (p.priorities || []).join(", "),
      });
    }).catch(() => {});
  }, []);

  const saveProfile = async () => {
    setBusy("profile");
    try {
      await api.setProfile({
        team: prof.team, language: prof.language, designation: prof.designation, manager_name: prof.manager_name,
        location: prof.location, timezone: prof.timezone, focus: prof.focus,
        responsibilities: splitList(prof.responsibilities), decision_authority: splitList(prof.decision_authority),
        working_style: splitList(prof.working_style), preferred_output: splitList(prof.preferred_output),
        custom_context: prof.custom_context,
      });
      setToast("✓ Profile saved — the advisor now tailors to your role");
    } catch {
      setToast("Couldn't save profile.");
    } finally {
      setBusy(null);
      setTimeout(() => setToast(null), 2800);
    }
  };

  const saveCompany = async () => {
    setBusy("company");
    try {
      await api.setOrgProfile({
        name: company.name, description: company.description, industry: company.industry,
        locations: splitList(company.locations), products: splitList(company.products),
        tech_stack: splitList(company.tech_stack), priorities: splitList(company.priorities),
      });
      setToast("✓ Company profile saved");
    } catch {
      setToast("Couldn't save — owner/admin only.");
    } finally {
      setBusy(null);
      setTimeout(() => setToast(null), 2800);
    }
  };

  const updateMember = async (id: string, patch: { role?: string; team?: string; manager_id?: string | null }) => {
    try {
      await api.updateMember(id, patch);
      setToast("✓ Team updated");
      setTimeout(() => setToast(null), 2000);
      load();
    } catch {
      setToast("Couldn't update — owner/admin only.");
      setTimeout(() => setToast(null), 2600);
    }
  };

  const toggleCapability = async (key: string) => {
    const next = { ...caps, [key]: !(caps[key] ?? true) };
    setCaps(next);
    try {
      await api.setCapabilities({ [key]: next[key] });
    } catch {
      setCaps(caps); // revert
      setToast("Couldn't update that setting.");
      setTimeout(() => setToast(null), 2600);
    }
  };

  const toggleAutopilot = async () => {
    const next = !autopilot;
    setAutopilot(next);
    try {
      await api.setAutopilot(next);
      setToast(next ? "✓ Auto-pilot on — I'll auto-join & summarize your meetings" : "Auto-pilot off — you'll bring the copilot in manually");
      setTimeout(() => setToast(null), 3000);
    } catch {
      setAutopilot(!next);
      setToast("Couldn't update auto-pilot.");
      setTimeout(() => setToast(null), 2600);
    }
  };

  useEffect(() => {
    load();
    const q = new URLSearchParams(window.location.search);
    if (q.get("upgraded")) {
      setToast(`✓ Upgraded to ${q.get("upgraded")}`);
      window.history.replaceState({}, "", window.location.pathname);
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
  const pf = (k: keyof typeof prof) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setProf({ ...prof, [k]: e.target.value });
  const cf = (k: keyof typeof company) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setCompany({ ...company, [k]: e.target.value });

  return (
    <main className="container">
      <h1 className="page-title">Settings &amp; billing</h1>

      <div className="settings-layout">
        <nav className="settings-nav">
          <a href="#s-autopilot">🤖 Auto-pilot</a>
          <a href="#s-capabilities">🎛️ Capabilities</a>
          <a href="#s-profile">🧑‍💼 Your profile</a>
          <a href="#s-company">🏢 Company</a>
          <a href="#s-billing">💳 Plan &amp; billing</a>
          <a href="#s-team">👥 Team</a>
        </nav>
        <div className="settings-col">

      <div id="s-autopilot" />
      {/* Auto-pilot */}
      <div className="card pad" style={{ marginBottom: 22 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <div className="section-title" style={{ marginBottom: 4 }}>🤖 Auto-pilot my meetings <span className="pill" style={{ fontSize: 10, marginLeft: 6 }}>on by default</span></div>
            <p style={{ color: "var(--muted)", fontSize: 13.5, lineHeight: 1.6, margin: 0 }}>
              The copilot <b>automatically joins your meetings the moment they start</b> (from your Google
              Calendar) and auto-generates the notes, actions and scorecard when each call ends — no manual
              join, send or end. This is on by default; turn it off here if you&apos;d rather bring the
              copilot in yourself. Solo holds with no other attendees are skipped.
            </p>
          </div>
          <button
            role="switch"
            aria-checked={!!autopilot}
            className={`switch ${autopilot ? "on" : ""}`}
            disabled={autopilot === null}
            onClick={toggleAutopilot}
            title="Toggle auto-pilot"
          >
            <span className="switch-knob" />
          </button>
        </div>
        {autopilot && (
          <div style={{ marginTop: 12, fontSize: 12.5, color: "var(--faint)" }}>
            Requires a connected Google Calendar + a reachable backend (your deployed URL). The bot still
            needs to be <b>admitted</b> from the meeting waiting room.
          </div>
        )}
      </div>

      <div id="s-capabilities" />
      {/* Per-user capability toggles — enable/disable individual copilot behaviours */}
      {capCatalog.length > 0 && (
        <div className="card pad" style={{ marginBottom: 22 }}>
          <div className="section-title" style={{ marginBottom: 4 }}>🎛️ Capabilities</div>
          <p style={{ color: "var(--muted)", fontSize: 13.5, lineHeight: 1.6, marginTop: 0, marginBottom: 14 }}>
            Turn individual copilot behaviours on or off. These apply to <b>your</b> account only.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            {capCatalog.map((c) => {
              const on = caps[c.key] ?? c.default;
              return (
                <div key={c.key} style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{c.label}</div>
                    <p style={{ color: "var(--muted)", fontSize: 13, lineHeight: 1.5, margin: "2px 0 0" }}>{c.description}</p>
                  </div>
                  <button
                    role="switch"
                    aria-checked={on}
                    aria-label={`Toggle ${c.label}`}
                    className={`switch ${on ? "on" : ""}`}
                    onClick={() => toggleCapability(c.key)}
                    title={`Toggle ${c.label}`}
                  >
                    <span className="switch-knob" />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div id="s-profile" />
      {/* Your advisory profile — injected into every AI request */}
      <div className="card pad" style={{ marginBottom: 22 }}>
        <div className="section-title" style={{ marginBottom: 4 }}>🧑‍💼 Your advisory profile</div>
        <p style={{ color: "var(--muted)", fontSize: 13.5, lineHeight: 1.6, marginTop: 0, marginBottom: 16 }}>
          The advisor uses this on <b>every</b> prep note, live answer and summary — so responses fit your
          role, decision authority and preferred style. Your <b>department</b> also decides which tools it
          uses (e.g. Jira/GitHub for Engineering, CRM for customer-facing roles).
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 }}>
          <div>
            <Label>Department</Label>
            <select className="member-select" style={{ width: "100%" }} value={prof.team} onChange={pf("team")}>
              {DEPARTMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div>
            <Label hint="answers, prep & summary come to you in this language">Language</Label>
            <select className="member-select" style={{ width: "100%" }} value={prof.language} onChange={pf("language")}>
              {LANGUAGES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div><Label>Designation</Label><input style={inputStyle} value={prof.designation} onChange={pf("designation")} placeholder="Head of Technology" /></div>
          <div><Label>Reports to</Label><input style={inputStyle} value={prof.manager_name} onChange={pf("manager_name")} placeholder="Manager name" /></div>
          <div><Label>Location</Label><input style={inputStyle} value={prof.location} onChange={pf("location")} placeholder="Dubai, UAE" /></div>
          <div><Label>Timezone</Label><input style={inputStyle} value={prof.timezone} onChange={pf("timezone")} placeholder="GST (UTC+4)" /></div>
          <div><Label>Focus</Label><input style={inputStyle} value={prof.focus} onChange={pf("focus")} placeholder="scalability, security, delivery" /></div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 14, marginTop: 14 }}>
          <div><Label hint="comma-separated">Responsibilities</Label><input style={inputStyle} value={prof.responsibilities} onChange={pf("responsibilities")} placeholder="roadmap, architecture, hiring" /></div>
          <div><Label hint="comma-separated">Decision authority</Label><input style={inputStyle} value={prof.decision_authority} onChange={pf("decision_authority")} placeholder="architecture, vendor selection" /></div>
          <div><Label hint="comma-separated">Working style</Label><input style={inputStyle} value={prof.working_style} onChange={pf("working_style")} placeholder="executive summaries, risk-first" /></div>
          <div><Label hint="comma-separated">Preferred output</Label><input style={inputStyle} value={prof.preferred_output} onChange={pf("preferred_output")} placeholder="bullet points, concise" /></div>
        </div>
        <div style={{ marginTop: 14 }}>
          <Label hint="free text, in your own words">More about you</Label>
          <textarea style={{ ...inputStyle, minHeight: 74, resize: "vertical" }} value={prof.custom_context} onChange={pf("custom_context")}
            placeholder="I represent engineering in customer architecture calls. I prefer concise, technical explanations focused on scalability and security." />
        </div>
        <div style={{ marginTop: 14 }}>
          <button className="btn primary sm" disabled={busy === "profile"} onClick={saveProfile}>
            {busy === "profile" ? "Saving…" : "Save profile"}
          </button>
        </div>
      </div>

      <div id="s-company" />
      {/* Company profile — one per workspace, injected into every request */}
      <div className="card pad" style={{ marginBottom: 22 }}>
        <div className="section-title" style={{ marginBottom: 4 }}>🏢 Company profile</div>
        <p style={{ color: "var(--muted)", fontSize: 13.5, lineHeight: 1.6, marginTop: 0, marginBottom: 16 }}>
          Shared context about your business — added to every employee&apos;s AI requests so answers fit the
          company. {canManageCompany ? "You can edit this (owner/admin)." : "Only an owner or admin can edit this."}
        </p>
        <fieldset disabled={!canManageCompany} style={{ border: 0, padding: 0, margin: 0, opacity: canManageCompany ? 1 : 0.7 }}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 }}>
            <div><Label>Company name</Label><input style={inputStyle} value={company.name} onChange={cf("name")} placeholder="AstroLabs" /></div>
            <div><Label>Industry</Label><input style={inputStyle} value={company.industry} onChange={cf("industry")} placeholder="Business setup / gov-tech platform" /></div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 14, marginTop: 14 }}>
            <div><Label hint="comma-separated">Locations</Label><input style={inputStyle} value={company.locations} onChange={cf("locations")} placeholder="UAE, Saudi Arabia" /></div>
            <div><Label hint="comma-separated">Core products</Label><input style={inputStyle} value={company.products} onChange={cf("products")} placeholder="Business Setup Platform, Gov Integrations" /></div>
            <div><Label hint="comma-separated">Tech stack</Label><input style={inputStyle} value={company.tech_stack} onChange={cf("tech_stack")} placeholder="Next.js, Postgres, AWS, Claude" /></div>
            <div><Label hint="comma-separated">Business priorities</Label><input style={inputStyle} value={company.priorities} onChange={cf("priorities")} placeholder="CX, AI-first, automation, security" /></div>
          </div>
          <div style={{ marginTop: 14 }}>
            <Label hint="free text">About the company</Label>
            <textarea style={{ ...inputStyle, minHeight: 74, resize: "vertical" }} value={company.description} onChange={cf("description")}
              placeholder="What the company does, who it serves, and anything the advisor should always keep in mind." />
          </div>
          {canManageCompany && (
            <div style={{ marginTop: 14 }}>
              <button className="btn primary sm" disabled={busy === "company"} onClick={saveCompany}>
                {busy === "company" ? "Saving…" : "Save company profile"}
              </button>
            </div>
          )}
        </fieldset>
      </div>

      <div id="s-billing" />
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

      <div id="s-team" />
      {org && (
        <>
          <div className="section-title" style={{ marginTop: 28 }}>Team · {org.name}</div>
          <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -6, marginBottom: 14, lineHeight: 1.6 }}>
            Set each teammate&apos;s <b>team</b> (which copilot joins their meetings — Sales or Tech),
            their <b>role</b>, and their <b>manager</b> (managers see everything for their reports).
          </p>
          <div className="card pad">
            <div className="team-list">
              {org.members.map((m) => (
                <div key={m.id} className="team-row">
                  <span className="team-avatar">{(m.name || m.email || "?")[0].toUpperCase()}</span>
                  <div style={{ flex: 1, minWidth: 140 }}>
                    <div style={{ fontWeight: 600, fontSize: 14 }}>{m.name || m.email || m.id}</div>
                    <div style={{ color: "var(--faint)", fontSize: 12.5 }}>{m.email}</div>
                  </div>
                  {org.can_manage ? (
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                      <select
                        className="member-select"
                        defaultValue={m.team}
                        title="Team → which copilot joins their meetings"
                        onChange={(e) => updateMember(m.id, { team: e.target.value })}
                      >
                        {DEPARTMENTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                      </select>
                      <select
                        className="member-select"
                        defaultValue={m.role}
                        title="Role"
                        onChange={(e) => updateMember(m.id, { role: e.target.value })}
                      >
                        <option value="member">Member</option>
                        <option value="manager">Manager</option>
                        <option value="admin">Admin</option>
                        <option value="owner" disabled>Owner</option>
                      </select>
                      <select
                        className="member-select"
                        defaultValue={m.manager_id || ""}
                        title="Manager"
                        onChange={(e) => updateMember(m.id, { manager_id: e.target.value })}
                      >
                        <option value="">No manager</option>
                        {org.members.filter((x) => x.id !== m.id).map((x) => (
                          <option key={x.id} value={x.id}>↳ {x.name || x.email}</option>
                        ))}
                      </select>
                    </div>
                  ) : (
                    <div style={{ display: "flex", gap: 8 }}>
                      <span className={`badge ${m.team === "tech" ? "fam-security" : "fam-product"}`} style={{ textTransform: "capitalize" }}>{m.team}</span>
                      <span className="badge fam-general" style={{ textTransform: "capitalize" }}>{m.role}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </>
      )}

        </div>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </main>
  );
}
