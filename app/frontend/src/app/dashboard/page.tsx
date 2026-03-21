"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import {
  Music,
  Film,
  Upload,
  Clock,
  ArrowUpRight,
  CheckCircle2,
  Youtube,
  Zap,
  Loader2,
  TrendingUp,
  Sparkles,
  AlertCircle,
  Activity,
} from "lucide-react";
import OnboardingModal from "@/components/OnboardingModal";
import HealthWidget from "@/components/HealthWidget";
import { useFetch, api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import { useSettings } from "@/hooks/useSettings";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

interface StatusData {
  total_beats: number;
  rendered: number;
  uploaded_yt: number;
  pending_renders: number;
  uploaded_social: number;
  recent_activity: {
    stem: string;
    title: string;
    uploadedAt: string;
    url: string;
    publishAt?: string;
  }[];
}

interface BeatSummary {
  stem: string;
  rendered: boolean;
  uploaded: boolean;
}

/* -- Ring chart SVG component ----------------------------------------- */

function RingChart({
  value,
  max,
  color,
  label,
  sublabel,
  size = 100,
}: {
  value: number;
  max: number;
  color: string;
  label: string;
  sublabel: string;
  size?: number;
}) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  const strokeWidth = 6;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (pct / 100) * circumference;

  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="rotate-[-90deg]">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="var(--border)"
            strokeWidth={strokeWidth}
          />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            className="ring-progress"
            style={{
              filter: `drop-shadow(0 0 8px ${color}60)`,
            }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className="text-2xl font-bold tabular-nums"
            style={{ color }}
          >
            {pct}%
          </span>
        </div>
      </div>
      <div className="text-center">
        <p className="text-[13px] font-semibold text-foreground">{label}</p>
        <p className="text-[11px] text-text-tertiary">{sublabel}</p>
      </div>
    </div>
  );
}

/* -- Main Dashboard --------------------------------------------------- */

