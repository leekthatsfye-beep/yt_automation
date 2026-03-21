"use client";

import { useEffect, useState } from "react";

function isChunkError(error: Error): boolean {
  const msg = (error.message || "").toLowerCase();
  return (
    msg.includes("failed to load") ||
    msg.includes("loading chunk") ||
    msg.includes("loading css chunk") ||
    msg.includes("dynamically imported module") ||
    msg.includes("failed to fetch") ||
    msg.includes("unexpected token '<'")
  );
}

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const [recovering, setRecovering] = useState(false);
  const isChunk = isChunkError(error);

  // Auto-recover from chunk errors
  useEffect(() => {
    if (!isChunk) return;

    const last = sessionStorage.getItem("fy3-global-recovery");
    const now = Date.now();
    if (last && now - parseInt(last) < 15000) return; // don't loop

    sessionStorage.setItem("fy3-global-recovery", String(now));
    setRecovering(true);

    // Clear caches then reload
    (async () => {
      try {
        if ("caches" in window) {
          const names = await caches.keys();
          await Promise.all(names.map((n) => caches.delete(n)));
        }
        if ("serviceWorker" in navigator) {
          const regs = await navigator.serviceWorker.getRegistrations();
          await Promise.all(regs.map((r) => r.unregister()));
        }
      } catch { /* best effort */ }
      window.location.reload();
    })();
  }, [isChunk]);

  const handleReload = () => {
    setRecovering(true);
    sessionStorage.removeItem("fy3-global-recovery");
    window.location.reload();
  };

  return (
    <html>
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#0b0d14",
          fontFamily: 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        }}
      >
        <div
          style={{
            maxWidth: 420,
            padding: "2.5rem",
            borderRadius: 20,
            textAlign: "center",
            background: "rgba(255, 255, 255, 0.04)",
            border: "1px solid rgba(255, 255, 255, 0.08)",
            backdropFilter: "blur(20px)",
            boxShadow: "0 8px 32px rgba(0, 0, 0, 0.3)",
          }}
        >
          {recovering ? (
            <>
              <div
                style={{
                  width: 40,
                  height: 40,
                  border: "3px solid rgba(255,255,255,0.1)",
                  borderTopColor: "#006aff",
                  borderRadius: "50%",
                  margin: "0 auto 1.5rem",
                  animation: "spin 0.8s linear infinite",
                }}
              />
              <p style={{ fontSize: 14, color: "#a0a8b8", fontWeight: 500 }}>
                Refreshing app...
              </p>
              <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            </>
          ) : (
            <>
              {/* Icon */}
              <div
                style={{
                  width: 56,
                  height: 56,
                  borderRadius: 14,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  margin: "0 auto 1.25rem",
                  background: isChunk ? "rgba(0, 106, 255, 0.1)" : "rgba(255, 69, 58, 0.1)",
                  fontSize: 24,
                }}
              >
                {isChunk ? "🔄" : "⚠️"}
              </div>

              <h1
                style={{
                  fontSize: 18,
                  fontWeight: 600,
                  color: "#f6f6f6",
                  margin: "0 0 0.5rem",
                  letterSpacing: "-0.02em",
                }}
              >
                {isChunk ? "App Update Available" : "Critical Error"}
              </h1>

              <p
                style={{
                  fontSize: 13,
                  color: "#606878",
                  lineHeight: 1.5,
                  margin: "0 0 1.5rem",
                }}
              >
                {isChunk
                  ? "A newer version is available. Click below to reload."
                  : "The app encountered an unrecoverable error. Click below to reload."}
              </p>

              <button
                onClick={handleReload}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "12px 28px",
                  borderRadius: 12,
                  border: "none",
                  background: "#006aff",
                  color: "#ffffff",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                  letterSpacing: "-0.01em",
                }}
              >
                Reload App
              </button>

              {error.message && !isChunk && (
                <p
                  style={{
                    marginTop: "1.25rem",
                    fontSize: 11,
                    color: "#e04545",
                    opacity: 0.7,
                    wordBreak: "break-word",
                  }}
                >
                  {error.message}
                </p>
              )}
            </>
          )}
        </div>
      </body>
    </html>
  );
}
