"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import {
  Disc3,
  Play,
  Pause,
  Check,
  X,
  ChevronDown,
  RefreshCw,
  Loader2,
  Music,
  Zap,
  Target,
  AlertCircle,
  CheckCircle2,
  Filter,
} from "lucide-react";
import { useFetch, api } from "@/hooks/useApi";
import { usePhaseProgress } from "@/hooks/useTaskProgress";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ToastProvider";
import { useGlobalAudio, globalAudio } from "@/hooks/useGlobalAudio";

/* ─── Types ───────────────────────────────────────────────────── */

interface DjResult {
  stem: string;
  title: string;
  top_artist: string;
  confidence: number;
  all_scores: { artist: string; score: number; lane?: string }[];
  features: {
    bpm: number | null;
    key: string | null;
    brightness_norm?: number;
    bass_energy_ratio?: number;
    bounce_factor?: number;
    onset_rate?: number;
    rms_mean?: number;
  };
  ai_reasoning: string;
  source: string;
  status: "pending" | "approved" | "rejected" | "overridden";
  current_artist: string;
  current_lane: string;
  applied_artist?: string;
}

interface DjData {
  analyzed_at: string | null;
  total_analyzed: number;
  results: Record<string, DjResult>;
}

interface DjProfiles {
  artists: Record<string, { lane: string; description: string; tags: string[] }>;
}

/* ─── Constants ───────────────────────────────────────────────── */

const ARTIST_COLORS: Record<string, string> = {
  "Glokk40Spaz": "#3b82f6",
  "Sexyy Red": "#ec4899",
  "BiggKutt8": "#22c55e",
  "Ola Runt": "#4ade80",
  "GloRilla": "#f472b6",
  "Babyxsosa": "#a855f7",
  "Sukihana": "#f43f5e",
};

const FILTER_TABS = [
  { key: "all", label: "All" },
  { key: "high", label: "High Confidence" },
  { key: "review", label: "Needs Review" },
  { key: "applied", label: "Applied" },
  { key: "rejected", label: "Rejected" },
] as const;

type FilterKey = (typeof FILTER_TABS)[number]["key"];

function confidenceColor(c: number): string {
  if (c >= 80) return "#22c55e";
  if (c >= 50) return "#f59e0b";
  return "#ef4444";
}

