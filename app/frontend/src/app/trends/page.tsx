"use client";

import { useState, useCallback } from "react";
import { useFetch, api } from "@/hooks/useApi";
import {
  TrendingUp,
  RefreshCw,
  ArrowUpRight,
  Shield,
  RotateCcw,
  MessageSquare,
  Link2,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  CheckCircle2,
  Send,
  Sparkles,
  Music,
  Loader2,
  Zap,
  Play,
  Upload,
  Search,
  FileText,
  Calendar,
  BarChart3,
} from "lucide-react";

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Recommendation {
  title: string;
  artist: string;
  gender: "male" | "female";
  seo_score: number;
  reason: string;
  niche_relevant: boolean;
  channel_uploads: number;
  views_7d: number;
  uploads_7d: number;
  avg_views: number;
  cluster: string[];
}

interface TrendsData {
  recommended_uploads: Recommendation[];
  analysis: {
    total_channel_uploads: number;
    unique_artists: number;
    top_artist: string | null;
  };
  data_source: "youtube" | "fallback";
  last_scan: string | null;
  gender_filter: string | null;
}

interface ScanStatus {
  has_data: boolean;
  scanned_at: string | null;
  total_scanned: number;
  errors: number;
  source: string;
  cache_fresh: boolean;
  scanned_at_male: string | null;
  scanned_at_female: string | null;
  male_count: number;
  female_count: number;
}

interface IntegrityData {
  health_score: number;
  health_level: string;
  stats: Record<string, number>;
  issue_summary: { high: number; medium: number; low: number; total: number };
  issues: Array<{ stem: string; severity: string; issue: string; message: string; action: string }>;
}

interface RevivalData {
  candidates: Array<{
    stem: string;
    title: string;
    url: string;
    age_days: number;
    issues: string[];
    actions: string[];
    priority: number;
  }>;
  summary: { revival_candidates: number; total_scanned: number };
}

interface SyncData {
  summary: Record<string, number>;
  missing_from_store: Array<{ stem: string; title: string; youtube_url: string }>;
}

interface AgentResponse {
  status: string;
  message?: string;
  result?: Record<string, unknown>;
  suggestions?: string[];
  module?: string;
  executed?: boolean;
}

/* ── Score bar ────────────────────────────────────────────────────────── */

function ScoreBar({ score }: { score: number }) {
  const color =
    score >= 85 ? "#10b981" : score >= 70 ? "#f59e0b" : score >= 50 ? "#f97316" : "#ef4444";
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-hover)" }}>
        <div className="h-full rounded-full" style={{ width: `${score}%`, background: color }} />
      </div>
      <span className="text-xs font-bold tabular-nums" style={{ color }}>{score}</span>
    </div>
  );
}

/* ── Collapsible section ──────────────────────────────────────────────── */

function Section({
  title,
  icon: Icon,
  badge,
  children,
  defaultOpen = true,
  onRefresh,
  loading,
}: {
  title: string;
  icon: React.ElementType;
  badge?: string | number;
  children: React.ReactNode;
  defaultOpen?: boolean;
  onRefresh?: () => void;
  loading?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl overflow-hidden" style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-3 px-5 py-4 text-left"
      >
        <Icon size={16} style={{ color: "var(--accent)" }} />
        <span className="text-sm font-semibold text-foreground flex-1">{title}</span>
        {badge !== undefined && (
          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full" style={{ background: "var(--accent-muted)", color: "var(--accent)" }}>
            {badge}
          </span>
        )}
        {onRefresh && (
          <span
            onClick={(e) => { e.stopPropagation(); onRefresh(); }}
            className="p-1 rounded-lg hover:opacity-70"
          >
            <RefreshCw size={12} className={loading ? "animate-spin" : ""} style={{ color: "var(--text-tertiary)" }} />
          </span>
        )}
        {open ? (
          <ChevronUp size={14} style={{ color: "var(--text-tertiary)" }} />
        ) : (
          <ChevronDown size={14} style={{ color: "var(--text-tertiary)" }} />
        )}
      </button>
      {open && <div className="px-5 pb-5">{children}</div>}
    </div>
  );
}

