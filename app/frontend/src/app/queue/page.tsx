"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { useFetch, api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import SearchInput from "@/components/ui/SearchInput";
import {
  ListOrdered,
  RefreshCw,
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  Film,
  Upload,
  CalendarClock,
  ArrowRight,
  Settings,
  Save,
  Plus,
  Trash2,
  Edit3,
  ChevronLeft,
  ChevronRight,
  Youtube,
  ExternalLink,
  Calendar,
} from "lucide-react";

/* ── Types ─────────────────────────────────────────────────────────────── */

interface StatusData {
  total_beats: number;
  rendered: number;
  uploaded_yt: number;
  pending_renders: number;
}

interface ScheduleSlot {
  slot: string;
  slot_est: string;
  stem: string | null;
}

interface QueueEntry {
  stem: string;
  added_at: string;
  priority: number;
}

interface ScheduleData {
  queue: QueueEntry[];
  slots: ScheduleSlot[];
  buffer_days: number;
  queue_length: number;
  settings: {
    daily_yt_count: number;
    yt_times_est: string[];
    buffer_warning_days: number;
    autopilot_enabled: boolean;
  };
}

interface TaskItem {
  id: string;
  type: string;
  stem: string;
  title: string;
  status: string;
  progress?: number;
  message?: string;
  started_at?: string;
  completed_at?: string;
}

interface QueueData {
  active: TaskItem[];
  pending: TaskItem[];
  completed: TaskItem[];
}

interface YTScheduledUpload {
  stem: string;
  videoId: string;
  url: string;
  title: string;
  uploadedAt: string;
  publishAt: string;
  isPast: boolean;
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case "completed":
    case "done":
      return <CheckCircle2 size={14} style={{ color: "#10b981" }} />;
    case "failed":
    case "error":
      return <XCircle size={14} style={{ color: "#ef4444" }} />;
    case "running":
    case "active":
      return <Loader2 size={14} className="animate-spin" style={{ color: "var(--accent)" }} />;
    default:
      return <Clock size={14} style={{ color: "var(--text-tertiary)" }} />;
  }
}

function getDaysInMonth(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate();
}

