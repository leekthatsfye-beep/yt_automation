"use client";

import { useEffect, useState, useCallback } from "react";
import { AlertTriangle, RotateCcw, ChevronDown, ChevronUp, RefreshCw } from "lucide-react";

/**
 * Detects if the error is a stale/missing chunk (common after deployments or hot-reload).
 * These are recoverable by clearing caches and reloading.
 */
function isChunkError(error: Error): boolean {
  const msg = (error.message || "").toLowerCase();
  return (
    msg.includes("failed to load") ||
    msg.includes("loading chunk") ||
    msg.includes("loading css chunk") ||
    msg.includes("dynamically imported module") ||
    msg.includes("failed to fetch") ||
    msg.includes("unexpected token '<'") // HTML returned instead of JS
  );
}

async function clearAllCaches() {
  try {
    // Clear CacheStorage (service worker caches)
    if ("caches" in window) {
      const names = await caches.keys();
      await Promise.all(names.map((n) => caches.delete(n)));
    }
    // Unregister service workers
    if ("serviceWorker" in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      await Promise.all(registrations.map((r) => r.unregister()));
    }
  } catch {
    // Ignore — best effort
  }
}

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const [showDetails, setShowDetails] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [autoRecoveryAttempted, setAutoRecoveryAttempted] = useState(false);

  const isChunk = isChunkError(error);

  // Auto-recover from chunk errors on first attempt
  useEffect(() => {
    console.error("[FY3 Error Boundary]", error);

    if (isChunk && !autoRecoveryAttempted) {
      setAutoRecoveryAttempted(true);
      setRecovering(true);

      // Check if we already tried auto-recovery recently
      const lastRecovery = sessionStorage.getItem("fy3-chunk-recovery");
      const now = Date.now();
      if (lastRecovery && now - parseInt(lastRecovery) < 10_000) {
        // Already tried within 10s — don't loop, show manual UI
        setRecovering(false);
        return;
      }

      sessionStorage.setItem("fy3-chunk-recovery", String(now));
      clearAllCaches().then(() => {
        window.location.reload();
      });
    }
  }, [error, isChunk, autoRecoveryAttempted]);

  const handleHardReload = useCallback(async () => {
    setRecovering(true);
    sessionStorage.removeItem("fy3-chunk-recovery");
    await clearAllCaches();
    window.location.reload();
  }, []);

  // Show a minimal loading state during auto-recovery
  if (recovering) {
    return (
      <div
        className="flex items-center justify-center"
        style={{ minHeight: "60vh", padding: "2rem" }}
      >
        <div className="text-center">
          <RefreshCw
            size={32}
            className="mx-auto mb-4 animate-spin"
            style={{ color: "var(--accent)" }}
          />
          <p
            className="text-sm font-medium"
            style={{ color: "var(--text-secondary)" }}
          >
            Refreshing app...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      className="flex items-center justify-center"
      style={{ minHeight: "60vh", padding: "2rem" }}
    >
      <div
        className="w-full max-w-md rounded-2xl p-8 text-center"
        style={{
          background: "var(--bg-card)",
          border: "1px solid var(--glass-border)",
          boxShadow: "0 8px 32px rgba(0, 0, 0, 0.2)",
        }}
      >
        {/* Icon */}
        <div
          className="w-14 h-14 rounded-xl flex items-center justify-center mx-auto mb-5"
          style={{ background: "rgba(255, 69, 58, 0.1)" }}
        >
          <AlertTriangle size={24} style={{ color: "var(--error)" }} />
        </div>

        {/* Title */}
        <h2
          className="text-lg font-semibold mb-2"
          style={{ color: "var(--text-primary)", letterSpacing: "-0.02em" }}
        >
          {isChunk ? "App Update Available" : "Something went wrong"}
        </h2>

        <p
          className="text-sm mb-6"
          style={{ color: "var(--text-tertiary)" }}
        >
          {isChunk
            ? "A newer version is available. Reload to get the latest."
            : "An error occurred while rendering this page. Try again or navigate to a different section."}
        </p>

        {/* Buttons */}
        <div className="flex items-center justify-center gap-3">
          {isChunk ? (
            <button
              onClick={handleHardReload}
              className="inline-flex items-center gap-2 px-6 py-3 rounded-xl text-sm font-semibold transition-all duration-200 cursor-pointer"
              style={{
                background: "var(--accent)",
                color: "#ffffff",
              }}
            >
              <RefreshCw size={14} />
              Reload App
            </button>
          ) : (
            <>
              <button
                onClick={reset}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 cursor-pointer"
                style={{
                  background: "var(--accent)",
                  color: "#ffffff",
                }}
              >
                <RotateCcw size={14} />
                Try Again
              </button>
              <button
                onClick={handleHardReload}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 cursor-pointer"
                style={{
                  background: "var(--bg-hover)",
                  color: "var(--text-secondary)",
                  border: "1px solid var(--border)",
                }}
              >
                <RefreshCw size={14} />
                Hard Reload
              </button>
            </>
          )}
        </div>

        {/* Error details (collapsible) */}
        {error.message && !isChunk && (
          <div className="mt-6">
            <button
              onClick={() => setShowDetails((p) => !p)}
              className="inline-flex items-center gap-1 text-xs font-medium transition-all duration-200 cursor-pointer"
              style={{ color: "var(--text-tertiary)" }}
            >
              {showDetails ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {showDetails ? "Hide Details" : "Show Details"}
            </button>

            {showDetails && (
              <pre
                className="mt-3 text-left text-xs p-4 rounded-xl overflow-auto max-h-40"
                style={{
                  background: "var(--bg-hover)",
                  color: "var(--error)",
                  border: "1px solid var(--border)",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                }}
              >
                {error.message}
                {error.digest && `\n\nDigest: ${error.digest}`}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
