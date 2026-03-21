"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  Shield,
  Film,
  Image as ImageIcon,
  X,
  Loader2,
  Trash2,
  Flag,
  Play,
  Clock,
  HardDrive,
  Monitor,
  Smartphone,
  ScanLine,
  AlertCircle,
  CheckCircle2,
  Music,
  ExternalLink,
  Upload,
  User,
  Video,
  FolderOpen,
} from "lucide-react";
import { useFetch, api } from "@/hooks/useApi";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useToast } from "@/components/ToastProvider";
import SearchInput from "@/components/ui/SearchInput";
import StatCard from "@/components/StatCard";
import AuthImage from "@/components/AuthImage";
import CopyrightBadge from "@/components/CopyrightBadge";
import ConfirmDialog from "@/components/ConfirmDialog";
import type { Beat } from "@/types/beat";

/* ── Types ────────────────────────────────────────────────────── */

interface MediaItem {
  path: string;
  name: string;
  folder: string;
  size_mb: number;
  source?: string;
  resolution?: string;
  width?: number;
  height?: number;
  duration?: number;
  orientation?: string;
}

interface BrowseResult {
  clips: MediaItem[];
  images: MediaItem[];
}

interface CopyrightFlags {
  flagged: Record<string, { risk: string; reasons: string[]; flagged_at?: string }>;
  scan_results: Record<string, { risk: string; reasons: string[]; scanned_at?: string }>;
}

interface MediaDetail {
  filename: string;
  type: string;
  size_mb: number;
  resolution?: string;
  width?: number;
  height?: number;
  duration?: number;
  orientation?: string;
  used_by: string[];
  copyright: { risk: string; reasons: string[] };
}

interface ScanResult {
  summary: { total: number; safe: number; caution: number; danger: number; flagged: number };
  results: Array<{ filename: string; risk: string; reasons: string[] }>;
}

type MainTab = "library" | "renders";
type FilterTab = "all" | "clips" | "images" | "flagged" | "safe";
type SortBy = "name" | "risk" | "size";
type Risk = "safe" | "caution" | "danger" | "flagged" | "unknown";

/* ── Helpers ──────────────────────────────────────────────────── */

/** Build a URL with the JWT token as query param — lets <video> stream natively */
function authUrl(path: string): string {
  const token = typeof window !== "undefined" ? localStorage.getItem("fy3-token") : null;
  return token ? `${path}?token=${encodeURIComponent(token)}` : path;
}

function getRisk(name: string, flags: CopyrightFlags | null, path?: string): { risk: Risk; reasons: string[] } {
  if (!flags) return { risk: "unknown", reasons: [] };
  // Check by name, path, and relative path (subfolder clips stored both ways)
  const keys = [name];
  if (path && path !== name) keys.push(path);
  for (const key of keys) {
    const flagged = flags.flagged?.[key];
    if (flagged) return { risk: flagged.risk as Risk, reasons: flagged.reasons };
    const scanned = flags.scan_results?.[key];
    if (scanned) return { risk: scanned.risk as Risk, reasons: scanned.reasons };
  }
  return { risk: "unknown", reasons: [] };
}

const RISK_ORDER: Record<Risk, number> = { danger: 0, flagged: 1, caution: 2, unknown: 3, safe: 4 };

