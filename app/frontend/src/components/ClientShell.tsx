"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Toaster } from "sonner";
import Sidebar from "./Sidebar";
import ToastProvider from "./ToastProvider";
import ConnectionProvider from "./ConnectionProvider";
import AuthProviderWrapper from "./AuthProvider";
import GlobalAudioPlayer from "./GlobalAudioPlayer";
import { useAuth } from "@/hooks/useAuth";
import { useSwipeNav } from "@/hooks/useSwipeNav";
import { useGlobalAudio } from "@/hooks/useGlobalAudio";

function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [isMobile, setIsMobile] = useState(false);
  const { user } = useAuth();
  const { beat: globalBeat } = useGlobalAudio();
  const isLandingPage = pathname === "/";
  const showSidebar = !isLandingPage && user;
  const hasGlobalPlayer = !!globalBeat;

  // Swipe left/right to navigate between pages
  useSwipeNav();

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    setIsMobile(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  return (
    <div className="flex min-h-screen overflow-x-hidden" style={{ background: 'linear-gradient(180deg, var(--bg-primary) 0%, color-mix(in srgb, var(--bg-primary) 95%, #000) 100%)' }}>
      {showSidebar && <Sidebar />}
      <main
        className="flex-1 min-h-screen min-w-0 relative z-0"
        style={{ marginLeft: showSidebar && !isMobile ? 240 : 0, overflowX: "hidden" }}
      >
        <div
          className={isLandingPage || !user ? "" : "max-w-7xl mx-auto"}
          style={{
            padding: isLandingPage || !user ? 0 : isMobile ? "3.5rem 1.25rem 2rem" : "2rem 2.5rem",
          }}
        >
          <ConnectionProvider>
            <ToastProvider>{children}</ToastProvider>
          </ConnectionProvider>
        </div>
        {/* Bottom padding when global audio player is active */}
        {hasGlobalPlayer && <div style={{ height: 72 }} />}
      </main>

      {/* Global persistent audio player — visible on all pages */}
      {user && <GlobalAudioPlayer />}

      {/* Sonner toast notifications */}
      <Toaster
        position="bottom-right"
        toastOptions={{
          style: {
            background: "var(--bg-card-solid)",
            border: "1px solid var(--border)",
            color: "var(--text-primary)",
          },
        }}
        gap={10}
      />
    </div>
  );
}

export default function ClientShell({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const saved = localStorage.getItem("fy3-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);

    // Auto-clear stale caches on app update
    import("@/lib/cache").then(({ checkAndClearOnUpdate }) => {
      checkAndClearOnUpdate().then((cleared) => {
        if (cleared) {
          console.log("[FY3] New version detected — caches cleared");
        }
      });
    });

    // Register service worker for push notifications
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker
        .register("/sw.js")
        .then((reg) => {
          console.log("[FY3] Service worker registered", reg.scope);
        })
        .catch((err) => {
          console.warn("[FY3] Service worker registration failed:", err);
        });
    }
  }, []);

  return (
    <AuthProviderWrapper>
      <AppLayout>{children}</AppLayout>
    </AuthProviderWrapper>
  );
}