function getFirstDayOfMonth(year: number, month: number) {
  return new Date(year, month, 1).getDay();
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/* ── Main Page ─────────────────────────────────────────────────────────── */

export default function QueuePage() {
  const { toast } = useToast();
  const { data: status, refetch: refetchStatus } = useFetch<StatusData>("/status");
  const { data: schedule, refetch: refetchSchedule } = useFetch<ScheduleData>("/schedule");
  const { data: taskQueue, refetch: refetchTasks } = useFetch<QueueData>("/queue");
  const [filter, setFilter] = useState("");

  /* Settings state */
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [editDailyCount, setEditDailyCount] = useState(2);
  const [editTimes, setEditTimes] = useState<string[]>(["11:00", "18:00"]);
  const [savingSettings, setSavingSettings] = useState(false);

  /* YouTube scheduled uploads */
  const [ytScheduled, setYtScheduled] = useState<YTScheduledUpload[]>([]);
  const [ytLoading, setYtLoading] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTime, setEditTime] = useState("");
  const [rescheduling, setRescheduling] = useState(false);

  /* Calendar state */
  const now = new Date();
  const [calMonth, setCalMonth] = useState(now.getMonth());
  const [calYear, setCalYear] = useState(now.getFullYear());

  const pendingRenders = status?.pending_renders ?? 0;
  const rendered = status?.rendered ?? 0;
  const uploaded = status?.uploaded_yt ?? 0;
  const total = status?.total_beats ?? 0;

  const queue = schedule?.queue || [];
  const slots = schedule?.slots || [];
  const bufferDays = schedule?.buffer_days ?? 0;

  const activeTasks = taskQueue?.active || [];
  const completedTasks = (taskQueue?.completed || []).slice(0, 10);

  const scheduledItems = slots.filter((s) => s.stem);
  const filteredSchedule = scheduledItems.filter(
    (s) => !filter || (s.stem || "").includes(filter.toLowerCase())
  );

  /* Load settings into edit state when schedule loads */
  useEffect(() => {
    if (schedule?.settings) {
      setEditDailyCount(schedule.settings.daily_yt_count);
      setEditTimes([...schedule.settings.yt_times_est]);
    }
  }, [schedule]);

  /* Fetch YouTube scheduled uploads */
  const fetchYTScheduled = useCallback(async () => {
    setYtLoading(true);
    try {
      const data = await api.get<{ uploads: YTScheduledUpload[]; count: number }>("/schedule/youtube-scheduled");
      setYtScheduled(data.uploads);
    } catch {
      // silent
    } finally {
      setYtLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchYTScheduled();
  }, [fetchYTScheduled]);

  function refreshAll() {
    refetchStatus();
    refetchSchedule();
    refetchTasks();
    fetchYTScheduled();
  }

  /* Save schedule settings */
  async function saveSettings() {
    setSavingSettings(true);
    try {
      await api.put("/schedule/settings", {
        daily_yt_count: editDailyCount,
        yt_times_est: editTimes.filter((t) => t.trim()),
      });
      toast("Schedule settings saved", "success");
      refetchSchedule();
      setSettingsOpen(false);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      toast(`Failed to save: ${msg}`, "error");
    } finally {
      setSavingSettings(false);
    }
  }

  function addTimeSlot() {
    setEditTimes((prev) => [...prev, "12:00"]);
  }

  function removeTimeSlot(idx: number) {
    setEditTimes((prev) => prev.filter((_, i) => i !== idx));
  }

  /* Reschedule a YouTube video */
  async function handleReschedule(stem: string, videoId: string) {
    if (!editTime) return;
    setRescheduling(true);
    try {
      await api.post("/schedule/reschedule", {
        video_id: videoId,
        stem,
        new_time: editTime,
      });
      toast("Video rescheduled successfully", "success");
      setEditingId(null);
      setEditTime("");
      fetchYTScheduled();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      toast(`Reschedule failed: ${msg}`, "error");
    } finally {
      setRescheduling(false);
    }
  }

  /* Calendar data — merge slots + YT scheduled uploads */
  const calendarEvents = useMemo(() => {
    const events: Record<string, { type: "slot" | "yt"; title: string; time: string; stem?: string; videoId?: string; isPast?: boolean }[]> = {};

    // Add computed schedule slots
    for (const slot of scheduledItems) {
      if (!slot.slot) continue;
      try {
        const d = new Date(slot.slot);
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
        if (!events[key]) events[key] = [];
        events[key].push({
          type: "slot",
          title: (slot.stem || "").replace(/_/g, " "),
          time: d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }),
          stem: slot.stem || undefined,
        });
      } catch { /* skip */ }
    }

    // Add YouTube scheduled uploads
    for (const yt of ytScheduled) {
      try {
        const d = new Date(yt.publishAt);
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
        if (!events[key]) events[key] = [];
        // Avoid duplicates (slot might overlap with yt scheduled)
        const already = events[key].some((e) => e.stem === yt.stem && e.type === "yt");
        if (!already) {
          events[key].push({
            type: "yt",
            title: yt.title,
            time: d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }),
            stem: yt.stem,
            videoId: yt.videoId,
            isPast: yt.isPast,
          });
        }
      } catch { /* skip */ }
    }

    return events;
  }, [scheduledItems, ytScheduled]);

  const daysInMonth = getDaysInMonth(calYear, calMonth);
  const firstDay = getFirstDayOfMonth(calYear, calMonth);
  const today = new Date();
  const todayKey = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  function prevMonth() {
    if (calMonth === 0) { setCalMonth(11); setCalYear(calYear - 1); }
    else setCalMonth(calMonth - 1);
  }
  function nextMonth() {
    if (calMonth === 11) { setCalMonth(0); setCalYear(calYear + 1); }
    else setCalMonth(calMonth + 1);
  }

  const futureYT = ytScheduled.filter((u) => !u.isPast);

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <ListOrdered size={24} style={{ color: "var(--accent)" }} />
            Queue
          </h1>
          <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
            Task monitor &amp; upload schedule
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setSettingsOpen(!settingsOpen)}
            className="p-2.5 rounded-xl transition-all cursor-pointer"
            style={{
              background: settingsOpen ? "var(--accent)" : "var(--bg-card)",
              border: `1px solid ${settingsOpen ? "var(--accent)" : "var(--glass-border)"}`,
              color: settingsOpen ? "#fff" : "var(--text-primary)",
            }}
          >
            <Settings size={15} />
          </button>
          <button
            onClick={refreshAll}
            className="p-2.5 rounded-xl transition-all cursor-pointer"
            style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
          >
            <RefreshCw size={15} />
          </button>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════
          SCHEDULE SETTINGS (collapsible)
          ═══════════════════════════════════════════════════════ */}
      {settingsOpen && (
        <div
          className="rounded-xl p-5 space-y-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
        >
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <Settings size={14} /> Schedule Settings
          </h3>

          {/* Daily count */}
          <div>
            <label className="block text-xs font-semibold mb-1 uppercase tracking-wider text-text-tertiary">
              Videos per Day
            </label>
            <input
              type="number"
              min={1}
              max={10}
              value={editDailyCount}
              onChange={(e) => setEditDailyCount(Math.max(1, Math.min(10, Number(e.target.value))))}
              className="w-20 px-3 py-2 rounded-lg text-sm outline-none"
              style={{ background: "var(--bg-hover)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
            />
          </div>

          {/* Upload times (EST) */}
          <div>
            <label className="block text-xs font-semibold mb-2 uppercase tracking-wider text-text-tertiary">
              Upload Times (EST)
            </label>
            <div className="space-y-2">
              {editTimes.map((t, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <input
                    type="time"
                    value={t}
                    onChange={(e) => {
                      const next = [...editTimes];
                      next[idx] = e.target.value;
                      setEditTimes(next);
                    }}
                    className="px-3 py-2 rounded-lg text-sm outline-none"
                    style={{ background: "var(--bg-hover)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
                  />
                  {editTimes.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeTimeSlot(idx)}
                      className="p-1.5 rounded-lg transition-all cursor-pointer"
                      style={{ color: "var(--text-tertiary)" }}
                    >
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
              ))}
              <button
                type="button"
                onClick={addTimeSlot}
                className="flex items-center gap-1 text-xs font-medium px-3 py-1.5 rounded-lg transition-all cursor-pointer"
                style={{ color: "var(--accent)", background: "rgba(var(--accent-rgb, 99,102,241), 0.1)" }}
              >
                <Plus size={12} /> Add Time
              </button>
            </div>
          </div>

          {/* Save */}
          <button
            type="button"
            onClick={saveSettings}
            disabled={savingSettings}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all cursor-pointer btn-gradient disabled:opacity-50"
          >
            {savingSettings ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            Save Settings
          </button>
        </div>
      )}

      {/* Pipeline Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Total Beats", value: total, icon: ListOrdered, color: "var(--text-primary)" },
          { label: "Rendered", value: rendered, icon: Film, color: "#10b981" },
          { label: "Uploaded", value: uploaded, icon: Upload, color: "#8b5cf6" },
          { label: "Pending Render", value: pendingRenders, icon: Clock, color: "#f59e0b" },
        ].map((s) => {
          const Icon = s.icon;
          return (
            <div
              key={s.label}
              className="rounded-xl p-4"
              style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
            >
              <div className="flex items-center gap-2 mb-1">
                <Icon size={14} style={{ color: "var(--text-tertiary)" }} />
                <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>{s.label}</span>
              </div>
              <p className="text-2xl font-bold" style={{ color: s.color }}>{s.value}</p>
            </div>
          );
        })}
      </div>

      {/* Progress Bars */}
      <div className="rounded-xl p-5" style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}>
        <h3 className="text-sm font-semibold mb-4 text-foreground">Pipeline Progress</h3>
        {[
          { label: "Render", pct: total > 0 ? Math.round((rendered / total) * 100) : 0, color: "#10b981" },
          { label: "Upload", pct: total > 0 ? Math.round((uploaded / total) * 100) : 0, color: "#8b5cf6" },
        ].map((bar) => (
          <div key={bar.label} className="mb-3">
            <div className="flex items-center justify-between mb-1">
              <span className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>{bar.label}</span>
              <span className="text-xs font-bold" style={{ color: bar.color }}>{bar.pct}%</span>
            </div>
            <div className="h-2 rounded-full overflow-hidden" style={{ background: "var(--bg-hover)" }}>
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{ width: `${bar.pct}%`, background: bar.color }}
              />
            </div>
          </div>
        ))}

        {/* Buffer days */}
        <div className="mt-4 pt-3 flex items-center gap-2" style={{ borderTop: "1px solid var(--glass-border)" }}>
          <CalendarClock size={14} style={{ color: "var(--text-tertiary)" }} />
          <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
            Content buffer: <strong style={{ color: bufferDays < 3 ? "#ef4444" : bufferDays < 7 ? "#f59e0b" : "#10b981" }}>{bufferDays.toFixed(1)} days</strong>
          </span>
          <span className="text-[10px] ml-auto" style={{ color: "var(--text-tertiary)" }}>
            {queue.length} beats queued
          </span>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════
          CALENDAR VIEW
          ═══════════════════════════════════════════════════════ */}
      <div
        className="rounded-xl p-5"
        style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <Calendar size={14} /> Schedule Calendar
          </h3>
          <div className="flex items-center gap-2">
            <button onClick={prevMonth} className="p-1.5 rounded-lg transition-all cursor-pointer" style={{ color: "var(--text-tertiary)" }}>
              <ChevronLeft size={16} />
            </button>
            <span className="text-sm font-semibold text-foreground min-w-[140px] text-center">
              {MONTH_NAMES[calMonth]} {calYear}
            </span>
            <button onClick={nextMonth} className="p-1.5 rounded-lg transition-all cursor-pointer" style={{ color: "var(--text-tertiary)" }}>
              <ChevronRight size={16} />
            </button>
          </div>
        </div>

        {/* Day headers */}
        <div className="grid grid-cols-7 gap-1 mb-1">
          {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
            <div key={d} className="text-center text-[10px] font-semibold py-1" style={{ color: "var(--text-tertiary)" }}>
              {d}
            </div>
          ))}
        </div>

        {/* Calendar grid */}
        <div className="grid grid-cols-7 gap-1">
          {/* Empty cells before first day */}
          {Array.from({ length: firstDay }).map((_, i) => (
            <div key={`empty-${i}`} className="min-h-[72px]" />
          ))}

          {/* Day cells */}
          {Array.from({ length: daysInMonth }).map((_, i) => {
            const day = i + 1;
            const dateKey = `${calYear}-${String(calMonth + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
            const dayEvents = calendarEvents[dateKey] || [];
            const isToday = dateKey === todayKey;

            return (
              <div
                key={day}
                className="min-h-[72px] rounded-lg p-1 transition-all"
                style={{
                  background: isToday ? "rgba(var(--accent-rgb, 99,102,241), 0.08)" : "var(--bg-hover)",
                  border: `1px solid ${isToday ? "var(--accent)" : "transparent"}`,
                }}
              >
                <span
                  className="text-[10px] font-bold block mb-0.5"
                  style={{ color: isToday ? "var(--accent)" : "var(--text-tertiary)" }}
                >
                  {day}
                </span>
                {dayEvents.slice(0, 3).map((ev, j) => (
                  <div
                    key={j}
                    className="text-[8px] font-medium truncate px-1 py-0.5 rounded mb-0.5"
                    style={{
                      background: ev.type === "yt"
                        ? (ev.isPast ? "rgba(16,185,129,0.15)" : "rgba(255,0,0,0.12)")
                        : "rgba(var(--accent-rgb, 99,102,241), 0.12)",
                      color: ev.type === "yt"
                        ? (ev.isPast ? "#10b981" : "#FF0000")
                        : "var(--accent)",
                    }}
                    title={`${ev.time} — ${ev.title}`}
                  >
                    {ev.time} {ev.title}
                  </div>
                ))}
                {dayEvents.length > 3 && (
                  <span className="text-[8px] font-medium px-1" style={{ color: "var(--text-tertiary)" }}>
                    +{dayEvents.length - 3} more
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 mt-3 pt-3" style={{ borderTop: "1px solid var(--glass-border)" }}>
          <div className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-sm" style={{ background: "rgba(var(--accent-rgb, 99,102,241), 0.5)" }} />
            <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>Queued</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-sm" style={{ background: "rgba(255,0,0,0.5)" }} />
            <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>Scheduled (YT)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-sm" style={{ background: "rgba(16,185,129,0.5)" }} />
            <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>Published</span>
          </div>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════
          YOUTUBE SCHEDULED UPLOADS (editable times)
          ═══════════════════════════════════════════════════════ */}
      <div
        className="rounded-xl p-5"
        style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <Youtube size={14} style={{ color: "#FF0000" }} /> YouTube Scheduled ({futureYT.length})
          </h3>
          {ytLoading && <Loader2 size={14} className="animate-spin text-text-tertiary" />}
        </div>

        {futureYT.length === 0 ? (
          <div className="rounded-xl p-8 text-center" style={{ background: "var(--bg-hover)" }}>
            <CalendarClock size={28} className="mx-auto mb-2" style={{ color: "var(--text-tertiary)", opacity: 0.3 }} />
            <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
              No upcoming scheduled YouTube uploads
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {futureYT.map((u) => {
              const pubDate = new Date(u.publishAt);
              const isEditing = editingId === u.videoId;

              return (
                <div
                  key={u.videoId}
                  className="flex flex-col sm:flex-row items-start sm:items-center gap-3 p-3 rounded-xl"
                  style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
                >
                  {/* YT icon */}
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: "#FF0000" }}>
                    <Youtube size={14} color="#fff" />
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate text-foreground">{u.title}</p>
                    <p className="text-[10px] text-text-tertiary">
                      Goes live: {pubDate.toLocaleDateString("en-US", {
                        weekday: "short", month: "short", day: "numeric",
                        hour: "numeric", minute: "2-digit",
                      })}
                    </p>
                  </div>

                  {/* Edit time or show actions */}
                  {isEditing ? (
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <input
                        type="datetime-local"
                        value={editTime}
                        onChange={(e) => setEditTime(e.target.value)}
                        className="px-2 py-1.5 rounded-lg text-xs outline-none"
                        style={{ background: "var(--bg-primary)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
                        autoFocus
                      />
                      <button
                        type="button"
                        onClick={() => handleReschedule(u.stem, u.videoId)}
                        disabled={!editTime || rescheduling}
                        className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer disabled:opacity-50"
                        style={{ background: "var(--accent)", color: "#fff" }}
                      >
                        {rescheduling ? <Loader2 size={12} className="animate-spin" /> : "Save"}
                      </button>
                      <button
                        type="button"
                        onClick={() => { setEditingId(null); setEditTime(""); }}
                        className="px-2 py-1.5 rounded-lg text-xs transition-all cursor-pointer"
                        style={{ color: "var(--text-tertiary)" }}
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <button
                        type="button"
                        onClick={() => {
                          setEditingId(u.videoId);
                          // Pre-fill with current time in datetime-local format
                          const d = new Date(u.publishAt);
                          const local = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
                          setEditTime(local);
                        }}
                        className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-semibold transition-all cursor-pointer"
                        style={{ color: "var(--accent)", background: "rgba(var(--accent-rgb, 99,102,241), 0.1)" }}
                      >
                        <Edit3 size={10} /> Edit Time
                      </button>
                      {u.url && (
                        <a
                          href={u.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-semibold transition-all"
                          style={{ color: "var(--text-tertiary)", background: "var(--bg-primary)" }}
                        >
                          <ExternalLink size={10} /> View
                        </a>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Active Tasks */}
      {activeTasks.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <Loader2 size={14} className="animate-spin" style={{ color: "var(--accent)" }} />
            Active Tasks ({activeTasks.length})
          </h3>
          {activeTasks.map((task) => (
            <div
              key={task.id}
              className="flex items-center gap-3 p-3 rounded-xl"
              style={{ background: "var(--bg-card)", border: "1px solid var(--accent)", boxShadow: "0 0 12px var(--accent-muted)" }}
            >
              <StatusIcon status={task.status} />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground truncate">{task.title || task.stem}</p>
                <p className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                  {task.type} • {task.message || "Processing..."}
                </p>
              </div>
              {task.progress !== undefined && (
                <div className="w-16">
                  <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-hover)" }}>
                    <div className="h-full rounded-full" style={{ width: `${task.progress}%`, background: "var(--accent)" }} />
                  </div>
                  <p className="text-[9px] text-right mt-0.5" style={{ color: "var(--text-tertiary)" }}>{task.progress}%</p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Recently Completed */}
      {completedTasks.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <CheckCircle2 size={14} style={{ color: "#10b981" }} />
            Recently Completed ({completedTasks.length})
          </h3>
          {completedTasks.map((task) => (
            <div
              key={task.id}
              className="flex items-center gap-3 p-3 rounded-xl"
              style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)", opacity: 0.7 }}
            >
              <StatusIcon status={task.status} />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-foreground truncate">{task.title || task.stem}</p>
                <p className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                  {task.type} • {task.completed_at ? new Date(task.completed_at).toLocaleString() : "Done"}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Scheduled Uploads (queue-computed slots) */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-foreground">
            Upload Queue ({scheduledItems.length})
          </h3>
          <SearchInput
            value={filter}
            onChange={setFilter}
            placeholder="Filter queue..."
            size="sm"
            className="w-44"
          />
        </div>

        {filteredSchedule.length === 0 ? (
          <div className="rounded-xl p-8 text-center" style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}>
            <Clock size={32} className="mx-auto mb-2" style={{ color: "var(--text-tertiary)" }} />
            <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
              {queue.length === 0
                ? "No beats in queue. Use the Automation page to add beats."
                : "No scheduled slots match your filter."
              }
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {filteredSchedule.map((slot, i) => (
              <div
                key={`${slot.stem}-${i}`}
                className="flex items-center gap-3 p-3 rounded-xl"
                style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
              >
                <span className="text-xs font-bold w-6 text-center" style={{ color: "var(--text-tertiary)" }}>
                  {i + 1}
                </span>
                <CalendarClock size={14} style={{ color: "var(--accent)" }} />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-foreground truncate">
                    {(slot.stem || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                  </p>
                  <p className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                    {slot.slot_est || "Pending slot"}
                  </p>
                </div>
                <ArrowRight size={12} style={{ color: "var(--text-tertiary)" }} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