export default function Dashboard() {
  const { data, loading, refetch } = useFetch<StatusData>("/status");
  const { data: beats, refetch: refetchBeats } = useFetch<BeatSummary[]>("/beats");
  const { toast } = useToast();
  const { settings } = useSettings();

  const [renderingAll, setRenderingAll] = useState(false);
  const [uploadingBatch, setUploadingBatch] = useState(false);

  const unrenderedStems = beats?.filter((b) => !b.rendered).map((b) => b.stem) ?? [];
  const uploadableStems = beats?.filter((b) => b.rendered && !b.uploaded).map((b) => b.stem) ?? [];

  const renderPct = data
    ? Math.round((data.rendered / Math.max(data.total_beats, 1)) * 100)
    : 0;
  const uploadPct = data
    ? Math.round((data.uploaded_yt / Math.max(data.rendered, 1)) * 100)
    : 0;
  const socialPct = data && data.uploaded_social > 0
    ? Math.round((data.uploaded_social / Math.max(data.uploaded_yt, 1)) * 100)
    : 0;

  const handleRenderAll = useCallback(async () => {
    if (unrenderedStems.length === 0) return;
    setRenderingAll(true);
    let ok = 0;
    for (const stem of unrenderedStems) {
      try {
        await api.post(`/render/${stem}`);
        ok++;
      } catch {
        /* continue */
      }
    }
    toast(
      `Rendered ${ok} beat${ok !== 1 ? "s" : ""}`,
      ok > 0 ? "success" : "error"
    );
    setRenderingAll(false);
    refetch();
    refetchBeats();
  }, [unrenderedStems, toast, refetch, refetchBeats]);

  const handleUploadBatch = useCallback(async () => {
    const batch = uploadableStems.slice(0, 10);
    if (batch.length === 0) return;
    setUploadingBatch(true);
    const privacy = settings.defaultPrivacy || "unlisted";
    let ok = 0;
    for (const stem of batch) {
      try {
        await api.post(`/youtube/upload/${stem}`, { privacy });
        ok++;
      } catch {
        /* continue */
      }
    }
    toast(
      `Uploaded ${ok} video${ok !== 1 ? "s" : ""}`,
      ok > 0 ? "success" : "error"
    );
    setUploadingBatch(false);
    refetch();
    refetchBeats();
  }, [uploadableStems, settings.defaultPrivacy, toast, refetch, refetchBeats]);

  return (
    <div className="animate-fade-in">
      <OnboardingModal />

      {/* ================================================================
          GLASS HEADER — Welcome greeting with stat pill
          ================================================================ */}
      <div className="page-header">
        <div className="flex items-center justify-between">
          <div>
            <h1>Dashboard</h1>
            <p className="page-subtitle">
              Welcome back — your automation pipeline at a glance
            </p>
          </div>
          <div className="flex items-center gap-2 relative z-10 flex-shrink-0">
            {!loading && data && (
              <div
                className="hidden sm:flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded-full whitespace-nowrap"
                style={{
                  background: "var(--bg-card)",
                  backdropFilter: "blur(12px)",
                  border: "1px solid var(--glass-border)",
                  color: "var(--text-secondary)",
                }}
              >
                <Activity size={12} className="text-success" />
                <span className="tabular-nums font-semibold" style={{ color: "var(--text-primary)" }}>{data.total_beats}</span>
                <span>beats</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ================================================================
          BENTO STAT GRID — First card is hero size, rest are standard
          ================================================================ */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5 mb-10 stagger-children">
        {/* Total Beats — Hero card */}
        <Link
          href="/beats"
          className="stat-card p-6 block cursor-pointer group col-span-2 row-span-2 lg:col-span-2 lg:row-span-2"
          style={{ "--stat-accent": "#006aff" } as React.CSSProperties}
        >
          <div className="relative z-10 h-full flex flex-col justify-between">
            <div className="flex items-center gap-3 mb-4">
              <div
                className="w-12 h-12 rounded-xl flex items-center justify-center"
                style={{ background: "rgba(0, 106, 255, 0.15)" }}
              >
                <Music size={22} className="text-accent" />
              </div>
              <div className="flex-1" />
              <div
                className="px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider"
                style={{ background: "var(--accent-muted)", color: "var(--accent)" }}
              >
                Library
              </div>
            </div>
            {loading ? (
              <div className="space-y-3 mt-auto">
                <Skeleton className="h-16 w-28 rounded-xl" />
                <Skeleton className="h-4 w-24 rounded-lg" />
              </div>
            ) : (
              <div className="mt-auto">
                <p
                  className="font-bold tabular-nums leading-none"
                  style={{ fontSize: "3.5rem", letterSpacing: "-0.035em", color: "var(--text-primary)" }}
                >
                  {data?.total_beats ?? 0}
                </p>
                <p className="metric-label mt-3">Total Beats</p>
                {/* Decorative ring chart */}
                <div className="absolute bottom-6 right-6 opacity-30 group-hover:opacity-50 transition-opacity">
                  <RingChart
                    value={data?.rendered ?? 0}
                    max={data?.total_beats ?? 1}
                    color="var(--accent)"
                    label=""
                    sublabel=""
                    size={100}
                  />
                </div>
              </div>
            )}
          </div>
        </Link>

        {/* Rendered */}
        <Link
          href="/automation"
          className="stat-card p-6 block cursor-pointer group"
          style={{ "--stat-accent": "#00d362" } as React.CSSProperties}
        >
          <div className="relative z-10">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: "rgba(0, 211, 98, 0.15)" }}>
                <Film size={18} style={{ color: "#00d362" }} />
              </div>
            </div>
            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-12 w-16 rounded-xl" />
                <Skeleton className="h-3 w-20 rounded" />
              </div>
            ) : (
              <>
                <p className="metric-value">{data?.rendered ?? 0}</p>
                <p className="metric-label">Rendered</p>
              </>
            )}
          </div>
        </Link>

        {/* Uploaded */}
        <Link
          href="/analytics"
          className="stat-card p-6 block cursor-pointer group"
          style={{ "--stat-accent": "#ff453a" } as React.CSSProperties}
        >
          <div className="relative z-10">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: "rgba(255, 69, 58, 0.15)" }}>
                <Upload size={18} style={{ color: "#ff453a" }} />
              </div>
            </div>
            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-12 w-16 rounded-xl" />
                <Skeleton className="h-3 w-20 rounded" />
              </div>
            ) : (
              <>
                <p className="metric-value">{data?.uploaded_yt ?? 0}</p>
                <p className="metric-label">Uploaded</p>
              </>
            )}
          </div>
        </Link>

        {/* Pending */}
        <Link
          href="/automation"
          className="stat-card p-6 block cursor-pointer group lg:col-span-2"
          style={{ "--stat-accent": "#ffd60a" } as React.CSSProperties}
        >
          <div className="relative z-10 flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2 mb-4">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center" style={{ background: "rgba(255, 214, 10, 0.15)" }}>
                  <Clock size={18} style={{ color: "#ffd60a" }} />
                </div>
              </div>
              {loading ? (
                <div className="space-y-2">
                  <Skeleton className="h-12 w-16 rounded-xl" />
                  <Skeleton className="h-3 w-20 rounded" />
                </div>
              ) : (
                <>
                  <p className="metric-value">{data?.pending_renders ?? 0}</p>
                  <p className="metric-label">Pending Renders</p>
                </>
              )}
            </div>
            {!loading && data && data.pending_renders > 0 && (
              <div
                className="px-3 py-1.5 rounded-full text-xs font-semibold"
                style={{ background: "rgba(255, 214, 10, 0.12)", color: "#ffd60a" }}
              >
                Needs attention
              </div>
            )}
          </div>
        </Link>
      </div>

      {/* ================================================================
          PIPELINE OVERVIEW — Glass card with big progress bars
          ================================================================ */}
      {!loading && data && (
        <div
          className="mb-10 animate-scale-in"
          style={{
            background: "var(--bg-card)",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            border: "1px solid var(--glass-border)",
            borderRadius: "20px",
          }}
        >
          <div className="px-8 pt-8 pb-3">
            <div className="section-header">Pipeline Overview</div>
          </div>

          <div className="px-8 pb-8">
            <div className="space-y-8">
              {/* Render Progress */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center"
                      style={{ background: "var(--success-muted)" }}
                    >
                      <Film size={15} className="text-success" />
                    </div>
                    <span className="text-sm font-semibold text-foreground">Render Progress</span>
                  </div>
                  <span
                    className="font-bold tabular-nums"
                    style={{ fontSize: "2rem", color: "var(--success)", lineHeight: 1, letterSpacing: "-0.03em" }}
                  >
                    {renderPct}%
                  </span>
                </div>
                <div
                  className="h-3 rounded-full overflow-hidden"
                  style={{ background: "var(--bg-hover)" }}
                >
                  <div
                    className="h-full rounded-full bg-success animate-bar-fill"
                    style={{
                      width: `${renderPct}%`,
                      boxShadow: "0 0 20px var(--success)",
                    }}
                  />
                </div>
                <p className="text-xs text-text-tertiary mt-2.5">
                  {data.rendered} of {data.total_beats} beats rendered
                </p>
              </div>

              {/* Upload Progress */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center"
                      style={{ background: "var(--accent-muted)" }}
                    >
                      <Upload size={15} className="text-accent" />
                    </div>
                    <span className="text-sm font-semibold text-foreground">Upload Progress</span>
                  </div>
                  <span
                    className="font-bold tabular-nums"
                    style={{ fontSize: "2rem", color: "var(--accent)", lineHeight: 1, letterSpacing: "-0.03em" }}
                  >
                    {uploadPct}%
                  </span>
                </div>
                <div
                  className="h-3 rounded-full overflow-hidden"
                  style={{ background: "var(--bg-hover)" }}
                >
                  <div
                    className="h-full rounded-full bg-accent animate-bar-fill"
                    style={{
                      width: `${uploadPct}%`,
                      boxShadow: "0 0 20px var(--accent)",
                    }}
                  />
                </div>
                <p className="text-xs text-text-tertiary mt-2.5">
                  {data.uploaded_yt} of {data.rendered} rendered videos uploaded
                </p>
              </div>

              {/* Social Progress */}
              {data.uploaded_social > 0 && (
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div
                        className="w-8 h-8 rounded-lg flex items-center justify-center"
                        style={{ background: "rgba(191, 90, 242, 0.12)" }}
                      >
                        <Sparkles size={15} style={{ color: "#bf5af2" }} />
                      </div>
                      <span className="text-sm font-semibold text-foreground">Social Distribution</span>
                    </div>
                    <span
                      className="font-extrabold tabular-nums"
                      style={{ fontSize: "2.5rem", color: "#bf5af2", lineHeight: 1, letterSpacing: "-0.03em" }}
                    >
                      {socialPct}%
                    </span>
                  </div>
                  <div
                    className="h-3 rounded-full overflow-hidden"
                    style={{ background: "var(--bg-hover)" }}
                  >
                    <div
                      className="h-full rounded-full animate-bar-fill"
                      style={{
                        width: `${socialPct}%`,
                        background: "#bf5af2",
                        boxShadow: "0 0 20px rgba(191, 90, 242, 0.5)",
                      }}
                    />
                  </div>
                  <p className="text-xs text-text-tertiary mt-2.5">
                    {data.uploaded_social} of {data.uploaded_yt} videos shared
                  </p>
                </div>
              )}
            </div>

            {/* Ring charts */}
            <div className="flex flex-wrap items-center justify-center gap-6 sm:gap-12 mt-10 pt-8" style={{ borderTop: "1px solid var(--border)" }}>
              <RingChart
                value={data.rendered}
                max={data.total_beats}
                color="var(--success)"
                label="Renders"
                sublabel={`${data.rendered}/${data.total_beats}`}
                size={110}
              />
              <RingChart
                value={data.uploaded_yt}
                max={data.rendered}
                color="var(--accent)"
                label="Uploads"
                sublabel={`${data.uploaded_yt}/${data.rendered}`}
                size={110}
              />
              {data.uploaded_social > 0 && (
                <RingChart
                  value={data.uploaded_social}
                  max={data.uploaded_yt}
                  color="#bf5af2"
                  label="Social"
                  sublabel={`${data.uploaded_social}/${data.uploaded_yt}`}
                  size={110}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {/* ================================================================
          QUICK ACTIONS — Accent glow glass card
          ================================================================ */}
      {!loading && (unrenderedStems.length > 0 || uploadableStems.length > 0) && (
        <div className="accent-glow-card p-8 mb-10">
          <h2 className="relative z-10 text-sm font-bold text-accent mb-6 flex items-center gap-2 uppercase tracking-wider">
            <Zap size={15} />
            Quick Actions
          </h2>
          <div className="relative z-10 flex flex-wrap gap-4">
            {unrenderedStems.length > 0 && (
              <button
                onClick={handleRenderAll}
                disabled={renderingAll}
                className="btn-gradient flex items-center gap-2.5 h-12 px-6"
                style={
                  renderingAll
                    ? { opacity: 0.5, cursor: "not-allowed", background: "var(--bg-hover)" }
                    : { background: "linear-gradient(135deg, var(--success), #00a848)" }
                }
              >
                {renderingAll ? (
                  <Loader2 size={17} className="animate-spin" />
                ) : (
                  <Zap size={17} />
                )}
                {renderingAll
                  ? "Rendering..."
                  : `Render All (${unrenderedStems.length})`}
              </button>
            )}
            {uploadableStems.length > 0 && (
              <button
                onClick={handleUploadBatch}
                disabled={uploadingBatch}
                className="btn-gradient flex items-center gap-2.5 h-12 px-6"
                style={
                  uploadingBatch
                    ? { opacity: 0.5, cursor: "not-allowed", background: "var(--bg-hover)" }
                    : {}
                }
              >
                {uploadingBatch ? (
                  <Loader2 size={17} className="animate-spin" />
                ) : (
                  <Upload size={17} />
                )}
                {uploadingBatch
                  ? "Uploading..."
                  : `Upload Batch (${Math.min(uploadableStems.length, 10)})`}
              </button>
            )}
          </div>
        </div>
      )}

      {/* ================================================================
          ACTION ITEMS — Glass cards with colored left gradient
          ================================================================ */}
      {!loading && data && (unrenderedStems.length > 0 || uploadableStems.length > 0) && (
        <div className="mb-10 animate-scale-in" style={{ animationDelay: "100ms" }}>
          <div className="section-header mb-5">
            <span className="flex items-center gap-2">
              <AlertCircle size={15} />
              Action Items
            </span>
          </div>
          <div className="space-y-4">
            {unrenderedStems.length > 0 && (
              <div
                className="flex items-center justify-between p-5 rounded-2xl transition-all duration-300"
                style={{
                  background: "var(--bg-card)",
                  backdropFilter: "blur(12px)",
                  WebkitBackdropFilter: "blur(12px)",
                  border: "1px solid var(--glass-border)",
                  borderLeft: "4px solid var(--warning)",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "var(--bg-card-hover)";
                  e.currentTarget.style.transform = "translateX(4px)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "var(--bg-card)";
                  e.currentTarget.style.transform = "translateX(0)";
                }}
              >
                <div className="flex items-center gap-4">
                  <div className="w-11 h-11 rounded-xl flex items-center justify-center bg-warning-muted">
                    <Film size={20} className="text-warning" />
                  </div>
                  <div>
                    <span className="text-sm font-semibold text-foreground">
                      {unrenderedStems.length} beat{unrenderedStems.length !== 1 ? "s" : ""} need rendering
                    </span>
                    <p className="text-xs text-text-tertiary mt-0.5">Ready to generate videos</p>
                  </div>
                </div>
                <Button variant="accent" size="xs" asChild>
                  <Link href="/automation" prefetch={false} className="font-semibold">
                    Render
                    <ArrowUpRight size={12} />
                  </Link>
                </Button>
              </div>
            )}
            {uploadableStems.length > 0 && (
              <div
                className="flex items-center justify-between p-5 rounded-2xl transition-all duration-300"
                style={{
                  background: "var(--bg-card)",
                  backdropFilter: "blur(12px)",
                  WebkitBackdropFilter: "blur(12px)",
                  border: "1px solid var(--glass-border)",
                  borderLeft: "4px solid var(--accent)",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "var(--bg-card-hover)";
                  e.currentTarget.style.transform = "translateX(4px)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "var(--bg-card)";
                  e.currentTarget.style.transform = "translateX(0)";
                }}
              >
                <div className="flex items-center gap-4">
                  <div className="w-11 h-11 rounded-xl flex items-center justify-center bg-accent-muted">
                    <Upload size={20} className="text-accent" />
                  </div>
                  <div>
                    <span className="text-sm font-semibold text-foreground">
                      {uploadableStems.length} video{uploadableStems.length !== 1 ? "s" : ""} ready to upload
                    </span>
                    <p className="text-xs text-text-tertiary mt-0.5">Rendered and ready for YouTube</p>
                  </div>
                </div>
                <Button variant="accent" size="xs" asChild>
                  <Link href="/automation" prefetch={false} className="font-semibold">
                    Upload
                    <ArrowUpRight size={12} />
                  </Link>
                </Button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ================================================================
          RECENT ACTIVITY — Glass table
          ================================================================ */}
      <div className="mb-10">
        <div className="section-header mb-5">
          <span className="flex items-center gap-2">
            <TrendingUp size={15} />
            Recent Activity
          </span>
        </div>
        <div
          className="overflow-hidden"
          style={{
            background: "var(--bg-card)",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            border: "1px solid var(--glass-border)",
            borderRadius: "20px",
          }}
        >
          {/* Table header */}
          <div
            className="grid grid-cols-[auto_1fr_auto_auto] gap-3 items-center px-5 py-3 text-[10px] font-medium uppercase tracking-wider"
            style={{
              borderBottom: "1px solid var(--border)",
              background: "var(--bg-hover)",
              color: "var(--text-tertiary)",
            }}
          >
            <span className="w-10">Type</span>
            <span className="truncate">Title</span>
            <span className="hidden sm:block whitespace-nowrap">Date</span>
            <span className="w-14 text-right">Action</span>
          </div>

          {loading ? (
            <div className="p-6 space-y-4">
              {[1, 2, 3].map((i) => (
                <div key={i} className="grid grid-cols-[auto_1fr_auto_auto] gap-4 items-center">
                  <Skeleton className="w-10 h-10 rounded-xl" />
                  <div className="space-y-2">
                    <Skeleton className="h-4 w-48 rounded-lg" />
                    <Skeleton className="h-3 w-32 rounded-lg" />
                  </div>
                  <Skeleton className="h-3 w-20 rounded hidden sm:block" />
                  <Skeleton className="h-7 w-16 rounded-lg" />
                </div>
              ))}
            </div>
          ) : data?.recent_activity?.length ? (
            <div>
              {data.recent_activity.map((item, idx) => (
                <div
                  key={item.stem}
                  className="grid grid-cols-[auto_1fr_auto_auto] gap-3 items-center px-5 py-3.5 transition-all duration-200 group"
                  style={{
                    borderBottom: idx < data.recent_activity.length - 1 ? "1px solid var(--border)" : "none",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = "var(--bg-hover)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "transparent";
                  }}
                >
                  {/* YouTube badge */}
                  <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 bg-[#ff0000]/10 group-hover:bg-[#ff0000]/20 transition-colors">
                    <Youtube
                      size={18}
                      style={{ color: "#ff0000" }}
                      strokeWidth={1.8}
                    />
                  </div>

                  {/* Title + schedule badge */}
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate text-foreground group-hover:text-accent transition-colors">
                      {item.title || item.stem}
                    </p>
                    {item.publishAt && (
                      <span className="badge badge-warning mt-1 inline-block">
                        Scheduled{" "}
                        {new Date(item.publishAt).toLocaleDateString(
                          "en-US",
                          { month: "short", day: "numeric" }
                        )}
                      </span>
                    )}
                  </div>

                  {/* Date */}
                  <span className="text-xs text-text-tertiary tabular-nums hidden sm:block">
                    {new Date(item.uploadedAt).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                      hour: "numeric",
                      minute: "2-digit",
                    })}
                  </span>

                  {/* Action */}
                  {item.url ? (
                    <Button variant="accent" size="xs" asChild>
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex-shrink-0 font-semibold"
                      >
                        View
                        <ArrowUpRight size={11} />
                      </a>
                    </Button>
                  ) : (
                    <div className="w-16" />
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="py-16 text-center">
              <div
                className="w-16 h-16 rounded-2xl flex items-center justify-center mx-auto mb-5"
                style={{
                  background: "var(--bg-hover)",
                  border: "1px solid var(--glass-border)",
                }}
              >
                <CheckCircle2
                  size={28}
                  className="text-text-tertiary"
                  strokeWidth={1.2}
                />
              </div>
              <p className="text-sm font-medium text-muted-foreground">
                No recent uploads yet
              </p>
              <p className="text-xs text-text-tertiary mt-2">
                Upload your first video to see activity here
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ================================================================
          SYSTEM HEALTH
          ================================================================ */}
      <div className="mb-6">
        <HealthWidget />
      </div>
    </div>
  );
}
