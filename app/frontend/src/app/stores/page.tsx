"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import {
  ShoppingBag,
  Star,
  RefreshCw,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ExternalLink,
  Upload,
  ChevronDown,
  ChevronUp,
  Youtube,
  Link2,
  Link2Off,
  DollarSign,
  Tag,
  Music,
  ArrowRight,
  Filter,
  X,
  Eye,
} from "lucide-react";
import { useFetch, api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import SearchInput from "@/components/ui/SearchInput";
import { useWebSocket } from "@/hooks/useWebSocket";

/* ── Upload task types ────────────────────────────────────────── */

interface UploadTask {
  id: string;
  type: string;
  stem: string;
  title: string;
  status: "running" | "done" | "failed";
  progress: number;
  detail: string;
  startedAt: number;
  finishedAt: number | null;
}

interface UploadTasksData {
  active: UploadTask[];
  completed: UploadTask[];
  summary: { uploading: number; done: number; failed: number };
}

/* ── Types ────────────────────────────────────────────────────── */

interface PlatformStatus {
  listed: boolean;
  url: string;
  listing_id: string;
  uploaded_at: string;
  synced: boolean | null;
}

interface BeatSync {
  stem: string;
  title: string;
  beat_name?: string;
  artist: string;
  seo_artist: string;
  lane: string;
  bpm: number;
  key: string;
  tags: string[];
  on_youtube: boolean;
  youtube_url: string;
  youtube_title: string;
  uploaded_at_yt: string;
  platforms: Record<string, PlatformStatus>;
  status: "synced" | "missing_from_store" | "missing_from_youtube" | "needs_update" | "not_uploaded";
}

interface PlatformInfo {
  id: string;
  name: string;
  color: string;
  connected: boolean;
  email: string;
  api_key_set: boolean;
  store_url: string;
}

interface SyncSummary {
  total_beats: number;
  on_youtube: number;
  synced: number;
  missing_from_store: number;
  missing_from_youtube: number;
  needs_update: number;
  not_uploaded: number;
  platforms: Record<string, { listed: number; not_listed: number; total_on_youtube: number }>;
}

interface ScanData {
  summary: SyncSummary;
  beats: BeatSync[];
  platforms: Record<string, { name: string; color: string }>;
}

interface PlatformData {
  platforms: PlatformInfo[];
  pricing: {
    basic_license: number;
    premium_license: number;
    exclusive_license: number;
    currency: string;
  };
}

/* ── Filter tabs ─────────────────────────────────────────────── */

type StatusFilter = "all" | "synced" | "missing_from_store" | "needs_update" | "not_uploaded";

const STATUS_TABS: { key: StatusFilter; label: string; color: string }[] = [
  { key: "all", label: "All Beats", color: "var(--text-secondary)" },
  { key: "missing_from_store", label: "Missing", color: "#ff4444" },
  { key: "needs_update", label: "Out of Sync", color: "#f5a623" },
  { key: "synced", label: "Synced", color: "#00d362" },
  { key: "not_uploaded", label: "Nowhere", color: "var(--text-tertiary)" },
];

/* ── Platform tab ────────────────────────────────────────────── */

type PlatformTab = "all" | "airbit" | "beatstars";

/* ── Page ─────────────────────────────────────────────────────── */

export default function StoresPage() {
  const { data: scanData, refetch: refetchScan, loading: scanning } = useFetch<ScanData>("/store-sync/scan");
  const { data: platformData, refetch: refetchPlatforms } = useFetch<PlatformData>("/store-sync/platforms");
  const { toast } = useToast();
  const { lastMessage } = useWebSocket();

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [platformTab, setPlatformTab] = useState<PlatformTab>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [showPlatformDetail, setShowPlatformDetail] = useState(false);
  const [bulkListing, setBulkListing] = useState(false);
  const [selectedStems, setSelectedStems] = useState<Set<string>>(new Set());
  const [bulkPlatform, setBulkPlatform] = useState<string>("airbit");
  const [expandedBeat, setExpandedBeat] = useState<string | null>(null);

  /* ── Upload task tracking ── */
  const [uploadTasks, setUploadTasks] = useState<UploadTask[]>([]);
  const [uploadSummary, setUploadSummary] = useState<{ uploading: number; done: number; failed: number }>({ uploading: 0, done: 0, failed: 0 });
  const pollRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const prevUploadingRef = useRef(0);

  /* ── Sync / Fix pending flags (declared here so polling effect can see them) ── */
  const [syncLinksPending, setSyncLinksPending] = useState(false);
  const [fixTitlesPending, setFixTitlesPending] = useState(false);

  // Poll for upload tasks when there's active uploading
  const fetchUploadTasks = useCallback(async () => {
    try {
      const data = await api.get<UploadTasksData>("/store-sync/upload-tasks");
      const all = [...data.active, ...data.completed].sort(
        (a, b) => (b.startedAt ?? 0) - (a.startedAt ?? 0)
      );
      setUploadTasks(all);
      setUploadSummary(data.summary);

      // Auto-refresh scan when uploads finish
      if (prevUploadingRef.current > 0 && data.summary.uploading === 0) {
        refetchScan();
        refetchPlatforms();
      }
      prevUploadingRef.current = data.summary.uploading;
    } catch { /* silent */ }
  }, [refetchScan, refetchPlatforms]);

  // Start/stop polling based on active uploads
  useEffect(() => {
    // Always do an initial fetch
    fetchUploadTasks();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const shouldPoll = uploadSummary.uploading > 0 || syncLinksPending || fixTitlesPending;
    if (shouldPoll) {
      if (!pollRef.current) {
        pollRef.current = setInterval(fetchUploadTasks, 3000);
      }
    } else {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = undefined;
      }
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [uploadSummary.uploading, syncLinksPending, fixTitlesPending, fetchUploadTasks]);

  // Also update from WebSocket messages
  useEffect(() => {
    if (!lastMessage) return;
    if (lastMessage.type === "progress" && lastMessage.phase && ["store_upload", "sync_links", "fix_titles"].includes(lastMessage.phase)) {
      // Got a real-time progress update — refresh tasks
      fetchUploadTasks();
    }
  }, [lastMessage, fetchUploadTasks]);

  const beats = scanData?.beats ?? [];
  const summary = scanData?.summary;
  const platforms = platformData?.platforms ?? [];
  const pricing = platformData?.pricing;

  /* ── Filtering ── */
  const filteredBeats = useMemo(() => {
    let list = beats;

    // Status filter
    if (statusFilter !== "all") {
      list = list.filter((b) => b.status === statusFilter);
    }

    // Platform filter
    if (platformTab !== "all") {
      list = list.filter((b) => {
        const ps = b.platforms[platformTab];
        if (!ps) return false;
        if (statusFilter === "missing_from_store") return !ps.listed && b.on_youtube;
        if (statusFilter === "synced") return ps.listed;
        return true;
      });
    }

    // Search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      list = list.filter((b) =>
        b.stem.toLowerCase().includes(q) ||
        b.title.toLowerCase().includes(q) ||
        b.artist.toLowerCase().includes(q) ||
        b.seo_artist.toLowerCase().includes(q)
      );
    }

    return list;
  }, [beats, statusFilter, platformTab, searchQuery]);

  /* ── Bulk select ── */
  const toggleStem = (stem: string) => {
    setSelectedStems((prev) => {
      const next = new Set(prev);
      if (next.has(stem)) next.delete(stem);
      else next.add(stem);
      return next;
    });
  };

  const selectAllMissing = (platform: string) => {
    const missing = beats.filter(
      (b) => b.on_youtube && !b.platforms[platform]?.listed
    );
    setSelectedStems(new Set(missing.map((b) => b.stem)));
    setBulkPlatform(platform);
  };

  const clearSelection = () => setSelectedStems(new Set());

  /* ── Bulk list ── */
  const handleBulkList = useCallback(async () => {
    if (selectedStems.size === 0) {
      toast("No beats selected", "error");
      return;
    }

    setBulkListing(true);
    try {
      const result = await api.post<{ listed: number; failed: number; async?: boolean; total?: number }>("/store-sync/bulk-list", {
        stems: Array.from(selectedStems),
        platform: bulkPlatform,
      });
      const pName = bulkPlatform.charAt(0).toUpperCase() + bulkPlatform.slice(1);
      if (result.async) {
        // Airbit: uploads run in background — start polling
        toast(`Uploading ${result.total} beats to ${pName} — track progress below`, "info");
        // Trigger immediate task poll
        setTimeout(fetchUploadTasks, 1000);
      } else {
        toast(`Listed ${result.listed} beats on ${pName} (${result.failed} failed)`, result.failed > 0 ? "error" : "success");
        refetchScan();
      }
      clearSelection();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Bulk list failed";
      toast(msg, "error");
    } finally {
      setBulkListing(false);
    }
  }, [selectedStems, bulkPlatform, toast, refetchScan, fetchUploadTasks]);

  /* ── Sync Links ── */

  // Derive active state from tasks: button stays lit while task is running
  const syncingLinks = syncLinksPending || uploadTasks.some(
    (t) => t.type === "sync_links" && t.status === "running"
  );
  const fixingTitles = fixTitlesPending || uploadTasks.some(
    (t) => t.type === "fix_titles" && t.status === "running"
  );

  // Track previous task states to detect completion → show toast
  const prevTasksRef = useRef<UploadTask[]>([]);
  useEffect(() => {
    const prev = prevTasksRef.current;
    prevTasksRef.current = uploadTasks;
    if (prev.length === 0) return;

    for (const task of uploadTasks) {
      if (task.status !== "running") {
        const prevTask = prev.find((t) => t.id === task.id);
        if (prevTask && prevTask.status === "running") {
          // Task just finished
          if (task.type === "sync_links") {
            setSyncLinksPending(false);
            if (task.status === "done") {
              toast(task.detail || "Purchase links synced", "success");
              refetchScan();
            } else {
              toast(task.detail || "Sync links failed", "error");
            }
          } else if (task.type === "fix_titles") {
            setFixTitlesPending(false);
            if (task.status === "done") {
              toast(task.detail || "Airbit titles fixed", "success");
              refetchScan();
            } else {
              toast(task.detail || "Fix titles failed", "error");
            }
          }
        }
      }
    }
  }, [uploadTasks, toast, refetchScan]);

  const handleSyncLinks = useCallback(async () => {
    setSyncLinksPending(true);
    try {
      const result = await api.post<{ status: string; task_id: string; message: string }>("/store-sync/sync-links", {});
      toast(result.message || "Syncing purchase links...", "info");
      // Start polling upload tasks for progress
      setTimeout(fetchUploadTasks, 2000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Sync links failed";
      toast(msg, "error");
      setSyncLinksPending(false);
    }
  }, [toast, fetchUploadTasks]);

  /* ── Fix Titles ── */

  const handleFixTitles = useCallback(async () => {
    setFixTitlesPending(true);
    try {
      const result = await api.post<{ status: string; task_id: string; message: string }>("/store-sync/fix-titles", {});
      toast(result.message || "Fixing Airbit titles...", "info");
      setTimeout(fetchUploadTasks, 2000);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Fix titles failed";
      toast(msg, "error");
      setFixTitlesPending(false);
    }
  }, [toast, fetchUploadTasks]);

  /* ── Rescan ── */
  const handleRescan = useCallback(() => {
    refetchScan();
    refetchPlatforms();
    toast("Rescanning stores...", "info");
  }, [refetchScan, refetchPlatforms, toast]);

  /* ── Status badge helpers ── */
  const statusColor = (status: string) => {
    switch (status) {
      case "synced": return "#00d362";
      case "missing_from_store": return "#ff4444";
      case "needs_update": return "#f5a623";
      case "missing_from_youtube": return "#38bdf8";
      case "not_uploaded": return "var(--text-tertiary)";
      default: return "var(--text-tertiary)";
    }
  };

  const statusLabel = (status: string) => {
    switch (status) {
      case "synced": return "Synced";
      case "missing_from_store": return "Not on Store";
      case "needs_update": return "Out of Sync";
      case "missing_from_youtube": return "Not on YT";
      case "not_uploaded": return "Nowhere";
      default: return status;
    }
  };

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="page-header">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2">
              <ShoppingBag size={20} className="text-accent" />
              Beat Store Sync
            </h1>
            <p className="page-subtitle">Sync your catalog across Airbit, BeatStars & YouTube</p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleFixTitles}
              disabled={fixingTitles}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold cursor-pointer transition-all"
              style={{
                background: fixingTitles ? "#f5a623" : "#f5a62315",
                color: fixingTitles ? "#fff" : "#f5a623",
                border: `1px solid ${fixingTitles ? "#f5a623" : "#f5a62350"}`,
                opacity: fixingTitles ? 0.8 : 1,
              }}
            >
              {fixingTitles ? <Loader2 size={13} className="animate-spin" /> : <Tag size={13} />}
              {fixingTitles ? "Fixing..." : "Fix Titles"}
            </button>
            <button
              onClick={handleSyncLinks}
              disabled={syncingLinks}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold cursor-pointer transition-all"
              style={{
                background: syncingLinks ? "var(--accent)" : "#22c55e15",
                color: syncingLinks ? "#fff" : "#22c55e",
                border: `1px solid ${syncingLinks ? "var(--accent)" : "#22c55e50"}`,
                opacity: syncingLinks ? 0.8 : 1,
              }}
            >
              {syncingLinks ? <Loader2 size={13} className="animate-spin" /> : <Link2 size={13} />}
              {syncingLinks ? "Syncing..." : "Sync Links"}
            </button>
            <button
              onClick={handleRescan}
              disabled={scanning}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold cursor-pointer transition-all"
              style={{
                background: "var(--accent-muted)",
                color: "var(--accent)",
                border: "1px solid var(--accent)",
                opacity: scanning ? 0.6 : 1,
              }}
            >
              {scanning ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              {scanning ? "Scanning..." : "Rescan"}
            </button>
          </div>
        </div>
      </div>

      {/* ===================================================================
          PLATFORM CONNECTIONS
          =================================================================== */}
      <div
        className="mb-5 p-5 rounded-2xl"
        style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="section-header">
            <span className="flex items-center gap-2"><Link2 size={15} /> Platforms</span>
          </h2>
          <button
            onClick={() => setShowPlatformDetail(!showPlatformDetail)}
            className="text-[10px] font-semibold px-2 py-0.5 rounded-md cursor-pointer transition-all"
            style={{ background: "var(--bg-hover)", color: "var(--text-tertiary)" }}
          >
            {showPlatformDetail ? "Less" : "Details"}
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {platforms.map((p) => {
            const stats = summary?.platforms?.[p.id];
            return (
              <div
                key={p.id}
                className="p-4 rounded-xl transition-all"
                style={{
                  background: p.connected ? `${p.color}08` : "var(--bg-hover)",
                  border: `1px solid ${p.connected ? `${p.color}30` : "var(--border)"}`,
                }}
              >
                <div className="flex items-center gap-3 mb-3">
                  <div
                    className="w-10 h-10 rounded-xl flex items-center justify-center"
                    style={{ background: `${p.color}15` }}
                  >
                    {p.id === "airbit" ? (
                      <ShoppingBag size={18} style={{ color: p.color }} />
                    ) : (
                      <Star size={18} style={{ color: p.color }} />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-bold text-foreground">{p.name}</p>
                    {p.connected ? (
                      <div className="flex items-center gap-1.5">
                        <CheckCircle2 size={10} style={{ color: p.color }} />
                        <span className="text-[10px] font-semibold" style={{ color: p.color }}>Connected</span>
                      </div>
                    ) : (
                      <div className="flex items-center gap-1.5">
                        <Link2Off size={10} className="text-text-tertiary" />
                        <span className="text-[10px] font-semibold text-text-tertiary">Not Connected</span>
                      </div>
                    )}
                  </div>
                  {stats && (
                    <div className="text-right">
                      <p className="text-lg font-bold tabular-nums" style={{ color: p.color }}>{stats.listed}</p>
                      <p className="text-[9px] text-text-tertiary uppercase">Listed</p>
                    </div>
                  )}
                </div>

                {/* Stats bar */}
                {stats && stats.total_on_youtube > 0 && (
                  <div className="mb-2">
                    <div className="flex items-center justify-between text-[10px] text-text-tertiary mb-1">
                      <span>{stats.listed} of {stats.total_on_youtube} YouTube beats listed</span>
                      <span className="font-bold tabular-nums" style={{ color: stats.not_listed > 0 ? "#ff4444" : p.color }}>
                        {stats.not_listed > 0 ? `${stats.not_listed} missing` : "All synced"}
                      </span>
                    </div>
                    <div className="h-2 rounded-full overflow-hidden" style={{ background: "var(--bg-primary)" }}>
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: `${Math.round((stats.listed / Math.max(stats.total_on_youtube, 1)) * 100)}%`,
                          background: p.color,
                        }}
                      />
                    </div>
                  </div>
                )}

                {showPlatformDetail && (
                  <div className="mt-3 pt-3 space-y-1.5" style={{ borderTop: `1px solid ${p.color}20` }}>
                    {p.email && (
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="text-text-tertiary">Email:</span>
                        <span className="text-foreground font-medium">{p.email}</span>
                      </div>
                    )}
                    <div className="flex items-center gap-2 text-[11px]">
                      <span className="text-text-tertiary">API Key:</span>
                      <span className={`font-medium ${p.api_key_set ? "text-foreground" : "text-text-tertiary"}`}>
                        {p.api_key_set ? "Set" : "Not set"}
                      </span>
                    </div>
                    {p.store_url && (
                      <div className="flex items-center gap-2 text-[11px]">
                        <span className="text-text-tertiary">Store:</span>
                        <span className="text-accent font-medium truncate">{p.store_url}</span>
                      </div>
                    )}
                    <a
                      href="/settings"
                      className="inline-flex items-center gap-1.5 text-[10px] font-semibold mt-1 transition-all"
                      style={{ color: p.color }}
                    >
                      Manage Connection <ArrowRight size={10} />
                    </a>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Pricing summary */}
        {pricing && showPlatformDetail && (
          <div
            className="mt-3 p-3.5 rounded-xl"
            style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
          >
            <div className="flex items-center gap-2 mb-2">
              <DollarSign size={13} className="text-text-tertiary" />
              <span className="text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">Default Pricing</span>
            </div>
            <div className="flex gap-4 text-xs">
              <div>
                <span className="text-text-tertiary">Basic: </span>
                <span className="font-bold text-foreground">${pricing.basic_license}</span>
              </div>
              <div>
                <span className="text-text-tertiary">Premium: </span>
                <span className="font-bold text-foreground">${pricing.premium_license}</span>
              </div>
              <div>
                <span className="text-text-tertiary">Exclusive: </span>
                <span className="font-bold text-foreground">${pricing.exclusive_license}</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ===================================================================
          LIVE TASK TRACKER
          =================================================================== */}
      {uploadTasks.length > 0 && (
        <div
          className="mb-5 p-5 rounded-2xl"
          style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
        >
          <div className="flex items-center justify-between mb-3">
            <h2 className="section-header">
              <span className="flex items-center gap-2">
                <Upload size={15} className={uploadSummary.uploading > 0 ? "text-accent animate-pulse" : "text-text-tertiary"} />
                Tasks
                {uploadSummary.uploading > 0 && (
                  <span className="ml-1 px-1.5 py-0.5 rounded-full text-[9px] font-bold tabular-nums" style={{ background: "var(--accent-muted)", color: "var(--accent)" }}>
                    {uploadSummary.uploading} active
                  </span>
                )}
              </span>
            </h2>
            {/* Summary badges */}
            <div className="flex items-center gap-2 text-[10px] font-bold tabular-nums">
              {uploadSummary.done > 0 && (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full" style={{ background: "#00d36215", color: "#00d362" }}>
                  <CheckCircle2 size={10} /> {uploadSummary.done}
                </span>
              )}
              {uploadSummary.failed > 0 && (
                <span className="flex items-center gap-1 px-2 py-0.5 rounded-full" style={{ background: "#ff444415", color: "#ff4444" }}>
                  <XCircle size={10} /> {uploadSummary.failed}
                </span>
              )}
            </div>
          </div>

          {/* Overall progress bar — only for bulk uploads (not sync/fix) */}
          {uploadTasks.filter((t) => t.type === "store_upload" && t.status === "running").length > 1 && (
            <div className="mb-3">
              <div className="flex items-center justify-between text-[10px] text-text-tertiary mb-1">
                <span>Uploading to Airbit...</span>
                <span className="font-bold tabular-nums">
                  {uploadSummary.done} / {uploadSummary.done + uploadSummary.uploading + uploadSummary.failed} done
                </span>
              </div>
              <div className="h-2 rounded-full overflow-hidden" style={{ background: "var(--bg-primary)" }}>
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{
                    width: `${Math.round((uploadSummary.done / Math.max(uploadSummary.done + uploadSummary.uploading + uploadSummary.failed, 1)) * 100)}%`,
                    background: "var(--accent)",
                  }}
                />
              </div>
            </div>
          )}

          {/* Task list */}
          <div className="max-h-[280px] overflow-y-auto space-y-1 pr-1" style={{ scrollbarWidth: "thin" }}>
            {uploadTasks.slice(0, 50).map((task) => {
              // Determine task appearance based on type
              const isSyncOrFix = task.type === "sync_links" || task.type === "fix_titles";
              const taskColor = task.type === "sync_links" ? "#22c55e" : task.type === "fix_titles" ? "#f5a623" : undefined;
              const taskLabel =
                task.type === "sync_links" ? "Sync Links" :
                task.type === "fix_titles" ? "Fix Titles" :
                undefined;

              return (
                <div
                  key={task.id}
                  className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs"
                  style={{
                    background: task.status === "running"
                      ? isSyncOrFix ? `${taskColor}10` : "var(--accent-muted)"
                      : "var(--bg-hover)",
                    border: task.status === "running"
                      ? `1px solid ${isSyncOrFix ? `${taskColor}50` : "var(--accent)"}`
                      : "1px solid transparent",
                  }}
                >
                  {/* Status icon */}
                  {task.status === "running" ? (
                    <Loader2 size={12} className="animate-spin flex-shrink-0" style={{ color: taskColor || "var(--accent)" }} />
                  ) : task.status === "done" ? (
                    <CheckCircle2 size={12} className="flex-shrink-0" style={{ color: "#00d362" }} />
                  ) : (
                    <XCircle size={12} className="flex-shrink-0" style={{ color: "#ff4444" }} />
                  )}

                  {/* Type badge for sync/fix tasks */}
                  {taskLabel && (
                    <span
                      className="text-[8px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide flex-shrink-0"
                      style={{
                        background: `${taskColor}15`,
                        color: taskColor,
                      }}
                    >
                      {taskLabel}
                    </span>
                  )}

                  {/* Task title / detail */}
                  <span className={`flex-1 min-w-0 truncate ${task.status === "running" ? "font-semibold text-foreground" : "text-text-secondary"}`}>
                    {isSyncOrFix
                      ? (task.detail || task.title)
                      : task.title.replace(/^Airbit:\s*/, "")}
                  </span>

                  {/* Progress or status */}
                  {task.status === "running" ? (
                    <span className="text-[10px] font-bold tabular-nums flex-shrink-0" style={{ color: taskColor || "var(--accent)" }}>
                      {isSyncOrFix
                        ? `${task.progress}%`
                        : (task.detail?.replace(/^Uploading to Airbit\.\.\.\s*/, "").replace(/^Queued.*/, "queued") || `${task.progress}%`)}
                    </span>
                  ) : task.status === "done" ? (
                    <span className="text-[10px] font-bold flex-shrink-0" style={{ color: "#00d362" }}>
                      {isSyncOrFix ? (task.detail || "done") : "done"}
                    </span>
                  ) : (
                    <span className="text-[10px] font-bold flex-shrink-0" style={{ color: "#ff4444" }}>failed</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ===================================================================
          SYNC OVERVIEW — Summary cards
          =================================================================== */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5 mb-5">
          {[
            { label: "Total Beats", value: summary.total_beats, color: "var(--text-primary)" },
            { label: "On YouTube", value: summary.on_youtube, color: "#ff0000" },
            { label: "Synced", value: summary.synced, color: "#00d362" },
            { label: "Missing", value: summary.missing_from_store, color: "#ff4444" },
            { label: "Out of Sync", value: summary.needs_update, color: "#f5a623" },
            { label: "Nowhere", value: summary.not_uploaded, color: "var(--text-tertiary)" },
          ].map((card) => (
            <div
              key={card.label}
              className="p-3.5 rounded-xl text-center"
              style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
            >
              <p className="text-xl font-bold tabular-nums" style={{ color: card.color }}>{card.value}</p>
              <p className="text-[9px] font-semibold uppercase tracking-wider text-text-tertiary mt-0.5">{card.label}</p>
            </div>
          ))}
        </div>
      )}

      {/* ===================================================================
          BEAT LIST — Filter + Search + Table
          =================================================================== */}
      <div
        className="mb-8 rounded-2xl overflow-hidden"
        style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
      >
        {/* Toolbar */}
        <div className="p-4" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="flex flex-wrap items-center gap-3">
            {/* Status filter tabs */}
            <div className="flex gap-1">
              {STATUS_TABS.map((tab) => {
                const active = statusFilter === tab.key;
                const count = tab.key === "all"
                  ? beats.length
                  : beats.filter((b) => b.status === tab.key).length;
                return (
                  <button
                    key={tab.key}
                    onClick={() => setStatusFilter(tab.key)}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-semibold cursor-pointer transition-all"
                    style={{
                      background: active ? `${tab.color}15` : "transparent",
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

            {/* Platform filter */}
            <div className="flex gap-1 ml-auto">
              {([
                { key: "all" as PlatformTab, label: "All Stores", color: "var(--text-secondary)" },
                { key: "airbit" as PlatformTab, label: "Airbit", color: "#22c55e" },
                { key: "beatstars" as PlatformTab, label: "BeatStars", color: "#fbbf24" },
              ]).map((tab) => {
                const active = platformTab === tab.key;
                return (
                  <button
                    key={tab.key}
                    onClick={() => setPlatformTab(tab.key)}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-semibold cursor-pointer transition-all"
                    style={{
                      background: active ? `${tab.color}15` : "transparent",
                      color: active ? tab.color : "var(--text-tertiary)",
                      border: `1px solid ${active ? `${tab.color}40` : "transparent"}`,
                    }}
                  >
                    {tab.key === "airbit" && <ShoppingBag size={10} />}
                    {tab.key === "beatstars" && <Star size={10} />}
                    {tab.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Search + Bulk Actions */}
          <div className="flex items-center gap-2.5 mt-3">
            <SearchInput
              value={searchQuery}
              onChange={setSearchQuery}
              placeholder="Search beats..."
              size="sm"
              className="flex-1"
            />

            {/* Bulk select buttons */}
            {platforms.filter((p) => p.connected).map((p) => (
              <button
                key={p.id}
                onClick={() => selectAllMissing(p.id)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-[10px] font-semibold cursor-pointer transition-all whitespace-nowrap"
                style={{
                  background: `${p.color}10`,
                  color: p.color,
                  border: `1px solid ${p.color}30`,
                }}
              >
                <Upload size={10} />
                Select Missing ({summary?.platforms?.[p.id]?.not_listed ?? 0})
              </button>
            ))}
          </div>

          {/* Selection bar */}
          {selectedStems.size > 0 && (
            <div
              className="flex items-center gap-3 mt-3 p-3 rounded-xl"
              style={{ background: "var(--accent-muted)", border: "1px solid var(--accent)" }}
            >
              <span className="text-xs font-semibold text-accent">
                {selectedStems.size} beat{selectedStems.size !== 1 ? "s" : ""} selected
              </span>
              <div className="flex-1" />

              {/* Platform selector for bulk */}
              <div className="flex gap-1">
                {platforms.filter((p) => p.connected).map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setBulkPlatform(p.id)}
                    className="px-2.5 py-1 rounded-md text-[10px] font-semibold cursor-pointer transition-all"
                    style={{
                      background: bulkPlatform === p.id ? `${p.color}20` : "transparent",
                      color: bulkPlatform === p.id ? p.color : "var(--text-tertiary)",
                      border: `1px solid ${bulkPlatform === p.id ? `${p.color}50` : "transparent"}`,
                    }}
                  >
                    {p.name}
                  </button>
                ))}
              </div>

              <button
                onClick={handleBulkList}
                disabled={bulkListing}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-bold cursor-pointer transition-all"
                style={{
                  background: "var(--accent)",
                  color: "#fff",
                  opacity: bulkListing ? 0.6 : 1,
                }}
              >
                {bulkListing ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
                {bulkListing ? "Listing..." : `List on ${bulkPlatform.charAt(0).toUpperCase() + bulkPlatform.slice(1)}`}
              </button>
              <button
                onClick={clearSelection}
                className="p-1.5 rounded-md cursor-pointer"
                style={{ color: "var(--text-tertiary)" }}
              >
                <X size={14} />
              </button>
            </div>
          )}
        </div>

        {/* Beat rows */}
        <div className="divide-y" style={{ borderColor: "var(--border)" }}>
          {filteredBeats.length === 0 && (
            <div className="text-center py-12">
              <ShoppingBag size={28} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.3 }} />
              <p className="text-sm text-text-tertiary">
                {beats.length === 0 ? "Run a scan to see your sync status" : "No beats match your filters"}
              </p>
            </div>
          )}

          {filteredBeats.map((beat) => {
            const isSelected = selectedStems.has(beat.stem);
            const isExpanded = expandedBeat === beat.stem;
            const color = statusColor(beat.status);

            return (
              <div key={beat.stem}>
                <div
                  className="flex items-center gap-3 px-4 py-3 transition-all cursor-pointer"
                  style={{
                    background: isSelected ? "var(--accent-muted)" : "transparent",
                  }}
                  onClick={() => setExpandedBeat(isExpanded ? null : beat.stem)}
                >
                  {/* Checkbox */}
                  <button
                    onClick={(e) => { e.stopPropagation(); toggleStem(beat.stem); }}
                    className="w-4 h-4 rounded flex items-center justify-center flex-shrink-0 cursor-pointer"
                    style={{
                      background: isSelected ? "var(--accent)" : "transparent",
                      border: `1.5px solid ${isSelected ? "var(--accent)" : "var(--border)"}`,
                    }}
                  >
                    {isSelected && <CheckCircle2 size={10} color="#fff" />}
                  </button>

                  {/* Beat info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-xs font-semibold text-foreground truncate">
                        {beat.beat_name || beat.stem}
                      </p>
                      {beat.lane && (
                        <span
                          className="text-[8px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide flex-shrink-0"
                          style={{
                            background: `${beat.lane === "breakfast" ? "#f5a623" : beat.lane === "lunch" ? "#00d362" : "#b44eff"}15`,
                            color: beat.lane === "breakfast" ? "#f5a623" : beat.lane === "lunch" ? "#00d362" : "#b44eff",
                          }}
                        >
                          {beat.lane.slice(0, 1)}
                        </span>
                      )}
                    </div>
                    <p className="text-[10px] text-text-tertiary truncate">
                      {beat.seo_artist || beat.artist || beat.stem}
                      {beat.bpm ? ` · ${beat.bpm} BPM` : ""}
                      {beat.key ? ` · ${beat.key}` : ""}
                    </p>
                  </div>

                  {/* YouTube badge */}
                  {beat.on_youtube ? (
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <Youtube size={11} style={{ color: "#ff0000" }} />
                      <span className="text-[9px] font-semibold" style={{ color: "#ff0000" }}>YT</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1 flex-shrink-0 opacity-30">
                      <Youtube size={11} />
                      <span className="text-[9px] font-semibold">YT</span>
                    </div>
                  )}

                  {/* Platform badges */}
                  {Object.entries(beat.platforms).map(([pid, ps]) => {
                    const pColor = pid === "airbit" ? "#22c55e" : "#fbbf24";
                    return (
                      <div
                        key={pid}
                        className="flex items-center gap-1 px-1.5 py-0.5 rounded flex-shrink-0"
                        style={{
                          background: ps.listed ? `${pColor}12` : "transparent",
                          border: `1px solid ${ps.listed ? `${pColor}30` : "var(--border)"}`,
                        }}
                      >
                        {pid === "airbit" ? <ShoppingBag size={9} style={{ color: ps.listed ? pColor : "var(--text-tertiary)" }} /> :
                         <Star size={9} style={{ color: ps.listed ? pColor : "var(--text-tertiary)" }} />}
                        <span
                          className="text-[8px] font-bold uppercase"
                          style={{ color: ps.listed ? pColor : "var(--text-tertiary)" }}
                        >
                          {ps.listed ? "Listed" : "---"}
                        </span>
                      </div>
                    );
                  })}

                  {/* Status badge */}
                  <span
                    className="text-[9px] font-bold px-2 py-0.5 rounded-full whitespace-nowrap flex-shrink-0"
                    style={{ background: `${color}15`, color }}
                  >
                    {statusLabel(beat.status)}
                  </span>

                  {/* Expand chevron */}
                  {isExpanded ? <ChevronUp size={13} className="text-text-tertiary" /> : <ChevronDown size={13} className="text-text-tertiary" />}
                </div>

                {/* Expanded detail */}
                {isExpanded && (
                  <div
                    className="px-4 pb-4 pt-1"
                    style={{ background: "var(--bg-hover)" }}
                  >
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                      {/* YouTube info */}
                      <div className="p-3 rounded-xl" style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}>
                        <div className="flex items-center gap-2 mb-2">
                          <Youtube size={13} style={{ color: "#ff0000" }} />
                          <span className="text-[11px] font-bold text-foreground">YouTube</span>
                        </div>
                        {beat.on_youtube ? (
                          <>
                            <p className="text-[10px] text-text-secondary truncate">{beat.title}</p>
                            {beat.youtube_url && (
                              <a
                                href={beat.youtube_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-[10px] font-semibold mt-1.5"
                                style={{ color: "#ff0000" }}
                              >
                                View on YouTube <ExternalLink size={9} />
                              </a>
                            )}
                          </>
                        ) : (
                          <p className="text-[10px] text-text-tertiary">Not uploaded</p>
                        )}
                      </div>

                      {/* Platform details */}
                      {Object.entries(beat.platforms).map(([pid, ps]) => {
                        const pColor = pid === "airbit" ? "#22c55e" : "#fbbf24";
                        const pName = pid === "airbit" ? "Airbit" : "BeatStars";
                        return (
                          <div
                            key={pid}
                            className="p-3 rounded-xl"
                            style={{ background: "var(--bg-primary)", border: `1px solid ${ps.listed ? `${pColor}30` : "var(--border)"}` }}
                          >
                            <div className="flex items-center gap-2 mb-2">
                              {pid === "airbit" ? <ShoppingBag size={13} style={{ color: pColor }} /> : <Star size={13} style={{ color: pColor }} />}
                              <span className="text-[11px] font-bold text-foreground">{pName}</span>
                              {ps.listed ? (
                                <CheckCircle2 size={11} style={{ color: pColor }} />
                              ) : (
                                <XCircle size={11} className="text-text-tertiary" />
                              )}
                            </div>
                            {ps.listed ? (
                              <>
                                {ps.uploaded_at && (
                                  <p className="text-[10px] text-text-tertiary">
                                    Listed {new Date(ps.uploaded_at).toLocaleDateString()}
                                  </p>
                                )}
                                {ps.url && (
                                  <a
                                    href={ps.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1 text-[10px] font-semibold mt-1.5"
                                    style={{ color: pColor }}
                                  >
                                    View Listing <ExternalLink size={9} />
                                  </a>
                                )}
                                {ps.synced === false && (
                                  <div className="flex items-center gap-1 mt-1.5">
                                    <AlertTriangle size={10} style={{ color: "#f5a623" }} />
                                    <span className="text-[10px] font-semibold" style={{ color: "#f5a623" }}>
                                      Metadata out of sync
                                    </span>
                                  </div>
                                )}
                              </>
                            ) : (
                              <p className="text-[10px] text-text-tertiary">Not listed on {pName}</p>
                            )}
                          </div>
                        );
                      })}
                    </div>

                    {/* Tags */}
                    {beat.tags.length > 0 && (
                      <div className="flex items-center gap-2 mt-3">
                        <Tag size={10} className="text-text-tertiary" />
                        <div className="flex flex-wrap gap-1">
                          {beat.tags.map((tag) => (
                            <span
                              key={tag}
                              className="text-[9px] font-medium px-1.5 py-0.5 rounded"
                              style={{ background: "var(--bg-primary)", color: "var(--text-secondary)", border: "1px solid var(--border)" }}
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Footer count */}
        <div className="px-4 py-3 text-[10px] text-text-tertiary text-center" style={{ borderTop: "1px solid var(--border)" }}>
          Showing {filteredBeats.length} of {beats.length} beats
        </div>
      </div>
    </div>
  );
}
