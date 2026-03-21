"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { Wifi, WifiOff, Loader2 } from "lucide-react";

/* ── Context ───────────────────────────────────────────── */

interface ConnectionContextValue {
  wsConnected: boolean;
  online: boolean;
  reconnecting: boolean;
}

const ConnectionContext = createContext<ConnectionContextValue>({
  wsConnected: false,
  online: true,
  reconnecting: false,
});

export function useConnection() {
  return useContext(ConnectionContext);
}

/* ── Provider ──────────────────────────────────────────── */

export default function ConnectionProvider({ children }: { children: React.ReactNode }) {
  const { connected: wsConnected, reconnect } = useWebSocket();
  const [online, setOnline] = useState(true);
  const wasDisconnected = useRef(false);
  const lastRefetchTime = useRef(0);

  // Debounced dispatch to prevent double-fetch from visibility + WS onopen
  function dispatchReconnected() {
    const now = Date.now();
    if (now - lastRefetchTime.current < 2000) return;
    lastRefetchTime.current = now;
    window.dispatchEvent(new Event("fy3:reconnected"));
  }

  // Track navigator.onLine
  useEffect(() => {
    setOnline(navigator.onLine);
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  // On visibility change → force reconnect + refetch stale data
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        if (!wsConnected) reconnect();
        dispatchReconnected();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsConnected, reconnect]);

  // Detect WS reconnection → refetch all data
  useEffect(() => {
    if (!wsConnected) {
      wasDisconnected.current = true;
    } else if (wasDisconnected.current) {
      wasDisconnected.current = false;
      dispatchReconnected();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsConnected]);

  const reconnecting = !wsConnected && online;

  return (
    <ConnectionContext.Provider value={{ wsConnected, online, reconnecting }}>
      {children}
      <ConnectionBanner
        wsConnected={wsConnected}
        online={online}
        reconnecting={reconnecting}
      />
    </ConnectionContext.Provider>
  );
}

/* ── Connection Status Banner ──────────────────────────── */

function ConnectionBanner({
  wsConnected,
  online,
  reconnecting,
}: {
  wsConnected: boolean;
  online: boolean;
  reconnecting: boolean;
}) {
  const [visible, setVisible] = useState(false);
  const [showConnected, setShowConnected] = useState(false);
  const wasDown = useRef(false);
  const hasConnectedOnce = useRef(false);
  const hideTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    // Track first successful connection — don't show banner on initial load
    if (wsConnected && !hasConnectedOnce.current) {
      hasConnectedOnce.current = true;
      return;
    }

    if (!online || (!wsConnected && hasConnectedOnce.current)) {
      wasDown.current = true;
      setShowConnected(false);
      setVisible(true);
      clearTimeout(hideTimer.current);
    } else if (wasDown.current) {
      wasDown.current = false;
      setShowConnected(true);
      setVisible(true);
      hideTimer.current = setTimeout(() => {
        setVisible(false);
        setTimeout(() => setShowConnected(false), 400);
      }, 2500);
    }
    return () => clearTimeout(hideTimer.current);
  }, [online, wsConnected]);

  if (!visible && !showConnected) return null;

  const isOffline = !online;
  const isBack = showConnected;

  let bg: string;
  let borderColor: string;
  let icon: React.ReactNode;
  let text: string;

  if (isOffline) {
    bg = "rgba(255, 69, 58, 0.15)";
    borderColor = "rgba(255, 69, 58, 0.3)";
    icon = <WifiOff size={14} style={{ color: "var(--error)" }} />;
    text = "No internet connection";
  } else if (isBack) {
    bg = "rgba(48, 209, 88, 0.15)";
    borderColor = "rgba(48, 209, 88, 0.3)";
    icon = <Wifi size={14} style={{ color: "var(--success)" }} />;
    text = "Connected";
  } else {
    bg = "rgba(255, 214, 10, 0.15)";
    borderColor = "rgba(255, 214, 10, 0.3)";
    icon = (
      <Loader2
        size={14}
        style={{ color: "var(--warning)", animation: "spin 1s linear infinite" }}
      />
    );
    text = "Reconnecting…";
  }

  return (
    <div
      style={{
        position: "fixed",
        top: 16,
        left: "50%",
        transform: `translateX(-50%) translateY(${visible ? 0 : -60}px)`,
        opacity: visible ? 1 : 0,
        transition: "all 0.35s cubic-bezier(0.4, 0, 0.2, 1)",
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "10px 18px",
        borderRadius: 14,
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        background: bg,
        border: `1px solid ${borderColor}`,
        boxShadow: "0 4px 20px rgba(0, 0, 0, 0.3)",
        fontSize: 13,
        fontWeight: 500,
        color: "var(--text-primary)",
        pointerEvents: "none",
        whiteSpace: "nowrap",
      }}
    >
      {icon}
      {text}
    </div>
  );
}