/* ── Gender tab type ─────────────────────────────────────────────────── */

type GenderTab = "all" | "male" | "female";

const GENDER_TABS: { key: GenderTab; label: string; color: string }[] = [
  { key: "all", label: "All Artists", color: "var(--accent)" },
  { key: "male", label: "Male", color: "#38bdf8" },
  { key: "female", label: "Female", color: "#e040fb" },
];

/* ── Agent quick commands ────────────────────────────────────────────── */

const QUICK_COMMANDS = [
  { label: "Render All", cmd: "render all beats", icon: Play, color: "#00d362" },
  { label: "Upload All", cmd: "upload all beats", icon: Upload, color: "#ff0000" },
  { label: "Gen SEO", cmd: "generate seo for all beats", icon: FileText, color: "#b44eff" },
  { label: "Schedule 5", cmd: "schedule next 5 uploads", icon: Calendar, color: "#f5a623" },
  { label: "Health", cmd: "scan channel health", icon: Shield, color: "#10b981" },
  { label: "Scan YT", cmd: "scan youtube trends", icon: TrendingUp, color: "#38bdf8" },
  { label: "Analytics", cmd: "show analytics", icon: BarChart3, color: "#e040fb" },
  { label: "Revive", cmd: "find revival candidates", icon: RotateCcw, color: "#f97316" },
];

/* ── Main Page ─────────────────────────────────────────────────────────── */

