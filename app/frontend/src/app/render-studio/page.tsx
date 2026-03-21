"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Film,
  Sparkles,
  ImagePlus,
  Smartphone,
  Minimize2,
  Music,
  Clock,
  CheckCircle2,
  Loader2,
  X,
  ChevronDown,
  ChevronUp,
  Activity,
  CloudOff,
  Trash2,
  XCircle,
  AlertCircle,
  Play,
  RotateCcw,
  ExternalLink,
  Users,
} from "lucide-react";
import { useFetch, api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import SearchInput from "@/components/ui/SearchInput";
import { useWebSocket } from "@/hooks/useWebSocket";
import StatCard from "@/components/StatCard";
import StatusBadge from "@/components/StatusBadge";
import VideoPreviewModal from "@/components/VideoPreviewModal";

/* ── Types ────────────────────────────────────────────────────── */

interface StatusData {
  total_beats: number;
  rendered: number;
  uploaded_yt: number;
  pending_renders: number;
}

interface BeatSummary {
  stem: string;
  title?: string;
  beat_name?: string;
  artist?: string;
  rendered: boolean;
  uploaded: boolean;
  has_thumbnail?: boolean;
  bpm?: number;
  key?: string;
  lane?: string;
  seo_artist?: string;
}

interface ArtistInfo {
  name: string;
  clips: number;
  images: number;
}

interface ArtistsResponse {
  artists: ArtistInfo[];
}

interface QueueTask {
  id: string;
  type: string;
  stem: string;
  status: string;
  progress?: number;
  created_at?: string;
}

interface QueueData {
  active: QueueTask[];
  pending: QueueTask[];
  completed: QueueTask[];
}

interface BackgroundJob {
  id: string;
  type: string;
  stems: string[];
  params: Record<string, unknown>;
  label: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  detail: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
}

interface JobsData {
  queued: number;
  running: number;
  done: number;
  failed: number;
  cancelled: number;
  total: number;
  jobs: BackgroundJob[];
}

/* ── Render-only steps ────────────────────────────────────────── */

const RENDER_STEPS = [
  { id: "seo", label: "SEO", jobType: "seo", icon: Sparkles, color: "#b44eff", description: "Auto-generate titles, tags & descriptions" },
  { id: "thumbnail", label: "Thumbnails", jobType: "thumbnail", icon: ImagePlus, color: "#e040fb", description: "Generate AI thumbnail for each beat" },
  { id: "render_16_9", label: "Render 16:9", jobType: "render", icon: Film, color: "#00d362", description: "Full YouTube video (1920x1080)" },
  { id: "convert_9_16", label: "Convert 9:16", jobType: "convert", icon: Smartphone, color: "#38bdf8", description: "Vertical for Shorts / Reels / TikTok" },
  { id: "compress", label: "Compress", jobType: "compress", icon: Minimize2, color: "#f5a623", description: "Compress videos for social platforms" },
];

const RENDER_JOB_TYPES = new Set(["seo", "thumbnail", "render", "convert", "compress"]);

/* ── Lane colors ──────────────────────────────────────────────── */

const LANE_COLORS: Record<string, string> = {
  breakfast: "#f5a623",
  lunch: "#38bdf8",
  dinner: "#e040fb",
};

/* ── Time ago helper ──────────────────────────────────────────── */

function timeAgo(iso: string | null): string {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

/* ── Job status icon ──────────────────────────────────────────── */

function JobStatusIcon({ status }: { status: string }) {
  switch (status) {
    case "queued":
      return <Clock size={13} className="text-text-tertiary" />;
    case "running":
      return <Loader2 size={13} className="animate-spin" style={{ color: "#38bdf8" }} />;
    case "done":
      return <CheckCircle2 size={13} style={{ color: "#00d362" }} />;
    case "failed":
      return <XCircle size={13} style={{ color: "#ff4444" }} />;
    case "cancelled":
      return <AlertCircle size={13} style={{ color: "#f5a623" }} />;
    default:
      return <Clock size={13} className="text-text-tertiary" />;
  }
}

/* ── Page ─────────────────────────────────────────────────────── */

export default function RenderStudioPage() {
  /* ── Data fetching ── */
  const router = useRouter();
  const { data: status, loading: statusLoading } = useFetch<StatusData>("/status");
  const { data: beats, refetch: refetchBeats } = useFetch<BeatSummary[]>("/beats");
  const { data: artistsData } = useFetch<ArtistsResponse>("/media/artists");
  const { data: queue } = useFetch<QueueData>("/queue");
  const { data: jobsData, refetch: refetchJobs } = useFetch<JobsData>("/jobs");
  const { toast } = useToast();
  const { lastMessage } = useWebSocket();

  /* ── Auto-poll background jobs every 5s ── */
  useEffect(() => {
    const interval = setInterval(() => {
      refetchJobs();
    }, 5000);
    return () => clearInterval(interval);
  }, [refetchJobs]);

  /* ── Live progress tracking from WebSocket ── */
  const [liveProgress, setLiveProgress] = useState<Map<string, { pct: number; detail: string; phase: string }>>(new Map());

  useEffect(() => {
    if (!lastMessage || lastMessage.type !== "progress") return;
    if (!lastMessage.stem) return;
    const stem = lastMessage.stem;
    const pct = lastMessage.pct ?? 0;

    setLiveProgress((prev) => {
      const next = new Map(prev);
      next.set(stem, {
        pct,
        detail: lastMessage.detail ?? "",
        phase: lastMessage.phase ?? "",
      });
      return next;
    });

    // Clear completed entries after a short delay + refetch
    if (pct >= 100) {
      setTimeout(() => {
        setLiveProgress((p) => {
          const n = new Map(p);
          n.delete(stem);
          return n;
        });
        refetchBeats();
      }, 2000);
    }
  }, [lastMessage, refetchBeats]);

  /* ── Selection + filter state ── */
  const [selectedStems, setSelectedStems] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<"all" | "pending" | "rendered" | "no_thumb">("all");
  const [artistFilter, setArtistFilter] = useState<string>("all");
  const [enabledSteps, setEnabledSteps] = useState<Set<string>>(new Set(["seo", "render_16_9"]));
  const [submitting, setSubmitting] = useState(false);
  const [showJobHistory, setShowJobHistory] = useState(false);
  const [showCompleted, setShowCompleted] = useState(false);
  const [videoPreviewStem, setVideoPreviewStem] = useState<string | null>(null);

  /* ── Derived beat lists ── */
  const allBeats = beats ?? [];

  const pendingBeats = useMemo(() => allBeats.filter((b) => !b.rendered), [allBeats]);
  const renderedBeats = useMemo(() => allBeats.filter((b) => b.rendered), [allBeats]);
  const missingThumbBeats = useMemo(() => allBeats.filter((b) => !b.has_thumbnail), [allBeats]);
  const artistNames = useMemo(() => (artistsData?.artists ?? []).map((a) => a.name), [artistsData]);
  const unassignedBeats = useMemo(() => allBeats.filter((b) => !b.seo_artist || b.seo_artist === "NOT SET"), [allBeats]);

  const filteredBeats = useMemo(() => {
    let list = allBeats;
    if (filter === "pending") list = list.filter((b) => !b.rendered);
    else if (filter === "rendered") list = list.filter((b) => b.rendered);
    else if (filter === "no_thumb") list = list.filter((b) => !b.has_thumbnail);

    if (artistFilter !== "all") {
      if (artistFilter === "unassigned") {
        list = list.filter((b) => !b.seo_artist || b.seo_artist === "NOT SET");
      } else {
        list = list.filter((b) => b.seo_artist === artistFilter);
      }
    }

    if (search) {
      const q = search.toLowerCase();
      list = list.filter(
        (b) =>
          b.stem.toLowerCase().includes(q) ||
          (b.title ?? "").toLowerCase().includes(q) ||
          (b.artist ?? "").toLowerCase().includes(q) ||
          (b.seo_artist ?? "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [allBeats, search, filter, artistFilter]);

  /* ── Background jobs — filtered to render types only ── */
  const bgJobs = jobsData?.jobs ?? [];
  const renderJobs = useMemo(() => bgJobs.filter((j) => {
    // Check job type or label for render-related work
    if (RENDER_JOB_TYPES.has(j.type)) return true;
    const labelLower = j.label.toLowerCase();
    return RENDER_JOB_TYPES.has(labelLower.split(" ")[0]) ||
      labelLower.includes("render") || labelLower.includes("seo") ||
      labelLower.includes("thumbnail") || labelLower.includes("convert") ||
      labelLower.includes("compress");
  }), [bgJobs]);
  const activeJobs = renderJobs.filter((j) => j.status === "running" || j.status === "queued");
  const completedJobs = renderJobs.filter((j) => j.status === "done" || j.status === "failed" || j.status === "cancelled");
  const hasActiveJobs = activeJobs.length > 0;

  /* ── Render queue — filtered to render types only ── */
  const renderQueue = useMemo(() => ({
    active: (queue?.active ?? []).filter((t) => RENDER_JOB_TYPES.has(t.type)),
    pending: (queue?.pending ?? []).filter((t) => RENDER_JOB_TYPES.has(t.type)),
    completed: (queue?.completed ?? []).filter((t) => RENDER_JOB_TYPES.has(t.type)),
  }), [queue]);

  /* ── Selection helpers ── */
  const toggleBeat = (stem: string) => {
    setSelectedStems((prev) => {
      const next = new Set(prev);
      if (next.has(stem)) next.delete(stem);
      else next.add(stem);
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelectedStems((prev) => {
      const next = new Set(prev);
      filteredBeats.forEach((b) => next.add(b.stem));
      return next;
    });
  };

  const clearSelection = () => setSelectedStems(new Set());

  /* ── Step toggle ── */
  const toggleStep = (id: string) => {
    setEnabledSteps((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  /* ── Actions ── */
  const renderSingle = useCallback(async (stem: string) => {
    try {
      await api.post(`/render/${stem}`);
      toast(`Rendering ${stem.replace(/_/g, " ")}`, "success");
      refetchBeats();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Render failed";
      toast(msg, "error");
    }
  }, [toast, refetchBeats]);

  const setArtistForBeat = useCallback(async (stem: string, artist: string) => {
    try {
      await api.put(`/seo/${stem}`, { seo_artist: artist });
      toast(`Set ${stem.replace(/_/g, " ")} → ${artist}`, "success");
      refetchBeats();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to set artist";
      toast(msg, "error");
    }
  }, [toast, refetchBeats]);

  const setArtistBatch = useCallback(async (stems: string[], artist: string) => {
    try {
      await Promise.all(stems.map((s) => api.put(`/seo/${s}`, { seo_artist: artist })));
      toast(`Set ${stems.length} beat${stems.length !== 1 ? "s" : ""} → ${artist}`, "success");
      refetchBeats();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to set artist";
      toast(msg, "error");
    }
  }, [toast, refetchBeats]);

  const renderBatch = useCallback(async (stems: string[]) => {
    if (stems.length === 0) {
      toast("No beats to render", "error");
      return;
    }
    if (enabledSteps.size === 0) {
      toast("No steps selected", "error");
      return;
    }

    setSubmitting(true);
    try {
      const steps = RENDER_STEPS
        .filter((s) => enabledSteps.has(s.id))
        .map((s) => s.jobType);

      const response = await api.post<{ submitted: number; job_ids: string[]; message: string }>("/jobs/submit", {
        steps,
        stems,
        params: {},
      });

      toast(response.message, "success");
      refetchJobs();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to submit";
      toast(msg, "error");
    } finally {
      setSubmitting(false);
    }
  }, [enabledSteps, toast, refetchJobs]);

  const cancelBackgroundJob = useCallback(async (jobId: string) => {
    try {
      await api.post(`/jobs/${jobId}/cancel`);
      toast("Job cancelled", "info");
      refetchJobs();
    } catch {
      toast("Failed to cancel job", "error");
    }
  }, [toast, refetchJobs]);

  const clearCompletedJobs = useCallback(async () => {
    try {
      const result = await api.post<{ cleared: number }>("/jobs/clear");
      toast(`Cleared ${result.cleared} jobs`, "info");
      refetchJobs();
    } catch {
      toast("Failed to clear jobs", "error");
    }
  }, [toast, refetchJobs]);

  /* ── Pending counts for step badges ── */
  const getPendingCount = (stepId: string): number => {
    switch (stepId) {
      case "seo": return allBeats.length;
      case "thumbnail": return missingThumbBeats.length;
      case "render_16_9": return pendingBeats.length;
      case "convert_9_16": return renderedBeats.length;
      case "compress": return renderedBeats.length;
      default: return 0;
    }
  };

  /* ── Selected stems for batch actions ── */
  const selectedPending = useMemo(
    () => allBeats.filter((b) => selectedStems.has(b.stem) && !b.rendered).map((b) => b.stem),
    [allBeats, selectedStems]
  );

  return (
    <div className="animate-fade-in">
      {/* ── Header ── */}
      <div className="page-header">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2">
              <Film size={20} className="text-accent" />
              Render Studio
            </h1>
            <p className="page-subtitle">Render, convert, and prepare your beats for publishing</p>
          </div>
          {status && (
            <div className="hidden sm:flex items-center gap-2 relative z-10 flex-shrink-0">
              <div
                className="text-[11px] px-2.5 py-1 rounded-full whitespace-nowrap"
                style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)", color: "var(--text-secondary)" }}
              >
                <span className="font-semibold text-foreground">{pendingBeats.length}</span> to render
              </div>
              <div
                className="text-[11px] px-2.5 py-1 rounded-full whitespace-nowrap"
                style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)", color: "var(--text-secondary)" }}
              >
                <span className="font-semibold text-foreground">{renderedBeats.length}</span> rendered
              </div>
              {hasActiveJobs && (
                <div
                  className="text-[11px] px-2.5 py-1 rounded-full whitespace-nowrap"
                  style={{ background: "#38bdf815", border: "1px solid #38bdf840", color: "#38bdf8" }}
                >
                  <Loader2 size={10} className="inline animate-spin mr-1" />
                  <span className="font-semibold">{activeJobs.length}</span> job{activeJobs.length !== 1 ? "s" : ""}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Stats Row ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatCard icon={Music} value={status?.total_beats ?? 0} label="Total Beats" loading={statusLoading} accentColor="var(--accent)" />
        <StatCard icon={Film} value={status?.rendered ?? 0} label="Rendered" loading={statusLoading} accentColor="#00d362" />
        <StatCard icon={Clock} value={status?.pending_renders ?? 0} label="Pending Renders" loading={statusLoading} accentColor="#f5a623" />
        <StatCard icon={ImagePlus} value={missingThumbBeats.length} label="Need Thumbnails" loading={statusLoading} accentColor="#e040fb" />
      </div>

      {/* ── Render Actions Bar ── */}
      <div
        className="mb-6 p-5 rounded-2xl"
        style={{
          background: "var(--bg-card)",
          backdropFilter: "blur(16px)",
          border: "1px solid var(--glass-border)",
        }}
      >
        <h2 className="section-header mb-4">
          <span className="flex items-center gap-2"><Activity size={15} /> Render Steps</span>
        </h2>

        {/* Step toggles */}
        <div className="flex flex-wrap gap-2 mb-5">
          {RENDER_STEPS.map((step) => {
            const active = enabledSteps.has(step.id);
            const Icon = step.icon;
            const count = getPendingCount(step.id);
            return (
              <button
                key={step.id}
                onClick={() => toggleStep(step.id)}
                className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-semibold transition-all cursor-pointer"
                style={{
                  background: active ? `${step.color}18` : "var(--bg-hover)",
                  border: `1.5px solid ${active ? `${step.color}50` : "var(--border)"}`,
                  color: active ? step.color : "var(--text-tertiary)",
                }}
                title={step.description}
              >
                <Icon size={14} style={{ color: active ? step.color : "var(--text-tertiary)" }} />
                {step.label}
                {count > 0 && (
                  <span
                    className="text-[9px] font-bold px-1.5 py-0.5 rounded-full ml-0.5"
                    style={{
                      background: active ? `${step.color}25` : "var(--bg-primary)",
                      color: active ? step.color : "var(--text-tertiary)",
                    }}
                  >
                    {count}
                  </span>
                )}
              </button>
            );
          })}
        </div>

        {/* Action buttons */}
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => renderBatch(pendingBeats.map((b) => b.stem))}
            disabled={submitting || pendingBeats.length === 0 || enabledSteps.size === 0}
            className="btn-gradient flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-all disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
          >
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
            Render All Pending ({pendingBeats.length})
          </button>

          {selectedStems.size > 0 && (
            <button
              onClick={() => renderBatch([...selectedStems])}
              disabled={submitting || enabledSteps.size === 0}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider transition-all cursor-pointer disabled:opacity-40"
              style={{
                background: "#38bdf818",
                color: "#38bdf8",
                border: "1.5px solid #38bdf840",
              }}
            >
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              Render Selected ({selectedStems.size})
            </button>
          )}
        </div>
      </div>

      {/* ── Beat Table ── */}
      <div
        className="mb-6 rounded-2xl overflow-hidden"
        style={{
          background: "var(--bg-card)",
          backdropFilter: "blur(16px)",
          border: "1px solid var(--glass-border)",
        }}
      >
        {/* Filter bar */}
        <div className="p-4 flex flex-col sm:flex-row items-start sm:items-center gap-3" style={{ borderBottom: "1px solid var(--border)" }}>
          {/* Search */}
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Search beats..."
            size="sm"
            className="flex-1 min-w-0 w-full sm:w-auto"
          />

          {/* Filter tabs */}
          <div className="flex items-center gap-1.5 flex-shrink-0">
            {(
              [
                { key: "all" as const, label: "All", count: allBeats.length, color: "var(--accent)" },
                { key: "pending" as const, label: "Pending", count: pendingBeats.length, color: "#f5a623" },
                { key: "rendered" as const, label: "Rendered", count: renderedBeats.length, color: "#00d362" },
                { key: "no_thumb" as const, label: "No Thumb", count: missingThumbBeats.length, color: "#e040fb" },
              ]
            ).map((tab) => {
              const active = filter === tab.key;
              const color = tab.color;
              return (
                <button
                  key={tab.key}
                  onClick={() => setFilter(tab.key)}
                  className="text-[10px] font-semibold px-2.5 py-1.5 rounded-lg transition-all cursor-pointer whitespace-nowrap"
                  style={{
                    background: active ? `${color}18` : "transparent",
                    border: `1px solid ${active ? `${color}40` : "transparent"}`,
                    color: active ? color : "var(--text-tertiary)",
                  }}
                >
                  {tab.label} ({tab.count})
                </button>
              );
            })}
          </div>

          {/* Artist filter */}
          <div className="flex items-center gap-1.5 flex-shrink-0">
            <Users size={12} className="text-text-tertiary" />
            <select
              value={artistFilter}
              onChange={(e) => setArtistFilter(e.target.value)}
              className="text-[10px] font-semibold px-2 py-1.5 rounded-lg cursor-pointer appearance-none"
              style={{
                background: artistFilter !== "all" ? "#b44eff18" : "var(--bg-hover)",
                border: `1px solid ${artistFilter !== "all" ? "#b44eff40" : "var(--border)"}`,
                color: artistFilter !== "all" ? "#b44eff" : "var(--text-tertiary)",
                paddingRight: "20px",
              }}
            >
              <option value="all">All Artists</option>
              <option value="unassigned">Unassigned ({unassignedBeats.length})</option>
              {artistNames.map((name) => (
                <option key={name} value={name}>
                  {name} ({allBeats.filter((b) => b.seo_artist === name).length})
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Selection bar */}
        {filteredBeats.length > 0 && (
          <div
            className="px-4 py-2 flex items-center gap-3"
            style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-hover)" }}
          >
            <button
              onClick={selectAllVisible}
              className="text-[10px] font-semibold text-accent cursor-pointer hover:underline"
            >
              Select All ({filteredBeats.length})
            </button>
            {selectedStems.size > 0 && (
              <>
                <button
                  onClick={clearSelection}
                  className="text-[10px] font-semibold text-text-tertiary cursor-pointer hover:underline"
                >
                  Clear
                </button>
                <span className="text-[10px] text-text-secondary">
                  {selectedStems.size} selected
                </span>
                {/* Batch Set Artist */}
                <select
                  value=""
                  onChange={(e) => {
                    if (e.target.value) {
                      setArtistBatch([...selectedStems], e.target.value);
                      e.target.value = "";
                    }
                  }}
                  className="text-[10px] font-semibold px-2 py-1 rounded-lg cursor-pointer appearance-none"
                  style={{
                    background: "#b44eff18",
                    border: "1px solid #b44eff40",
                    color: "#b44eff",
                    paddingRight: "18px",
                  }}
                >
                  <option value="">Set Artist...</option>
                  {artistNames.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </>
            )}
          </div>
        )}

        {/* Table header */}
        <div
          className="hidden sm:flex items-center gap-3 px-4 py-2.5 text-[9px] font-bold uppercase tracking-wider text-text-tertiary"
          style={{ borderBottom: "1px solid var(--border)", background: "var(--bg-hover)" }}
        >
          <div className="w-5 flex-shrink-0" />
          <div className="flex-1 min-w-0">Beat</div>
          <div className="w-28 flex-shrink-0">Artist</div>
          <div className="w-12 text-center flex-shrink-0">BPM</div>
          <div className="w-10 text-center flex-shrink-0">Key</div>
          <div className="w-8 text-center flex-shrink-0">Thumb</div>
          <div className="w-20 flex-shrink-0">Status</div>
          <div className="w-24 flex-shrink-0">Progress</div>
          <div className="w-20 text-right flex-shrink-0">Action</div>
        </div>

        {/* Table body */}
        <div style={{ maxHeight: "600px", overflowY: "auto" }}>
          {filteredBeats.length === 0 ? (
            <div className="text-center py-12">
              <Music size={24} className="mx-auto mb-2" style={{ color: "var(--text-tertiary)", opacity: 0.3 }} />
              <p className="text-xs text-text-tertiary">
                {search ? "No beats match your search" : "No beats found"}
              </p>
            </div>
          ) : (
            filteredBeats.map((beat) => {
              const isSelected = selectedStems.has(beat.stem);
              const progress = liveProgress.get(beat.stem);
              const isRendering = !!progress;
              const laneColor = beat.lane ? LANE_COLORS[beat.lane] ?? "var(--text-tertiary)" : undefined;
              const beatStatus = beat.uploaded ? "uploaded" : beat.rendered ? "rendered" : "pending";

              return (
                <div
                  key={beat.stem}
                  className="flex items-center gap-3 px-4 py-3 transition-all"
                  style={{
                    borderBottom: "1px solid var(--border)",
                    background: isRendering
                      ? "#38bdf808"
                      : isSelected
                      ? "var(--accent-muted, rgba(99, 102, 241, 0.05))"
                      : "transparent",
                    borderLeft: isRendering ? "3px solid #38bdf8" : "3px solid transparent",
                  }}
                >
                  {/* Checkbox */}
                  <div
                    onClick={() => toggleBeat(beat.stem)}
                    className="w-4 h-4 rounded flex items-center justify-center flex-shrink-0 cursor-pointer transition-all"
                    style={{
                      background: isSelected ? "var(--accent)" : "transparent",
                      border: `1.5px solid ${isSelected ? "var(--accent)" : "var(--text-tertiary)"}`,
                    }}
                  >
                    {isSelected && <CheckCircle2 size={10} color="#fff" />}
                  </div>

                  {/* Beat Info */}
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-foreground truncate">
                      {beat.beat_name || beat.stem.replace(/_/g, " ")}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[10px] text-text-tertiary">{beat.artist || "Unknown"}</span>
                      {beat.lane && (
                        <span
                          className="text-[8px] font-bold px-1.5 py-0.5 rounded uppercase"
                          style={{
                            background: `${laneColor}15`,
                            color: laneColor,
                          }}
                        >
                          {beat.lane.slice(0, 1).toUpperCase()}
                        </span>
                      )}
                      {beat.seo_artist && beat.seo_artist !== beat.artist && (
                        <span className="text-[9px] text-text-tertiary opacity-60 truncate">
                          {beat.seo_artist}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Artist Picker */}
                  <div className="hidden sm:block w-28 flex-shrink-0">
                    <select
                      value={beat.seo_artist && beat.seo_artist !== "NOT SET" ? beat.seo_artist : ""}
                      onChange={(e) => {
                        e.stopPropagation();
                        if (e.target.value) setArtistForBeat(beat.stem, e.target.value);
                      }}
                      onClick={(e) => e.stopPropagation()}
                      className="w-full text-[10px] font-semibold px-1.5 py-1 rounded-md cursor-pointer truncate"
                      style={{
                        background: beat.seo_artist && beat.seo_artist !== "NOT SET" ? "#b44eff10" : "#ff444418",
                        border: `1px solid ${beat.seo_artist && beat.seo_artist !== "NOT SET" ? "#b44eff30" : "#ff444430"}`,
                        color: beat.seo_artist && beat.seo_artist !== "NOT SET" ? "#b44eff" : "#ff4444",
                        appearance: "none" as const,
                        paddingRight: "14px",
                      }}
                    >
                      <option value="">No Artist</option>
                      {artistNames.map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                    </select>
                  </div>

                  {/* BPM */}
                  <span className="hidden sm:block text-[11px] tabular-nums text-text-secondary w-12 text-center flex-shrink-0">
                    {beat.bpm ?? "—"}
                  </span>

                  {/* Key */}
                  <span className="hidden sm:block text-[11px] text-text-secondary w-10 text-center flex-shrink-0">
                    {beat.key ?? "—"}
                  </span>

                  {/* Thumbnail Status */}
                  <div className="hidden sm:flex w-8 flex-shrink-0 justify-center">
                    {beat.has_thumbnail ? (
                      <CheckCircle2 size={13} style={{ color: "#00d362" }} />
                    ) : (
                      <Clock size={13} style={{ color: "#f5a623" }} />
                    )}
                  </div>

                  {/* Render Status */}
                  <div className="w-20 flex-shrink-0">
                    {beat.rendered ? (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          router.push(`/media-manager?stem=${beat.stem}`);
                        }}
                        className="group/badge inline-flex items-center gap-1 cursor-pointer transition-all hover:brightness-125"
                        title="View in Media Manager"
                      >
                        <StatusBadge status={beatStatus} size="sm" />
                        <ExternalLink size={9} className="text-text-tertiary opacity-0 group-hover/badge:opacity-100 transition-opacity" />
                      </button>
                    ) : (
                      <StatusBadge status={beatStatus} size="sm" />
                    )}
                  </div>

                  {/* Progress */}
                  <div className="hidden sm:block w-24 flex-shrink-0">
                    {isRendering ? (
                      <div>
                        <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-primary)" }}>
                          <div
                            className="h-full rounded-full transition-all duration-500"
                            style={{ width: `${progress.pct}%`, background: "#00d362" }}
                          />
                        </div>
                        <p className="text-[9px] font-bold tabular-nums text-center mt-0.5" style={{ color: "#00d362" }}>
                          {progress.pct}%
                        </p>
                      </div>
                    ) : null}
                  </div>

                  {/* Action Button */}
                  <div className="w-20 flex-shrink-0 flex justify-end">
                    {isRendering ? (
                      <div className="flex items-center gap-1.5">
                        <Loader2 size={12} className="animate-spin" style={{ color: "#38bdf8" }} />
                        <span className="text-[10px] font-semibold" style={{ color: "#38bdf8" }}>
                          {progress.phase || "Rendering"}
                        </span>
                      </div>
                    ) : !beat.rendered ? (
                      <button
                        onClick={() => renderSingle(beat.stem)}
                        className="text-[10px] font-semibold px-2.5 py-1 rounded-lg transition-all cursor-pointer hover:brightness-125"
                        style={{
                          background: "#00d36220",
                          color: "#00d362",
                          border: "1px solid #00d36240",
                        }}
                      >
                        <span className="flex items-center gap-1">
                          <Play size={10} />
                          Render
                        </span>
                      </button>
                    ) : (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => setVideoPreviewStem(beat.stem)}
                          className="text-[10px] font-semibold px-2.5 py-1 rounded-lg transition-all cursor-pointer hover:brightness-125"
                          style={{
                            background: "#8b5cf620",
                            color: "#8b5cf6",
                            border: "1px solid #8b5cf640",
                          }}
                          title="Play video"
                        >
                          <span className="flex items-center gap-1">
                            <Play size={10} />
                            Play
                          </span>
                        </button>
                        <button
                          onClick={() => renderSingle(beat.stem)}
                          className="p-1 rounded-md transition-all cursor-pointer opacity-40 hover:opacity-80"
                          style={{ color: "var(--text-tertiary)" }}
                          title="Re-render"
                        >
                          <RotateCcw size={10} />
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* ── Active Renders & Background Jobs ── */}
      <div
        className="mb-8 p-6 rounded-2xl"
        style={{
          background: "var(--bg-card)",
          backdropFilter: "blur(16px)",
          border: `1px solid ${hasActiveJobs ? "#38bdf840" : "var(--glass-border)"}`,
          boxShadow: hasActiveJobs ? "0 0 24px #38bdf810" : "none",
        }}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="section-header">
            <span className="flex items-center gap-2">
              <CloudOff size={15} style={{ color: "#38bdf8" }} />
              Render Jobs
              {hasActiveJobs && (
                <span
                  className="text-[10px] font-bold px-2 py-0.5 rounded-full ml-1"
                  style={{ background: "#38bdf820", color: "#38bdf8" }}
                >
                  {activeJobs.length} active
                </span>
              )}
            </span>
          </h2>
          {completedJobs.length > 0 && (
            <button
              onClick={clearCompletedJobs}
              className="flex items-center gap-1.5 text-[10px] font-semibold px-2.5 py-1 rounded-lg cursor-pointer transition-all"
              style={{ background: "var(--bg-hover)", color: "var(--text-tertiary)", border: "1px solid var(--border)" }}
            >
              <Trash2 size={11} />
              Clear Done
            </button>
          )}
        </div>

        {renderJobs.length === 0 ? (
          <div className="text-center py-8">
            <CloudOff size={24} className="mx-auto mb-2" style={{ color: "var(--text-tertiary)", opacity: 0.3 }} />
            <p className="text-xs text-text-tertiary">No render jobs</p>
            <p className="text-[10px] text-text-tertiary mt-1">
              Click <span className="font-semibold" style={{ color: "#00d362" }}>RENDER ALL PENDING</span> above to start
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {/* Active jobs */}
            {activeJobs.map((job) => (
              <div
                key={job.id}
                className="flex items-center gap-3 p-3 rounded-xl transition-all"
                style={{
                  background: job.status === "running" ? "#38bdf808" : "var(--bg-hover)",
                  border: `1px solid ${job.status === "running" ? "#38bdf830" : "var(--border)"}`,
                }}
              >
                <JobStatusIcon status={job.status} />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-semibold text-foreground truncate">{job.label}</p>
                  <p className="text-[10px] text-text-tertiary truncate">
                    {job.detail || (job.status === "queued" ? "Waiting..." : "Processing...")}
                    {job.stems.length > 0 && ` · ${job.stems.length} beats`}
                  </p>
                </div>
                {job.status === "running" && (
                  <div className="w-20 flex-shrink-0">
                    <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-primary)" }}>
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{ width: `${job.progress}%`, background: "#38bdf8" }}
                      />
                    </div>
                    <p className="text-[9px] font-bold tabular-nums text-center mt-0.5" style={{ color: "#38bdf8" }}>
                      {job.progress}%
                    </p>
                  </div>
                )}
                {(job.status === "queued" || job.status === "running") && (
                  <button
                    onClick={() => cancelBackgroundJob(job.id)}
                    className="p-1.5 rounded-lg cursor-pointer transition-all hover:brightness-125"
                    style={{ background: "#ff444415", color: "#ff4444" }}
                    title="Cancel job"
                  >
                    <X size={12} />
                  </button>
                )}
              </div>
            ))}

            {/* Completed/Failed jobs */}
            {completedJobs.length > 0 && (
              <>
                <button
                  onClick={() => setShowJobHistory(!showJobHistory)}
                  className="flex items-center gap-2 text-xs font-semibold text-text-tertiary hover:text-foreground transition-colors cursor-pointer mt-2"
                >
                  {showJobHistory ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  History ({completedJobs.length})
                </button>
                {showJobHistory && (
                  <div className="space-y-1.5 mt-1">
                    {completedJobs.slice(0, 20).map((job) => (
                      <div
                        key={job.id}
                        className="flex items-center gap-2.5 px-3 py-2 rounded-lg"
                        style={{
                          background: "var(--bg-hover)",
                          opacity: job.status === "cancelled" ? 0.5 : 0.7,
                        }}
                      >
                        <JobStatusIcon status={job.status} />
                        <div className="flex-1 min-w-0">
                          <p className="text-[11px] font-medium text-foreground truncate">{job.label}</p>
                          {job.error && (
                            <p className="text-[10px] truncate" style={{ color: "#ff4444" }}>{job.error}</p>
                          )}
                        </div>
                        <span
                          className="text-[9px] font-semibold px-1.5 py-0.5 rounded uppercase flex-shrink-0"
                          style={{
                            background: job.status === "done" ? "#00d36215" : job.status === "failed" ? "#ff444415" : "#f5a62315",
                            color: job.status === "done" ? "#00d362" : job.status === "failed" ? "#ff4444" : "#f5a623",
                          }}
                        >
                          {job.status}
                        </span>
                        <span className="text-[9px] text-text-tertiary tabular-nums flex-shrink-0">
                          {timeAgo(job.finished_at)}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* ── Task Monitor (active render tasks from queue) ── */}
      {(renderQueue.active.length > 0 || renderQueue.pending.length > 0) && (
        <div
          className="mb-8 p-6 rounded-2xl"
          style={{
            background: "var(--bg-card)",
            backdropFilter: "blur(16px)",
            border: "1px solid var(--glass-border)",
          }}
        >
          <h2 className="section-header mb-4">
            <span className="flex items-center gap-2"><Activity size={15} /> Active Renders</span>
          </h2>

          {renderQueue.active.length > 0 && (
            <div className="space-y-2 mb-4">
              {renderQueue.active.map((task) => (
                <div
                  key={task.id}
                  className="flex items-center gap-3 p-3 rounded-xl"
                  style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
                >
                  <Loader2 size={14} className="animate-spin text-accent" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{task.stem}</p>
                    <p className="text-[10px] text-text-tertiary uppercase">{task.type}</p>
                  </div>
                  {task.progress !== undefined && (
                    <div className="w-24">
                      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-primary)" }}>
                        <div className="h-full rounded-full bg-accent" style={{ width: `${task.progress}%` }} />
                      </div>
                    </div>
                  )}
                  <span className="text-xs font-bold tabular-nums text-accent">{task.progress ?? 0}%</span>
                </div>
              ))}
            </div>
          )}

          {renderQueue.pending.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary mb-2">
                Pending ({renderQueue.pending.length})
              </p>
              {renderQueue.pending.slice(0, 5).map((task) => (
                <div
                  key={task.id}
                  className="flex items-center gap-2 px-3 py-2 rounded-lg"
                  style={{ background: "var(--bg-hover)" }}
                >
                  <Clock size={12} className="text-text-tertiary" />
                  <span className="text-xs text-text-secondary truncate flex-1">{task.stem}</span>
                  <span className="text-[10px] text-text-tertiary uppercase">{task.type}</span>
                </div>
              ))}
            </div>
          )}

          {renderQueue.completed.length > 0 && (
            <div className="mt-4">
              <button
                onClick={() => setShowCompleted(!showCompleted)}
                className="flex items-center gap-2 text-xs font-semibold text-text-tertiary hover:text-foreground transition-colors cursor-pointer"
              >
                {showCompleted ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                Completed ({renderQueue.completed.length})
              </button>
              {showCompleted && (
                <div className="mt-2 space-y-1">
                  {renderQueue.completed.slice(0, 10).map((task) => (
                    <div
                      key={task.id}
                      className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-text-tertiary"
                      style={{ background: "var(--bg-hover)", opacity: 0.6 }}
                    >
                      <CheckCircle2 size={11} className="text-success" />
                      <span className="text-[11px] truncate flex-1">{task.stem}</span>
                      <span className="text-[10px] uppercase">{task.type}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
      {/* ── Video Preview Modal ── */}
      <VideoPreviewModal
        stem={videoPreviewStem}
        title={
          videoPreviewStem
            ? (allBeats.find((b) => b.stem === videoPreviewStem)?.beat_name ?? videoPreviewStem)
            : undefined
        }
        onClose={() => setVideoPreviewStem(null)}
      />
    </div>
  );
}
