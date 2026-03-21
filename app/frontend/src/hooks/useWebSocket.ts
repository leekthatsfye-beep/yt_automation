"use client";

import { useState, useEffect, useRef, useCallback } from "react";

export interface WSMessage {
  type: string;
  taskId?: string;
  stem?: string;
  phase?: string;
  pct?: number;
  detail?: string;
  [key: string]: unknown;
}

const BASE_DELAY = 1000;
const MAX_DELAY = 30000;

function getWsUrl(): string {
  if (typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const token = localStorage.getItem("fy3-token");
    const base = `${proto}//${window.location.host}/ws`;
    return token ? `${base}?token=${encodeURIComponent(token)}` : base;
  }
  return "ws://localhost:3000/ws";
}

export function useWebSocket(url = getWsUrl()) {
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const retryCountRef = useRef(0);
  const intentionalClose = useRef(false);

  const connect = useCallback(() => {
    // Guard: already open or mid-handshake
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    if (wsRef.current?.readyState === WebSocket.CONNECTING) return;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        retryCountRef.current = 0;
        setRetryCount(0);
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (!intentionalClose.current) {
          const delay = Math.min(
            BASE_DELAY * Math.pow(2, retryCountRef.current),
            MAX_DELAY
          );
          retryCountRef.current += 1;
          setRetryCount(retryCountRef.current);
          reconnectTimer.current = setTimeout(connect, delay);
        }
      };

      ws.onerror = () => ws.close();

      ws.onmessage = (e) => {
        try {
          setLastMessage(JSON.parse(e.data));
        } catch {
          // ignore non-JSON messages
        }
      };
    } catch {
      const delay = Math.min(
        BASE_DELAY * Math.pow(2, retryCountRef.current),
        MAX_DELAY
      );
      retryCountRef.current += 1;
      setRetryCount(retryCountRef.current);
      reconnectTimer.current = setTimeout(connect, delay);
    }
  }, [url]);

  // Force reconnect: reset counters, close stale socket, connect immediately
  const reconnect = useCallback(() => {
    clearTimeout(reconnectTimer.current);
    // Close stale socket without triggering auto-reconnect
    if (wsRef.current) {
      intentionalClose.current = true;
      wsRef.current.close();
      wsRef.current = null;
      intentionalClose.current = false;
    }
    retryCountRef.current = 0;
    setRetryCount(0);
    connect();
  }, [connect]);

  useEffect(() => {
    intentionalClose.current = false;
    connect();

    // When user returns to the app, reset retries and reconnect immediately
    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        if (wsRef.current?.readyState !== WebSocket.OPEN) {
          clearTimeout(reconnectTimer.current);
          retryCountRef.current = 0;
          setRetryCount(0);
          connect();
        }
      }
    };

    // When network comes back, reset retries and reconnect immediately
    const handleOnline = () => {
      if (wsRef.current?.readyState !== WebSocket.OPEN) {
        clearTimeout(reconnectTimer.current);
        retryCountRef.current = 0;
        setRetryCount(0);
        connect();
      }
    };

    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("online", handleOnline);

    return () => {
      intentionalClose.current = true;
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("online", handleOnline);
    };
  }, [connect]);

  return { connected, lastMessage, retryCount, reconnect };
}
