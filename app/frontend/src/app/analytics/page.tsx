"use client";

import { useState, useMemo } from "react";
import {
  Upload,
  Film,
  Calendar,
  ExternalLink,
  Clock,
  TrendingUp,
  ChevronLeft,
  ChevronRight,
  BarChart3,
  Activity,
  X,
  Eye,
  Heart,
  MessageCircle,
  Zap,
  RefreshCw,
  Shield,
  Youtube,
  Instagram,
  Smartphone,
} from "lucide-react";
import { useFetch, api } from "@/hooks/useApi";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

/* ─── Types ───────────────────────────────────────────────────── */

interface AnalyticsData {
  summary: {
    total_beats: number;
    rendered: number;
    uploaded_yt: number;
    uploaded_social: number;
    pending_renders: number;
  };
  uploads: UploadEntry[];
  daily_counts: Record<string, number>;
  social_distribution?: {
    youtube: number;
    youtube_shorts: number;
    instagram: number;
    tiktok: number;
  };
  schedule_health?: {
    buffer_days: number;
    queue_length: number;
  };
}

interface UploadEntry {
  stem: string;
  title: string;
  uploadedAt: string;
  url: string;
  publishAt?: string;
  videoId?: string;
}

interface YouTubeStats {
  fetched_at: string | null;
  video_count: number;
  totals: { views: number; likes: number; comments: number };
  averages: { views_per_video: number; likes_per_video: number };
  top_videos: TopVideo[];
  error?: string;
}

interface TopVideo {
  stem: string;
  title: string;
  url: string;
  videoId: string;
  viewCount: number;
  likeCount: number;
  commentCount: number;
  uploadedAt?: string;
}

interface ArtistPerf {
  artist: string;
  videos: number;
  total_views: number;
  avg_views: number;
  total_likes: number;
  avg_likes: number;
  total_comments: number;
}

/* ─── Helpers ─────────────────────────────────────────────────── */

const MONTHS = [
  "January","February","March","April","May","June",
  "July","August","September","October","November","December",
];
const DAYS_SHORT = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];

