"use client";

import { useState, useEffect, useCallback } from "react";

const API_BASE = "/api";

/**
 * Convert a base64 VAPID key to a Uint8Array for PushManager.subscribe().
 */
function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}

export type NotifStatus = "default" | "granted" | "denied" | "unsupported";

export function useNotifications() {
  const [status, setStatus] = useState<NotifStatus>("default");
  const [subscribed, setSubscribed] = useState(false);
  const [loading, setLoading] = useState(false);

  // Check initial state
  useEffect(() => {
    if (typeof window === "undefined" || !("Notification" in window) || !("serviceWorker" in navigator)) {
      setStatus("unsupported");
      return;
    }
    setStatus(Notification.permission as NotifStatus);

    // Check if already subscribed
    navigator.serviceWorker.ready.then((reg) => {
      reg.pushManager.getSubscription().then((sub) => {
        setSubscribed(!!sub);
      });
    });
  }, []);

  /**
   * Subscribe to push notifications.
   * 1. Request notification permission
   * 2. Get VAPID public key from backend
   * 3. Subscribe via PushManager
   * 4. Send subscription to backend
   */
  const subscribe = useCallback(async () => {
    if (status === "unsupported") return false;
    setLoading(true);

    try {
      // 1. Request permission
      const perm = await Notification.requestPermission();
      setStatus(perm as NotifStatus);
      if (perm !== "granted") {
        setLoading(false);
        return false;
      }

      // 2. Get VAPID key
      const token = localStorage.getItem("fy3-token");
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const keyRes = await fetch(`${API_BASE}/push/vapid-key`, { headers });
      if (!keyRes.ok) throw new Error("Failed to get VAPID key");
      const { publicKey } = await keyRes.json();

      // 3. Subscribe via PushManager
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey).buffer as ArrayBuffer,
      });

      // 4. Send subscription to backend
      const subRes = await fetch(`${API_BASE}/push/subscribe`, {
        method: "POST",
        headers,
        body: JSON.stringify(sub.toJSON()),
      });
      if (!subRes.ok) throw new Error("Failed to register subscription");

      setSubscribed(true);
      setLoading(false);
      return true;
    } catch (err) {
      console.error("[FY3] Push subscribe error:", err);
      setLoading(false);
      return false;
    }
  }, [status]);

  /**
   * Unsubscribe from push notifications.
   */
  const unsubscribe = useCallback(async () => {
    setLoading(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        const endpoint = sub.endpoint;
        await sub.unsubscribe();

        const token = localStorage.getItem("fy3-token");
        const headers: Record<string, string> = { "Content-Type": "application/json" };
        if (token) headers["Authorization"] = `Bearer ${token}`;

        await fetch(`${API_BASE}/push/unsubscribe`, {
          method: "POST",
          headers,
          body: JSON.stringify({ endpoint }),
        });
      }
      setSubscribed(false);
    } catch (err) {
      console.error("[FY3] Push unsubscribe error:", err);
    }
    setLoading(false);
  }, []);

  /**
   * Send a test notification.
   */
  const testNotification = useCallback(async () => {
    const token = localStorage.getItem("fy3-token");
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const res = await fetch(`${API_BASE}/push/test`, { method: "POST", headers });
    return res.ok;
  }, []);

  return { status, subscribed, loading, subscribe, unsubscribe, testNotification };
}
