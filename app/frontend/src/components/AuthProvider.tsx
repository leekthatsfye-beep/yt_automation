"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { AuthProvider as AuthContextProvider, useAuth } from "@/hooks/useAuth";
import LoginPage from "@/app/login/page";

function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const pathname = usePathname();
  const [timedOut, setTimedOut] = useState(false);

  // Safety timeout: if auth check takes more than 8s, stop waiting
  useEffect(() => {
    if (!loading) {
      setTimedOut(false);
      return;
    }
    const timer = setTimeout(() => setTimedOut(true), 8000);
    return () => clearTimeout(timer);
  }, [loading]);

  // Landing page is always public
  if (pathname === "/") return <>{children}</>;

  // Loading state — show spinner, but not forever
  if (loading && !timedOut) {
    return (
      <div
        className="flex items-center justify-center min-h-screen"
        style={{ background: "var(--bg-primary)" }}
      >
        <div
          className="w-8 h-8 rounded-full border-2 animate-spin"
          style={{
            borderColor: "var(--border)",
            borderTopColor: "var(--accent)",
          }}
        />
      </div>
    );
  }

  // Not authenticated (or timed out) → login
  if (!user) return <LoginPage />;

  return <>{children}</>;
}

export default function AuthProviderWrapper({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthContextProvider>
      <AuthGate>{children}</AuthGate>
    </AuthContextProvider>
  );
}