function formatDate(dateStr: string) {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function formatTime(dateStr: string) {
  const d = new Date(dateStr);
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function dateKey(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function formatViews(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function getWeeklyRate(uploads: UploadEntry[]): string {
  if (!uploads || uploads.length === 0) return "0";
  const dates = uploads.map((u) => new Date(u.uploadedAt).getTime());
  const earliest = Math.min(...dates);
  const latest = Math.max(...dates);
  const weeks = Math.max(1, (latest - earliest) / (7 * 24 * 60 * 60 * 1000));
  return (uploads.length / weeks).toFixed(1);
}

function timeAgo(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

/* ─── Artist lane colors ──────────────────────────────────────── */

const ARTIST_COLORS: Record<string, string> = {
  "Glokk40Spaz": "#3b82f6",
  "OsamaSon": "#60a5fa",
  "BiggKutt8": "#22c55e",
  "Ola Runt": "#4ade80",
  "Sexyy Red": "#ec4899",
  "GloRilla": "#f472b6",
  "Babyxsosa": "#a855f7",
  "Sukihana": "#f43f5e",
};

/* ─── Card Component ──────────────────────────────────────────── */

function StatCard({ icon: Icon, value, label, color, loading: isLoading }: {
  icon: React.ElementType;
  value: string | number;
  label: string;
  color: string;
  loading?: boolean;
}) {
  return (
    <div
      className="p-5 rounded-2xl transition-all duration-200"
      style={{
        background: "var(--bg-card)",
        backdropFilter: "blur(16px)",
        border: "1px solid var(--glass-border)",
      }}
    >
      {isLoading ? (
        <div className="space-y-3">
          <Skeleton className="w-8 h-8 rounded-lg" />
          <Skeleton className="h-8 w-16" />
          <Skeleton className="h-3 w-20" />
        </div>
      ) : (
        <>
          <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-3" style={{ background: `${color}15` }}>
            <Icon size={16} style={{ color }} />
          </div>
          <p className="text-2xl font-extrabold text-foreground tabular-nums">{value}</p>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary mt-1">{label}</p>
        </>
      )}
    </div>
  );
}

/* ─── Section wrapper ─────────────────────────────────────────── */

function Section({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`p-6 rounded-2xl ${className}`}
      style={{
        background: "var(--bg-card)",
        backdropFilter: "blur(16px)",
        border: "1px solid var(--glass-border)",
      }}
    >
      {children}
    </div>
  );
}

/* ─── Page ────────────────────────────────────────────────────── */

export default function AnalyticsPage() {
  const { data, loading } = useFetch<AnalyticsData>("/analytics");
  const { data: ytStats, loading: ytLoading, refetch: refetchYt } = useFetch<YouTubeStats>("/analytics/youtube-stats");
  const { data: artistPerf } = useFetch<ArtistPerf[]>("/analytics/artist-performance");
  const [refreshing, setRefreshing] = useState(false);

  const uploads = data?.uploads ?? [];
  const summary = data?.summary;
  const dailyCounts = data?.daily_counts ?? {};
  const social = data?.social_distribution;
  const scheduleHealth = data?.schedule_health;

  // Calendar state
  const now = new Date();
  const [calYear, setCalYear] = useState(now.getFullYear());
  const [calMonth, setCalMonth] = useState(now.getMonth());
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

  // Upload frequency chart data (last 30 days)
  const chartData = useMemo(() => {
    const days: { label: string; count: number; dateKey: string }[] = [];
    for (let i = 29; i >= 0; i--) {
      const d = new Date();
      d.setDate(d.getDate() - i);
      const dk = dateKey(d.getFullYear(), d.getMonth(), d.getDate());
      days.push({ label: `${d.getMonth() + 1}/${d.getDate()}`, count: dailyCounts[dk] ?? 0, dateKey: dk });
    }
    return days;
  }, [dailyCounts]);

  const maxCount = Math.max(1, ...chartData.map((d) => d.count));
  const totalUploads30d = chartData.reduce((sum, d) => sum + d.count, 0);

  // Calendar grid
  const calendarDays = useMemo(() => {
    const firstDay = new Date(calYear, calMonth, 1).getDay();
    const daysInMonth = new Date(calYear, calMonth + 1, 0).getDate();
    const days: (number | null)[] = [];
    for (let i = 0; i < firstDay; i++) days.push(null);
    for (let d = 1; d <= daysInMonth; d++) days.push(d);
    return days;
  }, [calYear, calMonth]);

  const prevMonth = () => {
    if (calMonth === 0) { setCalMonth(11); setCalYear(calYear - 1); }
    else setCalMonth(calMonth - 1);
    setSelectedDate(null);
  };
  const nextMonth = () => {
    if (calMonth === 11) { setCalMonth(0); setCalYear(calYear + 1); }
    else setCalMonth(calMonth + 1);
    setSelectedDate(null);
  };
  const isToday = (day: number) =>
    day === now.getDate() && calMonth === now.getMonth() && calYear === now.getFullYear();
  const getDayCount = (day: number) => dailyCounts[dateKey(calYear, calMonth, day)] ?? 0;

  const monthUploadCount = useMemo(() => {
    let count = 0;
    const daysInMonth = new Date(calYear, calMonth + 1, 0).getDate();
    for (let d = 1; d <= daysInMonth; d++) count += dailyCounts[dateKey(calYear, calMonth, d)] ?? 0;
    return count;
  }, [dailyCounts, calYear, calMonth]);

  const selectedDateUploads = useMemo(() => {
    if (!selectedDate) return [];
    return uploads.filter((u) => {
      const d = new Date(u.uploadedAt);
      return dateKey(d.getFullYear(), d.getMonth(), d.getDate()) === selectedDate;
    });
  }, [uploads, selectedDate]);

  const handleDayClick = (day: number) => {
    const dk = dateKey(calYear, calMonth, day);
    setSelectedDate(selectedDate === dk ? null : dk);
  };

  // Refresh YouTube stats
  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await api.post("/analytics/youtube-stats/refresh", {});
      refetchYt();
    } catch {
      // ignore
    }
    setRefreshing(false);
  };

  // Top videos
  const topVideos = ytStats?.top_videos ?? [];
  const maxViews = Math.max(1, ...topVideos.map((v) => v.viewCount));

  // Artist performance
  const artists = artistPerf ?? [];
  const maxArtistViews = Math.max(1, ...artists.map((a) => a.avg_views));

  // Buffer days color
  const bufferColor = scheduleHealth
    ? scheduleHealth.buffer_days > 14 ? "#22c55e" : scheduleHealth.buffer_days > 7 ? "#f59e0b" : "#ef4444"
    : "#6b7280";

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="page-header">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="flex items-center gap-2">
              <BarChart3 size={20} className="text-accent" />
              Analytics
            </h1>
            <p className="page-subtitle">YouTube performance and channel insights</p>
          </div>
          <div className="flex items-center gap-2">
            {ytStats?.fetched_at && (
              <span className="text-[10px] text-text-tertiary">
                Updated {timeAgo(ytStats.fetched_at)}
              </span>
            )}
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={handleRefresh}
              disabled={refreshing}
              className="text-text-tertiary hover:text-accent"
            >
              <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
            </Button>
          </div>
        </div>
      </div>

      {/* ═══════════════════════════════════════════════════════
          SECTION A: YOUTUBE PERFORMANCE CARDS
          ═══════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <StatCard
          icon={Eye}
          value={ytLoading ? "..." : formatViews(ytStats?.totals?.views ?? 0)}
          label="Total Views"
          color="#3b82f6"
          loading={ytLoading}
        />
        <StatCard
          icon={Heart}
          value={ytLoading ? "..." : formatViews(ytStats?.totals?.likes ?? 0)}
          label="Total Likes"
          color="#ef4444"
          loading={ytLoading}
        />
        <StatCard
          icon={TrendingUp}
          value={ytLoading ? "..." : formatViews(ytStats?.averages?.views_per_video ?? 0)}
          label="Avg Views / Video"
          color="#22c55e"
          loading={ytLoading}
        />
        <StatCard
          icon={Zap}
          value={loading ? "..." : getWeeklyRate(uploads)}
          label="Uploads / Week"
          color="#f59e0b"
          loading={loading}
        />
      </div>

      {/* ═══════════════════════════════════════════════════════
          SECTION B: TOP VIDEOS + UPLOAD FREQUENCY
          ═══════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 mb-6">
        {/* Top Videos by Views */}
        <Section>
          <h2 className="section-header mb-4">
            <span className="flex items-center gap-2"><Eye size={15} /> Top Videos</span>
          </h2>
          {ytLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-6 w-full" />)}
            </div>
          ) : topVideos.length === 0 ? (
            <p className="text-xs text-text-tertiary py-4 text-center">No YouTube stats yet</p>
          ) : (
            <div className="space-y-2.5">
              {topVideos.slice(0, 10).map((video, i) => (
                <div key={video.videoId} className="flex items-center gap-3">
                  <span className="text-[10px] text-text-tertiary w-4 text-right font-bold">{i + 1}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-medium truncate text-foreground" style={{ maxWidth: "60%" }}>
                        {video.title || video.stem}
                      </span>
                      {video.url && (
                        <a href={video.url} target="_blank" rel="noopener noreferrer" className="flex-shrink-0">
                          <ExternalLink size={10} className="text-text-tertiary hover:text-accent transition-colors" />
                        </a>
                      )}
                    </div>
                    <div className="h-4 rounded-full overflow-hidden" style={{ background: "var(--bg-hover)" }}>
                      <div
                        className="h-full rounded-full transition-all duration-500"
                        style={{
                          width: `${Math.max(2, (video.viewCount / maxViews) * 100)}%`,
                          background: "linear-gradient(90deg, var(--accent), #8b5cf6)",
                        }}
                      />
                    </div>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    <span className="text-xs font-bold text-foreground tabular-nums w-12 text-right">
                      {formatViews(video.viewCount)}
                    </span>
                    <span className="text-[10px] text-text-tertiary flex items-center gap-0.5">
                      <Heart size={8} /> {formatViews(video.likeCount)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* Upload Frequency (30 days) */}
        <Section>
          <div className="flex items-center justify-between mb-4">
            <h2 className="section-header mb-0">
              <span className="flex items-center gap-2"><Activity size={15} /> Upload Frequency</span>
            </h2>
            <span className="text-xs text-text-tertiary">
              <span className="font-semibold text-foreground">{totalUploads30d}</span> in 30 days
            </span>
          </div>
          <div className="flex items-end gap-[2px] h-36">
            {chartData.map((day, i) => {
              const height = day.count > 0 ? Math.max(12, (day.count / maxCount) * 100) : 0;
              const showLabel = i === 0 || i === chartData.length - 1 || i % 7 === 0;
              return (
                <div key={day.dateKey} className="flex-1 flex flex-col items-center justify-end group relative">
                  <div
                    className="w-full rounded-t transition-all duration-200 group-hover:brightness-125"
                    style={{
                      height: day.count > 0 ? `${height}%` : 3,
                      background: day.count > 0 ? "var(--accent)" : "var(--bg-hover)",
                      opacity: day.count > 0 ? 0.9 : 0.3,
                    }}
                  />
                  {day.count > 0 && (
                    <div
                      className="absolute -top-9 left-1/2 -translate-x-1/2 px-2 py-1 rounded-md text-[9px] font-bold whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10"
                      style={{ background: "var(--bg-card-solid, var(--bg-card))", border: "1px solid var(--border)", color: "var(--text-primary)" }}
                    >
                      {day.label}: {day.count}
                    </div>
                  )}
                  {showLabel && (
                    <span className="text-[8px] text-text-tertiary mt-1 whitespace-nowrap">{day.label}</span>
                  )}
                </div>
              );
            })}
          </div>
        </Section>
      </div>

      {/* ═══════════════════════════════════════════════════════
          SECTION C: PERFORMANCE BY ARTIST
          ═══════════════════════════════════════════════════════ */}
      {artists.length > 0 && (
        <Section className="mb-6">
          <h2 className="section-header mb-4">
            <span className="flex items-center gap-2"><TrendingUp size={15} /> Performance by Artist</span>
          </h2>
          <div className="space-y-3">
            {artists.map((artist) => {
              const color = ARTIST_COLORS[artist.artist] || "var(--accent)";
              const pct = Math.max(2, (artist.avg_views / maxArtistViews) * 100);
              return (
                <div key={artist.artist} className="flex items-center gap-3">
                  <span className="w-28 text-xs font-medium text-foreground truncate">{artist.artist}</span>
                  <div className="flex-1 h-5 rounded-full overflow-hidden" style={{ background: "var(--bg-hover)" }}>
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{ width: `${pct}%`, background: color }}
                    />
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0 text-[10px] text-text-tertiary">
                    <span className="w-12 text-right">
                      <span className="font-bold text-foreground">{formatViews(artist.avg_views)}</span> avg
                    </span>
                    <span className="w-20 text-right">{artist.videos} video{artist.videos !== 1 ? "s" : ""}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* ═══════════════════════════════════════════════════════
          SECTION D: SOCIAL DISTRIBUTION + SCHEDULE HEALTH
          ═══════════════════════════════════════════════════════ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5 mb-6">
        {/* Social Distribution */}
        {social && (
          <Section>
            <h2 className="section-header mb-4">
              <span className="flex items-center gap-2"><Smartphone size={15} /> Distribution</span>
            </h2>
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "YouTube", count: social.youtube, color: "#FF0000", icon: Youtube },
                { label: "Shorts", count: social.youtube_shorts, color: "#FF0000", icon: Film },
                { label: "Instagram", count: social.instagram, color: "#E4405F", icon: Instagram },
                { label: "TikTok", count: social.tiktok, color: "#fff", icon: Smartphone },
              ].map((p) => {
                const Ico = p.icon;
                return (
                  <div
                    key={p.label}
                    className="p-4 rounded-xl flex items-center gap-3"
                    style={{ background: "var(--bg-hover)" }}
                  >
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: `${p.color}15` }}>
                      <Ico size={14} style={{ color: p.color }} />
                    </div>
                    <div>
                      <p className="text-lg font-extrabold text-foreground tabular-nums">{p.count}</p>
                      <p className="text-[9px] font-semibold uppercase tracking-wider text-text-tertiary">{p.label}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </Section>
        )}

        {/* Schedule Health + Pipeline */}
        <Section>
          <h2 className="section-header mb-4">
            <span className="flex items-center gap-2"><Shield size={15} /> Pipeline Health</span>
          </h2>
          <div className="grid grid-cols-2 gap-3">
            {scheduleHealth && (
              <>
                <div className="p-4 rounded-xl" style={{ background: "var(--bg-hover)" }}>
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-2" style={{ background: `${bufferColor}15` }}>
                    <Calendar size={14} style={{ color: bufferColor }} />
                  </div>
                  <p className="text-lg font-extrabold text-foreground tabular-nums">{scheduleHealth.buffer_days}d</p>
                  <p className="text-[9px] font-semibold uppercase tracking-wider text-text-tertiary">Buffer Days</p>
                </div>
                <div className="p-4 rounded-xl" style={{ background: "var(--bg-hover)" }}>
                  <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-2" style={{ background: "#6366f115" }}>
                    <Film size={14} style={{ color: "#6366f1" }} />
                  </div>
                  <p className="text-lg font-extrabold text-foreground tabular-nums">{scheduleHealth.queue_length}</p>
                  <p className="text-[9px] font-semibold uppercase tracking-wider text-text-tertiary">Queue Length</p>
                </div>
              </>
            )}
            <div className="p-4 rounded-xl" style={{ background: "var(--bg-hover)" }}>
              <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-2" style={{ background: "#22c55e15" }}>
                <Upload size={14} style={{ color: "#22c55e" }} />
              </div>
              <p className="text-lg font-extrabold text-foreground tabular-nums">{summary?.rendered ?? 0}</p>
              <p className="text-[9px] font-semibold uppercase tracking-wider text-text-tertiary">Rendered</p>
            </div>
            <div className="p-4 rounded-xl" style={{ background: "var(--bg-hover)" }}>
              <div className="w-8 h-8 rounded-lg flex items-center justify-center mb-2" style={{ background: "#f59e0b15" }}>
                <Clock size={14} style={{ color: "#f59e0b" }} />
              </div>
              <p className="text-lg font-extrabold text-foreground tabular-nums">{summary?.pending_renders ?? 0}</p>
              <p className="text-[9px] font-semibold uppercase tracking-wider text-text-tertiary">Pending</p>
            </div>
          </div>
        </Section>
      </div>

      {/* ═══════════════════════════════════════════════════════
          SECTION E: TIMELINE + CALENDAR
          ═══════════════════════════════════════════════════════ */}
      <div className="flex flex-col lg:flex-row gap-5 items-start">
        {/* Upload Timeline */}
        <Section className="flex-1 min-w-0 w-full">
          <h2 className="section-header mb-4">
            <span className="flex items-center gap-2"><Upload size={15} /> Upload Timeline</span>
          </h2>
          {loading ? (
            <div className="space-y-4">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="flex items-center gap-4">
                  <Skeleton className="w-10 h-10 rounded-lg flex-shrink-0" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-[60%]" />
                    <Skeleton className="h-3 w-[40%]" />
                  </div>
                </div>
              ))}
            </div>
          ) : uploads.length === 0 ? (
            <div className="text-center py-10">
              <Upload className="mx-auto mb-3 text-text-tertiary" style={{ opacity: 0.2 }} size={32} />
              <p className="text-sm font-medium text-text-secondary">No uploads yet</p>
              <p className="text-xs text-text-tertiary mt-1">Uploaded videos will appear here</p>
            </div>
          ) : (
            <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
              {uploads.slice(0, 50).map((upload, idx) => (
                <div
                  key={`${upload.stem}-${idx}`}
                  className="flex items-center gap-4 px-4 py-3 rounded-xl transition-all duration-200"
                  style={{ background: "var(--bg-hover)" }}
                >
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0" style={{ background: "rgba(48,209,88,0.1)" }}>
                    <Upload size={14} style={{ color: "#30d158" }} strokeWidth={1.8} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate text-foreground">{upload.title || upload.stem}</p>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-0.5">
                      <span className="text-[10px] text-text-tertiary whitespace-nowrap">
                        {formatDate(upload.uploadedAt)} at {formatTime(upload.uploadedAt)}
                      </span>
                      {upload.publishAt && (
                        <span className="text-[9px] px-2 py-0.5 rounded-md font-medium inline-flex items-center gap-1 whitespace-nowrap"
                          style={{ background: "rgba(255,159,10,0.1)", color: "var(--warning, #ff9f0a)" }}>
                          <Calendar size={8} /> Scheduled: {formatDate(upload.publishAt)}
                        </span>
                      )}
                    </div>
                  </div>
                  {upload.url && (
                    <a
                      href={upload.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded-lg transition-all duration-200 flex-shrink-0 font-medium"
                      style={{ background: "rgba(255,0,0,0.1)", color: "#FF0000" }}
                    >
                      <ExternalLink size={11} /> YouTube
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* Upload Calendar */}
        <div
          className="w-full lg:w-[340px] lg:min-w-[340px] p-6 rounded-2xl"
          style={{
            background: "var(--bg-card)",
            backdropFilter: "blur(16px)",
            border: "1px solid var(--glass-border)",
          }}
        >
          <h2 className="section-header mb-4">
            <span className="flex items-center gap-2"><Calendar size={15} /> Calendar</span>
          </h2>

          <div className="flex items-center justify-between mb-4">
            <Button variant="ghost" size="icon-sm" onClick={prevMonth} className="text-text-tertiary">
              <ChevronLeft size={16} />
            </Button>
            <div className="text-center">
              <p className="text-sm font-semibold text-foreground">{MONTHS[calMonth]} {calYear}</p>
              {monthUploadCount > 0 && (
                <p className="text-[10px] mt-0.5 text-text-tertiary">
                  {monthUploadCount} upload{monthUploadCount !== 1 ? "s" : ""}
                </p>
              )}
            </div>
            <Button variant="ghost" size="icon-sm" onClick={nextMonth} className="text-text-tertiary">
              <ChevronRight size={16} />
            </Button>
          </div>

          <div className="grid grid-cols-7 gap-0 mb-1">
            {DAYS_SHORT.map((d) => (
              <div key={d} className="text-center text-[10px] font-medium py-1 text-text-tertiary">{d}</div>
            ))}
          </div>

          <div className="grid grid-cols-7 gap-0">
            {calendarDays.map((day, i) => {
              if (day === null) return <div key={i} style={{ height: 40 }} />;
              const count = getDayCount(day);
              const dk = dateKey(calYear, calMonth, day);
              const isSelected = selectedDate === dk;
              const today = isToday(day);
              return (
                <div key={i} className="flex flex-col items-center justify-center py-1" style={{ height: 42 }}>
                  <button
                    onClick={() => handleDayClick(day)}
                    className="relative flex items-center justify-center cursor-pointer transition-all duration-150 rounded-lg w-[32px] h-[32px]"
                    style={{
                      background: isSelected ? "var(--accent)" : today ? "var(--accent-muted)" : count > 0 ? "var(--bg-hover)" : "transparent",
                      color: isSelected || today ? isSelected ? "#fff" : "var(--accent)" : count > 0 ? "var(--text-primary)" : "var(--text-tertiary)",
                      fontWeight: count > 0 || today ? 700 : 400,
                    }}
                  >
                    <span className="text-xs">{day}</span>
                    {count > 0 && (
                      <span className="absolute w-[5px] h-[5px] rounded-full" style={{
                        bottom: 2, left: "50%", transform: "translateX(-50%)",
                        background: isSelected ? "#fff" : "var(--accent)",
                      }} />
                    )}
                    {count > 1 && (
                      <span className="absolute -top-0.5 -right-0.5 text-[8px] font-bold w-[14px] h-[14px] rounded-full flex items-center justify-center"
                        style={{ background: "var(--accent)", color: "#fff" }}>
                        {count}
                      </span>
                    )}
                  </button>
                </div>
              );
            })}
          </div>

          {selectedDate && (
            <div className="mt-4 pt-4" style={{ borderTop: "1px solid var(--border)" }}>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-foreground">{formatDate(selectedDate + "T00:00:00")}</p>
                <button onClick={() => setSelectedDate(null)} className="p-0.5 rounded cursor-pointer text-text-tertiary hover:text-foreground transition-colors">
                  <X size={12} />
                </button>
              </div>
              {selectedDateUploads.length === 0 ? (
                <p className="text-[11px] text-text-tertiary py-2">No uploads on this day</p>
              ) : (
                <div className="space-y-1.5">
                  {selectedDateUploads.map((upload, idx) => (
                    <div key={`${upload.stem}-${idx}`} className="flex items-center gap-2.5 px-3 py-2 rounded-lg" style={{ background: "var(--bg-hover)" }}>
                      <Upload size={11} style={{ color: "#30d158" }} className="flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-[11px] font-medium truncate text-foreground">{upload.title || upload.stem}</p>
                        <p className="text-[9px] text-text-tertiary">{formatTime(upload.uploadedAt)}</p>
                      </div>
                      {upload.url && (
                        <a href={upload.url} target="_blank" rel="noopener noreferrer" className="flex-shrink-0">
                          <ExternalLink size={10} className="text-text-tertiary hover:text-accent transition-colors" />
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