export default function TrendsPage() {
  /* ── Gender tab state ───────────────────────────────────────────────── */
  const [genderTab, setGenderTab] = useState<GenderTab>("all");

  /* ── Data — trends + integrity load immediately ─────────────────────── */
  const genderParam = genderTab === "all" ? "" : `&gender=${genderTab}`;
  const { data: trends, loading: trendsLoading, refetch: refetchTrends } = useFetch<TrendsData>(
    `/trends/recommend?count=20${genderParam}`
  );
  const { data: integrity, loading: integrityLoading, refetch: refetchIntegrity } = useFetch<IntegrityData>("/integrity/audit");
  const { data: scanStatus, refetch: refetchScanStatus } = useFetch<ScanStatus>("/trends/scan/status");
  const [scanning, setScanning] = useState(false);

  async function handleScan() {
    setScanning(true);
    try {
      const genderQuery = genderTab === "all" ? "" : `?gender=${genderTab}`;
      await api.post(`/trends/scan${genderQuery}`);
      refetchTrends();
      refetchScanStatus();
    } catch (e) {
      console.error("Scan failed:", e);
    }
    setScanning(false);
  }

  /* ── Revival + Sync lazy-load on expand ─────────────────────────────── */
  const [revivalLoaded, setRevivalLoaded] = useState(false);
  const { data: revival, loading: revivalLoading, refetch: refetchRevival } = useFetch<RevivalData>(revivalLoaded ? "/revival/scan?min_age=0" : null);
  const [syncLoaded, setSyncLoaded] = useState(false);
  const { data: sync, loading: syncLoading, refetch: refetchSync } = useFetch<SyncData>(syncLoaded ? "/airbit-sync/scan" : null);

  /* ── Agent ──────────────────────────────────────────────────────────── */
  const [agentInput, setAgentInput] = useState("");
  const [agentHistory, setAgentHistory] = useState<Array<{ role: string; text: string; executed?: boolean }>>([]);
  const [agentLoading, setAgentLoading] = useState(false);

  const handleAgentCommand = useCallback(async (cmd?: string) => {
    const command = cmd || agentInput.trim();
    if (!command) return;
    if (!cmd) setAgentInput("");
    setAgentHistory((h) => [...h, { role: "user", text: command }]);
    setAgentLoading(true);
    try {
      const res = await api.post<AgentResponse>("/agent/command", { command });
      let reply: string;
      const executed = res.executed ?? false;

      if (res.message) {
        reply = res.message;
        if (res.suggestions?.length) {
          reply += "\n\nTry:\n" + res.suggestions.map((s) => `• ${s}`).join("\n");
        }
      } else if (res.status === "ok" && res.result) {
        reply = formatAgentResult(res.module || "", res.result);
      } else {
        reply = "Done";
      }

      setAgentHistory((h) => [...h, { role: "agent", text: reply, executed }]);
    } catch {
      setAgentHistory((h) => [...h, { role: "agent", text: "Error — couldn't run that command." }]);
    }
    setAgentLoading(false);
  }, [agentInput]);

  /* ── Derived ────────────────────────────────────────────────────────── */
  const recs = trends?.recommended_uploads || [];
  const healthScore = integrity?.health_score ?? null;
  const totalIssues = integrity?.issue_summary?.total ?? 0;
  const revivalCount = revival?.summary?.revival_candidates ?? 0;
  const missingFromStore = sync?.missing_from_store?.length ?? 0;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div>
        <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
          <TrendingUp size={24} style={{ color: "var(--accent)" }} />
          Trends
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
          Upload recommendations, channel health, and tools
        </p>
      </div>

      {/* ── Quick Stats ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}>
          <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>Uploads</p>
          <p className="text-2xl font-bold text-foreground">{trends?.analysis?.total_channel_uploads ?? "—"}</p>
        </div>
        <div className="rounded-xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}>
          <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>Artists</p>
          <p className="text-2xl font-bold text-foreground">{trends?.analysis?.unique_artists ?? "—"}</p>
        </div>
        <div className="rounded-xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}>
          <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>Health</p>
          <p className="text-2xl font-bold" style={{
            color: healthScore === null ? "var(--text-tertiary)" : healthScore >= 80 ? "#10b981" : healthScore >= 60 ? "#f59e0b" : "#ef4444"
          }}>
            {healthScore ?? "—"}
          </p>
        </div>
        <div className="rounded-xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}>
          <p className="text-[10px] uppercase tracking-wider mb-1" style={{ color: "var(--text-tertiary)" }}>Top Artist</p>
          <p className="text-lg font-bold text-foreground truncate">{trends?.analysis?.top_artist ?? "—"}</p>
        </div>
      </div>

      {/* ── 1. NEXT UPLOADS with Gender Tabs ──────────────────────────── */}
      <Section
        title="Next Uploads"
        icon={Sparkles}
        badge={recs.length > 0 ? `${recs.length} picks` : undefined}
        onRefresh={refetchTrends}
        loading={trendsLoading}
      >
        {/* Gender Tabs + Data Source + Scan */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 mb-4 pb-3" style={{ borderBottom: "1px solid var(--glass-border)" }}>
          <div className="flex flex-col gap-2">
            {/* Gender tabs */}
            <div className="flex gap-1.5">
              {GENDER_TABS.map((tab) => {
                const active = genderTab === tab.key;
                return (
                  <button
                    key={tab.key}
                    onClick={() => setGenderTab(tab.key)}
                    className="px-3 py-1.5 rounded-lg text-[11px] font-bold transition-all cursor-pointer"
                    style={{
                      background: active ? `${tab.color}20` : "var(--bg-hover)",
                      color: active ? tab.color : "var(--text-tertiary)",
                      border: `1px solid ${active ? `${tab.color}50` : "transparent"}`,
                    }}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </div>
            {/* Data source + last scan */}
            <div>
              <p className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                Data: {trends?.data_source === "youtube" ? "YouTube API" : "Channel history only"}
                {genderTab !== "all" && ` · ${genderTab} artists`}
              </p>
              {trends?.last_scan && (
                <p className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                  Last scan: {new Date(trends.last_scan).toLocaleString()}
                </p>
              )}
              {!trends?.last_scan && !trendsLoading && (
                <p className="text-[10px]" style={{ color: "#f59e0b" }}>
                  No YouTube scan yet — click Scan to pull real data
                </p>
              )}
            </div>
          </div>
          <button
            onClick={handleScan}
            disabled={scanning}
            className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium flex-shrink-0"
            style={{
              background: scanning ? "var(--bg-hover)" : "var(--accent)",
              color: scanning ? "var(--text-tertiary)" : "#fff",
              opacity: scanning ? 0.6 : 1,
            }}
          >
            <RefreshCw size={12} className={scanning ? "animate-spin" : ""} />
            {scanning ? `Scanning ${genderTab === "all" ? "all" : genderTab}...` : `Scan ${genderTab === "all" ? "YouTube" : genderTab}`}
          </button>
        </div>

        {trendsLoading && recs.length === 0 ? (
          <div className="py-8 text-center">
            <RefreshCw size={20} className="animate-spin mx-auto mb-2" style={{ color: "var(--text-tertiary)" }} />
            <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>Loading recommendations...</p>
          </div>
        ) : recs.length === 0 ? (
          <p className="text-sm py-4 text-center" style={{ color: "var(--text-tertiary)" }}>
            No recommendations available{genderTab !== "all" ? ` for ${genderTab} artists` : ""}.
          </p>
        ) : (
          <div className="space-y-1">
            {/* Table header */}
            <div className="flex items-center gap-3 px-2 py-1">
              <span className="w-6" />
              <span className="flex-1 text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>Artist</span>
              {trends?.data_source === "youtube" && (
                <span className="w-20 text-[10px] uppercase tracking-wider text-right" style={{ color: "var(--text-tertiary)" }}>7d Views</span>
              )}
              <span className="w-16 text-[10px] uppercase tracking-wider text-right" style={{ color: "var(--text-tertiary)" }}>Yours</span>
              <span className="w-24 text-[10px] uppercase tracking-wider text-right" style={{ color: "var(--text-tertiary)" }}>Score</span>
            </div>

            {recs.map((rec, i) => (
              <div
                key={rec.artist}
                className="flex items-center gap-3 px-2 py-2.5 rounded-lg transition-colors"
                style={{ background: i % 2 === 0 ? "transparent" : "var(--bg-hover)" }}
              >
                <span className="text-xs font-bold w-6 text-center tabular-nums" style={{ color: "var(--text-tertiary)" }}>
                  {i + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold text-foreground">{rec.artist} Type Beat</p>
                    {rec.niche_relevant && (
                      <span title="In your lane ecosystem">
                        <ArrowUpRight size={12} style={{ color: "var(--accent)" }} />
                      </span>
                    )}
                    {/* Gender badge */}
                    <span
                      className="text-[8px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide"
                      style={{
                        background: rec.gender === "female" ? "#e040fb15" : "#38bdf815",
                        color: rec.gender === "female" ? "#e040fb" : "#38bdf8",
                        border: `1px solid ${rec.gender === "female" ? "#e040fb30" : "#38bdf830"}`,
                      }}
                    >
                      {rec.gender === "female" ? "F" : "M"}
                    </span>
                  </div>
                  <p className="text-[10px] mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                    {rec.reason}
                  </p>
                </div>
                {trends?.data_source === "youtube" && (
                  <span className="w-20 text-right text-xs tabular-nums" style={{ color: rec.views_7d > 100000 ? "#10b981" : "var(--text-secondary)" }}>
                    {rec.views_7d > 999999 ? `${(rec.views_7d / 1000000).toFixed(1)}M` : rec.views_7d > 999 ? `${(rec.views_7d / 1000).toFixed(0)}K` : rec.views_7d || "—"}
                  </span>
                )}
                <span className="w-16 text-right text-xs tabular-nums" style={{ color: rec.channel_uploads === 0 ? "#10b981" : "var(--text-secondary)" }}>
                  {rec.channel_uploads === 0 ? "NEW" : rec.channel_uploads}
                </span>
                <div className="w-24 flex justify-end">
                  <ScoreBar score={rec.seo_score} />
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* ── 2. CHANNEL HEALTH ───────────────────────────────────────────── */}
      <Section
        title="Channel Health"
        icon={Shield}
        badge={totalIssues > 0 ? `${totalIssues} issues` : healthScore !== null ? "clean" : undefined}
        onRefresh={refetchIntegrity}
        loading={integrityLoading}
      >
        {integrityLoading && !integrity ? (
          <div className="py-8 text-center">
            <RefreshCw size={20} className="animate-spin mx-auto mb-2" style={{ color: "var(--text-tertiary)" }} />
            <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>Running audit...</p>
          </div>
        ) : integrity ? (
          <div className="space-y-4">
            <div className="flex items-center gap-6">
              <div className="text-center">
                <p className="text-4xl font-black tabular-nums" style={{
                  color: integrity.health_score >= 80 ? "#10b981" : integrity.health_score >= 60 ? "#f59e0b" : "#ef4444"
                }}>
                  {integrity.health_score}
                </p>
                <p className="text-[10px] uppercase tracking-wider mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                  {integrity.health_level}
                </p>
              </div>
              <div className="flex-1 grid grid-cols-3 gap-3">
                {[
                  { label: "High", value: integrity.issue_summary.high, color: "#ef4444" },
                  { label: "Medium", value: integrity.issue_summary.medium, color: "#f59e0b" },
                  { label: "Low", value: integrity.issue_summary.low, color: "#10b981" },
                ].map((s) => (
                  <div key={s.label} className="text-center rounded-lg p-2" style={{ background: "var(--bg-hover)" }}>
                    <p className="text-lg font-bold tabular-nums" style={{ color: s.value > 0 ? s.color : "var(--text-tertiary)" }}>{s.value}</p>
                    <p className="text-[9px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>{s.label}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap gap-x-6 gap-y-1">
              {Object.entries(integrity.stats).map(([key, val]) => (
                <div key={key} className="flex items-center gap-1.5">
                  <span className="text-xs font-medium tabular-nums text-foreground">{val as number}</span>
                  <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>{key.replace(/_/g, " ")}</span>
                </div>
              ))}
            </div>

            {integrity.issues.length > 0 && (
              <div className="space-y-1 pt-2" style={{ borderTop: "1px solid var(--glass-border)" }}>
                {integrity.issues.slice(0, 15).map((issue, i) => (
                  <div key={i} className="flex items-center gap-2 py-1.5 text-xs">
                    <AlertTriangle size={12} style={{ color: issue.severity === "high" ? "#ef4444" : issue.severity === "medium" ? "#f59e0b" : "#10b981" }} />
                    <span className="font-medium text-foreground">{issue.stem}</span>
                    <span style={{ color: "var(--text-tertiary)" }}>—</span>
                    <span style={{ color: "var(--text-secondary)" }}>{issue.message}</span>
                  </div>
                ))}
                {integrity.issues.length > 15 && (
                  <p className="text-[10px] pt-1" style={{ color: "var(--text-tertiary)" }}>
                    +{integrity.issues.length - 15} more issues
                  </p>
                )}
              </div>
            )}

            {totalIssues === 0 && (
              <div className="flex items-center gap-2 py-2">
                <CheckCircle2 size={14} style={{ color: "#10b981" }} />
                <span className="text-xs" style={{ color: "#10b981" }}>All clear — no issues across {integrity.stats.total_beats || 0} beats</span>
              </div>
            )}
          </div>
        ) : null}
      </Section>

      {/* ── 3. REVIVAL ──────────────────────────────────────────────────── */}
      <Section
        title="Revival Candidates"
        icon={RotateCcw}
        badge={revivalLoaded ? (revivalCount > 0 ? revivalCount : "none") : undefined}
        defaultOpen={false}
        onRefresh={() => { setRevivalLoaded(true); refetchRevival(); }}
        loading={revivalLoading}
      >
        {!revivalLoaded ? (
          <button
            onClick={() => setRevivalLoaded(true)}
            className="w-full py-4 text-center text-xs rounded-lg cursor-pointer"
            style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
          >
            Scan for old uploads that could be refreshed
          </button>
        ) : revivalLoading ? (
          <div className="py-6 text-center">
            <RefreshCw size={16} className="animate-spin mx-auto mb-2" style={{ color: "var(--text-tertiary)" }} />
            <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>Scanning catalog...</p>
          </div>
        ) : revival && revival.candidates.length > 0 ? (
          <div className="space-y-2">
            {revival.candidates.slice(0, 15).map((c) => (
              <div key={c.stem} className="flex items-center gap-3 py-2 text-xs">
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-foreground truncate">{c.title || c.stem}</p>
                  <p className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>{c.age_days}d old</p>
                </div>
                <div className="flex gap-1 flex-shrink-0">
                  {c.actions.slice(0, 2).map((a, i) => (
                    <span key={i} className="px-2 py-0.5 rounded-full text-[9px]" style={{ background: "var(--accent-muted)", color: "var(--accent)" }}>
                      {a}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2 py-4">
            <CheckCircle2 size={14} style={{ color: "#10b981" }} />
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
              All uploads are recent — nothing to revive yet. Candidates appear after 30+ days.
            </span>
          </div>
        )}
      </Section>

      {/* ── 4. AIRBIT SYNC ──────────────────────────────────────────────── */}
      <Section
        title="Airbit Sync"
        icon={Link2}
        badge={syncLoaded ? (missingFromStore > 0 ? `${missingFromStore} missing` : "synced") : undefined}
        defaultOpen={false}
        onRefresh={() => { setSyncLoaded(true); refetchSync(); }}
        loading={syncLoading}
      >
        {!syncLoaded ? (
          <button
            onClick={() => setSyncLoaded(true)}
            className="w-full py-4 text-center text-xs rounded-lg cursor-pointer"
            style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
          >
            Compare YouTube uploads vs Airbit store
          </button>
        ) : syncLoading ? (
          <div className="py-6 text-center">
            <RefreshCw size={16} className="animate-spin mx-auto mb-2" style={{ color: "var(--text-tertiary)" }} />
            <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>Comparing stores...</p>
          </div>
        ) : sync ? (
          <div className="space-y-4">
            <div className="flex gap-4">
              {[
                { label: "YouTube", value: sync.summary.on_youtube ?? 0 },
                { label: "Airbit", value: sync.summary.on_airbit ?? 0 },
                { label: "Synced", value: sync.summary.synced ?? 0 },
                { label: "Missing", value: sync.summary.missing_from_store ?? 0 },
              ].map((s) => (
                <div key={s.label} className="text-center">
                  <p className="text-lg font-bold tabular-nums text-foreground">{s.value}</p>
                  <p className="text-[9px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>{s.label}</p>
                </div>
              ))}
            </div>

            {sync.missing_from_store && sync.missing_from_store.length > 0 && (
              <div className="space-y-1 pt-2" style={{ borderTop: "1px solid var(--glass-border)" }}>
                <p className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
                  Not on Airbit yet:
                </p>
                {sync.missing_from_store.slice(0, 15).map((b) => (
                  <div key={b.stem} className="flex items-center gap-2 py-1 text-xs">
                    <Music size={10} style={{ color: "var(--text-tertiary)" }} />
                    <span className="flex-1 text-foreground truncate">{b.title}</span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: "#f59e0b15", color: "#f59e0b" }}>
                      upload
                    </span>
                  </div>
                ))}
                {sync.missing_from_store.length > 15 && (
                  <p className="text-[10px] pt-1" style={{ color: "var(--text-tertiary)" }}>
                    +{sync.missing_from_store.length - 15} more
                  </p>
                )}
              </div>
            )}
          </div>
        ) : null}
      </Section>

      {/* ── 5. AGENT — now with quick commands + real execution ─────────── */}
      <Section
        title="Producer Agent"
        icon={Zap}
        defaultOpen={false}
      >
        {/* Quick command buttons */}
        <div className="mb-4">
          <p className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
            Quick Actions — click to execute
          </p>
          <div className="grid grid-cols-4 gap-2">
            {QUICK_COMMANDS.map((qc) => {
              const Icon = qc.icon;
              return (
                <button
                  key={qc.cmd}
                  onClick={() => handleAgentCommand(qc.cmd)}
                  disabled={agentLoading}
                  className="flex items-center gap-1.5 px-2.5 py-2 rounded-lg text-[10px] font-semibold cursor-pointer transition-all hover:brightness-110"
                  style={{
                    background: `${qc.color}12`,
                    color: qc.color,
                    border: `1px solid ${qc.color}30`,
                    opacity: agentLoading ? 0.5 : 1,
                  }}
                >
                  <Icon size={12} />
                  {qc.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Chat history */}
        <div className="rounded-lg p-3 space-y-2 min-h-[120px] max-h-[400px] overflow-y-auto mb-3" style={{ background: "var(--bg-hover)" }}>
          {agentHistory.length === 0 && (
            <p className="text-center text-[11px] py-8" style={{ color: "var(--text-tertiary)" }}>
              Click a quick action above or type a command below
            </p>
          )}
          {agentHistory.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className="max-w-[85%] px-3 py-2 rounded-xl text-xs whitespace-pre-wrap"
                style={{
                  background: msg.role === "user" ? "var(--accent)" : "var(--bg-card)",
                  color: msg.role === "user" ? "#fff" : "var(--text-primary)",
                  border: msg.role === "user" ? "none" : `1px solid ${msg.executed ? "#10b98140" : "var(--glass-border)"}`,
                }}
              >
                {msg.role === "agent" && msg.executed && (
                  <div className="flex items-center gap-1 mb-1 text-[9px] font-semibold" style={{ color: "#10b981" }}>
                    <CheckCircle2 size={10} /> Executed
                  </div>
                )}
                {msg.text}
              </div>
            </div>
          ))}
          {agentLoading && (
            <div className="flex justify-start">
              <div className="px-3 py-2 rounded-xl text-xs flex items-center gap-2" style={{ background: "var(--bg-card)", color: "var(--text-tertiary)", border: "1px solid var(--glass-border)" }}>
                <Loader2 size={10} className="animate-spin" /> Executing...
              </div>
            </div>
          )}
        </div>

        {/* Input */}
        <div className="flex gap-2">
          <input
            value={agentInput}
            onChange={(e) => setAgentInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !agentLoading && handleAgentCommand()}
            placeholder='e.g. "render all beats" or "upload army"'
            className="flex-1 px-3 py-2.5 rounded-lg text-xs outline-none"
            style={{ background: "var(--bg-hover)", border: "1px solid var(--glass-border)", color: "var(--text-primary)" }}
          />
          <button
            onClick={() => handleAgentCommand()}
            disabled={agentLoading || !agentInput.trim()}
            className="px-3 py-2.5 rounded-lg cursor-pointer"
            style={{ background: "var(--accent)", color: "#fff", opacity: agentLoading || !agentInput.trim() ? 0.4 : 1 }}
          >
            <Send size={14} />
          </button>
        </div>
      </Section>
    </div>
  );
}

/* ── Format agent results into readable text ──────────────────────────── */

function formatAgentResult(module: string, result: Record<string, unknown>): string {
  try {
    if (module === "integrity") {
      const r = result as Record<string, unknown>;
      const score = r.health_score ?? "?";
      const level = r.health_level ?? "";
      const summary = r.issue_summary as Record<string, number> | undefined;
      const total = summary?.total ?? 0;
      return `Health: ${score}/100 (${level})\nIssues: ${total} total${total > 0 ? ` — ${summary?.high ?? 0} high, ${summary?.medium ?? 0} medium, ${summary?.low ?? 0} low` : ""}`;
    }
    if (module === "trends") {
      const recs = (result as { recommended_uploads?: Array<{ artist: string; seo_score: number }> }).recommended_uploads;
      if (recs?.length) {
        return "Top recommendations:\n" + recs.slice(0, 5).map((r, i) => `${i + 1}. ${r.artist} Type Beat (score: ${r.seo_score})`).join("\n");
      }
    }
    if (module === "revival") {
      const candidates = (result as { candidates?: unknown[] }).candidates;
      return candidates?.length ? `Found ${candidates.length} revival candidates` : "No revival candidates — all uploads are recent.";
    }
    // Generic formatting for other modules
    const keys = Object.keys(result);
    if (keys.length <= 6) {
      return keys.map((k) => {
        const v = result[k];
        if (typeof v === "object" && v !== null) {
          if (Array.isArray(v)) return `${k.replace(/_/g, " ")}: ${v.length} items`;
          return `${k.replace(/_/g, " ")}: ${JSON.stringify(v)}`;
        }
        return `${k.replace(/_/g, " ")}: ${v}`;
      }).join("\n");
    }
    return JSON.stringify(result, null, 2).slice(0, 600);
  } catch {
    return JSON.stringify(result, null, 2).slice(0, 600);
  }
}
