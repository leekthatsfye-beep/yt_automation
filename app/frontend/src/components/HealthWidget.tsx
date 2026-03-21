"use client";

import { useState, useEffect } from "react";
import {
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  Activity,
  RefreshCw,
  Loader2,
  ChevronDown,
  ChevronUp,
  FileWarning,
  HardDrive,
  Link2,
  Wrench,
} from "lucide-react";
import { useFetch, api } from "@/hooks/useApi";
import { useWebSocket } from "@/hooks/useWebSocket";
import { Button } from "@/components/ui/button";

/* ── Types ────────────────────────────────────────────────── */

interface HealthData {
  last_scan_at: string | null;
  health_score: number | null;
  health_level: string;
  total_issues: number;
  auto_fixes_applied: number;
  scan_duration_ms?: number;
  issues?: {
    missing_metadata: { stem: string; auto_fixed: boolean }[];
    orphaned_metadata: { stem: string; file: string }[];
    orphaned_listings: { stem: string; file: string }[];
    invalid_json: { file: string; error: string }[];
    missing_renders: { stem: string }[];
    stale_uploads: { stem: string; videoId: string }[];
    integration_health: Record<
      string,
      { connected: boolean; detail: string }
    >;
    disk_space: {
      total_gb: number;
      free_gb: number;
      used_pct: number;
      warning: boolean;
    };
  };
}

/* ── Level config ─────────────────────────────────────────── */

const LEVEL_CONFIG = {
  green: {
    icon: ShieldCheck,
    color: "#30d158",
    label: "Healthy",
  },
  yellow: {
    icon: ShieldAlert,
    color: "#ffd60a",
    label: "Warnings",
  },
  red: {
    icon: ShieldX,
    color: "#ff375f",
    label: "Issues",
  },
  unknown: {
    icon: Activity,
    color: "var(--text-tertiary)",
    label: "No Data",
  },
};

/* ── Component ────────────────────────────────────────────── */

export default function HealthWidget() {
  const { data, loading, refetch } = useFetch<HealthData>("/health/status");
  const { lastMessage } = useWebSocket();
  const [expanded, setExpanded] = useState(false);
  const [scanning, setScanning] = useState(false);

  // Listen for real-time scan completion via WebSocket
  useEffect(() => {
    if (lastMessage?.type === "health_scan_complete") {
      refetch();
      setScanning(false);
    }
  }, [lastMessage, refetch]);

  const handleManualScan = async () => {
    setScanning(true);
    try {
      await api.post("/health/scan");
      // Wait for the WebSocket "health_scan_complete" message
    } catch {
      setScanning(false);
    }
  };

  const level = (data?.health_level || "unknown") as keyof typeof LEVEL_CONFIG;
  const config = LEVEL_CONFIG[level] || LEVEL_CONFIG.unknown;
  const Icon = config.icon;

  const lastScanLabel = data?.last_scan_at
    ? new Date(data.last_scan_at).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : "Never";

  return (
    <div className="bg-bg-card border border-border rounded-lg p-5 animate-scale-in" style={{ animationDelay: "200ms" }}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2.5">
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ background: `${config.color}18` }}
          >
            <Icon size={18} style={{ color: config.color }} strokeWidth={2} />
          </div>
          <div>
            <h2 className="text-[15px] font-semibold text-foreground">
              System Health
            </h2>
            <p className="text-[11px] text-text-tertiary">
              Last scan: {lastScanLabel}
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="xs"
          onClick={handleManualScan}
          disabled={scanning}
          className="text-text-tertiary hover:text-foreground"
        >
          {scanning ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <RefreshCw size={14} />
          )}
        </Button>
      </div>

      {/* Score + Stats Row */}
      {loading ? (
        <div className="h-12 rounded-lg bg-muted animate-pulse" />
      ) : (
        <div className="flex items-center gap-4 sm:gap-6 flex-wrap">
          {/* Score badge */}
          <div className="flex items-center gap-2">
            <span
              className="text-2xl font-bold tabular-nums"
              style={{ color: config.color }}
            >
              {data?.health_score ?? "--"}
            </span>
            <span
              className="text-[11px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full"
              style={{
                background: `${config.color}18`,
                color: config.color,
              }}
            >
              {config.label}
            </span>
          </div>

          {/* Mini stats */}
          <div className="flex items-center gap-4 text-[12px] text-text-tertiary">
            <span className="flex items-center gap-1">
              <FileWarning size={12} />
              {data?.total_issues ?? 0} issues
            </span>
            <span className="flex items-center gap-1">
              <Wrench size={12} />
              {data?.auto_fixes_applied ?? 0} fixed
            </span>
          </div>
        </div>
      )}

      {/* Expand/Collapse Toggle */}
      {data?.issues && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1 mt-3 text-[12px] font-medium transition-colors cursor-pointer"
          style={{ color: "var(--accent)" }}
        >
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          {expanded ? "Hide details" : "Show details"}
        </button>
      )}

      {/* Expanded Details */}
      {expanded && data?.issues && (
        <div className="mt-4 pt-4 border-t border-border space-y-3 animate-fade-in">
          {/* Issue categories */}
          {[
            {
              key: "missing_metadata",
              label: "Missing Metadata",
              items: data.issues.missing_metadata,
            },
            {
              key: "orphaned_metadata",
              label: "Orphaned Metadata",
              items: data.issues.orphaned_metadata,
            },
            {
              key: "orphaned_listings",
              label: "Orphaned Listings",
              items: data.issues.orphaned_listings,
            },
            {
              key: "invalid_json",
              label: "Invalid JSON",
              items: data.issues.invalid_json,
            },
            {
              key: "missing_renders",
              label: "Missing Renders",
              items: data.issues.missing_renders,
            },
            {
              key: "stale_uploads",
              label: "Stale Uploads",
              items: data.issues.stale_uploads,
            },
          ].map(({ key, label, items }) =>
            items && items.length > 0 ? (
              <div
                key={key}
                className="flex items-center justify-between text-[12px]"
              >
                <span className="text-text-secondary">{label}</span>
                <span className="font-semibold tabular-nums text-foreground">
                  {items.length}
                </span>
              </div>
            ) : null
          )}

          {/* Disk space */}
          {data.issues.disk_space && (
            <div className="flex items-center justify-between text-[12px]">
              <span className="flex items-center gap-1 text-text-secondary">
                <HardDrive size={12} />
                Disk Space
              </span>
              <span
                className="font-semibold tabular-nums"
                style={{
                  color: data.issues.disk_space.warning
                    ? "#ff375f"
                    : "var(--text-primary)",
                }}
              >
                {data.issues.disk_space.free_gb} GB free (
                {data.issues.disk_space.used_pct}% used)
              </span>
            </div>
          )}

          {/* Integrations */}
          {data.issues.integration_health && (
            <div className="pt-2 border-t border-border">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary mb-2 flex items-center gap-1">
                <Link2 size={11} />
                Integrations
              </p>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                {Object.entries(data.issues.integration_health).map(
                  ([name, info]) => (
                    <div
                      key={name}
                      className="flex items-center gap-1.5 text-[11px]"
                    >
                      <div
                        className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                        style={{
                          background: info.connected ? "#30d158" : "#ff375f",
                          boxShadow: `0 0 4px ${
                            info.connected ? "#30d158" : "#ff375f"
                          }`,
                        }}
                      />
                      <span className="text-text-secondary capitalize truncate">
                        {name}
                      </span>
                    </div>
                  )
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
