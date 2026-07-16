"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type Me = { id: string; email: string; name: string; org_id: string | null; role?: string };

// AstroLabs app shell — navy left sidebar + white top header. Pure chrome: it wraps every
// authenticated page and changes no behavior (same routes, same sign-out).
const NAV: { href: string; label: string; icon: string; roles?: string[] }[] = [
  { href: "/", label: "Dashboard", icon: "◱" },
  { href: "/ask", label: "Ask Cue", icon: "✦" },
  { href: "/connections", label: "Connections", icon: "⚡" },
  { href: "/activity", label: "Activity", icon: "◷" },
  { href: "/team", label: "Team", icon: "◎" },
  { href: "/costs", label: "Costs", icon: "＄", roles: ["owner", "admin"] },
  { href: "/settings", label: "Settings", icon: "⚙" },
];

const TITLES: [string, string][] = [
  ["/ask", "Ask Cue"],
  ["/connections", "Connections"],
  ["/activity", "Activity"],
  ["/team", "Team"],
  ["/costs", "Costs"],
  ["/settings", "Settings"],
  ["/meeting", "Live meeting"],
  ["/share", "Shared meeting"],
];

function pageTitle(path: string): string {
  for (const [pfx, title] of TITLES) if (path === pfx || path.startsWith(pfx + "/")) return title;
  return "Dashboard";
}

export default function Shell({
  user,
  onSignOut,
  children,
}: {
  user: Me | null;
  onSignOut: () => void;
  children: React.ReactNode;
}) {
  const path = usePathname() || "/";
  const isMeeting = path.startsWith("/meeting/");
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  const initial = (user?.name || user?.email || "U").charAt(0).toUpperCase();

  return (
    <div className="cue-shell">
      <aside className="cue-sidebar">
        <Link href="/" className="cue-brand">
          <span className="cue-brand-mark">✦</span>
          <span className="cue-brand-text">
            Cue
            <small>BY ASTROLABS</small>
          </span>
        </Link>
        <nav className="cue-nav">
          {NAV.filter((n) => !n.roles || (user?.role ? n.roles.includes(user.role) : false)).map((n) => (
            <Link key={n.href} href={n.href} className={`cue-nav-item ${active(n.href) ? "active" : ""}`}>
              <span className="cue-nav-icon" aria-hidden="true">{n.icon}</span>
              <span>{n.label}</span>
            </Link>
          ))}
        </nav>
        <div className="cue-side-spacer" />
        {user && (
          <div className="cue-side-user">
            <span className="cue-side-avatar">{initial}</span>
            <div className="cue-side-user-meta">
              <div className="cue-side-user-name">{user.name || user.email}</div>
              <div className="cue-side-user-role">{user.role || "Member"}</div>
            </div>
            <button className="cue-side-logout" onClick={onSignOut} title="Sign out" aria-label="Sign out">⎋</button>
          </div>
        )}
      </aside>

      <div className="cue-main">
        {!isMeeting && (
          <header className="cue-topbar">
            <div className="cue-page-title">{pageTitle(path)}</div>
            <div className="spacer" />
          </header>
        )}
        <div className={`cue-content ${isMeeting ? "cue-content-dark" : ""}`}>{children}</div>
      </div>
    </div>
  );
}