function isClip(name: string): boolean {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  return ["mp4", "mov"].includes(ext);
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}:${s.toString().padStart(2, "0")}` : `${s}s`;
}

/** Extract artist tag from path — folder name or first part of filename */
function guessArtist(item: MediaItem): string {
  if (item.folder) return item.folder;
  const base = item.name.replace(/\.[^.]+$/, "");
  const parts = base.split(/[_\-]/);
  if (parts.length >= 2) return parts[0];
  return "";
}

/** Group items by artist tag */
function groupByArtist(items: MediaItem[]): Record<string, MediaItem[]> {
  const groups: Record<string, MediaItem[]> = {};
  for (const item of items) {
    const artist = guessArtist(item) || "Uncategorized";
    if (!groups[artist]) groups[artist] = [];
    groups[artist].push(item);
  }
  return groups;
}

/* ── Page ─────────────────────────────────────────────────────── */

export default function MediaManagerPage() {
  const { toast } = useToast();
  const router = useRouter();
  const searchParams = useSearchParams();
  const stemParam = searchParams.get("stem");

  /* ── Data fetching ── */
  const { data: media, loading: mediaLoading, refetch: refetchMedia } = useFetch<BrowseResult>("/media/browse");
  const { data: flags, refetch: refetchFlags } = useFetch<CopyrightFlags>("/copyright/flags");
  const { data: beats, loading: beatsLoading } = useFetch<Beat[]>("/beats");

  /* ── State ── */
  const [mainTab, setMainTab] = useState<MainTab>("library");
  const [filter, setFilter] = useState<FilterTab>("all");
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortBy>("name");
  const [scanning, setScanning] = useState(false);
  const [previewItem, setPreviewItem] = useState<MediaItem | null>(null);
  const [previewDetail, setPreviewDetail] = useState<MediaDetail | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [videoBlobUrl, setVideoBlobUrl] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [flagTarget, setFlagTarget] = useState<string | null>(null);
  const [flagReason, setFlagReason] = useState("");
  const [flagging, setFlagging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [groupByArtistMode, setGroupByArtistMode] = useState(false);
  const [renderSearch, setRenderSearch] = useState("");
  const [renderVideoStem, setRenderVideoStem] = useState<string | null>(null);
  const [renderVideoUrl, setRenderVideoUrl] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  /* ── All media items combined ── */
  const allItems: MediaItem[] = useMemo(() => {
    if (!media) return [];
    return [...media.clips, ...media.images];
  }, [media]);

  /* ── Rendered beats ── */
  const renderedBeats = useMemo(() => {
    if (!beats) return [];
    return beats.filter((b) => b.rendered);
  }, [beats]);

  const filteredRenders = useMemo(() => {
    if (!renderSearch.trim()) return renderedBeats;
    const q = renderSearch.toLowerCase();
    return renderedBeats.filter(
      (b) =>
        (b.beat_name || "").toLowerCase().includes(q) ||
        b.stem.toLowerCase().includes(q) ||
        b.title.toLowerCase().includes(q)
    );
  }, [renderedBeats, renderSearch]);

  /* ── Filtered + sorted media items ── */
  const filteredItems = useMemo(() => {
    let items = allItems;

    if (filter === "clips") items = items.filter((i) => isClip(i.name));
    else if (filter === "images") items = items.filter((i) => !isClip(i.name));
    else if (filter === "flagged") {
      items = items.filter((i) => {
        const { risk } = getRisk(i.name, flags, i.path);
        return risk === "danger" || risk === "flagged" || risk === "caution";
      });
    } else if (filter === "safe") {
      items = items.filter((i) => getRisk(i.name, flags, i.path).risk === "safe");
    }

    if (search.trim()) {
      const q = search.toLowerCase();
      items = items.filter((i) => i.name.toLowerCase().includes(q) || i.path.toLowerCase().includes(q));
    }

    items = [...items].sort((a, b) => {
      if (sortBy === "risk") {
        const rA = RISK_ORDER[getRisk(a.name, flags, a.path).risk] ?? 3;
        const rB = RISK_ORDER[getRisk(b.name, flags, b.path).risk] ?? 3;
        return rA - rB;
      }
      if (sortBy === "size") return (b.size_mb ?? 0) - (a.size_mb ?? 0);
      return a.name.localeCompare(b.name);
    });

    return items;
  }, [allItems, filter, search, sortBy, flags]);

  /* ── Stats ── */
  const totalClips = media?.clips.length ?? 0;
  const totalImages = media?.images.length ?? 0;
  const flaggedCount = useMemo(() => {
    if (!flags) return 0;
    return allItems.filter((i) => {
      const { risk } = getRisk(i.name, flags, i.path);
      return risk === "danger" || risk === "flagged" || risk === "caution";
    }).length;
  }, [allItems, flags]);
  const safeCount = useMemo(() => {
    if (!flags) return 0;
    return allItems.filter((i) => getRisk(i.name, flags, i.path).risk === "safe").length;
  }, [allItems, flags]);

  /* ── Stem param → auto-open that beat's clip ── */
  const stemHandled = useRef(false);
  useEffect(() => {
    if (!stemParam || !media || stemHandled.current) return;
    const clipName = `${stemParam}.mp4`;
    const item = allItems.find((i) => i.name === clipName || i.path.includes(stemParam));
    if (item) {
      stemHandled.current = true;
      setPreviewItem(item);
      setPreviewDetail(null);
      setPreviewLoading(true);

      // Direct URL streaming — no blob download needed
      if (isClip(item.name)) {
        setVideoBlobUrl(authUrl(`/files/images/${item.path}`));
      } else {
        setVideoBlobUrl(null);
      }

      api.get<MediaDetail>(`/media/detail/${item.path}`)
        .then((detail) => setPreviewDetail(detail))
        .catch(() => {})
        .finally(() => setPreviewLoading(false));
    }
  }, [stemParam, media, allItems]);

  /* ── Scan progress ── */
  const [scanProgress, setScanProgress] = useState<{ current: number; total: number } | null>(null);
  const { lastMessage } = useWebSocket();

  /* ── Listen for WebSocket scan events ── */
  useEffect(() => {
    if (!lastMessage) return;

    if (lastMessage.type === "copyright_scan_progress") {
      setScanProgress({
        current: (lastMessage as Record<string, unknown>).current as number,
        total: (lastMessage as Record<string, unknown>).total as number,
      });
    } else if (lastMessage.type === "copyright_scan_complete") {
      setScanning(false);
      setScanProgress(null);
      const s = (lastMessage as Record<string, unknown>).summary as Record<string, number>;
      if (s) {
        toast(`Scan complete: ${s.total} clips (${s.safe} safe, ${s.caution} caution, ${s.danger} danger)`, "success");
      } else {
        toast("Scan complete", "success");
      }
      refetchFlags();
    } else if (lastMessage.type === "copyright_scan_error") {
      setScanning(false);
      setScanProgress(null);
      toast(`Scan failed: ${(lastMessage as Record<string, unknown>).error ?? "Unknown error"}`, "error");
    }
  }, [lastMessage, toast, refetchFlags]);

  /* ── Scan all ── */
  const handleScanAll = useCallback(async () => {
    setScanning(true);
    setScanProgress(null);
    try {
      const result = await api.get<{ status: string; message: string }>("/copyright/scan");
      if (result.status === "already_running") {
        toast("Scan already in progress", "info");
      } else {
        toast("Copyright scan started...", "info");
      }
    } catch (e) {
      toast(`Scan failed: ${e instanceof Error ? e.message : "Unknown error"}`, "error");
      setScanning(false);
    }
  }, [toast]);

  /* ── Upload ── */
  const handleUpload = useCallback(async (files: FileList) => {
    setUploading(true);
    let successCount = 0;

    for (const file of Array.from(files)) {
      try {
        const formData = new FormData();
        formData.append("file", file);

        const token = typeof window !== "undefined" ? localStorage.getItem("fy3-token") : null;
        const res = await fetch("/api/media/upload", {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: formData,
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: "Upload failed" }));
          throw new Error(err.detail || "Upload failed");
        }
        successCount++;
      } catch (e) {
        toast(`Failed: ${file.name} — ${e instanceof Error ? e.message : "Error"}`, "error");
      }
    }

    if (successCount > 0) {
      toast(`Uploaded ${successCount} file${successCount !== 1 ? "s" : ""}`, "success");
      refetchMedia();
    }
    setUploading(false);
  }, [toast, refetchMedia]);

  /* ── Open preview — uses direct URL streaming for videos ── */
  const openPreview = useCallback(async (item: MediaItem) => {
    setPreviewItem(item);
    setPreviewDetail(null);
    setPreviewLoading(true);

    // Set video URL directly for streaming (no blob download)
    if (isClip(item.name)) {
      setVideoBlobUrl(authUrl(`/files/images/${item.path}`));
    } else {
      setVideoBlobUrl(null);
    }

    // Fetch metadata in parallel
    try {
      const detail = await api.get<MediaDetail>(`/media/detail/${item.path}`);
      setPreviewDetail(detail);
    } catch {
      /* non-critical */
    } finally {
      setPreviewLoading(false);
    }
  }, []); // Stable

  /* ── Close preview ── */
  const closePreview = useCallback(() => {
    setPreviewItem(null);
    setPreviewDetail(null);
    setVideoBlobUrl(null);
  }, []);

  /* ── Open render video — uses direct URL streaming (no blob download) ── */
  const openRenderVideo = useCallback((stem: string) => {
    setRenderVideoStem(stem);
    setRenderVideoUrl(authUrl(`/files/output/${stem}.mp4`));
  }, []);

  /* ── Close render video ── */
  const closeRenderVideo = useCallback(() => {
    setRenderVideoStem(null);
    setRenderVideoUrl(null);
  }, []);

  /* ── Delete media ── */
  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api.del(`/media/${deleteTarget}`);
      toast(`Deleted ${deleteTarget}`, "success");
      setDeleteTarget(null);
      closePreview();
      refetchMedia();
      refetchFlags();
    } catch (e) {
      toast(`Delete failed: ${e instanceof Error ? e.message : "Unknown error"}`, "error");
    } finally {
      setDeleting(false);
    }
  }, [deleteTarget, toast, refetchMedia, refetchFlags, closePreview]);

  /* ── Flag / Unflag — use path for API calls ── */
  const handleFlag = useCallback(async (filePath: string, reason: string) => {
    setFlagging(true);
    try {
      await api.post(`/copyright/flag/${filePath}`, { reason });
      toast("Flagged successfully", "success");
      setFlagTarget(null);
      setFlagReason("");
      refetchFlags();
    } catch (e) {
      toast(`Flag failed: ${e instanceof Error ? e.message : "Unknown error"}`, "error");
    } finally {
      setFlagging(false);
    }
  }, [toast, refetchFlags]);

  const handleUnflag = useCallback(async (filePath: string) => {
    try {
      await api.del(`/copyright/flag/${filePath}`);
      toast("Unflagged successfully", "success");
      refetchFlags();
    } catch (e) {
      toast(`Unflag failed: ${e instanceof Error ? e.message : "Unknown error"}`, "error");
    }
  }, [toast, refetchFlags]);

  /* ── Artist groups ── */
  const artistGroups = useMemo(() => {
    if (!groupByArtistMode) return null;
    return groupByArtist(filteredItems);
  }, [filteredItems, groupByArtistMode]);

  /* (no blob cleanup needed — using direct URL streaming) */

  /* ── Render ── */
  return (
    <div className="animate-fade-in">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="video/mp4,video/quicktime,image/jpeg,image/png"
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files && e.target.files.length > 0) {
            handleUpload(e.target.files);
            e.target.value = "";
          }
        }}
      />

      {/* ── Header ── */}
      <div className="page-header">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2">
              <Shield size={20} className="text-accent" />
              Media Manager
            </h1>
            <p className="page-subtitle">Browse, upload, and protect your media assets</p>
          </div>
          <div className="hidden sm:flex items-center gap-2 relative z-10 flex-shrink-0">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer disabled:opacity-50"
              style={{
                background: "var(--accent-muted)",
                color: "var(--accent)",
                border: "1.5px solid color-mix(in srgb, var(--accent) 40%, transparent)",
              }}
            >
              {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
              {uploading ? "Uploading..." : "Upload"}
            </button>
            <button
              onClick={handleScanAll}
              disabled={scanning}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer disabled:opacity-50"
              style={{
                background: "#8b5cf618",
                color: "#8b5cf6",
                border: "1.5px solid #8b5cf640",
              }}
            >
              {scanning ? <Loader2 size={14} className="animate-spin" /> : <ScanLine size={14} />}
              {scanning && scanProgress
                ? `${scanProgress.current}/${scanProgress.total}`
                : scanning
                ? "Scanning..."
                : "Scan All"}
            </button>
          </div>
        </div>
      </div>

      {/* ── Stats ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatCard icon={Film} value={totalClips} label="Video Clips" loading={mediaLoading} accentColor="var(--accent)" />
        <StatCard icon={ImageIcon} value={totalImages} label="Images" loading={mediaLoading} accentColor="#38bdf8" />
        <StatCard icon={Flag} value={flaggedCount} label="Flagged" loading={mediaLoading} accentColor="#ef4444" />
        <StatCard icon={Video} value={renderedBeats.length} label="Renders" loading={beatsLoading} accentColor="#22c55e" />
      </div>

      {/* ── Main Tab Switch ── */}
      <div className="flex items-center gap-2 mb-5">
        {([
          { key: "library" as const, label: "Media Library", icon: FolderOpen },
          { key: "renders" as const, label: "Rendered Beats", icon: Video },
        ]).map((tab) => {
          const active = mainTab === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => setMainTab(tab.key)}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer"
              style={{
                background: active
                  ? "linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 70%, #8b5cf6))"
                  : "var(--bg-card)",
                color: active ? "#fff" : "var(--text-secondary)",
                border: active ? "none" : "1px solid var(--glass-border)",
                boxShadow: active ? "0 4px 16px var(--accent-muted)" : "none",
              }}
            >
              <tab.icon size={14} />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* ══════════════════════════════════════════════════════════ */}
      {/* LIBRARY TAB                                               */}
      {/* ══════════════════════════════════════════════════════════ */}
      {mainTab === "library" && (
        <div
          className="rounded-2xl overflow-hidden"
          style={{
            background: "var(--bg-card)",
            backdropFilter: "blur(16px)",
            border: "1px solid var(--glass-border)",
          }}
        >
          {/* Filter + Search */}
          <div className="p-4 flex flex-col sm:flex-row items-start sm:items-center gap-3" style={{ borderBottom: "1px solid var(--border)" }}>
            <SearchInput
              value={search}
              onChange={setSearch}
              placeholder="Search media..."
              size="sm"
              className="flex-1 min-w-0 w-full sm:w-auto"
            />

            <div className="flex items-center gap-1.5 flex-shrink-0 flex-wrap">
              {([
                { key: "all" as const, label: "All", count: allItems.length, color: "var(--accent)" },
                { key: "clips" as const, label: "Clips", count: totalClips, color: "#38bdf8" },
                { key: "images" as const, label: "Images", count: totalImages, color: "#e040fb" },
                { key: "flagged" as const, label: "Flagged", count: flaggedCount, color: "#ef4444" },
                { key: "safe" as const, label: "Safe", count: safeCount, color: "#22c55e" },
              ]).map((tab) => {
                const active = filter === tab.key;
                return (
                  <button
                    key={tab.key}
                    onClick={() => setFilter(tab.key)}
                    className="text-[10px] font-semibold px-2.5 py-1.5 rounded-lg transition-all cursor-pointer whitespace-nowrap"
                    style={{
                      background: active ? `${tab.color}18` : "transparent",
                      border: `1px solid ${active ? `${tab.color}40` : "transparent"}`,
                      color: active ? tab.color : "var(--text-tertiary)",
                    }}
                  >
                    {tab.label} ({tab.count})
                  </button>
                );
              })}
            </div>

            <div className="flex items-center gap-2 flex-shrink-0">
              <div className="flex items-center gap-1">
                <span className="text-[9px] text-text-tertiary uppercase tracking-wider mr-1">Sort:</span>
                {([
                  { key: "name" as const, label: "Name" },
                  { key: "risk" as const, label: "Risk" },
                  { key: "size" as const, label: "Size" },
                ]).map((s) => (
                  <button
                    key={s.key}
                    onClick={() => setSortBy(s.key)}
                    className="text-[10px] font-medium px-2 py-1 rounded-md transition-all cursor-pointer"
                    style={{
                      background: sortBy === s.key ? "var(--accent-muted)" : "transparent",
                      color: sortBy === s.key ? "var(--accent)" : "var(--text-tertiary)",
                    }}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
              <button
                onClick={() => setGroupByArtistMode(!groupByArtistMode)}
                className="text-[10px] font-medium px-2 py-1 rounded-md transition-all cursor-pointer flex items-center gap-1"
                style={{
                  background: groupByArtistMode ? "#8b5cf618" : "transparent",
                  color: groupByArtistMode ? "#8b5cf6" : "var(--text-tertiary)",
                  border: groupByArtistMode ? "1px solid #8b5cf630" : "1px solid transparent",
                }}
              >
                <User size={10} />
                Artist
              </button>
            </div>
          </div>

          {/* Media Grid */}
          <div className="p-4">
            {mediaLoading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 size={28} className="animate-spin text-accent" />
              </div>
            ) : filteredItems.length === 0 ? (
              <div className="text-center py-16">
                <Film size={28} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.3 }} />
                <p className="text-xs text-text-tertiary mb-3">
                  {search ? `No media matching "${search}"` : "No media found"}
                </p>
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer"
                  style={{
                    background: "var(--accent-muted)",
                    color: "var(--accent)",
                    border: "1px solid color-mix(in srgb, var(--accent) 30%, transparent)",
                  }}
                >
                  <Upload size={14} />
                  Upload Media
                </button>
              </div>
            ) : groupByArtistMode && artistGroups ? (
              Object.entries(artistGroups)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([artist, items]) => (
                  <div key={artist} className="mb-6 last:mb-0">
                    <div className="flex items-center gap-2 mb-3">
                      <User size={13} style={{ color: "var(--accent)" }} />
                      <h3 className="text-xs font-bold text-foreground capitalize">{artist}</h3>
                      <span className="text-[10px] text-text-tertiary">({items.length})</span>
                    </div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                      {items.map((item) => (
                        <MediaCard key={item.path} item={item} flags={flags} onOpen={openPreview} />
                      ))}
                    </div>
                  </div>
                ))
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                {filteredItems.map((item) => (
                  <MediaCard key={item.path} item={item} flags={flags} onOpen={openPreview} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════ */}
      {/* RENDERS TAB                                               */}
      {/* ══════════════════════════════════════════════════════════ */}
      {mainTab === "renders" && (
        <div
          className="rounded-2xl overflow-hidden"
          style={{
            background: "var(--bg-card)",
            backdropFilter: "blur(16px)",
            border: "1px solid var(--glass-border)",
          }}
        >
          <div className="p-4" style={{ borderBottom: "1px solid var(--border)" }}>
            <SearchInput
              value={renderSearch}
              onChange={setRenderSearch}
              placeholder="Search renders..."
              size="sm"
              className="max-w-sm"
            />
          </div>

          <div className="p-4">
            {beatsLoading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 size={28} className="animate-spin text-accent" />
              </div>
            ) : filteredRenders.length === 0 ? (
              <div className="text-center py-16">
                <Video size={28} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.3 }} />
                <p className="text-xs text-text-tertiary">
                  {renderSearch ? `No renders matching "${renderSearch}"` : "No rendered beats yet"}
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
                {filteredRenders.map((beat) => (
                  <button
                    key={beat.stem}
                    onClick={() => openRenderVideo(beat.stem)}
                    className="relative rounded-xl overflow-hidden text-left transition-all duration-200 group cursor-pointer hover:ring-1 hover:ring-accent/40"
                    style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
                  >
                    <div className="aspect-video bg-muted relative overflow-hidden">
                      <AuthImage
                        src={`/files/output/${beat.stem}_thumb.jpg`}
                        alt={beat.beat_name || beat.stem}
                        className="w-full h-full object-cover"
                        fallback={
                          <div className="w-full h-full flex items-center justify-center bg-muted">
                            <Video size={24} className="text-text-tertiary" />
                          </div>
                        }
                      />
                      <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
                        <div className="w-10 h-10 rounded-full bg-black/60 flex items-center justify-center">
                          <Play size={18} className="text-white ml-0.5" />
                        </div>
                      </div>
                      {beat.uploaded && (
                        <div className="absolute top-1.5 right-1.5">
                          <span
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-semibold"
                            style={{ background: "rgba(34,197,94,0.85)", color: "#fff" }}
                          >
                            <CheckCircle2 size={9} />
                            Uploaded
                          </span>
                        </div>
                      )}
                    </div>
                    <div className="p-2.5">
                      <p className="text-xs font-medium truncate text-foreground">
                        {beat.beat_name || beat.stem.replace(/_/g, " ")}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-[10px] text-text-tertiary">{beat.artist}</span>
                        {beat.file_size > 0 && (
                          <span className="text-[10px] text-text-tertiary flex items-center gap-0.5">
                            <HardDrive size={8} />
                            {(beat.file_size / (1024 * 1024)).toFixed(1)}MB
                          </span>
                        )}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════ */}
      {/* PREVIEW MODAL (Media Library)                             */}
      {/* ══════════════════════════════════════════════════════════ */}
      {previewItem && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)" }}
          onClick={(e) => { if (e.target === e.currentTarget) closePreview(); }}
        >
          <div
            className="w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-2xl"
            style={{
              background: "var(--bg-card-solid, var(--bg-card))",
              border: "1px solid var(--border-light)",
              boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
            }}
          >
            {/* Header */}
            <div className="flex items-center justify-between p-5" style={{ borderBottom: "1px solid var(--border)" }}>
              <div className="flex items-center gap-3 min-w-0">
                {isClip(previewItem.name) ? (
                  <Film size={18} className="text-accent flex-shrink-0" />
                ) : (
                  <ImageIcon size={18} className="text-accent flex-shrink-0" />
                )}
                <h2 className="text-base font-bold text-foreground truncate">{previewItem.name}</h2>
                {previewDetail && (
                  <CopyrightBadge
                    risk={(previewDetail.copyright.risk as Risk) || "unknown"}
                    reasons={previewDetail.copyright.reasons}
                    size="md"
                  />
                )}
              </div>
              <button onClick={closePreview} className="p-2 rounded-lg cursor-pointer hover:bg-[var(--bg-hover)] transition-all">
                <X size={18} className="text-text-tertiary" />
              </button>
            </div>

            {/* Body */}
            <div className="flex flex-col lg:flex-row">
              {/* Video / Image */}
              <div className="flex-1 p-5">
                {isClip(previewItem.name) ? (
                  videoBlobUrl ? (
                    <video
                      key={videoBlobUrl}
                      src={videoBlobUrl}
                      controls
                      autoPlay
                      playsInline
                      className="w-full rounded-xl"
                      style={{ maxHeight: "50vh", background: "#000" }}
                    />
                  ) : (
                    <div className="w-full flex flex-col items-center justify-center gap-2 rounded-xl" style={{ aspectRatio: "16/9", background: "#000" }}>
                      <AlertCircle size={24} className="text-text-tertiary" style={{ opacity: 0.5 }} />
                      <span className="text-[10px] text-text-tertiary">Failed to load video</span>
                    </div>
                  )
                ) : (
                  <AuthImage
                    src={`/files/images/${previewItem.path}`}
                    alt={previewItem.name}
                    className="w-full rounded-xl object-contain"
                    eager
                    fallback={
                      <div className="w-full flex items-center justify-center rounded-xl" style={{ aspectRatio: "16/9", background: "var(--bg-primary)" }}>
                        <ImageIcon size={28} className="text-text-tertiary" style={{ opacity: 0.5 }} />
                      </div>
                    }
                  />
                )}
              </div>

              {/* Sidebar */}
              <div className="w-full lg:w-72 p-5 flex-shrink-0 space-y-5" style={{ borderLeft: "1px solid var(--border)" }}>
                {/* Metadata */}
                <div>
                  <h3 className="text-[10px] font-bold uppercase tracking-wider text-text-tertiary mb-2.5">Details</h3>
                  <div className="space-y-2">
                    {previewItem.resolution && previewItem.resolution !== "unknown" && (
                      <DetailRow label="Resolution" value={previewItem.resolution} />
                    )}
                    {previewItem.duration != null && previewItem.duration > 0 && (
                      <DetailRow label="Duration" value={formatDuration(previewItem.duration)} />
                    )}
                    <DetailRow label="Size" value={`${previewItem.size_mb}MB`} />
                    {previewItem.orientation && <DetailRow label="Orientation" value={previewItem.orientation} />}
                    {previewItem.source && <DetailRow label="Source" value={previewItem.source} />}
                    {previewItem.folder && <DetailRow label="Folder" value={previewItem.folder} />}
                  </div>
                </div>

                {/* Copyright */}
                {previewDetail && (
                  <div>
                    <h3 className="text-[10px] font-bold uppercase tracking-wider text-text-tertiary mb-2.5">Copyright</h3>
                    <CopyrightBadge
                      risk={(previewDetail.copyright.risk as Risk) || "unknown"}
                      reasons={previewDetail.copyright.reasons}
                      size="md"
                    />
                    {previewDetail.copyright.reasons.length > 0 && (
                      <ul className="mt-2 space-y-1">
                        {previewDetail.copyright.reasons.map((r, i) => (
                          <li key={i} className="text-[10px] text-text-tertiary flex items-start gap-1.5">
                            <AlertCircle size={10} className="flex-shrink-0 mt-0.5" style={{ color: "#ef4444" }} />
                            {r}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                {/* Beats Using This */}
                {previewDetail && previewDetail.used_by.length > 0 && (
                  <div>
                    <h3 className="text-[10px] font-bold uppercase tracking-wider text-text-tertiary mb-2.5">
                      Used by ({previewDetail.used_by.length} beat{previewDetail.used_by.length !== 1 ? "s" : ""})
                    </h3>
                    <div className="space-y-1.5">
                      {previewDetail.used_by.map((stem) => (
                        <button
                          key={stem}
                          onClick={() => router.push(`/render-studio?search=${stem}`)}
                          className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-lg text-left transition-all cursor-pointer"
                          style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
                        >
                          <Music size={11} className="text-accent flex-shrink-0" />
                          <span className="text-[11px] font-medium text-foreground truncate">{stem.replace(/_/g, " ")}</span>
                          <ExternalLink size={9} className="text-text-tertiary flex-shrink-0 ml-auto" />
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {previewLoading && (
                  <div className="flex justify-center py-4">
                    <Loader2 size={16} className="animate-spin text-accent" />
                  </div>
                )}

                {/* Actions */}
                <div className="space-y-2 pt-2" style={{ borderTop: "1px solid var(--border)" }}>
                  {isClip(previewItem.name) && (
                    <button
                      onClick={async () => {
                        try {
                          await api.post(`/copyright/scan/${previewItem.path}`);
                          toast("Scan complete", "success");
                          refetchFlags();
                          const detail = await api.get<MediaDetail>(`/media/detail/${previewItem.path}`);
                          setPreviewDetail(detail);
                        } catch (e) {
                          toast(`Scan failed: ${e instanceof Error ? e.message : "Error"}`, "error");
                        }
                      }}
                      className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer"
                      style={{ background: "#8b5cf615", color: "#8b5cf6", border: "1px solid #8b5cf630" }}
                    >
                      <ScanLine size={13} />
                      Scan for Copyright
                    </button>
                  )}

                  {(() => {
                    const { risk: currentRisk } = getRisk(previewItem.name, flags, previewItem.path);
                    if (currentRisk === "flagged") {
                      return (
                        <button
                          onClick={() => handleUnflag(previewItem.path)}
                          className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer"
                          style={{ background: "#22c55e15", color: "#22c55e", border: "1px solid #22c55e30" }}
                        >
                          <CheckCircle2 size={13} />
                          Remove Flag
                        </button>
                      );
                    }
                    return (
                      <button
                        onClick={() => { setFlagTarget(previewItem.path); setFlagReason(""); }}
                        className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer"
                        style={{ background: "#ef444415", color: "#ef4444", border: "1px solid #ef444430" }}
                      >
                        <Flag size={13} />
                        Flag as Copyrighted
                      </button>
                    );
                  })()}

                  <button
                    onClick={() => setDeleteTarget(previewItem.path)}
                    className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-all cursor-pointer"
                    style={{ background: "#ef444410", color: "#ef4444", border: "1px solid #ef444420" }}
                  >
                    <Trash2 size={13} />
                    Delete
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════ */}
      {/* RENDER VIDEO PLAYER MODAL                                 */}
      {/* ══════════════════════════════════════════════════════════ */}
      {renderVideoStem && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: "rgba(0,0,0,0.8)", backdropFilter: "blur(6px)" }}
          onClick={(e) => { if (e.target === e.currentTarget) closeRenderVideo(); }}
        >
          <div
            className="w-full max-w-3xl rounded-2xl overflow-hidden"
            style={{
              background: "var(--bg-card-solid, var(--bg-card))",
              border: "1px solid var(--border-light)",
              boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
            }}
          >
            <div className="flex items-center justify-between p-4" style={{ borderBottom: "1px solid var(--border)" }}>
              <div className="flex items-center gap-2 min-w-0">
                <Video size={16} className="text-accent flex-shrink-0" />
                <h2 className="text-sm font-bold text-foreground truncate">
                  {(() => {
                    const beat = renderedBeats.find((b) => b.stem === renderVideoStem);
                    return beat?.beat_name || renderVideoStem.replace(/_/g, " ");
                  })()}
                </h2>
              </div>
              <button onClick={closeRenderVideo} className="p-2 rounded-lg cursor-pointer hover:bg-[var(--bg-hover)] transition-all">
                <X size={18} className="text-text-tertiary" />
              </button>
            </div>
            <div className="p-4">
              {renderVideoUrl ? (
                <video
                  key={renderVideoUrl}
                  src={renderVideoUrl}
                  controls
                  autoPlay
                  playsInline
                  className="w-full rounded-xl"
                  style={{ maxHeight: "70vh", background: "#000" }}
                  onError={(e) => {
                    // If token expired / auth failed, show error
                    const v = e.currentTarget;
                    if (v.error) {
                      v.style.display = "none";
                      v.parentElement?.insertAdjacentHTML(
                        "beforeend",
                        `<div class="w-full flex flex-col items-center justify-center gap-2 rounded-xl" style="aspect-ratio:16/9;background:#000"><span style="color:var(--text-tertiary);font-size:10px">Failed to load video</span></div>`
                      );
                    }
                  }}
                />
              ) : (
                <div className="w-full flex flex-col items-center justify-center gap-2 rounded-xl" style={{ aspectRatio: "16/9", background: "#000" }}>
                  <AlertCircle size={24} className="text-text-tertiary" style={{ opacity: 0.5 }} />
                  <span className="text-[10px] text-text-tertiary">Failed to load video</span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Flag Dialog ── */}
      {flagTarget && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" style={{ background: "rgba(0,0,0,0.6)" }}>
          <div
            className="w-full max-w-sm rounded-xl p-6"
            style={{
              background: "var(--bg-card-solid, var(--bg-card))",
              border: "1px solid var(--border-light)",
              boxShadow: "0 16px 48px rgba(0,0,0,0.5)",
            }}
          >
            <div className="flex items-center gap-2 mb-4">
              <Flag size={16} style={{ color: "#ef4444" }} />
              <h3 className="text-sm font-bold text-foreground truncate">Flag: {flagTarget.split("/").pop()}</h3>
            </div>
            <p className="text-xs text-text-tertiary mb-3">
              Why is this clip copyrighted? This helps detect similar clips in the future.
            </p>
            <input
              type="text"
              placeholder="e.g. Got copyright claim on YouTube"
              value={flagReason}
              onChange={(e) => setFlagReason(e.target.value)}
              className="w-full px-3 py-2 rounded-lg text-xs outline-none mb-4"
              style={{ background: "var(--bg-hover)", border: "1px solid var(--border)", color: "var(--foreground)" }}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter" && flagReason.trim()) handleFlag(flagTarget, flagReason.trim());
              }}
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => { setFlagTarget(null); setFlagReason(""); }}
                className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all cursor-pointer"
                style={{ color: "var(--text-tertiary)" }}
              >
                Cancel
              </button>
              <button
                onClick={() => flagReason.trim() && handleFlag(flagTarget, flagReason.trim())}
                disabled={flagging || !flagReason.trim()}
                className="px-4 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer disabled:opacity-40"
                style={{ background: "#ef4444", color: "#fff" }}
              >
                {flagging ? "Flagging..." : "Flag"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Delete Confirm ── */}
      <ConfirmDialog
        open={!!deleteTarget}
        title={`Delete ${deleteTarget?.split("/").pop()}?`}
        description="This will permanently delete the file and remove it from all beat assignments. This action cannot be undone."
        confirmLabel="Delete"
        variant="danger"
        loading={deleting}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}

/* ── MediaCard sub-component ──────────────────────────────────── */

function MediaCard({
  item,
  flags,
  onOpen,
}: {
  item: MediaItem;
  flags: CopyrightFlags | null;
  onOpen: (item: MediaItem) => void;
}) {
  const { risk, reasons } = getRisk(item.name, flags, item.path);
  const clip = isClip(item.name);

  return (
    <button
      onClick={() => onOpen(item)}
      className="relative rounded-xl overflow-hidden text-left transition-all duration-200 group cursor-pointer hover:ring-1 hover:ring-accent/40"
      style={{
        background: "var(--bg-card)",
        border: `1px solid ${risk === "danger" || risk === "flagged" ? "#ef444440" : risk === "caution" ? "#eab30840" : "var(--border)"}`,
      }}
    >
      <div className="aspect-video bg-muted relative overflow-hidden">
        {clip ? (
          /* Video clips: show backend-extracted thumbnail (small JPEG, not the full MP4) */
          <AuthImage
            src={`/files/thumbnail/${item.path}`}
            alt={item.name}
            className="w-full h-full object-cover"
            fallback={
              <div className="w-full h-full flex items-center justify-center" style={{ background: "var(--bg-hover)" }}>
                <Film size={28} style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
              </div>
            }
          />
        ) : (
          <AuthImage
            src={`/files/images/${item.path}`}
            alt={item.name}
            className="w-full h-full object-cover"
            fallback={
              <div className="w-full h-full flex items-center justify-center bg-muted">
                <ImageIcon size={24} className="text-text-tertiary" />
              </div>
            }
          />
        )}
        {clip && (
          <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
            <div className="w-10 h-10 rounded-full bg-black/60 flex items-center justify-center">
              <Play size={18} className="text-white ml-0.5" />
            </div>
          </div>
        )}
        {risk !== "unknown" && (
          <div className="absolute top-1.5 right-1.5">
            <CopyrightBadge risk={risk} reasons={reasons} size="sm" />
          </div>
        )}
        {item.orientation && (
          <div className="absolute bottom-1.5 left-1.5">
            <span
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-semibold"
              style={{ background: "rgba(0,0,0,0.6)", color: "#fff" }}
            >
              {item.orientation === "portrait" ? <Smartphone size={9} /> : <Monitor size={9} />}
              {item.orientation}
            </span>
          </div>
        )}
      </div>
      <div className="p-2.5">
        <p className="text-xs font-medium truncate text-foreground">{item.name}</p>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          {item.resolution && item.resolution !== "unknown" && (
            <span className="text-[10px] text-text-tertiary">{item.resolution}</span>
          )}
          {item.duration != null && item.duration > 0 && (
            <span className="text-[10px] text-text-tertiary flex items-center gap-0.5">
              <Clock size={8} />
              {formatDuration(item.duration)}
            </span>
          )}
          <span className="text-[10px] text-text-tertiary flex items-center gap-0.5">
            <HardDrive size={8} />
            {item.size_mb}MB
          </span>
        </div>
      </div>
    </button>
  );
}

/* ── DetailRow sub-component ──────────────────────────────────── */

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[11px] text-text-tertiary">{label}</span>
      <span className="text-[11px] font-medium text-foreground capitalize">{value}</span>
    </div>
  );
}