function formatViews(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

/* ─── Page ────────────────────────────────────────────────────── */

export default function DjPage() {
  const { toast } = useToast();
  const { data, loading, refetch } = useFetch<DjData>("/dj/results");
  const { data: profiles } = useFetch<DjProfiles>("/dj/profiles");

  // Global task progress — persists across page navigations
  const djProgress = usePhaseProgress("dj_analyze");
  const progress = djProgress ? { pct: djProgress.pct, detail: djProgress.detail } : null;
  const analyzing = !!djProgress && djProgress.pct < 100;

  const [filter, setFilter] = useState<FilterKey>("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [applying, setApplying] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState<string | null>(null);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  // Global audio player
  const { beat: globalBeat, isPlaying: globalIsPlaying } = useGlobalAudio();

  const handlePlay = useCallback(
    (result: DjResult) => {
      const beat = {
        stem: result.stem,
        title: result.title || result.stem,
        artist: result.current_artist || result.top_artist || "Unknown",
        filename: `${result.stem}.mp3`,
      };
      if (globalBeat?.stem === result.stem) {
        globalAudio.toggle();
      } else {
        globalAudio.play(beat);
      }
    },
    [globalBeat]
  );

  // Refetch results when analysis completes
  useEffect(() => {
    if (djProgress && djProgress.pct >= 100) {
      const t = setTimeout(() => refetch(), 2000);
      return () => clearTimeout(t);
    }
  }, [djProgress, refetch]);

  // Results list
  const results = useMemo(() => {
    if (!data?.results) return [];
    return Object.values(data.results);
  }, [data]);

  // Filtered results
  const filteredResults = useMemo(() => {
    switch (filter) {
      case "high":
        return results.filter((r) => r.confidence >= 80 && r.status === "pending");
      case "review":
        return results.filter((r) => r.confidence < 80 && r.status === "pending");
      case "applied":
        return results.filter((r) => r.status === "approved" || r.status === "overridden");
      case "rejected":
        return results.filter((r) => r.status === "rejected");
      default:
        return results;
    }
  }, [results, filter]);

  // Summary counts
  const counts = useMemo(() => {
    const total = results.length;
    const high = results.filter((r) => r.confidence >= 80 && r.status === "pending").length;
    const review = results.filter((r) => r.confidence < 80 && r.status === "pending").length;
    const applied = results.filter((r) => r.status === "approved" || r.status === "overridden").length;
    return { total, high, review, applied };
  }, [results]);

  // Artists list from profiles
  const artistList = useMemo(() => {
    if (!profiles?.artists) return [];
    return Object.entries(profiles.artists).map(([name, info]) => ({
      name,
      lane: info.lane,
      color: ARTIST_COLORS[name] || "var(--accent)",
    }));
  }, [profiles]);

  // Actions
  const handleAnalyze = async (stems?: string[]) => {
    try {
      await api.post("/dj/analyze", { stems: stems || null, force: false });
      toast("Analysis started — progress persists across pages", "success");
    } catch {
      toast("Failed to start analysis", "error");
    }
  };

  const handleApprove = async (result: DjResult) => {
    try {
      const lane = result.all_scores?.[0]?.lane ||
        artistList.find((a) => a.name === result.top_artist)?.lane || "";
      await api.post("/dj/apply", {
        assignments: [{ stem: result.stem, artist: result.top_artist, lane }],
      });
      toast(`Applied ${result.top_artist} to ${result.stem}`, "success");
      refetch();
    } catch {
      toast("Failed to apply", "error");
    }
  };

  const handleReject = async (stem: string) => {
    try {
      await api.post("/dj/reject", { stems: [stem] });
      toast("Rejected", "info");
      refetch();
    } catch {
      toast("Failed to reject", "error");
    }
  };

  const handleOverride = async (stem: string, artist: string) => {
    const lane = artistList.find((a) => a.name === artist)?.lane || "";
    try {
      await api.post("/dj/override", { stem, artist, lane });
      toast(`Overridden to ${artist}`, "success");
      setOverrideOpen(null);
      refetch();
    } catch {
      toast("Failed to override", "error");
    }
  };

  const handleBulkApprove = async () => {
    const toApply = filteredResults.filter(
      (r) => selected.has(r.stem) && r.status === "pending"
    );
    if (toApply.length === 0) return;
    setApplying(true);
    try {
      const assignments = toApply.map((r) => ({
        stem: r.stem,
        artist: r.top_artist,
        lane: r.all_scores?.[0]?.lane ||
          artistList.find((a) => a.name === r.top_artist)?.lane || "",
      }));
      await api.post("/dj/apply", { assignments });
      toast(`Applied ${assignments.length} classifications`, "success");
      setSelected(new Set());
      refetch();
    } catch {
      toast("Bulk apply failed", "error");
    }
    setApplying(false);
  };

  const toggleSelect = (stem: string) => {
    const next = new Set(selected);
    if (next.has(stem)) next.delete(stem);
    else next.add(stem);
    setSelected(next);
  };

  const toggleSelectAll = () => {
    if (selected.size === filteredResults.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(filteredResults.map((r) => r.stem)));
    }
  };

  /* ─── Render ─────────────────────────────────────────────── */

  return (
    <div className="animate-fade-in">
      {/* Header */}
      <div className="page-header">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="flex items-center gap-2">
              <Disc3 size={20} className="text-accent" />
              DJ
            </h1>
            <p className="page-subtitle">Intelligent beat-to-artist classification</p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => refetch()}
              disabled={loading}
              className="text-text-tertiary hover:text-accent"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            </Button>
            <button
              onClick={() => handleAnalyze()}
              disabled={analyzing}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold text-white transition-all duration-200"
              style={{
                background: analyzing ? "var(--bg-hover)" : "linear-gradient(135deg, var(--accent), #8b5cf6)",
                color: analyzing ? "var(--text-tertiary)" : "#fff",
                opacity: analyzing ? 0.6 : 1,
              }}
            >
              {analyzing ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              {analyzing ? "Analyzing..." : "Analyze All"}
            </button>
          </div>
        </div>
      </div>

      {/* Progress Bar */}
      {progress && (
        <div
          className="mb-4 p-4 rounded-2xl"
          style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-foreground flex items-center gap-2">
              <Loader2 size={12} className="animate-spin text-accent" />
              {progress.detail}
            </span>
            <span className="text-xs font-bold text-accent tabular-nums">{progress.pct}%</span>
          </div>
          <div className="h-2 rounded-full overflow-hidden" style={{ background: "var(--bg-hover)" }}>
            <div
              className="h-full rounded-full transition-all duration-300"
              style={{
                width: `${progress.pct}%`,
                background: "linear-gradient(90deg, var(--accent), #8b5cf6)",
              }}
            />
          </div>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { icon: Music, value: counts.total, label: "Analyzed", color: "#6366f1" },
          { icon: Target, value: counts.high, label: "High Confidence", color: "#22c55e" },
          { icon: AlertCircle, value: counts.review, label: "Needs Review", color: "#f59e0b" },
          { icon: CheckCircle2, value: counts.applied, label: "Applied", color: "#3b82f6" },
        ].map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.label}
              className="p-5 rounded-2xl"
              style={{
                background: "var(--bg-card)",
                backdropFilter: "blur(16px)",
                border: "1px solid var(--glass-border)",
              }}
            >
              {loading ? (
                <div className="space-y-3">
                  <Skeleton className="w-8 h-8 rounded-lg" />
                  <Skeleton className="h-8 w-16" />
                  <Skeleton className="h-3 w-20" />
                </div>
              ) : (
                <>
                  <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-3" style={{ background: `${card.color}15` }}>
                    <Icon size={16} style={{ color: card.color }} />
                  </div>
                  <p className="text-2xl font-extrabold text-foreground tabular-nums">{card.value}</p>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary mt-1">{card.label}</p>
                </>
              )}
            </div>
          );
        })}
      </div>

      {/* Filter Tabs + Bulk Actions */}
      <div
        className="mb-4 p-4 rounded-2xl flex items-center justify-between flex-wrap gap-3"
        style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
      >
        <div className="flex items-center gap-1">
          <Filter size={13} className="text-text-tertiary mr-1" />
          {FILTER_TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => { setFilter(tab.key); setSelected(new Set()); }}
              className="px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200"
              style={{
                background: filter === tab.key ? "var(--accent)" : "transparent",
                color: filter === tab.key ? "#fff" : "var(--text-tertiary)",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {selected.size > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-tertiary">{selected.size} selected</span>
            <button
              onClick={handleBulkApprove}
              disabled={applying}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white transition-all"
              style={{ background: "#22c55e" }}
            >
              {applying ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />}
              Approve Selected
            </button>
          </div>
        )}
      </div>

      {/* Results Table */}
      <div
        className="rounded-2xl overflow-hidden"
        style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
      >
        {/* Table Header */}
        <div
          className="grid items-center px-4 py-3 text-[10px] font-semibold uppercase tracking-wider text-text-tertiary"
          style={{
            gridTemplateColumns: "32px 36px 1fr 140px 100px 120px 100px",
            borderBottom: "1px solid var(--border)",
          }}
        >
          <div>
            <input
              type="checkbox"
              checked={selected.size === filteredResults.length && filteredResults.length > 0}
              onChange={toggleSelectAll}
              className="accent-[var(--accent)] w-3.5 h-3.5 cursor-pointer"
            />
          </div>
          <div></div>
          <div>Beat</div>
          <div>Recommended</div>
          <div>Confidence</div>
          <div>Current Artist</div>
          <div className="text-right">Actions</div>
        </div>

        {/* Rows */}
        {loading ? (
          <div className="p-6 space-y-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full rounded-lg" />
            ))}
          </div>
        ) : filteredResults.length === 0 ? (
          <div className="text-center py-16">
            <Disc3 className="mx-auto mb-3 text-text-tertiary" style={{ opacity: 0.2 }} size={40} />
            <p className="text-sm font-medium text-text-secondary">
              {results.length === 0 ? "No beats analyzed yet" : "No results match this filter"}
            </p>
            <p className="text-xs text-text-tertiary mt-1">
              {results.length === 0 ? 'Click "Analyze All" to classify your beats' : "Try a different filter"}
            </p>
          </div>
        ) : (
          <div className="max-h-[600px] overflow-y-auto">
            {filteredResults.map((result) => {
              const color = ARTIST_COLORS[result.top_artist] || "var(--accent)";
              const confColor = confidenceColor(result.confidence);
              const isExpanded = expandedRow === result.stem;
              const isPlayingThis = globalBeat?.stem === result.stem && globalIsPlaying;
              const statusIcon =
                result.status === "approved" || result.status === "overridden"
                  ? "applied"
                  : result.status === "rejected"
                  ? "rejected"
                  : null;

              return (
                <div key={result.stem}>
                  <div
                    className="grid items-center px-4 py-3 transition-all duration-150 cursor-pointer"
                    style={{
                      gridTemplateColumns: "32px 36px 1fr 140px 100px 120px 100px",
                      borderBottom: "1px solid var(--border)",
                      background: selected.has(result.stem)
                        ? "var(--accent-muted, rgba(99,102,241,0.05))"
                        : isPlayingThis
                        ? "var(--bg-hover)"
                        : "transparent",
                    }}
                    onClick={() => setExpandedRow(isExpanded ? null : result.stem)}
                  >
                    {/* Checkbox */}
                    <div onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selected.has(result.stem)}
                        onChange={() => toggleSelect(result.stem)}
                        className="accent-[var(--accent)] w-3.5 h-3.5 cursor-pointer"
                      />
                    </div>

                    {/* Play/Pause button */}
                    <div onClick={(e) => e.stopPropagation()}>
                      <button
                        onClick={() => handlePlay(result)}
                        className="w-7 h-7 rounded-lg flex items-center justify-center transition-all cursor-pointer"
                        style={{
                          background: isPlayingThis || (globalBeat?.stem === result.stem) ? "var(--accent)" : "transparent",
                          color: isPlayingThis || (globalBeat?.stem === result.stem) ? "#fff" : "var(--text-tertiary)",
                        }}
                      >
                        {isPlayingThis ? <PlayingBars /> : globalBeat?.stem === result.stem ? <Pause size={11} fill="currentColor" /> : <Play size={11} fill="currentColor" className="ml-0.5" />}
                      </button>
                    </div>

                    {/* Beat name */}
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-foreground truncate">{result.title || result.stem}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        {result.features?.bpm && (
                          <span className="text-[10px] text-text-tertiary">{result.features.bpm} BPM</span>
                        )}
                        {result.features?.key && (
                          <span className="text-[10px] text-text-tertiary">{result.features.key}</span>
                        )}
                        {statusIcon && (
                          <span
                            className="text-[9px] px-1.5 py-0.5 rounded font-semibold uppercase"
                            style={{
                              background: statusIcon === "applied" ? "#22c55e20" : "#ef444420",
                              color: statusIcon === "applied" ? "#22c55e" : "#ef4444",
                            }}
                          >
                            {result.status}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Recommended artist */}
                    <div className="flex items-center gap-2">
                      <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: color }} />
                      <span className="text-xs font-medium text-foreground truncate">{result.top_artist}</span>
                    </div>

                    {/* Confidence bar */}
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-3 rounded-full overflow-hidden" style={{ background: "var(--bg-hover)" }}>
                        <div
                          className="h-full rounded-full transition-all duration-500"
                          style={{ width: `${result.confidence}%`, background: confColor }}
                        />
                      </div>
                      <span className="text-[10px] font-bold text-foreground tabular-nums w-8">{result.confidence}</span>
                    </div>

                    {/* Current artist */}
                    <div className="text-xs text-text-tertiary truncate">
                      {result.current_artist || "—"}
                    </div>

                    {/* Actions */}
                    <div className="flex items-center justify-end gap-1" onClick={(e) => e.stopPropagation()}>
                      {result.status === "pending" && (
                        <>
                          <button
                            onClick={() => handleApprove(result)}
                            className="p-1.5 rounded-lg transition-all hover:scale-110"
                            style={{ background: "#22c55e20", color: "#22c55e" }}
                            title="Approve"
                          >
                            <Check size={13} />
                          </button>
                          <button
                            onClick={() => handleReject(result.stem)}
                            className="p-1.5 rounded-lg transition-all hover:scale-110"
                            style={{ background: "#ef444420", color: "#ef4444" }}
                            title="Reject"
                          >
                            <X size={13} />
                          </button>
                          <div className="relative">
                            <button
                              onClick={() => setOverrideOpen(overrideOpen === result.stem ? null : result.stem)}
                              className="p-1.5 rounded-lg transition-all hover:scale-110"
                              style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
                              title="Override"
                            >
                              <ChevronDown size={13} />
                            </button>
                            {overrideOpen === result.stem && (
                              <div
                                className="absolute right-0 top-full mt-1 py-1 rounded-xl z-50 min-w-[160px] shadow-xl"
                                style={{
                                  background: "var(--bg-card-solid, var(--bg-primary))",
                                  border: "1px solid var(--border)",
                                }}
                              >
                                <p className="px-3 py-1 text-[9px] font-semibold uppercase tracking-wider text-text-tertiary">
                                  Override to
                                </p>
                                {artistList.map((a) => (
                                  <button
                                    key={a.name}
                                    onClick={() => handleOverride(result.stem, a.name)}
                                    className="w-full text-left px-3 py-2 text-xs font-medium flex items-center gap-2 transition-colors"
                                    style={{ color: "var(--text-primary)" }}
                                    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-hover)")}
                                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                                  >
                                    <div className="w-2 h-2 rounded-full" style={{ background: a.color }} />
                                    {a.name}
                                  </button>
                                ))}
                              </div>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Expanded Detail Row */}
                  {isExpanded && (
                    <div
                      className="px-6 py-4"
                      style={{
                        background: "var(--bg-hover)",
                        borderBottom: "1px solid var(--border)",
                      }}
                    >
                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        {/* Feature Breakdown */}
                        <div>
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary mb-2">
                            Audio Features
                          </p>
                          <div className="grid grid-cols-2 gap-2">
                            {[
                              { label: "Brightness", value: result.features?.brightness_norm, fmt: (v: number) => `${(v * 100).toFixed(0)}%` },
                              { label: "Bass Energy", value: result.features?.bass_energy_ratio, fmt: (v: number) => `${(v * 100).toFixed(0)}%` },
                              { label: "Bounce", value: result.features?.bounce_factor, fmt: (v: number) => `${(v * 100).toFixed(0)}%` },
                              { label: "Onset Rate", value: result.features?.onset_rate, fmt: (v: number) => `${v.toFixed(1)}/s` },
                            ].map((feat) => (
                              <div key={feat.label} className="p-2 rounded-lg" style={{ background: "var(--bg-card)" }}>
                                <p className="text-[9px] text-text-tertiary uppercase">{feat.label}</p>
                                <p className="text-sm font-bold text-foreground tabular-nums">
                                  {feat.value != null ? feat.fmt(feat.value) : "—"}
                                </p>
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* Score Breakdown */}
                        <div>
                          <p className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary mb-2">
                            Artist Scores
                          </p>
                          <div className="space-y-1.5">
                            {(result.all_scores || []).slice(0, 5).map((score) => {
                              const sc = ARTIST_COLORS[score.artist] || "var(--accent)";
                              return (
                                <div key={score.artist} className="flex items-center gap-2">
                                  <span className="text-[10px] w-24 text-foreground font-medium truncate">{score.artist}</span>
                                  <div className="flex-1 h-3 rounded-full overflow-hidden" style={{ background: "var(--bg-card)" }}>
                                    <div
                                      className="h-full rounded-full"
                                      style={{ width: `${score.score}%`, background: sc }}
                                    />
                                  </div>
                                  <span className="text-[10px] font-bold text-foreground tabular-nums w-8 text-right">
                                    {Math.round(score.score)}
                                  </span>
                                </div>
                              );
                            })}
                          </div>
                          {result.ai_reasoning && (
                            <div className="mt-3 p-2 rounded-lg text-[10px] text-text-secondary italic" style={{ background: "var(--bg-card)" }}>
                              <Zap size={10} className="inline mr-1 text-accent" />
                              {result.ai_reasoning}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Playing indicator bars ──────────────────────────────── */

function PlayingBars() {
  return (
    <div className="flex items-end justify-center gap-[1.5px]" style={{ width: 10, height: 10 }}>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            width: 2,
            background: "#fff",
            borderRadius: 1,
            animation: `djPlayingBar 0.8s ease-in-out ${i * 0.15}s infinite alternate`,
          }}
        />
      ))}
      <style>{`@keyframes djPlayingBar { 0% { height: 25%; } 100% { height: 100%; } }`}</style>
    </div>
  );
}
