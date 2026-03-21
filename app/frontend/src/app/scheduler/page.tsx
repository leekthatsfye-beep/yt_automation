"use client";

import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import {
  CalendarClock,
  Play,
  Eye,
  Loader2,
  Music,
  Smartphone,
  Clock,
  Users,
  Layers,
  BarChart3,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  TrendingUp,
  Pencil,
  Save,
  X,
  Plus,
  Trash2,
  Trophy,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Pin,
  RotateCcw,
  CheckSquare,
  Square,
  MinusCircle,
  Calendar,
  Pause,
  Volume2,
  Youtube,
  ExternalLink,
} from "lucide-react";
import { useFetch, api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import SearchInput from "@/components/ui/SearchInput";
import { usePhaseProgress } from "@/hooks/useTaskProgress";
import { useGlobalAudio } from "@/hooks/useGlobalAudio";

/* ── Types ─────────────────────────────────────────────────────────────── */

interface PlanSlot {
  slot: string;
  slot_est: string;
  time: string;
  type: "beat" | "short";
  lane: string;
  label: string;
  stem: string | null;
  artist: string;
  title: string | null;
  has_short_video?: boolean;
  status: string;
  override?: boolean;
  execution?: string;
  reason?: string;
}

interface YouTubeScheduled {
  stem: string;
  title: string;
  time: string;
  time_est: string;
  url: string;
  videoId: string;
  publishAt: string;
  lane: string;
}

interface PlanData {
  date: string;
  slots: PlanSlot[];
  youtube_scheduled?: YouTubeScheduled[];
  summary: {
    total_slots: number;
    beats_planned: number;
    shorts_planned: number;
    shorts_ready: number;
    shorts_need_generation: number;
    youtube_on_date?: number;
  };
  clusters: Record<string, string[]>;
  lane_priority?: string[];
}

interface OptimizerData {
  ranked_lanes: string[];
  scores: Record<string, number>;
  analytics: Record<string, { videos: number; views: number; ctr: number }>;
  has_data: boolean;
  optimized_at?: string;
}

interface StatusData {
  total_beats: number;
  total_uploaded: number;
  rendered_ready: number;
  shorts_ready: number;
  shorts_needed: number;
  buffer_days: number;
  beats_per_day: number;
  beats_by_lane: Record<string, number>;
  clusters: Record<string, string[]>;
  last_execution: string;
  last_plan_date: string;
  execution_history: {
    date: string;
    executed_at: string;
    beats_scheduled: number;
    shorts_uploaded: number;
    errors: number;
  }[];
  scheduled_pending: number;
  optimizer?: OptimizerData;
}

interface AvailableBeat {
  stem: string;
  name: string;
  artist: string;
  lane: string;
  audio: string | null;
}

interface LaneBeat {
  stem: string;
  title: string;
  rendered: boolean;
  uploaded: boolean;
  seo_artist: string;
  lane: string;
}

type LaneBeatsData = Record<string, LaneBeat[]>;

/* ── Small components ──────────────────────────────────────────────────── */

function Stat({
  label,
  value,
  color = "var(--text-primary)",
  sub,
}: {
  label: string;
  value: string | number;
  color?: string;
  sub?: string;
}) {
  return (
    <div
      className="p-3 rounded-xl text-center"
      style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}
    >
      <p className="text-xl font-black" style={{ color }}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </p>
      <p className="text-[9px] text-text-tertiary uppercase tracking-wider font-bold mt-0.5">
        {label}
      </p>
      {sub && <p className="text-[9px] text-text-tertiary mt-0.5">{sub}</p>}
    </div>
  );
}

const LANE_COLORS: Record<string, string> = {
  breakfast: "#f59e0b",
  lunch: "#22c55e",
  dinner: "#a855f7",
};

const MEDAL_COLORS = ["#f59e0b", "#94a3b8", "#cd7f32"];

/** Convert "14:00" → "2:00 PM", "09:00" → "9:00 AM" */
function to12h(time24: string): string {
  const [hStr, mStr] = time24.split(":");
  let h = parseInt(hStr, 10);
  const suffix = h >= 12 ? "PM" : "AM";
  if (h === 0) h = 12;
  else if (h > 12) h -= 12;
  return `${h}:${mStr} ${suffix}`;
}

