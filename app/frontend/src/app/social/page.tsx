"use client";

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import {
  Share2,
  Send,
  Clock,
  CheckCircle2,
  XCircle,
  ChevronDown,
  Hash,
  Instagram,
  Music,
  Loader2,
  AlertCircle,
  Download,
  RefreshCw,
  ExternalLink,
  Link2,
  Monitor,
  Smartphone,
  Square,
  RectangleHorizontal,
  Filter,
  CalendarClock,
  Trash2,
  Timer,
} from "lucide-react";
import { useFetch, api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import SearchInput from "@/components/ui/SearchInput";
import { useWebSocket } from "@/hooks/useWebSocket";
import DimensionConverter from "@/components/DimensionConverter";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface Beat {
  stem: string;
  filename: string;
  title: string;
  rendered: boolean;
  uploaded: boolean;
  has_thumbnail: boolean;
  social?: Record<string, { platform: string; status: string; uploadedAt?: string; media_id?: string; publish_id?: string; videoId?: string; url?: string }>;
}

interface SocialPost {
  id: string;
  platform: "instagram" | "tiktok" | "youtube_shorts";
  stem: string;
  title: string;
  caption: string;
  status: "posted" | "failed" | "pending";
  postedAt: string;
}

interface ActiveUpload {
  taskId: string;
  stem: string;
  platform: "instagram" | "tiktok" | "youtube_shorts";
  pct: number;
  detail: string;
}

type Platform = "instagram" | "tiktok" | "youtube_shorts";

interface ScheduledPost {
  id: string;
  stem: string;
  platforms: string[];
  caption: string;
  privacy: string;
  scheduled_at: string;
  created_at: string;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  results: Record<string, unknown>;
}

interface AuthPlatformStatus {
  connected: boolean;
  detail: string;
  needs_reconnect: boolean;
}

interface AuthStatus {
  youtube: AuthPlatformStatus;
  instagram: AuthPlatformStatus;
  tiktok: AuthPlatformStatus;
}

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const SUGGESTED_HASHTAGS = [
  "#typebeat", "#beats", "#producer", "#beatmaker",
  "#trap", "#hiphop", "#instrumental", "#newmusic",
  "#beatsforsale", "#studiolife", "#FY3", "#freestyle",
];

const IG_CAPTION_LIMIT = 2200;
const TT_CAPTION_LIMIT = 2200;

function platformName(p: Platform | string): string {
  if (p === "instagram") return "Instagram";
  if (p === "tiktok") return "TikTok";
  if (p === "youtube_shorts") return "YouTube Shorts";
  return p;
}

/* ------------------------------------------------------------------ */
/*  TikTok SVG Icon                                                    */
/* ------------------------------------------------------------------ */

function TikTokIcon({ size = 18, color }: { size?: number; color?: string }) {
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

/* ------------------------------------------------------------------ */
/*  YouTube SVG Icon                                                    */
/* ------------------------------------------------------------------ */

function YouTubeIcon({ size = 16, color = "#fff" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={color}>
      <path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0C.488 3.45.029 5.804 0 12c.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0C23.512 20.55 23.971 18.196 24 12c-.029-6.185-.484-8.549-4.385-8.816zM9 16V8l8 4-8 4z" />
    </svg>
  );
}

/* ------------------------------------------------------------------ */
/*  Main Page                                                          */
/* ------------------------------------------------------------------ */

export default function SocialPage() {
  const { data: beats, loading: beatsLoading } = useFetch<Beat[]>("/beats");
  const { toast } = useToast();
  const { lastMessage } = useWebSocket();

  /* Auth status — real token validation with auto-refresh */
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const authPollRef = useRef<ReturnType<typeof setInterval>>(undefined);

  const fetchAuthStatus = useCallback(async () => {
    try {
      const data = await api.get<AuthStatus>("/social/auth/status");
      setAuthStatus(data);
    } catch {
      // Silently fail — will retry
    } finally {
      setAuthLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAuthStatus();
    authPollRef.current = setInterval(fetchAuthStatus, 5000);
    return () => clearInterval(authPollRef.current);
  }, [fetchAuthStatus]);

  const igConnected = authStatus?.instagram?.connected ?? false;
  const ttConnected = authStatus?.tiktok?.connected ?? false;
  const ytConnected = authStatus?.youtube?.connected ?? false;

  /* Connection flow state */
  const [connectingPlatform, setConnectingPlatform] = useState<string | null>(null);
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [authCode, setAuthCode] = useState("");
  const [connectError, setConnectError] = useState<string | null>(null);

  /* Social post history from backend */
  interface HistoryPost {
    id: string;
    stem: string;
    platform: string;
    status: string;
    uploadedAt: string;
    media_id?: string;
    publish_id?: string;
    videoId?: string;
    url?: string;
  }
  const { data: historyData, refetch: refetchHistory } = useFetch<{
    posts: HistoryPost[];
    count: number;
  }>("/social/history");

  /* State */
  const [selectedStem, setSelectedStem] = useState<string>("");
  const [caption, setCaption] = useState("");
  const [beatSearch, setBeatSearch] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [postHistory, setPostHistory] = useState<SocialPost[]>([]);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastSuccess, setLastSuccess] = useState<string | null>(null);
  const [activeUploads, setActiveUploads] = useState<ActiveUpload[]>([]);
  const trackedTasks = useRef<Set<string>>(new Set());
  const [historyFilter, setHistoryFilter] = useState<"all" | Platform>("all");

  /* Schedule mode state */
  const [scheduleMode, setScheduleMode] = useState(false);
  const [scheduleTime, setScheduleTime] = useState("");
  const [scheduledPosts, setScheduledPosts] = useState<ScheduledPost[]>([]);
  const [scheduledLoading, setScheduledLoading] = useState(false);
  const [historyTab, setHistoryTab] = useState<"history" | "scheduled">("history");
  const [selectedSchedulePlatforms, setSelectedSchedulePlatforms] = useState<Set<Platform>>(
    new Set(["instagram", "tiktok", "youtube_shorts"])
  );

  /* Fetch scheduled posts */
  const fetchScheduled = useCallback(async () => {
    try {
      setScheduledLoading(true);
      const data = await api.get<{ posts: ScheduledPost[]; pending: number }>("/social/schedule");
      setScheduledPosts(Array.isArray(data) ? data : data?.posts ?? []);
    } catch {
      // silent
    } finally {
      setScheduledLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchScheduled();
  }, [fetchScheduled]);

  // Auto-refresh scheduled posts every 10s when on the scheduled tab
  useEffect(() => {
    if (historyTab !== "scheduled") return;
    const iv = setInterval(fetchScheduled, 10_000);
    return () => clearInterval(iv);
  }, [historyTab, fetchScheduled]);

  // Listen for social_schedule WebSocket updates
  useEffect(() => {
    if (!lastMessage || lastMessage.type !== "social_schedule") return;
    const post = (lastMessage as unknown as { post: ScheduledPost }).post;
    if (!post?.id) return;
    setScheduledPosts((prev) =>
      prev.map((p) => (p.id === post.id ? { ...p, ...post } : p))
    );
    if (post.status === "done") {
      toast("Scheduled post completed!", "success");
      setTimeout(() => refetchHistory(), 1000);
    } else if (post.status === "failed") {
      toast("Scheduled post failed", "error");
    }
  }, [lastMessage, toast, refetchHistory]);

  const pendingScheduleCount = scheduledPosts.filter((p) => p.status === "pending" || p.status === "running").length;

  /* Dimension converter state */
  const [convertOpen, setConvertOpen] = useState(false);
  const [dimStatus, setDimStatus] = useState<Record<string, { exists: boolean; size_mb?: number; label?: string }>>({});

  /* Fetch dimension status when selected stem changes */
  useEffect(() => {
    if (!selectedStem) { setDimStatus({}); return; }
    api.get<Record<string, unknown>>(`/convert/status/${selectedStem}`)
      .then((data) => {
        const statuses: Record<string, { exists: boolean; size_mb?: number; label?: string }> = {};
        for (const key of ["9x16", "4x5", "1x1"]) {
          const ps = data[key] as { exists: boolean; size_mb?: number; label?: string } | undefined;
          if (ps) statuses[key] = ps;
        }
        setDimStatus(statuses);
      })
      .catch(() => setDimStatus({}));
  }, [selectedStem]);

  /* Load history from backend */
  useEffect(() => {
    if (!historyData?.posts) return;
    const mapped: SocialPost[] = historyData.posts
      .filter((p) => p.platform === "instagram" || p.platform === "tiktok" || p.platform === "youtube_shorts")
      .map((p) => ({
        id: p.id,
        platform: p.platform as Platform,
        stem: p.stem,
        title: beats?.find((b) => b.stem === p.stem)?.title || p.stem.replace(/_/g, " "),
        caption: "",
        status: (p.status === "ok" ? "posted" : "failed") as "posted" | "failed",
        postedAt: p.uploadedAt,
      }));
    setPostHistory(mapped);
  }, [historyData, beats]);

  /* ─── WebSocket progress tracking ────────────────────────────────── */
  useEffect(() => {
    if (!lastMessage || lastMessage.type !== "progress") return;

    const { phase, pct, detail, stem: wsStem, taskId } = lastMessage;

    if (phase !== "ig_upload" && phase !== "tiktok_upload" && phase !== "shorts_upload") return;
    if (!taskId || !trackedTasks.current.has(taskId as string)) return;

    const platform: Platform =
      phase === "ig_upload" ? "instagram" : phase === "tiktok_upload" ? "tiktok" : "youtube_shorts";
    const isError = typeof detail === "string" && detail.startsWith("Error:");
    const isDone = pct === 100;

    if (isDone || isError) {
      trackedTasks.current.delete(taskId as string);
      setActiveUploads((prev) => prev.filter((u) => u.taskId !== taskId));

      const beatTitle =
        beats?.find((b) => b.stem === wsStem)?.title ||
        (typeof wsStem === "string" ? wsStem.replace(/_/g, " ") : "") || "";

      if (isDone) {
        setPostHistory((h) => [{
          id: `${platform}-${wsStem}-${Date.now()}`,
          platform, stem: (wsStem as string) || "", title: beatTitle,
          caption: "", status: "posted", postedAt: new Date().toISOString(),
        }, ...h]);
        setLastSuccess(`Posted to ${platformName(platform)} successfully`);
        toast(`Posted to ${platformName(platform)}`, "success");
        setTimeout(() => refetchHistory(), 1000);
      } else {
        setPostHistory((h) => [{
          id: `${platform}-${wsStem}-${Date.now()}`,
          platform, stem: (wsStem as string) || "", title: beatTitle,
          caption: "", status: "failed", postedAt: new Date().toISOString(),
        }, ...h]);
        setLastError(`Failed to post to ${platformName(platform)}: ${detail}`);
        toast(`Upload failed`, "error");
      }
    } else {
      setActiveUploads((prev) =>
        prev.map((u) =>
          u.taskId === taskId
            ? { ...u, pct: (pct as number) ?? u.pct, detail: typeof detail === "string" ? detail : u.detail }
            : u
        )
      );
    }
  }, [lastMessage, beats, toast, refetchHistory]);

  /* Derived */
  const renderedBeats = useMemo(() => beats?.filter((b) => b.rendered) ?? [], [beats]);
  const filteredBeats = useMemo(
    () => renderedBeats.filter((b) =>
      b.stem.toLowerCase().includes(beatSearch.toLowerCase()) ||
      b.title.toLowerCase().includes(beatSearch.toLowerCase())
    ),
    [renderedBeats, beatSearch]
  );
  const selectedBeat = renderedBeats.find((b) => b.stem === selectedStem);

  const igPostCount = postHistory.filter((p) => p.platform === "instagram" && p.status === "posted").length;
  const ttPostCount = postHistory.filter((p) => p.platform === "tiktok" && p.status === "posted").length;
  const ytPostCount = postHistory.filter((p) => p.platform === "youtube_shorts" && p.status === "posted").length;

  /** Which platforms this beat has already been posted to */
  function postedPlatforms(b: Beat): Platform[] {
    if (!b.social) return [];
    return (Object.keys(b.social) as Platform[]).filter(
      (p) => b.social?.[p]?.status === "ok"
    );
  }

  const captionLimit = Math.min(IG_CAPTION_LIMIT, TT_CAPTION_LIMIT);

  const igBusy = activeUploads.some((u) => u.stem === selectedStem && u.platform === "instagram");
  const ytBusy = activeUploads.some((u) => u.stem === selectedStem && u.platform === "youtube_shorts");
  const ttBusy = activeUploads.some((u) => u.stem === selectedStem && u.platform === "tiktok");
  const anyBusy = igBusy || ttBusy || ytBusy;

  const filteredHistory = useMemo(
    () => historyFilter === "all" ? postHistory : postHistory.filter((p) => p.platform === historyFilter),
    [postHistory, historyFilter]
  );

  /* Handlers */
  function addHashtag(tag: string) {
    const trimmed = caption.trimEnd();
    const separator = trimmed.length > 0 ? " " : "";
    const next = trimmed + separator + tag;
    if (next.length <= captionLimit) setCaption(next);
  }

  function clearMessages() { setLastError(null); setLastSuccess(null); }

  async function postTo(platform: Platform) {
    if (!selectedStem) return;
    clearMessages();
    try {
      const slug = platform === "instagram" ? "ig" : platform === "tiktok" ? "tiktok" : "shorts";
      const body: Record<string, unknown> = { caption };
      if (platform === "youtube_shorts") body.privacy = "unlisted";

      const result = await api.post<{ task_id: string; status: string; stem: string; platform: string }>(
        `/social/${slug}/${selectedStem}`, body
      );

      if (result.task_id) {
        setActiveUploads((prev) => [...prev, {
          taskId: result.task_id, stem: selectedStem, platform, pct: 0, detail: "Starting upload...",
        }]);
        trackedTasks.current.add(result.task_id);
        toast(`${platformName(platform)} upload started`, "success");
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setLastError(`Failed to start ${platformName(platform)} upload: ${msg}`);
      toast(`Failed to start upload`, "error");
    }
  }

  async function postToAll() {
    if (!selectedStem) return;
    clearMessages();
    const platforms: { platform: Platform; slug: string; body: Record<string, unknown> }[] = [
      { platform: "instagram", slug: "ig", body: { caption } },
      { platform: "tiktok", slug: "tiktok", body: { caption } },
      { platform: "youtube_shorts", slug: "shorts", body: { caption, privacy: "unlisted" } },
    ];

    let started = 0;
    for (const { platform, slug, body } of platforms) {
      try {
        const result = await api.post<{ task_id: string; status: string; stem: string; platform: string }>(
          `/social/${slug}/${selectedStem}`, body
        );
        if (result.task_id) {
          setActiveUploads((prev) => [...prev, {
            taskId: result.task_id, stem: selectedStem, platform, pct: 0, detail: "Starting upload...",
          }]);
          trackedTasks.current.add(result.task_id);
          started++;
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Unknown error";
        setLastError(`Failed to start ${platformName(platform)} upload: ${msg}`);
        toast(`Failed to start ${platformName(platform)} upload`, "error");
      }
    }
    if (started > 0) toast(`${started} uploads started`, "success");
  }

  async function downloadForTikTok() {
    if (!selectedStem) return;
    clearMessages();
    try {
      const info = await api.get<{
        available: boolean; format?: string; filename?: string; download_url?: string; size_mb?: number;
      }>(`/social/tiktok-video/${selectedStem}`);

      if (!info.available || !info.download_url) {
        setLastError("No video available for download. Render the beat first.");
        return;
      }
      toast(`Downloading ${info.filename} (${info.size_mb}MB)...`, "success");

      const token = localStorage.getItem("fy3-token");
      const headers: Record<string, string> = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch(info.download_url!, { headers });
      if (!res.ok) throw new Error(`Download failed: ${res.status}`);

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = info.filename || `${selectedStem}.mp4`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      toast(`Downloaded! Upload ${info.filename} to TikTok manually`, "success");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setLastError(`Download failed: ${msg}`);
    }
  }

  /* ─── Schedule Handlers ────────────────────────────────────────── */

  async function schedulePost() {
    if (!selectedStem || !scheduleTime) return;
    clearMessages();

    const platforms = Array.from(selectedSchedulePlatforms);
    if (platforms.length === 0) {
      toast("Select at least one platform", "error");
      return;
    }

    try {
      await api.post("/social/schedule", {
        stem: selectedStem,
        platforms,
        caption,
        privacy: "public",
        scheduled_at: scheduleTime,
      });
      toast(`Scheduled for ${platforms.length} platform(s)`, "success");
      setScheduleTime("");
      setScheduleMode(false);
      fetchScheduled();
      setHistoryTab("scheduled");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setLastError(`Failed to schedule: ${msg}`);
      toast("Failed to schedule post", "error");
    }
  }

  async function cancelScheduledPost(postId: string) {
    try {
      await api.del(`/social/schedule/${postId}`);
      toast("Scheduled post cancelled", "success");
      setScheduledPosts((prev) =>
        prev.map((p) => (p.id === postId ? { ...p, status: "cancelled" as const } : p))
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      toast(`Failed to cancel: ${msg}`, "error");
    }
  }

  function toggleSchedulePlatform(p: Platform) {
    setSelectedSchedulePlatforms((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });
  }

  /* ─── Platform Connection Handlers ──────────────────────────────── */

  async function connectYouTube() {
    setConnectingPlatform("youtube");
    setConnectError(null);
    try {
      const res = await api.post<{ status: string; message: string }>("/social/auth/youtube/connect", {});
      toast(res.message || "Check your browser for Google sign-in", "success");
      const fastPoll = setInterval(fetchAuthStatus, 2000);
      setTimeout(() => { clearInterval(fastPoll); setConnectingPlatform(null); }, 300_000);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setConnectError(`YouTube: ${msg}`);
      setConnectingPlatform(null);
    }
  }

  async function connectInstagram() {
    setConnectingPlatform("instagram");
    setConnectError(null);
    setAuthCode("");
    try {
      const res = await api.get<{ auth_url: string }>("/social/auth/instagram/url");
      setAuthUrl(res.auth_url);
      window.open(res.auth_url, "_blank");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setConnectError(`Instagram: ${msg}`);
      setConnectingPlatform(null);
    }
  }

  async function connectTikTok() {
    setConnectingPlatform("tiktok");
    setConnectError(null);
    setAuthCode("");
    try {
      const res = await api.get<{ auth_url: string }>("/social/auth/tiktok/url");
      setAuthUrl(res.auth_url);
      window.open(res.auth_url, "_blank");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setConnectError(`TikTok: ${msg}`);
      setConnectingPlatform(null);
    }
  }

  async function submitAuthCode(platform: "instagram" | "tiktok") {
    if (!authCode.trim()) return;
    setConnectError(null);
    try {
      const endpoint = platform === "instagram" ? "/social/auth/instagram/exchange" : "/social/auth/tiktok/exchange";
      await api.post(endpoint, { code: authCode.trim() });
      toast(`${platformName(platform)} connected successfully!`, "success");
      setConnectingPlatform(null);
      setAuthUrl(null);
      setAuthCode("");
      fetchAuthStatus();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Unknown error";
      setConnectError(`${platformName(platform)}: ${msg}`);
    }
  }

  function cancelConnect() {
    setConnectingPlatform(null);
    setAuthUrl(null);
    setAuthCode("");
    setConnectError(null);
  }

  /* ---------------------------------------------------------------- */
  /*  Render                                                           */
  /* ---------------------------------------------------------------- */

  const PLATFORM_CONFIG = [
    {
      key: "instagram" as const,
      label: "Instagram",
      icon: <Instagram size={15} color="#fff" strokeWidth={1.8} />,
      bg: "linear-gradient(135deg, #833AB4, #E1306C, #F77737)",
      connected: igConnected,
      posts: igPostCount,
      detail: authStatus?.instagram?.detail,
      needsReconnect: authStatus?.instagram?.needs_reconnect,
      connect: connectInstagram,
    },
    {
      key: "tiktok" as const,
      label: "TikTok",
      icon: <TikTokIcon size={15} color="#fff" />,
      bg: "#010101",
      connected: ttConnected,
      posts: ttPostCount,
      detail: authStatus?.tiktok?.detail,
      needsReconnect: authStatus?.tiktok?.needs_reconnect,
      connect: connectTikTok,
    },
    {
      key: "youtube" as const,
      label: "YouTube",
      icon: <YouTubeIcon size={15} />,
      bg: "#FF0000",
      connected: ytConnected,
      posts: ytPostCount,
      detail: authStatus?.youtube?.detail,
      needsReconnect: authStatus?.youtube?.needs_reconnect,
      connect: connectYouTube,
    },
  ];

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="page-header">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2">
              <Share2 size={20} className="text-accent" />
              Social
            </h1>
            <p className="page-subtitle">Post to Instagram, TikTok &amp; YouTube Shorts</p>
          </div>
          <div className="hidden sm:flex items-center gap-2 flex-shrink-0">
            <div className="text-[11px] px-2.5 py-1 rounded-full whitespace-nowrap" style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)", color: "var(--text-secondary)" }}>
              <span className="font-semibold text-foreground">{renderedBeats.length}</span> ready
            </div>
            <div className="text-[11px] px-2.5 py-1 rounded-full whitespace-nowrap" style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)", color: "var(--text-secondary)" }}>
              <span className="font-semibold text-foreground">{postHistory.length}</span> posted
            </div>
          </div>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════
          PLATFORM CONNECTIONS
          ═══════════════════════════════════════════════════════ */}
      <div
        className="mb-6 p-6 rounded-2xl"
        style={{
          background: "var(--bg-card)",
          backdropFilter: "blur(16px)",
          border: "1px solid var(--glass-border)",
        }}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="section-header">
            <span className="flex items-center gap-2"><Link2 size={15} /> Platform Connections</span>
          </h2>
          {authLoading && <Loader2 size={14} className="animate-spin text-text-tertiary" />}
        </div>

        {/* Connection error banner */}
        {connectError && (
          <div className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs mb-4" style={{ background: "rgba(255,69,58,0.1)", color: "var(--error)" }}>
            <AlertCircle size={13} />
            <span className="flex-1">{connectError}</span>
            <button type="button" onClick={() => setConnectError(null)} className="cursor-pointer"><XCircle size={12} className="opacity-70" /></button>
          </div>
        )}

        {/* Auth code input (IG / TikTok flow) */}
        {connectingPlatform && connectingPlatform !== "youtube" && authUrl && (
          <div className="rounded-xl p-4 mb-4" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
            <p className="text-xs font-medium mb-2 text-text-secondary">
              Step 1: Authorize in the tab that opened. After approving, you&apos;ll see a code on the callback page.
            </p>
            <p className="text-xs font-medium mb-3 text-text-secondary">
              Step 2: Paste the authorization code below:
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                value={authCode}
                onChange={(e) => setAuthCode(e.target.value)}
                placeholder="Paste authorization code here..."
                className="flex-1 px-3 py-2 rounded-lg text-xs outline-none"
                style={{ background: "var(--bg-primary)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
                onKeyDown={(e) => { if (e.key === "Enter") submitAuthCode(connectingPlatform as "instagram" | "tiktok"); }}
                autoFocus
              />
              <Button type="button" onClick={() => submitAuthCode(connectingPlatform as "instagram" | "tiktok")} disabled={!authCode.trim()} variant={authCode.trim() ? "default" : "ghost"} size="sm">
                Connect
              </Button>
              <Button type="button" onClick={cancelConnect} variant="ghost" size="sm">Cancel</Button>
            </div>
            <a href={authUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs mt-2 text-accent opacity-80">
              <ExternalLink size={11} /> Re-open authorization page
            </a>
          </div>
        )}

        {/* YouTube connecting state */}
        {connectingPlatform === "youtube" && (
          <div className="rounded-xl p-4 mb-4 flex items-center gap-3" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
            <Loader2 size={16} className="animate-spin" style={{ color: "#FF0000" }} />
            <div>
              <p className="text-xs font-medium text-foreground">Waiting for Google sign-in...</p>
              <p className="text-xs text-text-tertiary">Complete authorization in your browser, then come back here.</p>
            </div>
            <Button type="button" onClick={cancelConnect} variant="ghost" size="sm" className="ml-auto">Cancel</Button>
          </div>
        )}

        {/* Platform cards — horizontal */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {PLATFORM_CONFIG.map((p) => (
            <div
              key={p.key}
              className="flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-200"
              style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
            >
              <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: p.bg }}>
                {p.icon}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-semibold text-foreground">{p.label}</p>
                  <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: p.connected ? "var(--success, #30D158)" : "var(--error, #FF453A)" }} />
                </div>
                <p className="text-[10px] text-text-tertiary truncate">{p.detail || "Checking..."}</p>
              </div>
              <div className="flex flex-col items-end gap-1">
                <span className="text-xs font-bold tabular-nums text-foreground">{p.posts}</span>
                {p.needsReconnect && (
                  <button
                    type="button"
                    onClick={p.connect}
                    disabled={connectingPlatform === p.key}
                    className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-medium text-white disabled:opacity-60 cursor-pointer transition-all"
                    style={{ background: p.bg }}
                  >
                    {connectingPlatform === p.key ? <Loader2 size={9} className="animate-spin" /> : <RefreshCw size={9} />}
                    {p.connected ? "Refresh" : "Connect"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* All connected */}
        {authStatus && igConnected && ttConnected && ytConnected && (
          <div className="flex items-center gap-2 mt-3 px-3 py-2 rounded-xl text-xs" style={{ background: "rgba(48,209,88,0.1)", color: "var(--success)" }}>
            <CheckCircle2 size={13} /> All platforms connected
          </div>
        )}
      </div>

      {/* ═══════════════════════════════════════════════════════
          ACTIVE UPLOADS — real-time progress
          ═══════════════════════════════════════════════════════ */}
      {activeUploads.length > 0 && (
        <div
          className="mb-6 p-6 rounded-2xl"
          style={{
            background: "var(--bg-card)",
            backdropFilter: "blur(16px)",
            border: "1px solid var(--glass-border)",
          }}
        >
          <h2 className="section-header mb-4">
            <span className="flex items-center gap-2"><Loader2 size={15} className="animate-spin text-accent" /> Uploading</span>
          </h2>
          <div className="space-y-4">
            {activeUploads.map((upload) => (
              <div key={upload.taskId} className="flex items-center gap-4 p-3 rounded-xl" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
                <div className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0" style={{
                  background: upload.platform === "instagram" ? "linear-gradient(135deg, #833AB4, #E1306C)" : upload.platform === "youtube_shorts" ? "#FF0000" : "#010101",
                }}>
                  {upload.platform === "instagram" ? <Instagram size={18} color="#fff" strokeWidth={1.8} /> :
                   upload.platform === "youtube_shorts" ? <YouTubeIcon size={18} /> :
                   <TikTokIcon size={18} color="#fff" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between mb-1.5">
                    <p className="text-sm font-medium truncate text-foreground">
                      {beats?.find((b) => b.stem === upload.stem)?.title || upload.stem.replace(/_/g, " ")}
                    </p>
                    <span className="text-xs font-bold tabular-nums ml-3 text-accent">{upload.pct}%</span>
                  </div>
                  <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-primary)" }}>
                    <div className="h-full rounded-full transition-all duration-700 ease-out" style={{
                      width: `${Math.max(upload.pct, 2)}%`,
                      background: upload.platform === "instagram" ? "linear-gradient(135deg, #833AB4, #E1306C)" : upload.platform === "youtube_shorts" ? "#FF0000" : "var(--accent)",
                    }} />
                  </div>
                  <p className="text-[10px] mt-1 truncate text-text-tertiary">{upload.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ═══════════════════════════════════════════════════════
          COMPOSE POST
          ═══════════════════════════════════════════════════════ */}
      <div
        className="mb-6 p-6 rounded-2xl"
        style={{
          background: "var(--bg-card)",
          backdropFilter: "blur(16px)",
          border: "1px solid var(--glass-border)",
        }}
      >
        <h2 className="section-header mb-5">
          <span className="flex items-center gap-2"><Send size={15} /> Compose Post</span>
        </h2>

        {/* Beat Selector */}
        <div className="mb-5">
          <label className="block text-xs font-semibold mb-2 uppercase tracking-wider text-text-tertiary">
            Select Beat
          </label>
          {beatsLoading ? (
            <Skeleton className="h-12 rounded-xl" />
          ) : (
            <div className="relative">
              <button
                type="button"
                onClick={() => setDropdownOpen(!dropdownOpen)}
                className="w-full flex items-center justify-between px-4 py-3 rounded-xl text-sm text-left transition-all duration-200 cursor-pointer"
                style={{
                  background: "var(--bg-hover)",
                  border: `1px solid ${dropdownOpen ? "var(--accent)" : "var(--border)"}`,
                  color: selectedBeat ? "var(--text-primary)" : "var(--text-tertiary)",
                }}
              >
                <div className="flex items-center gap-3">
                  {selectedBeat && (
                    <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: "rgba(var(--accent-rgb, 99,102,241), 0.15)" }}>
                      <Music size={14} className="text-accent" strokeWidth={1.8} />
                    </div>
                  )}
                  <span>{selectedBeat ? selectedBeat.title || selectedBeat.stem : "Choose a rendered beat..."}</span>
                </div>
                <ChevronDown size={16} className="text-text-tertiary transition-transform duration-200" style={{ transform: dropdownOpen ? "rotate(180deg)" : "rotate(0)" }} />
              </button>

              {dropdownOpen && (
                <div className="absolute z-50 w-full mt-1 rounded-xl overflow-hidden shadow-lg" style={{ background: "var(--bg-card-solid, var(--bg-card))", border: "1px solid var(--border-light)", maxHeight: 280 }}>
                  <div className="px-3 py-2" style={{ borderBottom: "1px solid var(--border)" }}>
                    <SearchInput
                      value={beatSearch}
                      onChange={setBeatSearch}
                      placeholder="Search beats..."
                      size="sm"
                      autoFocus
                    />
                  </div>
                  <div style={{ maxHeight: 220, overflowY: "auto" }}>
                    {filteredBeats.length === 0 ? (
                      <div className="px-4 py-6 text-center">
                        <p className="text-xs text-text-tertiary">
                          {renderedBeats.length === 0 ? "No rendered beats available" : "No beats match your search"}
                        </p>
                      </div>
                    ) : (
                      filteredBeats.map((b) => (
                        <button
                          key={b.stem}
                          type="button"
                          onClick={() => { setSelectedStem(b.stem); setDropdownOpen(false); setBeatSearch(""); }}
                          className="w-full flex items-center gap-3 px-4 py-3 text-left text-sm transition-all duration-150 cursor-pointer"
                          style={{
                            color: "var(--text-primary)",
                            background: b.stem === selectedStem ? "var(--bg-hover)" : "transparent",
                          }}
                          onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-hover)"; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = b.stem === selectedStem ? "var(--bg-hover)" : "transparent"; }}
                        >
                          <div className="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: "rgba(var(--accent-rgb, 99,102,241), 0.15)" }}>
                            <Music size={14} className="text-accent" strokeWidth={1.8} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium truncate">{b.title || b.stem}</p>
                            <div className="flex items-center gap-1.5 mt-0.5">
                              <span className="text-[10px] truncate text-text-tertiary">{b.stem}</span>
                              {(() => {
                                const posted = postedPlatforms(b);
                                if (posted.length === 0) return null;
                                return (
                                  <span className="flex items-center gap-0.5 ml-1">
                                    {posted.includes("instagram") && (
                                      <span className="w-3.5 h-3.5 rounded-sm flex items-center justify-center" style={{ background: "linear-gradient(135deg, #833AB4, #E1306C)" }}>
                                        <Instagram size={8} color="#fff" strokeWidth={2} />
                                      </span>
                                    )}
                                    {posted.includes("tiktok") && (
                                      <span className="w-3.5 h-3.5 rounded-sm flex items-center justify-center" style={{ background: "#010101" }}>
                                        <TikTokIcon size={8} color="#fff" />
                                      </span>
                                    )}
                                    {posted.includes("youtube_shorts") && (
                                      <span className="w-3.5 h-3.5 rounded-sm flex items-center justify-center" style={{ background: "#FF0000" }}>
                                        <YouTubeIcon size={8} />
                                      </span>
                                    )}
                                  </span>
                                );
                              })()}
                            </div>
                          </div>
                          {postedPlatforms(b).length === 3 && (
                            <span className="text-[9px] font-semibold px-1.5 py-0.5 rounded-full flex-shrink-0" style={{ background: "rgba(48,209,88,0.15)", color: "var(--success)" }}>ALL</span>
                          )}
                          {b.stem === selectedStem && <CheckCircle2 size={16} className="ml-auto flex-shrink-0 text-accent" />}
                        </button>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
          {renderedBeats.length === 0 && !beatsLoading && (
            <p className="text-xs mt-2 text-text-tertiary">No rendered beats found. Render some beats first.</p>
          )}
        </div>

        {/* Already Posted Indicator */}
        {selectedBeat && postedPlatforms(selectedBeat).length > 0 && (
          <div className="mb-4 flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs" style={{ background: "rgba(48,209,88,0.08)", border: "1px solid rgba(48,209,88,0.15)" }}>
            <CheckCircle2 size={13} style={{ color: "var(--success)" }} />
            <span className="text-text-secondary">Already posted to</span>
            <div className="flex items-center gap-1.5">
              {postedPlatforms(selectedBeat).map((p) => (
                <span
                  key={p}
                  className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] font-semibold"
                  style={{
                    background: p === "instagram" ? "linear-gradient(135deg, #833AB4, #E1306C)" : p === "tiktok" ? "#010101" : "#FF0000",
                    color: "#fff",
                  }}
                >
                  {p === "instagram" ? <><Instagram size={9} strokeWidth={2} /> IG</> :
                   p === "tiktok" ? <><TikTokIcon size={9} /> TT</> :
                   <><YouTubeIcon size={9} /> Shorts</>}
                </span>
              ))}
            </div>
            {postedPlatforms(selectedBeat).length === 3 && (
              <span className="ml-auto text-[10px] font-bold" style={{ color: "var(--success)" }}>All platforms</span>
            )}
          </div>
        )}

        {/* Caption Editor */}
        <div className="mb-5">
          <div className="flex items-center justify-between mb-2">
            <label className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">Caption</label>
            <span className={`text-xs tabular-nums ${caption.length > captionLimit ? "text-error" : "text-text-tertiary"}`}>
              {caption.length} / {captionLimit}
            </span>
          </div>
          <textarea
            value={caption}
            onChange={(e) => setCaption(e.target.value)}
            placeholder={selectedBeat ? `Write a caption for "${selectedBeat.title || selectedBeat.stem}"...` : "Select a beat first..."}
            rows={4}
            className="w-full px-4 py-3 rounded-xl text-sm outline-none resize-none transition-all duration-200"
            style={{
              background: "var(--bg-hover)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          />
        </div>

        {/* Hashtag Suggestions */}
        <div className="mb-5">
          <label className="flex items-center gap-1.5 text-xs font-semibold mb-2 uppercase tracking-wider text-text-tertiary">
            <Hash size={11} /> Hashtags
          </label>
          <div className="flex flex-wrap gap-2">
            {SUGGESTED_HASHTAGS.map((tag) => {
              const isActive = caption.includes(tag);
              return (
                <button
                  key={tag}
                  type="button"
                  onClick={() => { if (!isActive) addHashtag(tag); }}
                  className="px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all duration-150 cursor-pointer"
                  style={{
                    background: isActive ? "rgba(var(--accent-rgb, 99,102,241), 0.15)" : "var(--bg-hover)",
                    color: isActive ? "var(--accent)" : "var(--text-secondary)",
                    border: `1px solid ${isActive ? "var(--accent)" : "var(--border)"}`,
                    opacity: isActive ? 1 : 0.85,
                  }}
                >
                  {tag}
                </button>
              );
            })}
          </div>
        </div>

        {/* Dimension Status */}
        {selectedStem && (
          <div className="mb-5 p-4 rounded-xl" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
            <div className="flex items-center justify-between mb-3">
              <label className="text-xs font-semibold flex items-center gap-1.5 uppercase tracking-wider text-text-tertiary">
                <Monitor size={11} /> Video Dimensions
              </label>
              <Button type="button" onClick={() => setConvertOpen(true)} variant="ghost" size="xs" className="text-[11px] h-6 text-accent">
                Convert
              </Button>
            </div>
            <div className="flex flex-wrap gap-2">
              {[
                { key: "9x16", label: "9:16", icon: <Smartphone size={11} /> },
                { key: "4x5", label: "4:5", icon: <RectangleHorizontal size={11} className="rotate-90" /> },
                { key: "1x1", label: "1:1", icon: <Square size={11} /> },
              ].map((dim) => (
                <div
                  key={dim.key}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium"
                  style={{
                    background: dimStatus[dim.key]?.exists ? "rgba(48,209,88,0.1)" : "var(--bg-primary)",
                    color: dimStatus[dim.key]?.exists ? "var(--success)" : "var(--text-tertiary)",
                    border: `1px solid ${dimStatus[dim.key]?.exists ? "rgba(48,209,88,0.2)" : "var(--border)"}`,
                  }}
                >
                  {dim.icon} {dim.label}
                  {dimStatus[dim.key]?.exists && <CheckCircle2 size={10} />}
                  {dimStatus[dim.key]?.exists && dimStatus[dim.key]?.size_mb && (
                    <span className="opacity-70">{dimStatus[dim.key].size_mb}MB</span>
                  )}
                </div>
              ))}
            </div>
            {Object.values(dimStatus).some(d => !d.exists) && (
              <p className="text-[10px] text-text-tertiary mt-2">Missing formats? Click Convert to create them.</p>
            )}
          </div>
        )}

        {/* Status Messages */}
        {lastError && (
          <div className="flex items-center gap-2 px-4 py-3 rounded-xl text-sm mb-4" style={{ background: "rgba(255,69,58,0.1)", color: "var(--error)" }}>
            <AlertCircle size={16} />
            <span className="flex-1 text-xs">{lastError}</span>
            <button type="button" onClick={() => setLastError(null)} className="opacity-70 cursor-pointer"><XCircle size={14} /></button>
          </div>
        )}
        {lastSuccess && (
          <div className="flex items-center gap-2 px-4 py-3 rounded-xl text-sm mb-4" style={{ background: "rgba(48,209,88,0.1)", color: "var(--success)" }}>
            <CheckCircle2 size={16} />
            <span className="flex-1 text-xs">{lastSuccess}</span>
            <button type="button" onClick={() => setLastSuccess(null)} className="opacity-70 cursor-pointer"><XCircle size={14} /></button>
          </div>
        )}

        {/* Schedule Toggle */}
        <div className="mb-5 flex items-center gap-3">
          <button
            type="button"
            onClick={() => setScheduleMode(!scheduleMode)}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-all duration-200 cursor-pointer"
            style={{
              background: scheduleMode ? "rgba(var(--accent-rgb, 99,102,241), 0.15)" : "var(--bg-hover)",
              color: scheduleMode ? "var(--accent)" : "var(--text-secondary)",
              border: `1px solid ${scheduleMode ? "var(--accent)" : "var(--border)"}`,
            }}
          >
            <CalendarClock size={14} />
            {scheduleMode ? "Schedule Mode" : "Post Now"}
          </button>
          <span className="text-[10px] text-text-tertiary">
            {scheduleMode ? "Pick a date & time, then schedule" : "Post immediately to selected platforms"}
          </span>
        </div>

        {/* Schedule Datetime + Platform Picker (shown in schedule mode) */}
        {scheduleMode && (
          <div className="mb-5 p-4 rounded-xl space-y-4" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
            <div>
              <label className="block text-xs font-semibold mb-2 uppercase tracking-wider text-text-tertiary">
                Schedule Date & Time (EST)
              </label>
              <input
                type="datetime-local"
                value={scheduleTime}
                onChange={(e) => setScheduleTime(e.target.value)}
                className="w-full sm:w-auto px-4 py-2.5 rounded-xl text-sm outline-none transition-all duration-200"
                style={{
                  background: "var(--bg-primary)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </div>
            <div>
              <label className="block text-xs font-semibold mb-2 uppercase tracking-wider text-text-tertiary">
                Platforms
              </label>
              <div className="flex flex-wrap gap-2">
                {([
                  { key: "instagram" as const, label: "Instagram", icon: <Instagram size={13} strokeWidth={1.8} />, bg: "linear-gradient(135deg, #833AB4, #E1306C)" },
                  { key: "tiktok" as const, label: "TikTok", icon: <TikTokIcon size={13} />, bg: "#010101" },
                  { key: "youtube_shorts" as const, label: "Shorts", icon: <YouTubeIcon size={13} />, bg: "#FF0000" },
                ] as const).map((p) => {
                  const active = selectedSchedulePlatforms.has(p.key);
                  const alreadyPosted = selectedBeat ? postedPlatforms(selectedBeat).includes(p.key) : false;
                  return (
                    <button
                      key={p.key}
                      type="button"
                      onClick={() => toggleSchedulePlatform(p.key)}
                      className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-all duration-200 cursor-pointer"
                      style={{
                        background: active ? p.bg : "var(--bg-primary)",
                        color: active ? "#fff" : "var(--text-tertiary)",
                        border: `1px solid ${active ? "transparent" : "var(--border)"}`,
                        opacity: active ? 1 : 0.7,
                      }}
                    >
                      {p.icon} {p.label}
                      {alreadyPosted && <CheckCircle2 size={11} className="opacity-60" />}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* Post Controls */}
        {!scheduleMode ? (
          (() => {
            const posted = selectedBeat ? postedPlatforms(selectedBeat) : [];
            const igPosted = posted.includes("instagram");
            const ttPosted = posted.includes("tiktok");
            const ytPosted = posted.includes("youtube_shorts");
            return (
          <div className="flex flex-wrap gap-3">
            {/* Instagram */}
            <button
              type="button"
              onClick={() => postTo("instagram")}
              disabled={!selectedStem || igBusy}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              style={{
                background: !selectedStem || igBusy ? "var(--bg-hover)" : "linear-gradient(135deg, #833AB4, #E1306C)",
                color: !selectedStem || igBusy ? "var(--text-tertiary)" : "#fff",
              }}
            >
              {igBusy ? <Loader2 size={16} className="animate-spin" /> : <Instagram size={16} strokeWidth={1.8} />}
              Instagram
              {igPosted && !igBusy && <CheckCircle2 size={13} className="opacity-70" />}
            </button>

            {/* TikTok */}
            <button
              type="button"
              onClick={() => postTo("tiktok")}
              disabled={!selectedStem || ttBusy}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              style={{
                background: !selectedStem || ttBusy ? "var(--bg-hover)" : "#010101",
                color: !selectedStem || ttBusy ? "var(--text-tertiary)" : "#fff",
              }}
            >
              {ttBusy ? <Loader2 size={16} className="animate-spin" /> : <TikTokIcon size={16} color={!selectedStem || ttBusy ? undefined : "#fff"} />}
              TikTok
              {ttPosted && !ttBusy && <CheckCircle2 size={13} className="opacity-70" />}
            </button>

            {/* YouTube Shorts */}
            <button
              type="button"
              onClick={() => postTo("youtube_shorts")}
              disabled={!selectedStem || ytBusy}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              style={{
                background: !selectedStem || ytBusy ? "var(--bg-hover)" : "#FF0000",
                color: !selectedStem || ytBusy ? "var(--text-tertiary)" : "#fff",
              }}
            >
              {ytBusy ? <Loader2 size={16} className="animate-spin" /> : <YouTubeIcon size={16} color={!selectedStem || ytBusy ? "currentColor" : "#fff"} />}
              Shorts
              {ytPosted && !ytBusy && <CheckCircle2 size={13} className="opacity-70" />}
            </button>

            {/* Post All */}
            <button
              type="button"
              onClick={postToAll}
              disabled={!selectedStem || anyBusy}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer btn-gradient"
            >
              {anyBusy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} strokeWidth={1.8} />}
              {posted.length === 3 ? "Repost All" : posted.length > 0 ? "Post All" : "Post All"}
            </button>

            {/* Download */}
            <Button type="button" onClick={downloadForTikTok} disabled={!selectedStem} variant="outline" size="sm" className="text-xs rounded-xl">
              <Download size={14} strokeWidth={1.8} /> Download 9:16
            </Button>
          </div>
            );
          })()
        ) : (
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={schedulePost}
              disabled={!selectedStem || !scheduleTime || selectedSchedulePlatforms.size === 0}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-bold transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer btn-gradient"
            >
              <CalendarClock size={16} />
              Schedule{selectedSchedulePlatforms.size > 0 ? ` (${selectedSchedulePlatforms.size})` : ""}
            </button>

            {/* Download */}
            <Button type="button" onClick={downloadForTikTok} disabled={!selectedStem} variant="outline" size="sm" className="text-xs rounded-xl">
              <Download size={14} strokeWidth={1.8} /> Download 9:16
            </Button>
          </div>
        )}
      </div>

      {/* ═══════════════════════════════════════════════════════
          POST HISTORY & SCHEDULED
          ═══════════════════════════════════════════════════════ */}
      <div
        className="mb-8 p-6 rounded-2xl"
        style={{
          background: "var(--bg-card)",
          backdropFilter: "blur(16px)",
          border: "1px solid var(--glass-border)",
        }}
      >
        {/* Tab pills: History | Scheduled */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 mb-4">
          <div className="flex items-center gap-1 p-1 rounded-xl" style={{ background: "var(--bg-hover)" }}>
            <button
              type="button"
              onClick={() => setHistoryTab("history")}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer"
              style={{
                background: historyTab === "history" ? "var(--bg-card)" : "transparent",
                color: historyTab === "history" ? "var(--text-primary)" : "var(--text-tertiary)",
                boxShadow: historyTab === "history" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
              }}
            >
              <Clock size={13} /> History
            </button>
            <button
              type="button"
              onClick={() => { setHistoryTab("scheduled"); fetchScheduled(); }}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer"
              style={{
                background: historyTab === "scheduled" ? "var(--bg-card)" : "transparent",
                color: historyTab === "scheduled" ? "var(--text-primary)" : "var(--text-tertiary)",
                boxShadow: historyTab === "scheduled" ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
              }}
            >
              <CalendarClock size={13} /> Scheduled
              {pendingScheduleCount > 0 && (
                <span className="ml-0.5 px-1.5 py-0.5 rounded-full text-[9px] font-bold text-white" style={{ background: "var(--accent)" }}>
                  {pendingScheduleCount}
                </span>
              )}
            </button>
          </div>

          {/* Filter pills (only in history tab) */}
          {historyTab === "history" && (
            <div className="flex flex-wrap items-center gap-1">
              <Filter size={12} className="text-text-tertiary mr-1" />
              {(["all", "instagram", "tiktok", "youtube_shorts"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setHistoryFilter(f)}
                  className="px-2.5 py-1 rounded-lg text-[10px] font-semibold transition-all cursor-pointer"
                  style={{
                    background: historyFilter === f ? "var(--accent)" : "var(--bg-hover)",
                    color: historyFilter === f ? "#fff" : "var(--text-tertiary)",
                  }}
                >
                  {f === "all" ? "All" : f === "youtube_shorts" ? "Shorts" : platformName(f)}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* ─── History Tab ─── */}
        {historyTab === "history" && (
          <>
            {filteredHistory.length === 0 ? (
              <div className="text-center py-10">
                <Share2 className="mx-auto mb-3 text-text-tertiary" style={{ opacity: 0.2 }} size={32} />
                <p className="text-sm font-medium text-text-secondary">No posts yet</p>
                <p className="text-xs text-text-tertiary mt-1">Select a beat and post it to see your history here</p>
              </div>
            ) : (
              <div className="space-y-2">
                {filteredHistory.map((post) => (
                  <div
                    key={post.id}
                    className="flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-150"
                    style={{ background: "var(--bg-hover)" }}
                  >
                    {/* Platform icon */}
                    <div
                      className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{
                        background: post.platform === "instagram"
                          ? "linear-gradient(135deg, #833AB4, #E1306C, #F77737)"
                          : post.platform === "youtube_shorts"
                          ? "#FF0000"
                          : "#010101",
                      }}
                    >
                      {post.platform === "instagram" ? <Instagram size={14} color="#fff" strokeWidth={1.8} /> :
                       post.platform === "youtube_shorts" ? <YouTubeIcon size={14} /> :
                       <TikTokIcon size={14} color="#fff" />}
                    </div>

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate text-foreground">{post.title}</p>
                      <p className="text-[10px] text-text-tertiary">
                        {platformName(post.platform)} · {new Date(post.postedAt).toLocaleDateString("en-US", {
                          month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
                        })}
                      </p>
                    </div>

                    {/* Status */}
                    {post.status === "posted" ? (
                      <Badge variant="success" className="gap-1"><CheckCircle2 size={10} /> Posted</Badge>
                    ) : post.status === "failed" ? (
                      <Badge variant="error" className="gap-1"><XCircle size={10} /> Failed</Badge>
                    ) : (
                      <Badge variant="warning" className="gap-1"><Clock size={10} /> Pending</Badge>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* ─── Scheduled Tab ─── */}
        {historyTab === "scheduled" && (
          <>
            {scheduledLoading && scheduledPosts.length === 0 ? (
              <div className="text-center py-10">
                <Loader2 size={24} className="animate-spin mx-auto mb-3 text-text-tertiary" />
                <p className="text-xs text-text-tertiary">Loading scheduled posts...</p>
              </div>
            ) : scheduledPosts.length === 0 ? (
              <div className="text-center py-10">
                <CalendarClock className="mx-auto mb-3 text-text-tertiary" style={{ opacity: 0.2 }} size={32} />
                <p className="text-sm font-medium text-text-secondary">No scheduled posts</p>
                <p className="text-xs text-text-tertiary mt-1">Toggle &quot;Schedule Mode&quot; above to schedule posts for later</p>
              </div>
            ) : (
              <div className="space-y-2">
                {scheduledPosts.map((sp) => {
                  const beatTitle = beats?.find((b) => b.stem === sp.stem)?.title || sp.stem.replace(/_/g, " ");
                  const scheduledDate = new Date(sp.scheduled_at);
                  const now = new Date();
                  const diffMs = scheduledDate.getTime() - now.getTime();
                  const isPast = diffMs <= 0;
                  const diffMins = Math.round(diffMs / 60_000);
                  const diffHours = Math.round(diffMs / 3_600_000);
                  const diffDays = Math.round(diffMs / 86_400_000);

                  let timeLabel = "";
                  if (isPast) {
                    timeLabel = "Due now";
                  } else if (diffMins < 60) {
                    timeLabel = `in ${diffMins}m`;
                  } else if (diffHours < 24) {
                    timeLabel = `in ${diffHours}h`;
                  } else {
                    timeLabel = `in ${diffDays}d`;
                  }

                  return (
                    <div
                      key={sp.id}
                      className="flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-150"
                      style={{ background: "var(--bg-hover)" }}
                    >
                      {/* Platform badges */}
                      <div className="flex flex-col gap-1">
                        {sp.platforms.map((plat) => (
                          <div
                            key={plat}
                            className="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0"
                            style={{
                              background: plat === "instagram"
                                ? "linear-gradient(135deg, #833AB4, #E1306C)"
                                : plat === "youtube_shorts"
                                ? "#FF0000"
                                : "#010101",
                            }}
                          >
                            {plat === "instagram" ? <Instagram size={12} color="#fff" strokeWidth={1.8} /> :
                             plat === "youtube_shorts" ? <YouTubeIcon size={12} /> :
                             <TikTokIcon size={12} color="#fff" />}
                          </div>
                        ))}
                      </div>

                      {/* Info */}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate text-foreground">{beatTitle}</p>
                        <p className="text-[10px] text-text-tertiary">
                          {sp.platforms.map((p) => platformName(p)).join(", ")} · {scheduledDate.toLocaleDateString("en-US", {
                            month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
                          })}
                        </p>
                        {sp.caption && (
                          <p className="text-[10px] text-text-tertiary mt-0.5 truncate">{sp.caption}</p>
                        )}
                      </div>

                      {/* Countdown + Status */}
                      <div className="flex items-center gap-2">
                        {sp.status === "pending" && (
                          <span className="flex items-center gap-1 text-[10px] font-medium tabular-nums" style={{ color: "var(--accent)" }}>
                            <Timer size={10} /> {timeLabel}
                          </span>
                        )}
                        <Badge
                          variant={
                            sp.status === "done" ? "success"
                              : sp.status === "failed" ? "error"
                              : sp.status === "running" ? "warning"
                              : sp.status === "cancelled" ? "secondary"
                              : "default"
                          }
                          className="gap-1 text-[10px]"
                        >
                          {sp.status === "pending" && <Clock size={9} />}
                          {sp.status === "running" && <Loader2 size={9} className="animate-spin" />}
                          {sp.status === "done" && <CheckCircle2 size={9} />}
                          {sp.status === "failed" && <XCircle size={9} />}
                          {sp.status === "cancelled" && <XCircle size={9} />}
                          {sp.status.charAt(0).toUpperCase() + sp.status.slice(1)}
                        </Badge>
                        {sp.status === "pending" && (
                          <button
                            type="button"
                            onClick={() => cancelScheduledPost(sp.id)}
                            className="p-1.5 rounded-lg transition-all cursor-pointer"
                            style={{ color: "var(--text-tertiary)" }}
                            onMouseEnter={(e) => { e.currentTarget.style.color = "var(--error)"; e.currentTarget.style.background = "rgba(255,69,58,0.1)"; }}
                            onMouseLeave={(e) => { e.currentTarget.style.color = "var(--text-tertiary)"; e.currentTarget.style.background = "transparent"; }}
                            title="Cancel scheduled post"
                          >
                            <Trash2 size={13} />
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>

      {/* Dimension Converter Modal */}
      {selectedStem && (
        <DimensionConverter
          stems={[selectedStem]}
          open={convertOpen}
          onClose={() => setConvertOpen(false)}
          onComplete={() => {
            api.get<Record<string, unknown>>(`/convert/status/${selectedStem}`)
              .then((data) => {
                const statuses: Record<string, { exists: boolean; size_mb?: number; label?: string }> = {};
                for (const key of ["9x16", "4x5", "1x1"]) {
                  const ps = data[key] as { exists: boolean; size_mb?: number; label?: string } | undefined;
                  if (ps) statuses[key] = ps;
                }
                setDimStatus(statuses);
              })
              .catch(() => {});
          }}
        />
      )}
    </div>
  );
}
