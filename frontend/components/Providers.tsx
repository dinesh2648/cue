"use client";

import { useEffect } from "react";
import Link from "next/link";
import { ClerkProvider, SignedIn, SignedOut, SignIn, UserButton, useAuth } from "@clerk/nextjs";
import { setTokenGetter } from "@/lib/api";

const PK = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

function TokenBridge() {
  const { getToken } = useAuth();
  useEffect(() => {
    setTokenGetter(() => getToken());
    return () => setTokenGetter(null);
  }, [getToken]);
  return null;
}

function Header({ withUser = false }: { withUser?: boolean }) {
  return (
    <header className="topbar">
      <Link href="/" className="brand">
        <span className="logo">🛰️</span>
        <span>
          Sales Copilot
          <small>Real-time AI Sales Engineer</small>
        </span>
      </Link>
      <span className="spacer" />
      <Link href="/connections" className="btn ghost sm">
        🔌 Connections
      </Link>
      {withUser && <UserButton afterSignOutUrl="/" />}
    </header>
  );
}

export default function Providers({ children }: { children: React.ReactNode }) {
  // DEV mode: no Clerk key → single seeded user, no login.
  if (!PK) {
    return (
      <>
        <Header />
        {children}
      </>
    );
  }
  // Real mode: Clerk SSO gates the app and supplies per-request tokens.
  return (
    <ClerkProvider publishableKey={PK}>
      <TokenBridge />
      <SignedIn>
        <Header withUser />
        {children}
      </SignedIn>
      <SignedOut>
        <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", padding: 24 }}>
          <SignIn routing="hash" />
        </div>
      </SignedOut>
    </ClerkProvider>
  );
}