/** "2026-03-11" → "Tue, Mar 11" */
function fmtDate(iso: string): string {
  const d = new Date(iso + "T12:00:00"); // noon to avoid TZ issues
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

/** Today as YYYY-MM-DD in local time */
function todayISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Shift a YYYY-MM-DD string by N days */
function shiftDate(iso: string, days: number): string {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/* ── Page ──────────────────────────────────────────────────────────────── */

export default function SchedulerPage() {
  const [selectedDate, setSelectedDate] = useState(todayISO());
  const isToday = selectedDate === todayISO();
  const [showCalendar, setShowCalendar] = useState(false);
  const [calMonth, setCalMonth] = useState(() => {
    const d = new Date(selectedDate + "T12:00:00");
    return { year: d.getFullYear(), month: d.getMonth() };
  });
  const calRef = useRef<HTMLDivElement>(null);

  // Close calendar on outside click
  useEffect(() => {
    if (!showCalendar) return;
    const handler = (e: MouseEvent) => {
      if (calRef.current && !calRef.current.contains(e.target as Node)) {
        setShowCalendar(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showCalendar]);

  const { data: status, loading: statusLoading, refetch: refetchStatus } =
    useFetch<StatusData>("/content-schedule/status");
  const planUrl = `/content-schedule/plan?date=${selectedDate}`;
  const { data: plan, loading: planLoading, refetch: refetchPlan } =
    useFetch<PlanData>(planUrl);
  const { toast } = useToast();

  const [executing, setExecuting] = useState(false);
  const [dryRunning, setDryRunning] = useState(false);

  // Global task progress — persists across page navigations
  const scheduleProgress = usePhaseProgress("content_schedule");
  const execProgress = scheduleProgress ? { pct: scheduleProgress.pct, detail: scheduleProgress.detail } : null;

  // Cluster editing state
  const [editingLane, setEditingLane] = useState<string | null>(null);
  const [editArtists, setEditArtists] = useState<string[]>([]);
  const [newArtist, setNewArtist] = useState("");
  const [savingCluster, setSavingCluster] = useState(false);

  // Optimizer refresh state
  const [refreshingOptimizer, setRefreshingOptimizer] = useState(false);

  // Beat picker state
  const [pickerSlot, setPickerSlot] = useState<number | null>(null);
  const [pickerSearch, setPickerSearch] = useState("");
  const [pickerBeats, setPickerBeats] = useState<AvailableBeat[]>([]);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [savingSlot, setSavingSlot] = useState(false);

  // Audio preview via global player — persists across page navigations
  const { beat: globalBeat, isPlaying: globalIsPlaying, play: globalPlay, toggle: globalToggle, close: globalClose } = useGlobalAudio();
  const playingStem = globalBeat?.stem ?? null;

  const togglePreview = (beat: AvailableBeat) => {
    if (!beat.audio) return;
    // If same beat, toggle play/pause
    if (globalBeat?.stem === beat.stem) {
      globalToggle();
      return;
    }
    globalPlay({ stem: beat.stem, title: beat.name || beat.stem, artist: beat.artist, filename: beat.audio });
  };

  // Close picker (no need to stop audio — global player handles it)
  const closePicker = () => {
    setPickerSlot(null);
  };

  // Lane beats management state
  const { data: laneBeats, refetch: refetchLaneBeats } =
    useFetch<LaneBeatsData>("/lanes/beats");
  const [laneSelected, setLaneSelected] = useState<Record<string, Set<string>>>({});
  const [removingFromLane, setRemovingFromLane] = useState(false);
  const [expandedLane, setExpandedLane] = useState<string | null>(null);

  const handleExecute = useCallback(
    async (dryRun: boolean) => {
      if (dryRun) setDryRunning(true);
      else setExecuting(true);

      try {
        await api.post("/content-schedule/execute", { dry_run: dryRun });
        toast(
          dryRun ? "Dry run started" : "Content schedule executing...",
          "info"
        );

        const poll = setInterval(async () => {
          try {
            const fresh = await api.get<StatusData>("/content-schedule/status");
            if (fresh?.last_execution !== status?.last_execution && !dryRun) {
              clearInterval(poll);
              refetchStatus();
              refetchPlan();
              setExecuting(false);
              setDryRunning(false);
              toast("Schedule execution complete!", "success");
            }
          } catch {
            /* still running */
          }
        }, 5000);

        setTimeout(() => {
          clearInterval(poll);
          setExecuting(false);
          setDryRunning(false);
        }, 300000);

        if (dryRun) {
          setTimeout(() => {
            setDryRunning(false);
            toast("Dry run complete", "success");
          }, 8000);
        }
      } catch (e: unknown) {
        toast(e instanceof Error ? e.message : "Failed", "error");
        setExecuting(false);
        setDryRunning(false);
      }
    },
    [status, refetchStatus, refetchPlan, toast]
  );

  // Beat picker handlers
  const openPicker = async (slotIndex: number) => {
    if (pickerSlot === slotIndex) {
      closePicker();
      return;
    }
    setPickerSlot(slotIndex);
    setPickerSearch("");
    setPickerLoading(true);
    try {
      const res = await api.get<{ beats: AvailableBeat[] }>("/content-schedule/available-beats");
      setPickerBeats(res?.beats || []);
    } catch {
      toast("Failed to load beats", "error");
      setPickerBeats([]);
    } finally {
      setPickerLoading(false);
    }
  };

  const selectBeat = async (slotIndex: number, stem: string) => {
    setSavingSlot(true);
    try {
      await api.put("/content-schedule/plan/slot", { slot_index: slotIndex, stem });
      toast("Slot updated", "success");
      closePicker();
      refetchPlan();
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : "Failed", "error");
    } finally {
      setSavingSlot(false);
    }
  };

  const clearOverride = async (slotIndex: number) => {
    setSavingSlot(true);
    try {
      await api.put("/content-schedule/plan/slot", { slot_index: slotIndex, stem: null });
      toast("Slot reset to auto", "success");
      closePicker();
      refetchPlan();
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : "Failed", "error");
    } finally {
      setSavingSlot(false);
    }
  };

  const filteredPickerBeats = useMemo(() => {
    if (!pickerSearch.trim()) return pickerBeats;
    const q = pickerSearch.toLowerCase();
    return pickerBeats.filter(
      (b) =>
        b.name.toLowerCase().includes(q) ||
        b.stem.toLowerCase().includes(q) ||
        b.artist.toLowerCase().includes(q)
    );
  }, [pickerBeats, pickerSearch]);

  // Lane beat selection handlers
  const toggleLaneBeatSel = (lane: string, stem: string) => {
    setLaneSelected((prev) => {
      const s = new Set(prev[lane] || []);
      if (s.has(stem)) s.delete(stem); else s.add(stem);
      return { ...prev, [lane]: s };
    });
  };

  const selectAllInLane = (lane: string) => {
    const beats = laneBeats?.[lane] || [];
    setLaneSelected((prev) => ({
      ...prev,
      [lane]: new Set(beats.map((b) => b.stem)),
    }));
  };

  const clearLaneSel = (lane: string) => {
    setLaneSelected((prev) => ({ ...prev, [lane]: new Set() }));
  };

  const removeSelectedFromLane = async (lane: string) => {
    const selected = laneSelected[lane];
    if (!selected?.size) return;
    setRemovingFromLane(true);
    try {
      await api.post("/lanes/unassign", { stems: Array.from(selected) });
      toast(`Removed ${selected.size} beats from ${lane}`, "success");
      clearLaneSel(lane);
      refetchLaneBeats();
      refetchStatus();
      refetchPlan();
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : "Failed", "error");
    } finally {
      setRemovingFromLane(false);
    }
  };

  const removeSingleFromLane = async (stem: string) => {
    setRemovingFromLane(true);
    try {
      await api.post("/lanes/unassign", { stems: [stem] });
      toast("Beat removed from lane", "success");
      refetchLaneBeats();
      refetchStatus();
      refetchPlan();
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : "Failed", "error");
    } finally {
      setRemovingFromLane(false);
    }
  };

  const startEditing = (lane: string, artists: string[]) => {
    setEditingLane(lane);
    setEditArtists([...artists]);
    setNewArtist("");
  };

  const cancelEditing = () => {
    setEditingLane(null);
    setEditArtists([]);
    setNewArtist("");
  };

  const addArtist = () => {
    const name = newArtist.trim();
    if (name && !editArtists.includes(name)) {
      setEditArtists([...editArtists, name]);
      setNewArtist("");
    }
  };

  const removeArtist = (idx: number) => {
    setEditArtists(editArtists.filter((_, i) => i !== idx));
  };

  const saveCluster = async () => {
    if (!editingLane || editArtists.length === 0) return;
    setSavingCluster(true);
    try {
      await api.put(`/content-schedule/clusters/${editingLane}`, {
        artists: editArtists,
      });
      toast(`${editingLane} cluster updated`, "success");
      cancelEditing();
      refetchStatus();
      refetchPlan();
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : "Failed to save", "error");
    } finally {
      setSavingCluster(false);
    }
  };

  const handleRefreshOptimizer = async () => {
    setRefreshingOptimizer(true);
    try {
      await api.post("/content-schedule/optimizer/refresh");
      toast("Analytics refreshed", "success");
      refetchStatus();
      refetchPlan();
    } catch (e: unknown) {
      toast(e instanceof Error ? e.message : "Failed", "error");
    } finally {
      setRefreshingOptimizer(false);
    }
  };

  const timeAgo = (iso: string) => {
    if (!iso) return "Never";
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "Just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  };

  const loading = statusLoading || planLoading;
  const optimizer = status?.optimizer;

  return (
    <div className="min-h-screen p-4 md:p-6" style={{ background: "var(--bg-primary)" }}>
      {/* Header */}
      <div
        className="mb-6 p-4 md:p-5 rounded-2xl"
        style={{
          background: "linear-gradient(135deg, var(--bg-secondary), var(--bg-primary))",
          border: "1px solid var(--border)",
        }}
      >
        <div className="flex items-center gap-3 mb-3 md:mb-0">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
            style={{ background: "#8b5cf615" }}
          >
            <CalendarClock size={20} style={{ color: "#8b5cf6" }} />
          </div>
          <div>
            <h1 className="text-xl font-black text-foreground">Content Scheduler</h1>
            <p className="text-[11px] text-text-secondary">
              6 daily slots &middot; 3 Beats + 3 Shorts &middot; rotated across lanes
            </p>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-2 md:flex md:items-center md:justify-end md:gap-2 md:mt-[-40px]">
          <button
            onClick={() => { refetchStatus(); refetchPlan(); }}
            className="px-3 py-2.5 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5"
            style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
          >
            <RefreshCw size={13} /> Refresh
          </button>
          <button
            onClick={() => handleExecute(true)}
            disabled={executing || dryRunning}
            className="px-3 py-2.5 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5"
            style={{
              background: "var(--bg-hover)",
              border: "1px solid var(--border)",
              opacity: executing || dryRunning ? 0.5 : 1,
            }}
          >
            {dryRunning ? <Loader2 size={13} className="animate-spin" /> : <Eye size={13} />}
            {dryRunning ? "Running..." : "Dry Run"}
          </button>
          <button
            onClick={() => handleExecute(false)}
            disabled={executing || dryRunning}
            className="px-3 py-2.5 rounded-xl text-xs font-bold flex items-center justify-center gap-1.5"
            style={{
              background: executing ? "#8b5cf630" : "#8b5cf615",
              border: `1px solid ${executing ? "#8b5cf650" : "#8b5cf630"}`,
              color: "#8b5cf6",
              opacity: executing || dryRunning ? 0.5 : 1,
            }}
          >
            {executing ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
            {executing ? "Executing..." : "Execute"}
          </button>
        </div>
      </div>

      {/* Execution progress bar */}
      {execProgress && (
        <div
          className="rounded-xl p-3 mb-4"
          style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
        >
          <div className="flex items-center gap-3 mb-2">
            <Loader2 size={14} className="animate-spin" style={{ color: "#8b5cf6" }} />
            <span className="text-xs font-bold text-foreground">
              {execProgress.pct >= 100 ? "Complete!" : "Executing Schedule..."}
            </span>
            <span className="text-[10px] font-bold ml-auto" style={{ color: "#8b5cf6" }}>
              {execProgress.pct}%
            </span>
          </div>
          <div
            className="w-full h-2 rounded-full overflow-hidden"
            style={{ background: "var(--bg-hover)" }}
          >
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{
                width: `${execProgress.pct}%`,
                background: execProgress.pct >= 100
                  ? "#22c55e"
                  : "linear-gradient(90deg, #8b5cf6, #a78bfa)",
              }}
            />
          </div>
          {execProgress.detail && (
            <p className="text-[10px] text-text-tertiary mt-1.5 truncate">
              {execProgress.detail}
            </p>
          )}
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64 gap-3 text-text-secondary">
          <Loader2 size={20} className="animate-spin" />
          <span className="text-sm">Loading scheduler data...</span>
        </div>
      ) : (
        <>
          {/* Stats Row */}
          {status && (
            <div className="grid grid-cols-3 md:grid-cols-6 gap-3 mb-6">
              <Stat label="Rendered Ready" value={status.rendered_ready} color="#22c55e" />
              <Stat
                label="Buffer"
                value={`${status.buffer_days}d`}
                color={status.buffer_days < 3 ? "#ef4444" : "#22c55e"}
                sub={`${status.beats_per_day}/day`}
              />
              <Stat label="Shorts Ready" value={status.shorts_ready} color="#3b82f6" />
              <Stat label="Shorts Needed" value={status.shorts_needed} color={status.shorts_needed > 0 ? "#f59e0b" : "#22c55e"} />
              <Stat label="Uploaded" value={status.total_uploaded} color="#8b5cf6" />
              <Stat label="Pending" value={status.scheduled_pending} color="#f59e0b" />
            </div>
          )}

          {/* Main Grid: Plan + Sidebar */}
          <div className="grid grid-cols-1 xl:grid-cols-[1fr_380px] gap-6">
            {/* Daily Plan */}
            <div className="space-y-6">
              <div
                className="p-4 md:p-5 rounded-2xl"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
              >
                {/* Date navigation */}
                <div className="flex items-center gap-2 mb-4">
                  <button
                    onClick={() => setSelectedDate(shiftDate(selectedDate, -1))}
                    className="p-1.5 rounded-lg flex-shrink-0"
                    style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
                    title="Previous day"
                  >
                    <ChevronLeft size={14} />
                  </button>

                  {/* Date display — click to open calendar */}
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <div className="relative" ref={calRef}>
                      <button
                        onClick={() => {
                          const d = new Date(selectedDate + "T12:00:00");
                          setCalMonth({ year: d.getFullYear(), month: d.getMonth() });
                          setShowCalendar(!showCalendar);
                        }}
                        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg cursor-pointer"
                        style={{ background: "var(--bg-hover)" }}
                      >
                        <Calendar size={13} style={{ color: "#8b5cf6" }} />
                        <span className="text-sm font-bold text-foreground">
                          {fmtDate(selectedDate)}
                        </span>
                        {isToday && (
                          <span className="text-[8px] font-bold px-1.5 py-0.5 rounded-full"
                            style={{ background: "#8b5cf615", color: "#8b5cf6" }}>
                            Today
                          </span>
                        )}
                      </button>

                      {/* Calendar dropdown */}
                      {showCalendar && (
                        <div
                          className="absolute top-full left-0 mt-2 z-50 rounded-xl p-3 shadow-2xl"
                          style={{
                            background: "var(--bg-secondary)",
                            border: "1px solid var(--border)",
                            minWidth: 280,
                          }}
                        >
                          {/* Month nav */}
                          <div className="flex items-center justify-between mb-3">
                            <button
                              onClick={() => setCalMonth(prev => {
                                const m = prev.month - 1;
                                return m < 0 ? { year: prev.year - 1, month: 11 } : { ...prev, month: m };
                              })}
                              className="p-1 rounded-lg"
                              style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
                            >
                              <ChevronLeft size={14} />
                            </button>
                            <span className="text-xs font-bold text-foreground">
                              {new Date(calMonth.year, calMonth.month).toLocaleDateString("en-US", { month: "long", year: "numeric" })}
                            </span>
                            <button
                              onClick={() => setCalMonth(prev => {
                                const m = prev.month + 1;
                                return m > 11 ? { year: prev.year + 1, month: 0 } : { ...prev, month: m };
                              })}
                              className="p-1 rounded-lg"
                              style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
                            >
                              <ChevronRight size={14} />
                            </button>
                          </div>

                          {/* Day headers */}
                          <div className="grid grid-cols-7 gap-1 mb-1">
                            {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map(d => (
                              <div key={d} className="text-[9px] font-bold text-text-tertiary text-center py-1">
                                {d}
                              </div>
                            ))}
                          </div>

                          {/* Day grid */}
                          <div className="grid grid-cols-7 gap-1">
                            {(() => {
                              const firstDay = new Date(calMonth.year, calMonth.month, 1).getDay();
                              const daysInMonth = new Date(calMonth.year, calMonth.month + 1, 0).getDate();
                              const cells: React.ReactNode[] = [];
                              // Empty cells before first day
                              for (let i = 0; i < firstDay; i++) {
                                cells.push(<div key={`e${i}`} />);
                              }
                              for (let day = 1; day <= daysInMonth; day++) {
                                const iso = `${calMonth.year}-${String(calMonth.month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
                                const isSel = iso === selectedDate;
                                const isTod = iso === todayISO();
                                cells.push(
                                  <button
                                    key={day}
                                    onClick={() => {
                                      setSelectedDate(iso);
                                      setShowCalendar(false);
                                    }}
                                    className="w-8 h-8 rounded-lg text-xs font-semibold flex items-center justify-center transition-colors"
                                    style={{
                                      background: isSel ? "#8b5cf6" : isTod ? "#8b5cf615" : "transparent",
                                      color: isSel ? "#fff" : isTod ? "#8b5cf6" : "var(--text-secondary)",
                                      border: isTod && !isSel ? "1px solid #8b5cf640" : "1px solid transparent",
                                    }}
                                  >
                                    {day}
                                  </button>
                                );
                              }
                              return cells;
                            })()}
                          </div>

                          {/* Today shortcut */}
                          <button
                            onClick={() => {
                              setSelectedDate(todayISO());
                              setShowCalendar(false);
                              const d = new Date();
                              setCalMonth({ year: d.getFullYear(), month: d.getMonth() });
                            }}
                            className="w-full mt-2 text-[10px] font-bold py-1.5 rounded-lg text-center"
                            style={{ background: "#8b5cf615", color: "#8b5cf6" }}
                          >
                            Go to Today
                          </button>
                        </div>
                      )}
                    </div>

                    {!isToday && (
                      <button
                        onClick={() => setSelectedDate(todayISO())}
                        className="text-[10px] font-bold px-2 py-1 rounded-lg flex-shrink-0"
                        style={{ background: "#8b5cf615", color: "#8b5cf6" }}
                      >
                        Today
                      </button>
                    )}

                    {plan?.lane_priority && plan.lane_priority.length > 0 && (
                      <span className="text-[9px] text-text-tertiary px-2 py-0.5 rounded-full hidden md:inline-block" style={{ background: "var(--bg-hover)" }}>
                        Priority: {plan.lane_priority.join(" > ")}
                      </span>
                    )}
                  </div>

                  {plan?.summary && (
                    <span className="text-[10px] text-text-tertiary flex-shrink-0">
                      {plan.summary.beats_planned}b &middot; {plan.summary.shorts_planned}s &middot; EST
                    </span>
                  )}

                  <button
                    onClick={() => setSelectedDate(shiftDate(selectedDate, 1))}
                    className="p-1.5 rounded-lg flex-shrink-0"
                    style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
                    title="Next day"
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>

                {/* YouTube Scheduled Uploads for this date */}
                {plan?.youtube_scheduled && plan.youtube_scheduled.length > 0 && (
                  <div className="mb-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Youtube size={14} style={{ color: "#ff0000" }} />
                      <p className="text-xs font-bold text-foreground">
                        YouTube Scheduled
                      </p>
                      <span
                        className="text-[9px] font-bold px-1.5 py-0.5 rounded-full"
                        style={{ background: "#ff000015", color: "#ff0000" }}
                      >
                        {plan.youtube_scheduled.length} video{plan.youtube_scheduled.length !== 1 ? "s" : ""}
                      </span>
                    </div>
                    <div className="space-y-1">
                      {plan.youtube_scheduled.map((yt) => {
                        const laneColor = "#ff0000";  // always red for YT scheduled section
                        return (
                          <div
                            key={yt.videoId}
                            className="flex items-center gap-2 md:gap-3 p-2.5 rounded-xl"
                            style={{
                              background: `${laneColor}08`,
                              border: `1px solid ${laneColor}18`,
                            }}
                          >
                            <span className="text-[10px] font-mono font-bold text-text-secondary w-[52px] flex-shrink-0">
                              {yt.time_est}
                            </span>
                            <div
                              className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                              style={{ background: `${laneColor}15` }}
                            >
                              <Youtube size={13} style={{ color: laneColor }} />
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5">
                                <p className="text-xs font-semibold text-foreground truncate">
                                  {yt.title}
                                </p>
                                {yt.lane && (
                                  <span
                                    className="text-[7px] font-bold px-1 py-0.5 rounded uppercase tracking-wide flex-shrink-0"
                                    style={{ background: `${laneColor}15`, color: laneColor }}
                                  >
                                    {yt.lane}
                                  </span>
                                )}
                              </div>
                              <p className="text-[10px] text-text-tertiary truncate">
                                {yt.stem.replace(/_/g, " ")}
                              </p>
                            </div>
                            {yt.url && (
                              <a
                                href={yt.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="p-1.5 rounded-lg flex-shrink-0 transition-colors"
                                style={{ color: "var(--text-tertiary)" }}
                                title="View on YouTube"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <ExternalLink size={12} />
                              </a>
                            )}
                            <span
                              className="text-[8px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0"
                              style={{ background: "#ff000012", color: "#ff0000" }}
                            >
                              Scheduled
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {!plan?.slots?.length ? (
                  <div className="text-center py-8 text-text-tertiary text-sm">
                    No plan generated yet
                  </div>
                ) : (
                  <div className="space-y-2">
                    {plan.slots.map((slot, i) => {
                      const laneColor = LANE_COLORS[slot.lane] || "#6b7280";
                      const isBeat = slot.type === "beat";
                      const isPickerOpen = pickerSlot === i;
                      const isOverride = !!(slot as PlanSlot & { override?: boolean }).override;

                      return (
                        <div key={i}>
                          {/* Slot Row */}
                          <div
                            className="flex items-center gap-2 md:gap-3 p-3 rounded-xl transition-all"
                            style={{
                              background: isPickerOpen ? "var(--bg-hover)" : "var(--bg-primary)",
                              border: isOverride ? "1px solid #8b5cf640" : "1px solid transparent",
                            }}
                          >
                            <span className="text-[10px] font-mono font-bold text-text-secondary w-[52px] flex-shrink-0">
                              {to12h(slot.time)}
                            </span>
                            <div
                              className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0"
                              style={{ background: `${laneColor}15` }}
                            >
                              {isBeat ? (
                                <Music size={13} style={{ color: laneColor }} />
                              ) : (
                                <Smartphone size={13} style={{ color: laneColor }} />
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5">
                                <p className="text-xs font-semibold text-foreground truncate">
                                  {slot.label}
                                </p>
                                <span
                                  className="text-[7px] font-bold px-1 py-0.5 rounded uppercase tracking-wide flex-shrink-0"
                                  style={{ background: `${laneColor}15`, color: laneColor }}
                                >
                                  {slot.lane}
                                </span>
                                {isOverride && (
                                  <Pin size={9} style={{ color: "#8b5cf6" }} className="flex-shrink-0" />
                                )}
                              </div>
                              {slot.stem ? (
                                <p className="text-[10px] text-text-tertiary truncate">
                                  {slot.artist} &mdash; {slot.stem.replace(/_/g, " ")}
                                </p>
                              ) : (
                                <p className="text-[10px] text-text-tertiary italic">
                                  No beats available
                                </p>
                              )}
                            </div>

                            {/* Status + Change button */}
                            <div className="flex items-center gap-1.5 flex-shrink-0">
                              {slot.status === "planned" && slot.stem ? (
                                <span className="text-[9px] font-bold px-2 py-0.5 rounded-full hidden md:inline-block"
                                  style={{ background: "#22c55e15", color: "#22c55e" }}>
                                  Ready
                                </span>
                              ) : slot.status === "no_beats_available" ? (
                                <span className="text-[9px] font-bold px-2 py-0.5 rounded-full"
                                  style={{ background: "#ef444415", color: "#ef4444" }}>
                                  Empty
                                </span>
                              ) : null}

                              {slot.type === "short" && slot.stem && (
                                <div className="flex-shrink-0">
                                  {slot.has_short_video ? (
                                    <CheckCircle2 size={13} style={{ color: "#22c55e" }} />
                                  ) : (
                                    <AlertTriangle size={13} style={{ color: "#f59e0b" }} />
                                  )}
                                </div>
                              )}

                              {/* Change beat button */}
                              <button
                                onClick={() => openPicker(i)}
                                className="p-1.5 rounded-lg transition-all"
                                style={{
                                  background: isPickerOpen ? "#8b5cf620" : "transparent",
                                  color: isPickerOpen ? "#8b5cf6" : "var(--text-tertiary)",
                                }}
                                title="Change beat"
                              >
                                <ChevronDown
                                  size={14}
                                  style={{
                                    transform: isPickerOpen ? "rotate(180deg)" : "rotate(0deg)",
                                    transition: "transform 0.2s",
                                  }}
                                />
                              </button>
                            </div>
                          </div>

                          {/* Beat Picker (expanded) */}
                          {isPickerOpen && (
                            <div
                              className="mt-1 p-3 rounded-xl space-y-2"
                              style={{
                                background: "var(--bg-primary)",
                                border: "1px solid var(--border)",
                              }}
                            >
                              {/* Picker header */}
                              <div className="flex items-center gap-2">
                                <SearchInput
                                  value={pickerSearch}
                                  onChange={setPickerSearch}
                                  placeholder="Search beats..."
                                  size="sm"
                                  autoFocus
                                  className="flex-1"
                                />
                                {isOverride && (
                                  <button
                                    onClick={() => clearOverride(i)}
                                    disabled={savingSlot}
                                    className="px-2.5 py-2 rounded-lg text-[10px] font-bold flex items-center gap-1"
                                    style={{
                                      background: "var(--bg-secondary)",
                                      border: "1px solid var(--border)",
                                      color: "var(--text-secondary)",
                                      opacity: savingSlot ? 0.5 : 1,
                                    }}
                                    title="Reset to auto-assigned beat"
                                  >
                                    <RotateCcw size={10} /> Auto
                                  </button>
                                )}
                                <button
                                  onClick={closePicker}
                                  className="p-2 rounded-lg"
                                  style={{ color: "var(--text-tertiary)", background: "var(--bg-secondary)" }}
                                >
                                  <X size={12} />
                                </button>
                              </div>

                              {/* Beat list */}
                              {pickerLoading ? (
                                <div className="flex items-center justify-center py-4 gap-2 text-text-tertiary">
                                  <Loader2 size={14} className="animate-spin" />
                                  <span className="text-xs">Loading beats...</span>
                                </div>
                              ) : filteredPickerBeats.length === 0 ? (
                                <div className="text-center py-4 text-text-tertiary text-xs">
                                  {pickerSearch ? "No beats match your search" : "No available beats"}
                                </div>
                              ) : (
                                <div className="max-h-[200px] overflow-y-auto space-y-1">
                                  {filteredPickerBeats.map((beat) => {
                                    const isCurrentBeat = slot.stem === beat.stem;
                                    const beatLaneColor = beat.lane ? LANE_COLORS[beat.lane] || "#6b7280" : "";
                                    const isPlaying = playingStem === beat.stem && globalIsPlaying;
                                    return (
                                      <div
                                        key={beat.stem}
                                        className="flex items-center gap-1.5 p-2 rounded-lg transition-all"
                                        style={{
                                          background: isCurrentBeat ? "#8b5cf610" : isPlaying ? "#22c55e08" : "transparent",
                                          border: isCurrentBeat ? "1px solid #8b5cf630" : "1px solid transparent",
                                          opacity: savingSlot ? 0.5 : 1,
                                        }}
                                      >
                                        {/* Play/Pause preview button */}
                                        <button
                                          onClick={(e) => { e.stopPropagation(); togglePreview(beat); }}
                                          className="w-6 h-6 rounded-md flex items-center justify-center flex-shrink-0 transition-all"
                                          style={{
                                            background: isPlaying ? "#22c55e20" : "var(--bg-hover)",
                                            color: isPlaying ? "#22c55e" : "var(--text-tertiary)",
                                          }}
                                          title={beat.audio ? (isPlaying ? "Pause" : playingStem === beat.stem ? "Resume" : "Preview") : "No audio"}
                                          disabled={!beat.audio}
                                        >
                                          {isPlaying ? <Pause size={10} /> : playingStem === beat.stem ? <Play size={10} /> : <Volume2 size={10} />}
                                        </button>

                                        {/* Beat info — clickable to select */}
                                        <button
                                          onClick={() => !isCurrentBeat && selectBeat(i, beat.stem)}
                                          disabled={savingSlot || isCurrentBeat}
                                          className="flex-1 min-w-0 text-left"
                                        >
                                          <p className="text-[11px] font-semibold text-foreground truncate">
                                            {beat.name}
                                          </p>
                                          <p className="text-[9px] text-text-tertiary truncate">
                                            {beat.artist || "No artist"} &middot; {beat.stem}
                                          </p>
                                        </button>
                                        {beat.lane && (
                                          <span
                                            className="text-[7px] font-bold px-1 py-0.5 rounded uppercase flex-shrink-0"
                                            style={{ background: `${beatLaneColor}15`, color: beatLaneColor }}
                                          >
                                            {beat.lane}
                                          </span>
                                        )}
                                        {isCurrentBeat && (
                                          <span className="text-[8px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0"
                                            style={{ background: "#8b5cf615", color: "#8b5cf6" }}>
                                            Current
                                          </span>
                                        )}
                                      </div>
                                    );
                                  })}
                                </div>
                              )}

                              <p className="text-[9px] text-text-tertiary text-center">
                                {filteredPickerBeats.length} beats available &middot; Tap to assign
                              </p>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Lane Optimizer */}
              <div
                className="p-4 md:p-5 rounded-2xl"
                style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
              >
                <div className="flex items-center gap-2 mb-4">
                  <TrendingUp size={15} style={{ color: "#f59e0b" }} />
                  <h2 className="text-sm font-bold text-foreground">Lane Optimizer</h2>
                  <button
                    onClick={handleRefreshOptimizer}
                    disabled={refreshingOptimizer}
                    className="ml-auto px-2.5 py-1 rounded-lg text-[10px] font-bold flex items-center gap-1"
                    style={{
                      background: "var(--bg-hover)",
                      border: "1px solid var(--border)",
                      opacity: refreshingOptimizer ? 0.5 : 1,
                    }}
                  >
                    {refreshingOptimizer ? (
                      <Loader2 size={10} className="animate-spin" />
                    ) : (
                      <RefreshCw size={10} />
                    )}
                    Refresh Analytics
                  </button>
                </div>

                {!optimizer?.has_data ? (
                  <div
                    className="text-center py-6 rounded-xl"
                    style={{ background: "var(--bg-primary)" }}
                  >
                    <TrendingUp size={24} className="mx-auto mb-2" style={{ color: "var(--text-tertiary)" }} />
                    <p className="text-xs text-text-tertiary mb-1">No analytics data yet</p>
                    <p className="text-[10px] text-text-tertiary">
                      Click &quot;Refresh Analytics&quot; to build from upload history
                    </p>
                  </div>
                ) : (
                  <div className="space-y-2">
                    {optimizer.ranked_lanes.map((lane, i) => {
                      const score = optimizer.scores[lane] || 0;
                      const data = optimizer.analytics[lane];
                      const laneColor = LANE_COLORS[lane] || "#6b7280";
                      const maxScore = Math.max(...Object.values(optimizer.scores), 1);
                      const pct = Math.round((score / maxScore) * 100);
                      const medal = i < 3 ? MEDAL_COLORS[i] : undefined;

                      return (
                        <div
                          key={lane}
                          className="p-3 rounded-xl flex items-center gap-3"
                          style={{ background: "var(--bg-primary)" }}
                        >
                          {/* Rank */}
                          <div className="flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center"
                            style={{
                              background: medal ? `${medal}20` : "var(--bg-hover)",
                            }}
                          >
                            {medal ? (
                              <Trophy size={12} style={{ color: medal }} />
                            ) : (
                              <span className="text-[10px] font-bold text-text-tertiary">{i + 1}</span>
                            )}
                          </div>

                          {/* Lane info */}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-xs font-bold" style={{ color: laneColor }}>
                                {lane}
                              </span>
                              <span className="text-[10px] font-semibold text-foreground">
                                {score.toLocaleString(undefined, { maximumFractionDigits: 0 })} pts
                              </span>
                            </div>
                            {data && (
                              <div className="flex items-center gap-3 text-[9px] text-text-tertiary">
                                <span>{data.videos} videos</span>
                                <span>{data.views.toLocaleString()} views</span>
                                <span>{data.ctr}% CTR</span>
                              </div>
                            )}
                            <div
                              className="h-1 rounded-full overflow-hidden mt-1.5"
                              style={{ background: "var(--bg-hover)" }}
                            >
                              <div
                                className="h-full rounded-full transition-all duration-500"
                                style={{ width: `${pct}%`, background: laneColor }}
                              />
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>

            {/* Sidebar: Clusters + History */}
            <div className="space-y-4">
              {/* Editable Clusters */}
              {status?.clusters && (
                <div
                  className="p-4 rounded-2xl"
                  style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
                >
                  <div className="flex items-center gap-2 mb-3">
                    <Users size={14} style={{ color: "#8b5cf6" }} />
                    <h3 className="text-xs font-bold text-foreground">Artist Clusters</h3>
                  </div>
                  <div className="space-y-3">
                    {Object.entries(status.clusters).map(([lane, artists]) => {
                      const color = LANE_COLORS[lane] || "#6b7280";
                      const isEditing = editingLane === lane;

                      return (
                        <div key={lane}>
                          <div className="flex items-center justify-between mb-1">
                            <span
                              className="text-[9px] font-bold uppercase tracking-wider"
                              style={{ color }}
                            >
                              {lane}
                            </span>
                            {!isEditing ? (
                              <button
                                onClick={() => startEditing(lane, artists as string[])}
                                className="p-1 rounded-md transition-colors"
                                style={{ color: "var(--text-tertiary)" }}
                                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
                                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                                title={`Edit ${lane} artists`}
                              >
                                <Pencil size={10} />
                              </button>
                            ) : (
                              <div className="flex items-center gap-1">
                                <button
                                  onClick={saveCluster}
                                  disabled={savingCluster || editArtists.length === 0}
                                  className="p-1 rounded-md"
                                  style={{
                                    color: "#22c55e",
                                    opacity: savingCluster ? 0.5 : 1,
                                  }}
                                  title="Save"
                                >
                                  {savingCluster ? <Loader2 size={10} className="animate-spin" /> : <Save size={10} />}
                                </button>
                                <button
                                  onClick={cancelEditing}
                                  className="p-1 rounded-md"
                                  style={{ color: "#ef4444" }}
                                  title="Cancel"
                                >
                                  <X size={10} />
                                </button>
                              </div>
                            )}
                          </div>

                          {isEditing ? (
                            <div className="space-y-1.5">
                              {editArtists.map((artist, idx) => (
                                <div
                                  key={idx}
                                  className="flex items-center gap-1.5 px-2 py-1 rounded-lg"
                                  style={{ background: "var(--bg-primary)" }}
                                >
                                  <span className="text-[10px] text-foreground flex-1">
                                    {artist}
                                  </span>
                                  <button
                                    onClick={() => removeArtist(idx)}
                                    className="p-0.5 rounded"
                                    style={{ color: "#ef4444" }}
                                    title="Remove artist"
                                  >
                                    <Trash2 size={9} />
                                  </button>
                                </div>
                              ))}
                              <div className="flex items-center gap-1">
                                <input
                                  type="text"
                                  value={newArtist}
                                  onChange={(e) => setNewArtist(e.target.value)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter") {
                                      e.preventDefault();
                                      addArtist();
                                    }
                                  }}
                                  placeholder="Add artist..."
                                  className="flex-1 px-2 py-1 rounded-lg text-[10px] outline-none"
                                  style={{
                                    background: "var(--bg-primary)",
                                    border: "1px solid var(--border)",
                                    color: "var(--text-primary)",
                                  }}
                                />
                                <button
                                  onClick={addArtist}
                                  disabled={!newArtist.trim()}
                                  className="p-1 rounded-lg"
                                  style={{
                                    background: `${color}15`,
                                    color,
                                    opacity: newArtist.trim() ? 1 : 0.3,
                                  }}
                                >
                                  <Plus size={10} />
                                </button>
                              </div>
                            </div>
                          ) : (
                            <div className="flex flex-wrap gap-1 mt-1">
                              {(artists as string[]).map((artist) => (
                                <span
                                  key={artist}
                                  className="text-[9px] font-medium px-1.5 py-0.5 rounded-md"
                                  style={{ background: `${color}10`, color: "var(--text-secondary)" }}
                                >
                                  {artist}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Lane Beats — interactive management */}
              {laneBeats && (
                <div
                  className="p-4 rounded-2xl"
                  style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
                >
                  <div className="flex items-center gap-2 mb-3">
                    <Layers size={14} style={{ color: "#3b82f6" }} />
                    <h3 className="text-xs font-bold text-foreground">Beats by Lane</h3>
                  </div>
                  <div className="space-y-2">
                    {Object.entries(laneBeats)
                      .filter(([lane]) => lane !== "unassigned")
                      .map(([lane, beats]) => {
                        const color = LANE_COLORS[lane] || "#6b7280";
                        const isExpanded = expandedLane === lane;
                        const selected = laneSelected[lane] || new Set<string>();
                        const allSelected = beats.length > 0 && selected.size === beats.length;

                        return (
                          <div key={lane}>
                            {/* Lane header — tappable to expand */}
                            <button
                              onClick={() => setExpandedLane(isExpanded ? null : lane)}
                              className="w-full flex items-center justify-between p-2.5 rounded-lg transition-all"
                              style={{
                                background: isExpanded ? `${color}10` : "var(--bg-primary)",
                              }}
                            >
                              <div className="flex items-center gap-2">
                                <span className="text-[10px] font-bold uppercase tracking-wide" style={{ color }}>
                                  {lane}
                                </span>
                                <span className="text-[10px] text-text-secondary">
                                  {beats.length} beats
                                </span>
                              </div>
                              <ChevronDown
                                size={12}
                                style={{
                                  color: "var(--text-tertiary)",
                                  transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)",
                                  transition: "transform 0.2s",
                                }}
                              />
                            </button>

                            {/* Expanded beat list */}
                            {isExpanded && (
                              <div className="mt-1 space-y-1">
                                {/* Select All / Clear / Remove toolbar */}
                                {beats.length > 0 && (
                                  <div className="flex items-center gap-1.5 px-1 py-1">
                                    <button
                                      onClick={() => allSelected ? clearLaneSel(lane) : selectAllInLane(lane)}
                                      className="text-[9px] font-bold px-2 py-1 rounded-md flex items-center gap-1"
                                      style={{
                                        background: "var(--bg-hover)",
                                        color: allSelected ? color : "var(--text-secondary)",
                                      }}
                                    >
                                      {allSelected ? <CheckSquare size={9} /> : <Square size={9} />}
                                      {allSelected ? "Clear" : "Select All"}
                                    </button>
                                    {selected.size > 0 && (
                                      <button
                                        onClick={() => removeSelectedFromLane(lane)}
                                        disabled={removingFromLane}
                                        className="text-[9px] font-bold px-2 py-1 rounded-md flex items-center gap-1"
                                        style={{
                                          background: "#ef444415",
                                          color: "#ef4444",
                                          opacity: removingFromLane ? 0.5 : 1,
                                        }}
                                      >
                                        {removingFromLane ? (
                                          <Loader2 size={9} className="animate-spin" />
                                        ) : (
                                          <MinusCircle size={9} />
                                        )}
                                        Remove {selected.size}
                                      </button>
                                    )}
                                  </div>
                                )}

                                {/* Beat rows */}
                                <div className="max-h-[180px] overflow-y-auto space-y-0.5">
                                  {beats.length === 0 ? (
                                    <p className="text-[10px] text-text-tertiary text-center py-3 italic">
                                      No beats in this lane
                                    </p>
                                  ) : (
                                    beats.map((beat) => {
                                      const isSel = selected.has(beat.stem);
                                      return (
                                        <div
                                          key={beat.stem}
                                          className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg"
                                          style={{
                                            background: isSel ? `${color}10` : "var(--bg-primary)",
                                          }}
                                        >
                                          {/* Checkbox */}
                                          <button
                                            onClick={() => toggleLaneBeatSel(lane, beat.stem)}
                                            className="flex-shrink-0"
                                            style={{ color: isSel ? color : "var(--text-tertiary)" }}
                                          >
                                            {isSel ? <CheckSquare size={12} /> : <Square size={12} />}
                                          </button>

                                          {/* Beat info */}
                                          <div className="flex-1 min-w-0">
                                            <p className="text-[10px] font-semibold text-foreground truncate">
                                              {beat.title || beat.stem.replace(/_/g, " ")}
                                            </p>
                                            <p className="text-[8px] text-text-tertiary truncate">
                                              {beat.seo_artist || "No artist"}
                                            </p>
                                          </div>

                                          {/* Status */}
                                          {beat.uploaded ? (
                                            <CheckCircle2 size={10} style={{ color: "#22c55e" }} className="flex-shrink-0" />
                                          ) : beat.rendered ? (
                                            <Music size={10} style={{ color: "#3b82f6" }} className="flex-shrink-0" />
                                          ) : null}

                                          {/* Remove single */}
                                          <button
                                            onClick={() => removeSingleFromLane(beat.stem)}
                                            disabled={removingFromLane}
                                            className="p-0.5 rounded flex-shrink-0"
                                            style={{ color: "var(--text-tertiary)" }}
                                            title="Remove from lane"
                                          >
                                            <X size={10} />
                                          </button>
                                        </div>
                                      );
                                    })
                                  )}
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })}
                  </div>
                </div>
              )}

              {/* History */}
              {status?.execution_history && status.execution_history.length > 0 && (
                <div
                  className="p-4 rounded-2xl"
                  style={{ background: "var(--bg-secondary)", border: "1px solid var(--border)" }}
                >
                  <div className="flex items-center gap-2 mb-3">
                    <BarChart3 size={14} style={{ color: "#f59e0b" }} />
                    <h3 className="text-xs font-bold text-foreground">Recent Runs</h3>
                  </div>
                  <div className="space-y-1.5">
                    {status.execution_history.map((h, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 text-[10px] p-1.5 rounded-lg"
                        style={{ background: "var(--bg-primary)" }}
                      >
                        <span className="text-text-tertiary font-mono w-20 flex-shrink-0">
                          {h.date}
                        </span>
                        <span style={{ color: "#22c55e" }}>{h.beats_scheduled}b</span>
                        <span style={{ color: "#3b82f6" }}>{h.shorts_uploaded}s</span>
                        {h.errors > 0 && (
                          <span style={{ color: "#ef4444" }}>{h.errors}err</span>
                        )}
                      </div>
                    ))}
                  </div>
                  {status.last_execution && (
                    <p className="text-[9px] text-text-tertiary mt-2">
                      Last run: {timeAgo(status.last_execution)}
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
