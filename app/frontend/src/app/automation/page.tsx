"use client";

import { useState, useCallback, useMemo, useRef, useEffect, type ComponentType } from "react";
import {
  Upload,
  Play,
  Loader2,
  CheckCircle2,
  Clock,
  Activity,
  Settings,
  ChevronDown,
  ChevronUp,
  Youtube,
  PlaySquare,
  Instagram,
  ShoppingBag,
  Star,
  Music,
  X,
  ListFilter,
  Eye,
  EyeOff,
  Lock,
  Square,
  XCircle,
  AlertCircle,
  Trash2,
  CloudOff,
} from "lucide-react";
import { useFetch, api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import SearchInput from "@/components/ui/SearchInput";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useSchedule } from "@/hooks/useSchedule";
import { Button } from "@/components/ui/button";

/* ── TikTok SVG Icon ─────────────────────────────────────────── */

function TikTokIcon({ size = 15, color }: { size?: number; color?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke={color || "currentColor"}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M9 12a4 4 0 1 0 4 4V4a5 5 0 0 0 5 5" />
    </svg>
  );
}

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

/* ── Pipeline Categories ─────────────────────────────────────── */

interface PipelineStep {
  id: string;
  label: string;
  description: string;
  icon: ComponentType<{ size?: number; style?: React.CSSProperties }> | "tiktok";
  color: string;
}

interface PipelineCategory {
  id: string;
  label: string;
  icon: ComponentType<{ size?: number; style?: React.CSSProperties }>;
  color: string;
  steps: PipelineStep[];
}

const PIPELINE_CATEGORIES: PipelineCategory[] = [
  {
    id: "publish",
    label: "Publish",
    icon: Upload,
    color: "#ff0000",
    steps: [
      { id: "upload_yt", label: "Upload YouTube", description: "Upload full video to YouTube", icon: Youtube, color: "#ff0000" },
      { id: "shorts", label: "YouTube Shorts", description: "Post 9:16 as a YouTube Short", icon: PlaySquare, color: "#ff4444" },
      { id: "tiktok", label: "TikTok", description: "Post to TikTok", icon: "tiktok", color: "#69C9D0" },
      { id: "instagram", label: "Instagram Reel", description: "Post as Instagram Reel", icon: Instagram, color: "#E1306C" },
    ],
  },
  {
    id: "stores",
    label: "Beat Stores",
    icon: ShoppingBag,
    color: "#f5a623",
    steps: [
      { id: "airbit", label: "Upload Airbit", description: "List beat on Airbit marketplace", icon: ShoppingBag, color: "#22c55e" },
      { id: "beatstars", label: "Upload BeatStars", description: "List beat on BeatStars", icon: Star, color: "#fbbf24" },
    ],
  },
];

const ALL_STEPS = PIPELINE_CATEGORIES.flatMap((c) => c.steps);
const TOTAL_STEPS = ALL_STEPS.length;

const PRIVACY_OPTIONS = [
  { value: "public", label: "Public", icon: Eye, color: "#00d362" },
  { value: "unlisted", label: "Unlisted", icon: EyeOff, color: "#f5a623" },
  { value: "private", label: "Private", icon: Lock, color: "#ff4444" },
] as const;

/* Map frontend step IDs to backend job types */
const STEP_TO_JOB_TYPE: Record<string, string> = {
  upload_yt: "upload",
  shorts: "shorts",
  tiktok: "tiktok",
  instagram: "instagram",
  airbit: "airbit",
  beatstars: "beatstars",
};

/* ── Step Icon Renderer ──────────────────────────────────────── */

function StepIcon({ step, size = 15, spinning, done }: { step: PipelineStep; size?: number; spinning?: boolean; done?: boolean }) {
  if (spinning) return <Loader2 size={size} className="animate-spin" style={{ color: step.color }} />;
  if (done) return <CheckCircle2 size={size} style={{ color: step.color }} />;
  if (step.icon === "tiktok") return <TikTokIcon size={size} color={step.color} />;
  const Icon = step.icon;
  return <Icon size={size} style={{ color: step.color }} />;
}

/* ── Time ago helper ─────────────────────────────────────────── */

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

/* ── Job status icon ─────────────────────────────────────────── */

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

