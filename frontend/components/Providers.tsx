"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, setTokenGetter } from "@/lib/api";
import { BRAND, TAGLINE } from "@/lib/brand";
import PrepWatcherProvider from "@/components/PrepWatcher";

const TOKEN_KEY = "cue_session_token";

function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

type Me = { id: string; email: string; name: string; org_id: string | null; role?: string };
type Phase = "loading" | "dev" | "authed" | "signin";

function GoogleMark() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  );
}

function Header({ user, onSignOut }: { user: Me | null; onSignOut: () => void }) {
  return (
    <header className="topbar">
      <Link href="/" className="brand">
        <span className="logo">🛰️</span>
        <span>
          {BRAND}
          <small>{TAGLINE}</small>
        </span>
      </Link>
      <span className="spacer" />
      <Link href="/ask" className="btn ghost sm">
        💬 Ask
      </Link>
      <Link href="/team" className="btn ghost sm">
        📊 Team
      </Link>
      <Link href="/connections" className="btn ghost sm">
        🔌 Connections
      </Link>
      <Link href="/settings" className="btn ghost sm">
        ⚙ Settings
      </Link>
      {user && (
        <div className="user-chip" title={user.email}>
          <span className="user-avatar">{(user.name || user.email || "?").charAt(0).toUpperCase()}</span>
          <span className="user-email">{user.email || user.name}</span>
          <button className="btn ghost sm" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      )}
    </header>
  );
}

function SignIn({ url }: { url: string }) {
  return (
    <div className="signin-wrap">
      <div className="signin-card">
        <span className="signin-logo">🛰️</span>
        <h1>{BRAND}</h1>
        <p className="signin-tag">{TAGLINE}</p>
        <a className="btn google-btn" href={url}>
          <GoogleMark />
          Continue with Google
        </a>
        <p className="signin-fine">
          You sign in with your own Google account and connect your own tools — the copilot only ever
          sees what you can.
        </p>
      </div>
    </div>
  );
}

export default function Providers({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [user, setUser] = useState<Me | null>(null);
  const [loginUrl, setLoginUrl] = useState<string | null>(null);

  // Bridge the stored session token into the API client (Bearer header + WS).
  useEffect(() => {
    setTokenGetter(() => Promise.resolve(getStoredToken()));
    return () => setTokenGetter(null);
  }, []);

  const boot = useCallback(async () => {
    // Capture a token handed back in the URL fragment after Google redirect.
    if (typeof window !== "undefined" && window.location.hash.startsWith("#token=")) {
      const t = decodeURIComponent(window.location.hash.slice("#token=".length));
      if (t) window.localStorage.setItem(TOKEN_KEY, t);
      window.history.replaceState({}, "", window.location.pathname + window.location.search);
    }

    const cfg = await api.authConfig().catch(() => null);
    if (!cfg || cfg.dev_mode) {
      setPhase("dev");
      return;
    }
    setLoginUrl(cfg.google_login_url);
    if (!getStoredToken()) {
      setPhase("signin");
      return;
    }
    const me = await api.me().catch(() => null);
    if (!me) {
      window.localStorage.removeItem(TOKEN_KEY); // stale/expired session
      setPhase("signin");
      return;
    }
    setUser(me);
    setPhase("authed");
  }, []);

  useEffect(() => {
    boot();
  }, [boot]);

  const signOut = () => {
    window.localStorage.removeItem(TOKEN_KEY);
    // Go to the app root under the sub-path (basePath), not the domain root (the HRMS app).
    window.location.href = (process.env.NEXT_PUBLIC_BASE_PATH || "") + "/";
  };

  // Public share pages (/share/<token>) are viewable without signing in — render them bare,
  // with no auth gate and no app chrome (they carry their own minimal header).
  const isPublicShare =
    typeof window !== "undefined" && /(^|\/)share\/[^/]+/.test(window.location.pathname);
  if (isPublicShare) {
    return <>{children}</>;
  }

  if (phase === "loading") {
    return <div className="boot">Loading…</div>;
  }
  if (phase === "signin" && loginUrl) {
    return <SignIn url={loginUrl} />;
  }
  // dev mode (no user chip) or authed (with user chip)
  return (
    <PrepWatcherProvider>
      <Header user={user} onSignOut={signOut} />
      {children}
    </PrepWatcherProvider>
  );
}
