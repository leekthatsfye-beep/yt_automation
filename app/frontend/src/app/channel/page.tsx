"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Youtube,
  Activity,
  AlertTriangle,
  CheckCircle2,
  Zap,
  Eye,
  ThumbsUp,
  TrendingUp,
  Shield,
  RefreshCw,
  Loader2,
  Wrench,
  BarChart3,
  ExternalLink,
  Gauge,
  Music,
  Smartphone,
} from "lucide-react";
import { useFetch, api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";

/* ── types ─────────────────────────────────────────────────────────────── */

interface ChannelReport {
  channel_health_score: number;
  health_level: string;
  scanned_at: string;
  scan_duration_seconds?: number;
  overview: {
    total_videos: number;
    total_views: number;
    total_likes: number;
    clean_videos: number;
    flagged_videos: number;
    beats_count?: number;
    shorts_count?: number;
    beats_views?: number;
    shorts_views?: number;
    beats_likes?: number;
    shorts_likes?: number;
  };
  issues: {
    total: number;
    high_severity: number;
    medium_severity: number;
    low_severity: number;
    auto_fixable: number;
    by_type: Record<string, number>;
  };
  fixes: {
    applied: number;
    failed: number;
    remaining: number;
  };
  top_videos: {
    title: string;
    video_id: string;
    views: number;
    likes: number;
  }[];
}

interface QuotaData {
  daily_quota: number;
  scan_cost_estimate: number;
  fix_cost_estimate: number;
  total_if_scan_and_fix: number;
  remaining_for_uploads: number;
  upload_cost_each: number;
  safe_uploads_remaining: number;
  total_videos: number;
  auto_fixable_issues: number;
}

/* ── small components ──────────────────────────────────────────────────── */

function ScoreGauge({ score, level }: { score: number; level: string }) {
  const color =
    level === "excellent"
      ? "#22c55e"
      : level === "good"
        ? "#22c55e"
        : level === "warning"
          ? "#f59e0b"
          : "#ef4444";

  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;

  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative" style={{ width: 120, height: 120 }}>
        <svg width={120} height={120} className="rotate-[-90deg]">
          <circle
            cx={60}
            cy={60}
            r={radius}
            fill="none"
            stroke="var(--border)"
            strokeWidth={8}
          />
          <circle
            cx={60}
            cy={60}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={8}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            style={{ transition: "stroke-dashoffset 1s ease" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-black" style={{ color }}>
            {score}
          </span>
          <span className="text-[9px] uppercase tracking-wider text-text-secondary font-bold">
            / 100
          </span>
        </div>
      </div>
      <span
        className="text-[10px] uppercase font-bold tracking-widest px-2.5 py-0.5 rounded-full"
        style={{
          color,
          background: `${color}15`,
        }}
      >
        {level}
      </span>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  color = "var(--text-primary)",
  sub,
}: {
  icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }>;
  label: string;
  value: string | number;
  color?: string;
  sub?: string;
}) {
  return (
    <div
      className="p-4 rounded-xl flex items-center gap-3"
      style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
    >
      <div
        className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
        style={{ background: `${color}15` }}
      >
        <Icon size={16} style={{ color }} />
      </div>
      <div>
        <p className="text-lg font-black" style={{ color }}>
          {typeof value === "number" ? value.toLocaleString() : value}
        </p>
        <p className="text-[10px] text-text-tertiary uppercase tracking-wide font-semibold">
          {label}
        </p>
        {sub && <p className="text-[9px] text-text-tertiary mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

const ISSUE_TYPE_LABELS: Record<string, { label: string; color: string }> = {
  missing_purchase_link: { label: "Missing Purchase Link", color: "#ef4444" },
  weak_title: { label: "Weak Title", color: "#f59e0b" },
  missing_tags: { label: "Missing Tags", color: "#ef4444" },
  low_tags: { label: "Low Tag Count", color: "#f59e0b" },
  missing_producer_credit: { label: "No Producer Credit", color: "#6b7280" },
  stale_purchase_link: { label: "Stale Purchase Link", color: "#f59e0b" },
  wrong_category: { label: "Wrong Category", color: "#6b7280" },
  free_language: { label: "Free Language", color: "#6b7280" },
};

/* ── page ──────────────────────────────────────────────────────────────── */

export default function ChannelManagerPage() {
  const { data: reportData, loading, refetch } = useFetch<{ report: ChannelReport | null }>(
    "/channel/report"
  );
  const { data: quotaData } = useFetch<QuotaData>("/channel/quota");
  const { toast } = useToast();

  const [scanning, setScanning] = useState(false);
  const [fixing, setFixing] = useState(false);

  const report = reportData?.report;

  const handleScan = useCallback(
    async (fix: boolean) => {
      if (fix) setFixing(true);
      else setScanning(true);

      try {
        await api.post("/channel/scan", { fix, dry_run: false });
        toast(fix ? "Channel scan + fix started" : "Channel scan started", "info");

        // Poll for completion
        const poll = setInterval(async () => {
          try {
            const fresh = await api.get<{ report: ChannelReport | null }>("/channel/report");
            if (
              fresh?.report &&
              fresh.report.scanned_at !== report?.scanned_at
            ) {
              clearInterval(poll);
              refetch();
              setScanning(false);
              setFixing(false);
              toast(
                fix
                  ? `Scan complete! ${fresh.report.fixes.applied} fixes applied`
                  : `Scan complete! Score: ${fresh.report.channel_health_score}/100`,
                "success"
              );
            }
          } catch {
            /* still running */
          }
        }, 5000);

        // Timeout after 5 minutes
        setTimeout(() => {
          clearInterval(poll);
          setScanning(false);
          setFixing(false);
        }, 300000);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : "Scan failed";
        toast(msg, "error");
        setScanning(false);
        setFixing(false);
      }
    },
    [report, refetch, toast]
  );

  // Format relative time
  const timeAgo = (iso: string) => {
    if (!iso) return "Never";
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "Just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    return `${days}d ago`;
  };

  return (
    <div className="min-h-screen p-6" style={{ background: "var(--bg-primary)" }}>
      {/* Header */}
      <div
        className="flex items-center justify-between mb-6 p-5 rounded-2xl"
        style={{
          background: "linear-gradient(135deg, var(--bg-secondary), var(--bg-primary))",
          border: "1px solid var(--border)",
        }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center"
            style={{ background: "#ff000015" }}
          >
            <Youtube size={20} style={{ color: "#ff0000" }} />
          </div>
          <div>
            <h1 className="text-xl font-black text-foreground">Channel Manager</h1>
            <p className="text-xs text-text-secondary">
              YouTube catalog health, metadata validation & auto-fixes
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => handleScan(false)}
            disabled={scanning || fixing}
            className="px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 transition-all"
            style={{
              background: "var(--bg-hover)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
              opacity: scanning || fixing ? 0.5 : 1,
            }}
          >
            {scanning ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <RefreshCw size={13} />
            )}
            {scanning ? "Scanning..." : "Scan Channel"}
          </button>

          <button
            onClick={() => handleScan(true)}
            disabled={scanning || fixing}
            className="px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 transition-all"
            style={{
              background: fixing ? "#f59e0b30" : "#22c55e15",
              border: `1px solid ${fixing ? "#f59e0b50" : "#22c55e30"}`,
              color: fixing ? "#f59e0b" : "#22c55e",
              opacity: scanning || fixing ? 0.5 : 1,
            }}
          >
            {fixing ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Wrench size={13} />
            )}
            {fixing ? "Fixing..." : "Scan & Fix"}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-64 gap-3 text-text-secondary">
          <Loader2 size={20} className="animate-spin" />
          <span className="text-sm">Loading channel data...</span>
        </div>
      ) : !report ? (
        <div
          className="p-8 rounded-2xl text-center"
          style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
        >
          <Youtube size={40} className="mx-auto mb-4" style={{ color: "#ff000040" }} />
          <h2 className="text-lg font-bold text-foreground mb-2">No Scan Data Yet</h2>
          <p className="text-sm text-text-secondary mb-4">
            Run your first channel scan to see health metrics, detect issues, and auto-fix metadata.
          </p>
          <button
            onClick={() => handleScan(false)}
            disabled={scanning}
            className="px-6 py-2.5 rounded-xl text-sm font-bold"
            style={{
              background: "linear-gradient(135deg, #ff0000, #cc0000)",
              color: "#fff",
            }}
          >
            {scanning ? "Scanning..." : "Run First Scan"}
          </button>
        </div>
      ) : (
        <>
          {/* Score + Overview Row */}
          <div className="grid grid-cols-1 lg:grid-cols-[auto_1fr] gap-6 mb-6">
            {/* Health Score */}
            <div
              className="p-6 rounded-2xl flex flex-col items-center justify-center"
              style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
            >
              <ScoreGauge score={report.channel_health_score} level={report.health_level} />
              <p className="text-[9px] text-text-tertiary mt-2">
                Last scan: {timeAgo(report.scanned_at)}
              </p>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              <StatCard
                icon={Youtube}
                label="Total Videos"
                value={report.overview.total_videos}
                color="#ff0000"
                sub={
                  report.overview.beats_count != null
                    ? `${report.overview.beats_count} beats · ${report.overview.shorts_count ?? 0} shorts`
                    : undefined
                }
              />
              <StatCard
                icon={Eye}
                label="Total Views"
                value={report.overview.total_views}
                color="#3b82f6"
              />
              <StatCard
                icon={ThumbsUp}
                label="Total Likes"
                value={report.overview.total_likes}
                color="#22c55e"
              />
              <StatCard
                icon={CheckCircle2}
                label="Clean Videos"
                value={report.overview.clean_videos}
                color="#22c55e"
                sub={`${Math.round(
                  (report.overview.clean_videos / Math.max(report.overview.total_videos, 1)) * 100
                )}% of catalog`}
              />
              <StatCard
                icon={AlertTriangle}
                label="Flagged"
                value={report.overview.flagged_videos}
                color={report.overview.flagged_videos > 0 ? "#f59e0b" : "#22c55e"}
              />
              <StatCard
                icon={Zap}
                label="Auto-Fixable"
                value={report.issues.auto_fixable}
                color="#8b5cf6"
                sub="Can be fixed with one click"
              />
              <StatCard
                icon={Wrench}
                label="Fixes Applied"
                value={report.fixes.applied}
                color="#22c55e"
              />
              <StatCard
                icon={Activity}
                label="Issues Left"
                value={report.fixes.remaining}
                color={report.fixes.remaining > 0 ? "#f59e0b" : "#22c55e"}
              />
            </div>
          </div>

          {/* Beats vs Shorts Breakdown */}
          {report.overview.beats_count != null && (
            <div
              className="p-5 rounded-2xl"
              style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
            >
              <h3 className="text-sm font-bold text-foreground mb-4 flex items-center gap-2">
                <BarChart3 size={15} style={{ color: "#8b5cf6" }} />
                Beats vs Shorts
              </h3>
              <div className="grid grid-cols-2 gap-4">
                {/* Beats */}
                <div className="p-4 rounded-xl" style={{ background: "var(--bg-primary)" }}>
                  <div className="flex items-center gap-2 mb-3">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: "#3b82f615" }}>
                      <Music size={15} style={{ color: "#3b82f6" }} />
                    </div>
                    <div>
                      <p className="text-lg font-black text-foreground">{report.overview.beats_count}</p>
                      <p className="text-[9px] text-text-tertiary uppercase tracking-wider font-bold">Full Beats</p>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-[10px]">
                      <span className="text-text-tertiary">Views</span>
                      <span className="font-semibold text-foreground">{(report.overview.beats_views ?? 0).toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between text-[10px]">
                      <span className="text-text-tertiary">Likes</span>
                      <span className="font-semibold text-foreground">{(report.overview.beats_likes ?? 0).toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between text-[10px]">
                      <span className="text-text-tertiary">Avg views/beat</span>
                      <span className="font-semibold text-foreground">
                        {report.overview.beats_count! > 0
                          ? Math.round((report.overview.beats_views ?? 0) / report.overview.beats_count!).toLocaleString()
                          : "0"}
                      </span>
                    </div>
                  </div>
                  {/* Bar */}
                  <div className="h-2 rounded-full overflow-hidden mt-3" style={{ background: "var(--bg-hover)" }}>
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.round((report.overview.beats_count! / Math.max(report.overview.total_videos, 1)) * 100)}%`,
                        background: "#3b82f6",
                      }}
                    />
                  </div>
                  <p className="text-[9px] text-text-tertiary mt-1 text-right">
                    {Math.round((report.overview.beats_count! / Math.max(report.overview.total_videos, 1)) * 100)}% of catalog
                  </p>
                </div>

                {/* Shorts */}
                <div className="p-4 rounded-xl" style={{ background: "var(--bg-primary)" }}>
                  <div className="flex items-center gap-2 mb-3">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: "#f59e0b15" }}>
                      <Smartphone size={15} style={{ color: "#f59e0b" }} />
                    </div>
                    <div>
                      <p className="text-lg font-black text-foreground">{report.overview.shorts_count ?? 0}</p>
                      <p className="text-[9px] text-text-tertiary uppercase tracking-wider font-bold">Shorts</p>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <div className="flex justify-between text-[10px]">
                      <span className="text-text-tertiary">Views</span>
                      <span className="font-semibold text-foreground">{(report.overview.shorts_views ?? 0).toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between text-[10px]">
                      <span className="text-text-tertiary">Likes</span>
                      <span className="font-semibold text-foreground">{(report.overview.shorts_likes ?? 0).toLocaleString()}</span>
                    </div>
                    <div className="flex justify-between text-[10px]">
                      <span className="text-text-tertiary">Avg views/short</span>
                      <span className="font-semibold text-foreground">
                        {(report.overview.shorts_count ?? 0) > 0
                          ? Math.round((report.overview.shorts_views ?? 0) / report.overview.shorts_count!).toLocaleString()
                          : "0"}
                      </span>
                    </div>
                  </div>
                  {/* Bar */}
                  <div className="h-2 rounded-full overflow-hidden mt-3" style={{ background: "var(--bg-hover)" }}>
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${Math.round(((report.overview.shorts_count ?? 0) / Math.max(report.overview.total_videos, 1)) * 100)}%`,
                        background: "#f59e0b",
                      }}
                    />
                  </div>
                  <p className="text-[9px] text-text-tertiary mt-1 text-right">
                    {Math.round(((report.overview.shorts_count ?? 0) / Math.max(report.overview.total_videos, 1)) * 100)}% of catalog
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Issues Breakdown + Quota */}
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6 mb-6">
            {/* Issues by Type */}
            <div
              className="p-5 rounded-2xl"
              style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
            >
              <div className="flex items-center gap-2 mb-4">
                <Shield size={15} style={{ color: "var(--accent)" }} />
                <h2 className="text-sm font-bold text-foreground">Issues Breakdown</h2>
                <span className="text-[10px] text-text-tertiary ml-auto">
                  {report.issues.high_severity} high · {report.issues.medium_severity} med ·{" "}
                  {report.issues.low_severity} low
                </span>
              </div>

              {Object.keys(report.issues.by_type).length === 0 ? (
                <div className="text-center py-8">
                  <CheckCircle2 size={28} className="mx-auto mb-2" style={{ color: "#22c55e" }} />
                  <p className="text-sm font-semibold text-foreground">All Clear!</p>
                  <p className="text-xs text-text-secondary">No metadata issues detected</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {Object.entries(report.issues.by_type)
                    .sort(([, a], [, b]) => (b as number) - (a as number))
                    .map(([type, count]) => {
                      const meta = ISSUE_TYPE_LABELS[type] || {
                        label: type.replace(/_/g, " "),
                        color: "#6b7280",
                      };
                      const pct = Math.round(
                        ((count as number) / Math.max(report.issues.total, 1)) * 100
                      );
                      return (
                        <div key={type}>
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs font-semibold text-foreground">
                              {meta.label}
                            </span>
                            <span className="text-xs font-bold" style={{ color: meta.color }}>
                              {count as number}
                            </span>
                          </div>
                          <div
                            className="h-1.5 rounded-full overflow-hidden"
                            style={{ background: "var(--bg-hover)" }}
                          >
                            <div
                              className="h-full rounded-full transition-all duration-500"
                              style={{
                                width: `${pct}%`,
                                background: meta.color,
                              }}
                            />
                          </div>
                        </div>
                      );
                    })}
                </div>
              )}
            </div>

            {/* API Quota */}
            <div
              className="p-5 rounded-2xl"
              style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
            >
              <div className="flex items-center gap-2 mb-4">
                <Gauge size={15} style={{ color: "#f59e0b" }} />
                <h2 className="text-sm font-bold text-foreground">API Quota</h2>
              </div>

              {quotaData ? (
                <div className="space-y-3">
                  <div className="flex justify-between text-xs">
                    <span className="text-text-secondary">Daily limit</span>
                    <span className="font-bold text-foreground">
                      {quotaData.daily_quota.toLocaleString()} units
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-text-secondary">Scan cost</span>
                    <span className="font-semibold text-text-primary">
                      ~{quotaData.scan_cost_estimate} units
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-text-secondary">Fix cost (if all)</span>
                    <span className="font-semibold text-text-primary">
                      ~{quotaData.fix_cost_estimate.toLocaleString()} units
                    </span>
                  </div>

                  <div
                    className="h-px my-2"
                    style={{ background: "var(--border)" }}
                  />

                  <div className="flex justify-between text-xs">
                    <span className="text-text-secondary">Remaining for uploads</span>
                    <span className="font-bold" style={{ color: "#22c55e" }}>
                      {quotaData.remaining_for_uploads.toLocaleString()} units
                    </span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-text-secondary">Safe uploads today</span>
                    <span className="font-bold" style={{ color: "#22c55e" }}>
                      {quotaData.safe_uploads_remaining}
                    </span>
                  </div>

                  <div
                    className="p-2.5 rounded-lg mt-2"
                    style={{ background: "#22c55e08", border: "1px solid #22c55e20" }}
                  >
                    <p className="text-[10px] text-text-secondary leading-relaxed">
                      Daily auto-scan uses <b>~{quotaData.scan_cost_estimate} units</b> (scan
                      only). Fixes use 50 units each and are only applied manually via
                      &quot;Scan & Fix&quot;.
                    </p>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-text-tertiary">Loading quota data...</p>
              )}
            </div>
          </div>

          {/* Top Videos */}
          {report.top_videos && report.top_videos.length > 0 && (
            <div
              className="p-5 rounded-2xl"
              style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
            >
              <div className="flex items-center gap-2 mb-4">
                <TrendingUp size={15} style={{ color: "#3b82f6" }} />
                <h2 className="text-sm font-bold text-foreground">Top Performing Videos</h2>
              </div>

              <div className="space-y-2">
                {report.top_videos.map((v, i) => (
                  <div
                    key={v.video_id}
                    className="flex items-center gap-3 p-2.5 rounded-xl"
                    style={{ background: "var(--bg-primary)" }}
                  >
                    <span
                      className="w-6 h-6 rounded-lg flex items-center justify-center text-[10px] font-black flex-shrink-0"
                      style={{
                        background: i < 3 ? "#f59e0b15" : "var(--bg-hover)",
                        color: i < 3 ? "#f59e0b" : "var(--text-tertiary)",
                      }}
                    >
                      {i + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-foreground truncate">{v.title}</p>
                      <p className="text-[10px] text-text-tertiary">
                        {v.views.toLocaleString()} views · {v.likes.toLocaleString()} likes
                      </p>
                    </div>
                    <a
                      href={`https://youtube.com/watch?v=${v.video_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[10px] font-bold flex items-center gap-1 flex-shrink-0"
                      style={{ color: "#ff0000" }}
                    >
                      <ExternalLink size={10} />
                    </a>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