export default function AutomationPage() {
  const { data: status } = useFetch<StatusData>("/status");
  const { data: beats, refetch: refetchBeats } = useFetch<BeatSummary[]>("/beats");
  const { data: queue, refetch: refetchQueue } = useFetch<QueueData>("/queue");
  const { data: jobsData, refetch: refetchJobs } = useFetch<JobsData>("/jobs");
  const { toast } = useToast();
  useWebSocket();
  const { schedule, settings: scheduleSettings } = useSchedule();

  /* ── Auto-poll background jobs every 5s when jobs are active ── */
  useEffect(() => {
    const interval = setInterval(() => {
      refetchJobs();
    }, 5000);
    return () => clearInterval(interval);
  }, [refetchJobs]);

  /* ── Abort controller for cancel ── */
  const abortRef = useRef<AbortController | null>(null);
  const [cancelled, setCancelled] = useState(false);

  /* ── Pipeline config state ── */
  const [selectedBeats, setSelectedBeats] = useState<Set<string>>(new Set()); // empty = ALL
  const [beatSearch, setBeatSearch] = useState("");
  const [beatFilter, setBeatFilter] = useState<"all" | "pending" | "rendered" | "uploaded">("all");
  const [showBeatPicker, setShowBeatPicker] = useState(false);
  const [privacy, setPrivacy] = useState<"public" | "unlisted" | "private">("unlisted");

  /* ── Pipeline step state ── */
  const [enabledSteps, setEnabledSteps] = useState<Set<string>>(new Set(["upload_yt"]));
  const [running, setRunning] = useState(false);
  const [currentStep, setCurrentStep] = useState<string | null>(null);
  const [completedSteps, setCompletedSteps] = useState<Set<string>>(new Set());
  const [showCompleted, setShowCompleted] = useState(false);
  const [submittingBackground, setSubmittingBackground] = useState(false);
  const [showJobHistory, setShowJobHistory] = useState(false);

  /* ── Derived: which beats will the pipeline act on ── */
  const allBeats = beats ?? [];
  const useAllBeats = selectedBeats.size === 0;
  const targetBeats = useMemo(
    () => useAllBeats ? allBeats : allBeats.filter((b) => selectedBeats.has(b.stem)),
    [allBeats, selectedBeats, useAllBeats]
  );

  const targetStems = useMemo(() => targetBeats.map((b) => b.stem), [targetBeats]);
  const renderedStems = useMemo(() => targetBeats.filter((b) => b.rendered).map((b) => b.stem), [targetBeats]);
  const uploadableStems = useMemo(() => targetBeats.filter((b) => b.rendered && !b.uploaded).map((b) => b.stem), [targetBeats]);

  /* ── Background jobs derived ── */
  const bgJobs = jobsData?.jobs ?? [];
  const activeJobs = bgJobs.filter((j) => j.status === "running" || j.status === "queued");
  const completedJobs = bgJobs.filter((j) => j.status === "done" || j.status === "failed" || j.status === "cancelled");
  const hasActiveJobs = activeJobs.length > 0;

  /* Beat picker filter + search */
  const filteredPickerBeats = useMemo(() => {
    let list = allBeats;
    // Status filter
    if (beatFilter === "pending") list = list.filter((b) => !b.rendered);
    else if (beatFilter === "rendered") list = list.filter((b) => b.rendered && !b.uploaded);
    else if (beatFilter === "uploaded") list = list.filter((b) => b.uploaded);
    // Text search
    if (beatSearch) {
      const q = beatSearch.toLowerCase();
      list = list.filter(
        (b) => b.stem.toLowerCase().includes(q) || (b.title ?? "").toLowerCase().includes(q) || (b.artist ?? "").toLowerCase().includes(q)
      );
    }
    return list;
  }, [allBeats, beatSearch, beatFilter]);

  /* Filter counts for tabs */
  const filterCounts = useMemo(() => ({
    all: allBeats.length,
    pending: allBeats.filter((b) => !b.rendered).length,
    rendered: allBeats.filter((b) => b.rendered && !b.uploaded).length,
    uploaded: allBeats.filter((b) => b.uploaded).length,
  }), [allBeats]);

  /* Beat selection helpers */
  const toggleBeat = (stem: string) => {
    setSelectedBeats((prev) => {
      const next = new Set(prev);
      if (next.has(stem)) next.delete(stem);
      else next.add(stem);
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelectedBeats((prev) => {
      const next = new Set(prev);
      filteredPickerBeats.forEach((b) => next.add(b.stem));
      return next;
    });
  };

  const clearSelection = () => setSelectedBeats(new Set());

  /* Step toggle */
  const toggleStep = (id: string) => {
    if (running) return;
    setEnabledSteps((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  /* Category toggle */
  const toggleCategory = (categoryId: string) => {
    if (running) return;
    const category = PIPELINE_CATEGORIES.find((c) => c.id === categoryId);
    if (!category) return;
    const stepIds = category.steps.map((s) => s.id);
    setEnabledSteps((prev) => {
      const next = new Set(prev);
      const allEnabled = stepIds.every((id) => next.has(id));
      if (allEnabled) stepIds.forEach((id) => next.delete(id));
      else stepIds.forEach((id) => next.add(id));
      return next;
    });
  };

  /* Pending counts (scoped to selected beats) */
  const getPendingCount = (stepId: string): number => {
    switch (stepId) {
      case "upload_yt":    return uploadableStems.length;
      case "shorts":       return renderedStems.length;
      case "tiktok":       return renderedStems.length;
      case "instagram":    return renderedStems.length;
      case "airbit":       return targetStems.length;
      case "beatstars":    return targetStems.length;
      default:             return 0;
    }
  };

  /* Cancel pipeline */
  const cancelPipeline = useCallback(() => {
    abortRef.current?.abort();
    setCancelled(true);
    toast("Pipeline cancelled", "info");
  }, [toast]);

  /* Helper: fetch fresh beat lists scoped to current selection */
  const getFreshStems = async (
    controller: AbortController,
    selectedSet: Set<string> | null,
  ) => {
    try {
      const freshBeats = await api.get<BeatSummary[]>("/beats");
      const scoped = freshBeats.filter(
        (b) => selectedSet === null || selectedSet.has(b.stem),
      );
      return {
        all: scoped.map((b) => b.stem),
        unrendered: scoped.filter((b) => !b.rendered).map((b) => b.stem),
        rendered: scoped.filter((b) => b.rendered).map((b) => b.stem),
        uploadable: scoped.filter((b) => b.rendered && !b.uploaded).map((b) => b.stem),
        missingThumb: scoped.filter((b) => !b.has_thumbnail).map((b) => b.stem),
      };
    } catch {
      return null; // fallback to stale data
    }
  };

  /* ── Run in Background ── */
  const runInBackground = useCallback(async () => {
    if (targetStems.length === 0) {
      toast("No beats selected", "error");
      return;
    }
    if (enabledSteps.size === 0) {
      toast("No steps selected", "error");
      return;
    }

    setSubmittingBackground(true);

    try {
      // Map frontend step IDs to backend job types
      const steps = ALL_STEPS
        .filter((s) => enabledSteps.has(s.id))
        .map((s) => STEP_TO_JOB_TYPE[s.id])
        .filter(Boolean);

      const response = await api.post<{ submitted: number; job_ids: string[]; message: string }>("/jobs/submit", {
        steps,
        stems: targetStems,
        params: { privacy },
      });

      toast(`${response.message}`, "success");
      refetchJobs();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to submit";
      toast(msg, "error");
    } finally {
      setSubmittingBackground(false);
    }
  }, [enabledSteps, targetStems, privacy, toast, refetchJobs]);

  /* ── Cancel background job ── */
  const cancelBackgroundJob = useCallback(async (jobId: string) => {
    try {
      await api.post(`/jobs/${jobId}/cancel`);
      toast("Job cancelled", "info");
      refetchJobs();
    } catch {
      toast("Failed to cancel job", "error");
    }
  }, [toast, refetchJobs]);

  /* ── Clear completed jobs ── */
  const clearCompletedJobs = useCallback(async () => {
    try {
      const result = await api.post<{ cleared: number }>("/jobs/clear");
      toast(`Cleared ${result.cleared} jobs`, "info");
      refetchJobs();
    } catch {
      toast("Failed to clear jobs", "error");
    }
  }, [toast, refetchJobs]);

  /* Run pipeline */
  const runPipeline = useCallback(async () => {
    if (targetStems.length === 0) {
      toast("No beats selected", "error");
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    const selectedSet = selectedBeats.size === 0 ? null : selectedBeats;

    setRunning(true);
    setCancelled(false);
    setCompletedSteps(new Set());

    let failCount = 0;

    for (const step of ALL_STEPS) {
      if (controller.signal.aborted) break;
      if (!enabledSteps.has(step.id)) continue;
      setCurrentStep(step.id);

      try {
        switch (step.id) {
          case "upload_yt": {
            const fresh = await getFreshStems(controller, selectedSet);
            const toUpload = fresh?.uploadable ?? uploadableStems;
            for (const stem of toUpload) {
              if (controller.signal.aborted) break;
              try { await api.post(`/youtube/upload/${stem}`, { privacy }); } catch {}
            }
            await refetchBeats();
            break;
          }

          case "shorts": {
            const fresh = await getFreshStems(controller, selectedSet);
            const toPost = fresh?.rendered ?? renderedStems;
            for (const stem of toPost) {
              if (controller.signal.aborted) break;
              try {
                await api.post(`/social/shorts/${stem}`, { privacy });
              } catch (e) {
                failCount++;
                toast(`Shorts failed: ${stem}`, "error");
              }
            }
            break;
          }

          case "tiktok": {
            const fresh = await getFreshStems(controller, selectedSet);
            const toPost = fresh?.rendered ?? renderedStems;
            for (const stem of toPost) {
              if (controller.signal.aborted) break;
              try {
                await api.post(`/social/tiktok/${stem}`, {});
              } catch (e) {
                failCount++;
                toast(`TikTok failed: ${stem}`, "error");
              }
            }
            break;
          }

          case "instagram": {
            const fresh = await getFreshStems(controller, selectedSet);
            const toPost = fresh?.rendered ?? renderedStems;
            for (const stem of toPost) {
              if (controller.signal.aborted) break;
              try {
                await api.post(`/social/ig/${stem}`, {});
              } catch (e) {
                failCount++;
                toast(`Instagram failed: ${stem}`, "error");
              }
            }
            break;
          }

          case "airbit":
            if (targetStems.length > 0) {
              try { await api.post("/stores/upload/airbit/bulk", { stems: targetStems }); } catch {}
            }
            break;
          case "beatstars":
            if (targetStems.length > 0) {
              try { await api.post("/stores/upload/beatstars/bulk", { stems: targetStems }); } catch {}
            }
            break;
        }
        if (!controller.signal.aborted) {
          setCompletedSteps((prev) => new Set([...prev, step.id]));
        }
      } catch {
        if (!controller.signal.aborted) {
          toast(`${step.label} failed`, "error");
        }
      }
    }

    setCurrentStep(null);
    setRunning(false);
    abortRef.current = null;

    if (controller.signal.aborted) {
      toast("Pipeline stopped", "info");
    } else if (failCount > 0) {
      toast(`Pipeline done with ${failCount} error${failCount > 1 ? "s" : ""}`, "error");
    } else {
      toast("Pipeline complete!", "success");
    }
    refetchBeats();
    refetchQueue();
  }, [enabledSteps, targetStems, useAllBeats, selectedBeats, renderedStems, uploadableStems, privacy, toast, refetchBeats, refetchQueue]);

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="page-header">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2">
              <Upload size={20} className="text-accent" />
              Publish &amp; Distribute
            </h1>
            <p className="page-subtitle">Upload beats to YouTube, socials, and beat stores</p>
          </div>
          {status && (
            <div className="hidden sm:flex items-center gap-2 relative z-10 flex-shrink-0">
              <div className="text-[11px] px-2.5 py-1 rounded-full whitespace-nowrap" style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)", color: "var(--text-secondary)" }}>
                <span className="font-semibold text-foreground">{uploadableStems.length}</span> to upload
              </div>
              {hasActiveJobs && (
                <div className="text-[11px] px-2.5 py-1 rounded-full whitespace-nowrap" style={{ background: "#38bdf815", border: "1px solid #38bdf840", color: "#38bdf8" }}>
                  <Loader2 size={10} className="inline animate-spin mr-1" />
                  <span className="font-semibold">{activeJobs.length}</span> bg job{activeJobs.length !== 1 ? "s" : ""}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ===================================================================
          PIPELINE CONFIG — Beat selection + Privacy
          =================================================================== */}
      <div
        className="mb-4 p-5 rounded-2xl relative z-20"
        style={{
          background: "var(--bg-card)",
          border: "1px solid var(--glass-border)",
        }}
      >
        <h2 className="section-header mb-4">
          <span className="flex items-center gap-2"><ListFilter size={15} /> Pipeline Config</span>
        </h2>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* -- Beat Selection -- */}
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary mb-2 block">
              Beats
            </label>
            <div className="relative">
              <button
                onClick={() => setShowBeatPicker(!showBeatPicker)}
                className="w-full flex items-center gap-2 px-3.5 py-2.5 rounded-xl text-left transition-all cursor-pointer"
                style={{
                  background: "var(--bg-hover)",
                  border: `1px solid ${showBeatPicker ? "var(--accent)" : "var(--border)"}`,
                }}
              >
                <Music size={14} className="text-text-tertiary flex-shrink-0" />
                <span className="text-sm text-foreground flex-1 truncate">
                  {useAllBeats ? (
                    <span>All beats <span className="text-text-tertiary">({allBeats.length})</span></span>
                  ) : (
                    <span>{selectedBeats.size} beat{selectedBeats.size !== 1 ? "s" : ""} selected</span>
                  )}
                </span>
                {!useAllBeats && (
                  <button
                    onClick={(e) => { e.stopPropagation(); clearSelection(); }}
                    className="p-0.5 rounded hover:bg-bg-primary transition-colors"
                  >
                    <X size={12} className="text-text-tertiary" />
                  </button>
                )}
                <ChevronDown size={14} className={`text-text-tertiary transition-transform ${showBeatPicker ? "rotate-180" : ""}`} />
              </button>

              {/* Beat Picker Dropdown */}
              {showBeatPicker && (
                <div
                  className="absolute z-50 w-full mt-1.5 rounded-xl shadow-xl"
                  style={{
                    background: "var(--bg-card-solid, var(--bg-card))",
                    border: "1px solid var(--border-light)",
                    maxHeight: 320,
                  }}
                >
                  {/* Filter Tabs + Search */}
                  <div className="p-2.5 border-b" style={{ borderColor: "var(--border)" }}>
                    {/* Status filter tabs */}
                    <div className="flex gap-1 mb-2">
                      {([
                        { key: "all", label: "All", color: "var(--text-secondary)" },
                        { key: "pending", label: "Pending", color: "#f5a623" },
                        { key: "rendered", label: "Rendered", color: "#00d362" },
                        { key: "uploaded", label: "Uploaded", color: "#ff4444" },
                      ] as const).map((tab) => {
                        const active = beatFilter === tab.key;
                        const count = filterCounts[tab.key];
                        return (
                          <button
                            key={tab.key}
                            onClick={() => setBeatFilter(tab.key)}
                            className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-semibold cursor-pointer transition-all"
                            style={{
                              background: active ? `${tab.color}18` : "transparent",
                              color: active ? tab.color : "var(--text-tertiary)",
                              border: `1px solid ${active ? `${tab.color}40` : "transparent"}`,
                            }}
                          >
                            {tab.label}
                            <span className="tabular-nums opacity-70">{count}</span>
                          </button>
                        );
                      })}
                    </div>
                    <SearchInput
                      value={beatSearch}
                      onChange={setBeatSearch}
                      placeholder="Search beats..."
                      size="sm"
                      autoFocus
                    />
                    <div className="flex items-center gap-2 mt-2">
                      <button
                        onClick={selectAllVisible}
                        className="text-[10px] font-semibold px-2 py-0.5 rounded-md cursor-pointer transition-all"
                        style={{ background: "var(--accent-muted)", color: "var(--accent)" }}
                      >
                        Select All
                      </button>
                      <button
                        onClick={clearSelection}
                        className="text-[10px] font-semibold px-2 py-0.5 rounded-md cursor-pointer transition-all"
                        style={{ background: "var(--bg-hover)", color: "var(--text-tertiary)" }}
                      >
                        Clear
                      </button>
                      <span className="text-[10px] text-text-tertiary ml-auto">
                        {selectedBeats.size === 0 ? "All" : selectedBeats.size} selected
                      </span>
                    </div>
                  </div>
                  {/* Beat List */}
                  <div className="overflow-y-auto" style={{ maxHeight: 220 }}>
                    {filteredPickerBeats.map((beat) => {
                      const isSelected = selectedBeats.has(beat.stem);
                      return (
                        <button
                          key={beat.stem}
                          onClick={() => toggleBeat(beat.stem)}
                          className="w-full flex items-center gap-2.5 px-3 py-2 text-left transition-all cursor-pointer hover:brightness-110"
                          style={{
                            background: isSelected ? "var(--accent-muted)" : "transparent",
                            borderBottom: "1px solid var(--border)",
                          }}
                        >
                          <div
                            className="w-4 h-4 rounded flex items-center justify-center flex-shrink-0"
                            style={{
                              background: isSelected ? "var(--accent)" : "transparent",
                              border: `1.5px solid ${isSelected ? "var(--accent)" : "var(--text-tertiary)"}`,
                            }}
                          >
                            {isSelected && <CheckCircle2 size={10} color="#fff" />}
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-xs font-medium text-foreground truncate">
                              {beat.beat_name || beat.stem.replace(/_/g, " ")}
                            </p>
                            <p className="text-[10px] text-text-tertiary truncate">
                              {beat.artist || "Unknown"}{beat.bpm ? ` · ${beat.bpm} BPM` : ""}{beat.key ? ` · ${beat.key}` : ""}
                            </p>
                          </div>
                          <div className="flex items-center gap-1.5 flex-shrink-0">
                            {beat.lane && (
                              <span
                                className="text-[8px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide"
                                style={{
                                  background: `${beat.lane === "breakfast" ? "#f5a623" : beat.lane === "lunch" ? "#00d362" : "#b44eff"}15`,
                                  color: beat.lane === "breakfast" ? "#f5a623" : beat.lane === "lunch" ? "#00d362" : "#b44eff",
                                  border: `1px solid ${beat.lane === "breakfast" ? "#f5a623" : beat.lane === "lunch" ? "#00d362" : "#b44eff"}30`,
                                }}
                              >
                                {beat.lane.slice(0, 1)}
                              </span>
                            )}
                            {!beat.rendered && (
                              <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded" style={{ background: "#f5a62320", color: "#f5a623" }}>
                                Pending
                              </span>
                            )}
                            {beat.rendered && !beat.uploaded && (
                              <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded" style={{ background: "#00d36220", color: "#00d362" }}>
                                Rendered
                              </span>
                            )}
                            {beat.uploaded && (
                              <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded" style={{ background: "#ff000020", color: "#ff4444" }}>
                                Uploaded
                              </span>
                            )}
                          </div>
                        </button>
                      );
                    })}
                    {filteredPickerBeats.length === 0 && (
                      <div className="text-center py-6 text-xs text-text-tertiary">No beats found</div>
                    )}
                  </div>
                  {/* Close */}
                  <div className="p-2 border-t" style={{ borderColor: "var(--border)" }}>
                    <button
                      onClick={() => { setShowBeatPicker(false); setBeatSearch(""); setBeatFilter("all"); }}
                      className="w-full py-1.5 rounded-lg text-xs font-semibold cursor-pointer transition-all text-center"
                      style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
                    >
                      Done
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Selected beat chips */}
            {!useAllBeats && selectedBeats.size > 0 && selectedBeats.size <= 6 && (
              <div className="flex flex-wrap gap-1.5 mt-2">
                {Array.from(selectedBeats).map((stem) => {
                  const beat = allBeats.find((b) => b.stem === stem);
                  return (
                    <span
                      key={stem}
                      className="flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full"
                      style={{ background: "var(--accent-muted)", color: "var(--accent)" }}
                    >
                      {beat?.title || stem.replace(/_/g, " ")}
                      <button onClick={() => toggleBeat(stem)} className="cursor-pointer hover:opacity-70">
                        <X size={10} />
                      </button>
                    </span>
                  );
                })}
              </div>
            )}
          </div>

          {/* -- Privacy Setting -- */}
          <div>
            <label className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary mb-2 block">
              YouTube Privacy
            </label>
            <div className="flex gap-2">
              {PRIVACY_OPTIONS.map((opt) => {
                const active = privacy === opt.value;
                const Icon = opt.icon;
                return (
                  <button
                    key={opt.value}
                    onClick={() => setPrivacy(opt.value)}
                    className="flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl text-xs font-semibold transition-all cursor-pointer"
                    style={{
                      background: active ? `${opt.color}15` : "var(--bg-hover)",
                      border: `1px solid ${active ? `${opt.color}60` : "var(--border)"}`,
                      color: active ? opt.color : "var(--text-tertiary)",
                    }}
                  >
                    <Icon size={13} />
                    {opt.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* ===================================================================
          PIPELINE STEPS
          =================================================================== */}
      <div
        className="mb-8 p-6 rounded-2xl relative z-10"
        style={{
          background: "var(--bg-card)",
          backdropFilter: "blur(16px)",
          border: "1px solid var(--glass-border)",
        }}
      >
        <h2 className="section-header mb-5">
          <span className="flex items-center gap-2"><Upload size={15} /> Publishing Steps</span>
        </h2>

        {/* Categories */}
        {PIPELINE_CATEGORIES.map((category) => {
          const stepIds = category.steps.map((s) => s.id);
          const allEnabled = stepIds.every((id) => enabledSteps.has(id));
          const CategoryIcon = category.icon;

          return (
            <div key={category.id} className="mb-5 last:mb-0">
              {/* Category Header */}
              <div className="flex items-center gap-3 mb-3">
                <div className="w-1 h-5 rounded-full" style={{ background: category.color }} />
                <CategoryIcon size={14} style={{ color: category.color }} />
                <span className="text-xs font-bold uppercase tracking-wider" style={{ color: category.color }}>
                  {category.label}
                </span>
                <div className="flex-1" />
                <button
                  onClick={() => toggleCategory(category.id)}
                  className="text-[10px] font-semibold px-2 py-0.5 rounded-md cursor-pointer transition-all"
                  style={{
                    background: allEnabled ? `${category.color}20` : "var(--bg-hover)",
                    color: allEnabled ? category.color : "var(--text-tertiary)",
                    border: `1px solid ${allEnabled ? `${category.color}40` : "var(--border)"}`,
                  }}
                >
                  {allEnabled ? "Deselect All" : "Select All"}
                </button>
              </div>

              {/* Steps Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2.5">
                {category.steps.map((step) => {
                  const enabled = enabledSteps.has(step.id);
                  const isCurrent = currentStep === step.id;
                  const isDone = completedSteps.has(step.id);
                  const pending = getPendingCount(step.id);

                  return (
                    <button
                      key={step.id}
                      onClick={() => toggleStep(step.id)}
                      className="flex items-start gap-3 px-3.5 py-3 rounded-xl transition-all duration-200 cursor-pointer text-left"
                      style={{
                        background: isDone ? `${step.color}15` : enabled ? "var(--bg-hover)" : "var(--bg-primary)",
                        border: `1px solid ${isCurrent ? step.color : isDone ? `${step.color}40` : enabled ? "var(--border-light)" : "var(--border)"}`,
                        opacity: enabled || running ? 1 : 0.4,
                        boxShadow: isCurrent ? `0 0 20px ${step.color}30` : "none",
                      }}
                    >
                      <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5" style={{ background: `${step.color}15` }}>
                        <StepIcon step={step} spinning={isCurrent} done={isDone} />
                      </div>
                      <div className="min-w-0">
                        <p className="text-xs font-semibold text-foreground truncate">{step.label}</p>
                        <p className="text-[10px] text-text-tertiary leading-tight mt-0.5">{step.description}</p>
                        <p className="text-[10px] text-text-tertiary mt-1 tabular-nums">{pending} pending</p>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}

        {/* Summary + Run Buttons */}
        <div className="mt-6 pt-5" style={{ borderTop: "1px solid var(--border)" }}>
          <div className="flex items-center justify-center gap-3 text-xs text-text-tertiary mb-3">
            <span><span className="font-semibold text-foreground">{enabledSteps.size}</span> of {TOTAL_STEPS} steps</span>
            <span className="text-text-tertiary/30">·</span>
            <span><span className="font-semibold text-foreground">{targetStems.length}</span> beat{targetStems.length !== 1 ? "s" : ""}</span>
            <span className="text-text-tertiary/30">·</span>
            <span className="capitalize">{privacy}</span>
          </div>
          {running ? (
            <div className="flex gap-2">
              <div
                className="flex-1 py-4 rounded-xl text-base font-bold flex items-center justify-center gap-3 btn-gradient"
                style={{ opacity: 0.5, fontSize: "1rem" }}
              >
                <Loader2 size={18} className="animate-spin" /> Running Pipeline...
              </div>
              <button
                onClick={cancelPipeline}
                className="px-6 py-4 rounded-xl text-base font-bold flex items-center justify-center gap-2 transition-all duration-200 cursor-pointer"
                style={{
                  background: "linear-gradient(135deg, #ff4444, #cc0000)",
                  color: "#fff",
                  fontSize: "1rem",
                  boxShadow: "0 4px 16px rgba(255,68,68,0.3)",
                }}
              >
                <Square size={16} fill="currentColor" /> CANCEL
              </button>
            </div>
          ) : (
            <div className="flex gap-2">
              <button
                onClick={runPipeline}
                disabled={enabledSteps.size === 0}
                className="flex-1 py-4 rounded-xl text-base font-bold flex items-center justify-center gap-3 transition-all duration-200 cursor-pointer btn-gradient"
                style={{ opacity: enabledSteps.size === 0 ? 0.5 : 1, fontSize: "1rem" }}
              >
                <Play size={18} fill="currentColor" /> RUN PIPELINE
              </button>
              <button
                onClick={runInBackground}
                disabled={enabledSteps.size === 0 || submittingBackground}
                className="px-5 py-4 rounded-xl text-base font-bold flex items-center justify-center gap-2 transition-all duration-200 cursor-pointer"
                style={{
                  background: submittingBackground
                    ? "#38bdf830"
                    : "linear-gradient(135deg, #1e3a5f, #0f4c81)",
                  color: "#38bdf8",
                  fontSize: "0.8rem",
                  opacity: enabledSteps.size === 0 ? 0.5 : 1,
                  border: "1px solid #38bdf840",
                  boxShadow: "0 4px 16px rgba(56,189,248,0.15)",
                }}
              >
                {submittingBackground ? (
                  <><Loader2 size={15} className="animate-spin" /> Submitting...</>
                ) : (
                  <><CloudOff size={15} /> BACKGROUND</>
                )}
              </button>
            </div>
          )}
          {!running && (
            <p className="text-[10px] text-text-tertiary text-center mt-2">
              <span className="font-semibold" style={{ color: "#38bdf8" }}>BACKGROUND</span> = jobs keep running even if you close this tab
            </p>
          )}
        </div>
      </div>

      {/* ===================================================================
          BACKGROUND JOBS
          =================================================================== */}
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
              Background Jobs
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

        {bgJobs.length === 0 ? (
          <div className="text-center py-8">
            <CloudOff size={24} className="mx-auto mb-2" style={{ color: "var(--text-tertiary)", opacity: 0.3 }} />
            <p className="text-xs text-text-tertiary">No background jobs</p>
            <p className="text-[10px] text-text-tertiary mt-1">
              Click <span className="font-semibold" style={{ color: "#38bdf8" }}>BACKGROUND</span> above to start jobs that keep running when you leave
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {/* Active jobs first */}
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

      {/* ===================================================================
          TASK MONITOR
          =================================================================== */}
      <div
        className="mb-8 p-6 rounded-2xl"
        style={{
          background: "var(--bg-card)",
          backdropFilter: "blur(16px)",
          border: "1px solid var(--glass-border)",
        }}
      >
        <h2 className="section-header mb-4">
          <span className="flex items-center gap-2"><Activity size={15} /> Task Monitor</span>
        </h2>

        {queue?.active && queue.active.length > 0 ? (
          <div className="space-y-2 mb-4">
            {queue.active.map((task) => (
              <div key={task.id} className="flex items-center gap-3 p-3 rounded-xl" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
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
        ) : (
          <div className="text-center py-8 mb-4">
            <CheckCircle2 size={20} className="text-text-tertiary/30 mx-auto mb-2" />
            <p className="text-xs text-text-tertiary">No active tasks</p>
          </div>
        )}

        {queue?.pending && queue.pending.length > 0 && (
          <div className="space-y-1.5 mb-4">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary mb-2">Pending ({queue.pending.length})</p>
            {queue.pending.slice(0, 5).map((task) => (
              <div key={task.id} className="flex items-center gap-2 px-3 py-2 rounded-lg" style={{ background: "var(--bg-hover)" }}>
                <Clock size={12} className="text-text-tertiary" />
                <span className="text-xs text-text-secondary truncate flex-1">{task.stem}</span>
                <span className="text-[10px] text-text-tertiary uppercase">{task.type}</span>
              </div>
            ))}
          </div>
        )}

        {queue?.completed && queue.completed.length > 0 && (
          <div>
            <button
              onClick={() => setShowCompleted(!showCompleted)}
              className="flex items-center gap-2 text-xs font-semibold text-text-tertiary hover:text-foreground transition-colors cursor-pointer"
            >
              {showCompleted ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              Completed ({queue.completed.length})
            </button>
            {showCompleted && (
              <div className="mt-2 space-y-1">
                {queue.completed.slice(0, 10).map((task) => (
                  <div key={task.id} className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-text-tertiary" style={{ background: "var(--bg-hover)", opacity: 0.6 }}>
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

      {/* ===================================================================
          SCHEDULE OVERVIEW
          =================================================================== */}
      <div
        className="mb-8 p-6 rounded-2xl"
        style={{
          background: "var(--bg-card)",
          backdropFilter: "blur(16px)",
          border: "1px solid var(--glass-border)",
        }}
      >
        <h2 className="section-header mb-4">
          <span className="flex items-center gap-2"><Clock size={15} /> Schedule</span>
        </h2>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
          <div className="p-3.5 rounded-xl text-center" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
            <p className="text-xl font-bold text-foreground tabular-nums">{schedule?.queue?.length ?? 0}</p>
            <p className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary mt-1">Queued</p>
          </div>
          <div className="p-3.5 rounded-xl text-center" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
            <p className="text-xl font-bold text-foreground tabular-nums">{scheduleSettings?.daily_yt_count ?? 1}</p>
            <p className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary mt-1">Per Day</p>
          </div>
          <div className="p-3.5 rounded-xl text-center" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
            <p className="text-xl font-bold text-foreground tabular-nums">{scheduleSettings?.buffer_warning_days ?? 0}</p>
            <p className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary mt-1">Buffer</p>
          </div>
          <div className="p-3.5 rounded-xl text-center" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
            <p className="text-xl font-bold text-foreground tabular-nums">{schedule?.slots?.length ?? 0}</p>
            <p className="text-[10px] font-medium uppercase tracking-wider text-text-tertiary mt-1">Slots</p>
          </div>
        </div>

        <Button variant="accent" size="sm" asChild>
          <a href="/settings" className="font-semibold">
            <Settings size={13} />
            Schedule Settings
          </a>
        </Button>
      </div>
    </div>
  );
}
