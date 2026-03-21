"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import {
  Link2,
  ExternalLink,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  RefreshCw,
  Pencil,
  Wand2,
  Play,
  Pause,
  Youtube,
  ShoppingBag,
  X,
  Check,
  Zap,
  Trash2,
} from "lucide-react";
import { useFetch, api } from "@/hooks/useApi";
import { usePhaseProgress } from "@/hooks/useTaskProgress";
import { useToast } from "@/components/ToastProvider";
import SearchInput from "@/components/ui/SearchInput";
import { useGlobalAudio, globalAudio } from "@/hooks/useGlobalAudio";

/* ── Types ───────────────────────────────────────────────────── */

interface LinkItem {
  stem: string;
  title: string;
  videoId: string;
  youtubeUrl: string;
  uploadedAt: string;
  publishAt: string | null;
  airbitUrl: string;
  listingId: string;
  seoArtist: string;
  lane: string;
  linkStatus: "linked" | "profile_only" | "missing";
}

interface LinkStatusData {
  items: LinkItem[];
  totals: {
    total: number;
    linked: number;
    profile_only: number;
    missing: number;
  };
}

type FilterTab = "all" | "missing" | "profile_only" | "linked";

/* ── Status Badge ────────────────────────────────────────────── */

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { label: string; color: string; bg: string; icon: typeof CheckCircle2 }> = {
    linked: { label: "Linked", color: "var(--success, #34d399)", bg: "rgba(52, 211, 153, 0.12)", icon: CheckCircle2 },
    profile_only: { label: "Profile Only", color: "var(--warning, #fbbf24)", bg: "rgba(251, 191, 36, 0.12)", icon: AlertTriangle },
    missing: { label: "Missing", color: "var(--error, #ef4444)", bg: "rgba(239, 68, 68, 0.12)", icon: XCircle },
  };
  const c = config[status] || config.missing;
  const Icon = c.icon;

  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold"
      style={{ color: c.color, background: c.bg }}
    >
      <Icon size={11} />
      {c.label}
    </span>
  );
}

/* ── Summary Card ────────────────────────────────────────────── */

function SummaryCard({
  label,
  value,
  icon: Icon,
  color,
  accent,
}: {
  label: string;
  value: number;
  icon: typeof Link2;
  color: string;
  accent: string;
}) {
  return (
    <div
      className="rounded-2xl p-4 transition-all duration-200"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center"
          style={{ background: accent }}
        >
          <Icon size={16} style={{ color }} />
        </div>
        <span className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          {value}
        </span>
      </div>
      <p className="text-xs font-medium" style={{ color: "var(--text-tertiary)" }}>
        {label}
      </p>
    </div>
  );
}

/* ── Description Editor Modal ────────────────────────────────── */

function DescriptionEditor({
  item,
  onClose,
  onSaved,
}: {
  item: LinkItem;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [currentDesc, setCurrentDesc] = useState("");
  const [editedDesc, setEditedDesc] = useState("");
  const [rebuiltDesc, setRebuiltDesc] = useState<string | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [ytTitle, setYtTitle] = useState("");

  // Fetch live description on mount
  useEffect(() => {
    api.get<{ title: string; description: string }>(`/organizer/description/${item.videoId}`)
      .then((data) => {
        setCurrentDesc(data.description);
        setEditedDesc(data.description);
        setYtTitle(data.title);
        setLoading(false);
      })
      .catch((err) => {
        toast.toast(`Failed to load description: ${err.message}`, "error");
        setLoading(false);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.videoId]);

  const handleRebuild = useCallback(async () => {
    setRebuilding(true);
    try {
      const data = await api.get<{ description: string; purchaseLink: string }>(
        `/organizer/rebuild/${item.stem}`
      );
      setRebuiltDesc(data.description);
    } catch (err: unknown) {
      toast.toast(`Failed to rebuild: ${(err as Error).message}`, "error");
    } finally {
      setRebuilding(false);
    }
  }, [item.stem, toast]);

  const handleApplyRebuilt = useCallback(() => {
    if (rebuiltDesc) {
      setEditedDesc(rebuiltDesc);
      setRebuiltDesc(null);
    }
  }, [rebuiltDesc]);

  const handleSave = useCallback(async () => {
    if (editedDesc === currentDesc) {
      toast.toast("No changes to save");
      return;
    }
    setSaving(true);
    try {
      await api.post(`/organizer/description/${item.videoId}`, {
        description: editedDesc,
      });
      toast.toast("YouTube description updated!", "success");
      onSaved();
      onClose();
    } catch (err: unknown) {
      toast.toast(`Failed to update: ${(err as Error).message}`, "error");
    } finally {
      setSaving(false);
    }
  }, [editedDesc, currentDesc, item.videoId, toast, onSaved, onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: "rgba(0,0,0,0.6)" }}>
      <div
        className="w-full max-w-2xl mx-4 rounded-2xl overflow-hidden"
        style={{
          background: "var(--bg-card-solid)",
          border: "1px solid var(--border)",
          boxShadow: "0 24px 64px rgba(0,0,0,0.4)",
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-4"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <div className="min-w-0">
            <h3 className="text-base font-bold truncate" style={{ color: "var(--text-primary)" }}>
              {item.title}
            </h3>
            <div className="flex items-center gap-2 mt-1">
              <StatusBadge status={item.linkStatus} />
              {item.airbitUrl && (
                <a
                  href={item.airbitUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] font-medium flex items-center gap-1 hover:underline"
                  style={{ color: "var(--accent)" }}
                >
                  <ShoppingBag size={10} /> Airbit
                </a>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg transition-colors"
            style={{ color: "var(--text-tertiary)" }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={24} className="animate-spin" style={{ color: "var(--accent)" }} />
            </div>
          ) : (
            <>
              {/* YouTube title */}
              <div>
                <label className="text-xs font-semibold mb-1 block" style={{ color: "var(--text-tertiary)" }}>
                  YouTube Title
                </label>
                <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                  {ytTitle}
                </p>
              </div>

              {/* Description editor */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-semibold" style={{ color: "var(--text-tertiary)" }}>
                    Description
                  </label>
                  <button
                    onClick={handleRebuild}
                    disabled={rebuilding}
                    className="flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-lg transition-all"
                    style={{
                      color: "var(--accent)",
                      background: "var(--accent-muted)",
                    }}
                  >
                    {rebuilding ? <Loader2 size={11} className="animate-spin" /> : <Wand2 size={11} />}
                    Auto-Fix
                  </button>
                </div>
                <textarea
                  value={editedDesc}
                  onChange={(e) => setEditedDesc(e.target.value)}
                  rows={10}
                  className="w-full rounded-xl px-3 py-2.5 text-sm outline-none resize-none transition-all"
                  style={{
                    background: "var(--bg-primary)",
                    border: "1px solid var(--border)",
                    color: "var(--text-primary)",
                  }}
                  onFocus={(e) => { e.currentTarget.style.borderColor = "var(--accent)"; }}
                  onBlur={(e) => { e.currentTarget.style.borderColor = "var(--border)"; }}
                />
              </div>

              {/* Rebuilt preview */}
              {rebuiltDesc && (
                <div
                  className="rounded-xl p-3"
                  style={{ background: "rgba(52, 211, 153, 0.08)", border: "1px solid rgba(52, 211, 153, 0.2)" }}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold" style={{ color: "#34d399" }}>
                      Auto-Generated Description
                    </span>
                    <button
                      onClick={handleApplyRebuilt}
                      className="flex items-center gap-1 text-[11px] font-semibold px-2 py-1 rounded-lg transition-all"
                      style={{ color: "#fff", background: "#34d399" }}
                    >
                      <Check size={11} /> Use This
                    </button>
                  </div>
                  <pre
                    className="text-xs whitespace-pre-wrap"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    {rebuiltDesc}
                  </pre>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div
          className="flex items-center justify-between px-5 py-3"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <a
            href={item.youtubeUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-xs font-medium hover:underline"
            style={{ color: "var(--text-tertiary)" }}
          >
            <Youtube size={12} /> View on YouTube
          </a>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
              style={{ color: "var(--text-secondary)", background: "var(--bg-hover)" }}
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving || editedDesc === currentDesc}
              className="px-4 py-1.5 rounded-lg text-xs font-semibold transition-all disabled:opacity-40"
              style={{
                color: "#fff",
                background: "var(--accent)",
              }}
            >
              {saving ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                "Save to YouTube"
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Main Page ───────────────────────────────────────────────── */

export default function OrganizerPage() {
  const { data, loading, error, refetch } = useFetch<LinkStatusData>("/organizer/status");
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [activeFilter, setActiveFilter] = useState<FilterTab>("all");
  const [editingItem, setEditingItem] = useState<LinkItem | null>(null);
  const [fixingAll, setFixingAll] = useState(false);
  const [syncingLinks, setSyncingLinks] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // Task progress (WebSocket-backed, persists across navigation)
  const fixProgress = usePhaseProgress("fix_links");
  const syncProgress = usePhaseProgress("sync_links");
  const activeProgress = fixProgress || syncProgress;
  const isTaskRunning = !!activeProgress && activeProgress.pct < 100;

  // Auto-refetch when task completes
  useEffect(() => {
    if (activeProgress && activeProgress.pct >= 100) {
      const t = setTimeout(() => refetch(), 2000);
      return () => clearTimeout(t);
    }
  }, [activeProgress, refetch]);

  // Global audio
  const { beat: globalBeat, isPlaying: globalIsPlaying } = useGlobalAudio();

  const handlePlay = useCallback(
    (item: LinkItem) => {
      // Find the audio filename from metadata
      const beat = {
        stem: item.stem,
        title: item.title,
        artist: item.seoArtist || "Unknown",
        filename: `${item.stem}.mp3`,
      };
      if (globalBeat?.stem === item.stem) {
        globalAudio.toggle();
      } else {
        globalAudio.play(beat);
      }
    },
    [globalBeat]
  );

  const handleFixAll = useCallback(async () => {
    setFixingAll(true);
    try {
      await api.post("/organizer/fix-all", {});
      toast.toast("Fix All started — descriptions will update shortly", "success");
    } catch (err: unknown) {
      toast.toast(`Failed: ${(err as Error).message}`, "error");
    } finally {
      setFixingAll(false);
    }
  }, [toast]);

  const handleSyncLinks = useCallback(async () => {
    setSyncingLinks(true);
    try {
      await api.post("/store-sync/sync-links", {});
      toast.toast("Sync started — scraping Airbit for purchase links", "success");
      // Refetch after a delay to let the sync complete
      setTimeout(refetch, 5000);
    } catch (err: unknown) {
      toast.toast(`Failed: ${(err as Error).message}`, "error");
    } finally {
      setSyncingLinks(false);
    }
  }, [toast, refetch]);

  const handleRemove = useCallback(async (stem: string) => {
    setDeleting(true);
    try {
      await api.del(`/organizer/${stem}`);
      toast.toast("Removed from list", "success");
      setConfirmDelete(null);
      refetch();
    } catch (err: unknown) {
      toast.toast(`Failed: ${(err as Error).message}`, "error");
    } finally {
      setDeleting(false);
    }
  }, [toast, refetch]);

  // Filter + search
  const filtered = useMemo(() => {
    if (!data?.items) return [];
    let items = data.items;

    if (activeFilter !== "all") {
      items = items.filter((i) => i.linkStatus === activeFilter);
    }

    if (search) {
      const q = search.toLowerCase();
      items = items.filter(
        (i) =>
          i.stem.toLowerCase().includes(q) ||
          i.title.toLowerCase().includes(q) ||
          i.seoArtist.toLowerCase().includes(q)
      );
    }

    return items;
  }, [data, activeFilter, search]);

  const totals = data?.totals || { total: 0, linked: 0, profile_only: 0, missing: 0 };

  const filterTabs: { key: FilterTab; label: string; count: number }[] = [
    { key: "all", label: "All", count: totals.total },
    { key: "missing", label: "Missing", count: totals.missing },
    { key: "profile_only", label: "Profile Only", count: totals.profile_only },
    { key: "linked", label: "Linked", count: totals.linked },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center"
            style={{
              background: "linear-gradient(135deg, var(--accent), #8b5cf6)",
              boxShadow: "0 4px 16px var(--accent-muted)",
            }}
          >
            <Link2 size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>
              Link Organizer
            </h1>
            <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
              YouTube ↔ Airbit connection manager
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleSyncLinks}
            disabled={syncingLinks || isTaskRunning}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold transition-all disabled:opacity-40"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-secondary)",
            }}
          >
            {syncingLinks || (syncProgress && syncProgress.pct < 100) ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            Sync Airbit
          </button>
          <button
            onClick={handleFixAll}
            disabled={fixingAll || isTaskRunning || totals.missing + totals.profile_only === 0}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold transition-all disabled:opacity-40"
            style={{
              background: "var(--accent)",
              color: "#fff",
              boxShadow: "0 2px 12px var(--accent-muted)",
            }}
          >
            {fixingAll || (fixProgress && fixProgress.pct < 100) ? <Loader2 size={13} className="animate-spin" /> : <Zap size={13} />}
            Fix All Links
          </button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <SummaryCard
          label="Total Videos"
          value={totals.total}
          icon={Youtube}
          color="var(--text-primary)"
          accent="var(--bg-hover)"
        />
        <SummaryCard
          label="Linked"
          value={totals.linked}
          icon={CheckCircle2}
          color="#34d399"
          accent="rgba(52, 211, 153, 0.12)"
        />
        <SummaryCard
          label="Missing Links"
          value={totals.missing}
          icon={XCircle}
          color="#ef4444"
          accent="rgba(239, 68, 68, 0.12)"
        />
        <SummaryCard
          label="Profile Only"
          value={totals.profile_only}
          icon={AlertTriangle}
          color="#fbbf24"
          accent="rgba(251, 191, 36, 0.12)"
        />
      </div>

      {/* Progress Bar (fix-all or sync) */}
      {activeProgress && (
        <div
          className="p-4 rounded-2xl"
          style={{ background: "var(--bg-card)", border: "1px solid var(--glass-border)" }}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-foreground flex items-center gap-2">
              <Loader2 size={12} className={activeProgress.pct < 100 ? "animate-spin text-accent" : "text-green-400"} />
              {activeProgress.detail}
            </span>
            <span className="text-xs font-bold text-accent tabular-nums">{activeProgress.pct}%</span>
          </div>
          <div className="h-2 rounded-full overflow-hidden" style={{ background: "var(--bg-hover)" }}>
            <div
              className="h-full rounded-full transition-all duration-300"
              style={{
                width: `${activeProgress.pct}%`,
                background: activeProgress.pct >= 100
                  ? "#22c55e"
                  : "linear-gradient(90deg, var(--accent), #8b5cf6)",
              }}
            />
          </div>
        </div>
      )}

      {/* Search + Filter Tabs */}
      <div className="flex flex-col sm:flex-row gap-3">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search beats..."
          showShortcut
          className="flex-1 max-w-xs"
        />
        <div className="flex items-center gap-1">
          {filterTabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveFilter(tab.key)}
              className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all"
              style={
                activeFilter === tab.key
                  ? {
                      background: "var(--accent)",
                      color: "#fff",
                    }
                  : {
                      background: "var(--bg-hover)",
                      color: "var(--text-secondary)",
                    }
              }
            >
              {tab.label}
              <span
                className="ml-1 px-1 py-0 rounded text-[10px]"
                style={{
                  background: activeFilter === tab.key ? "rgba(255,255,255,0.2)" : "var(--bg-card)",
                }}
              >
                {tab.count}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-16">
          <Loader2 size={28} className="animate-spin" style={{ color: "var(--accent)" }} />
        </div>
      )}

      {/* Error */}
      {error && (
        <div
          className="rounded-xl p-4 text-sm"
          style={{ background: "rgba(239, 68, 68, 0.1)", color: "#ef4444" }}
        >
          {error}
        </div>
      )}

      {/* Table */}
      {!loading && !error && (
        <div
          className="rounded-2xl overflow-hidden"
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--border)",
          }}
        >
          {/* Table Header */}
          <div
            className="hidden sm:grid items-center gap-3 px-4 py-2.5 text-[11px] font-semibold uppercase tracking-wider"
            style={{
              gridTemplateColumns: "36px 1fr 120px 100px 100px 100px",
              color: "var(--text-tertiary)",
              borderBottom: "1px solid var(--border)",
              background: "var(--bg-hover)",
            }}
          >
            <span></span>
            <span>Beat</span>
            <span>Artist</span>
            <span>YouTube</span>
            <span>Airbit</span>
            <span className="text-right">Actions</span>
          </div>

          {/* Rows */}
          {filtered.length === 0 ? (
            <div className="px-4 py-12 text-center">
              <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
                {search ? "No beats match your search" : "No videos found"}
              </p>
            </div>
          ) : (
            filtered.map((item) => {
              const isPlayingThis = globalBeat?.stem === item.stem && globalIsPlaying;

              return (
                <div
                  key={item.stem}
                  className="grid items-center gap-3 px-4 py-2.5 transition-all duration-150 hover:bg-[var(--bg-hover)] group"
                  style={{
                    gridTemplateColumns: "36px 1fr 120px 100px 100px 100px",
                    borderBottom: "1px solid var(--border)",
                  }}
                >
                  {/* Play button */}
                  <button
                    onClick={() => handlePlay(item)}
                    className="w-8 h-8 rounded-lg flex items-center justify-center transition-all flex-shrink-0"
                    style={{
                      background: isPlayingThis
                        ? "var(--accent)"
                        : "var(--bg-hover)",
                      color: isPlayingThis ? "#fff" : "var(--text-secondary)",
                    }}
                  >
                    {isPlayingThis ? <Pause size={13} fill="#fff" /> : <Play size={13} fill="currentColor" style={{ marginLeft: 1 }} />}
                  </button>

                  {/* Beat info */}
                  <div className="min-w-0">
                    <p className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }}>
                      {item.title || item.stem}
                    </p>
                    <div className="flex items-center gap-2 mt-0.5">
                      <StatusBadge status={item.linkStatus} />
                    </div>
                  </div>

                  {/* Artist */}
                  <span className="text-xs font-medium truncate hidden sm:block" style={{ color: "var(--text-secondary)" }}>
                    {item.seoArtist || "—"}
                  </span>

                  {/* YouTube link */}
                  <div className="hidden sm:block">
                    {item.youtubeUrl ? (
                      <a
                        href={item.youtubeUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 text-[11px] font-medium hover:underline"
                        style={{ color: "#ff4444" }}
                      >
                        <Youtube size={11} /> Watch
                        <ExternalLink size={9} />
                      </a>
                    ) : (
                      <span className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>—</span>
                    )}
                  </div>

                  {/* Airbit link */}
                  <div className="hidden sm:block">
                    {item.airbitUrl && item.listingId ? (
                      <a
                        href={item.airbitUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 text-[11px] font-medium hover:underline"
                        style={{ color: "var(--accent)" }}
                      >
                        <ShoppingBag size={11} /> View
                        <ExternalLink size={9} />
                      </a>
                    ) : (
                      <span
                        className="text-[11px] font-medium"
                        style={{ color: item.linkStatus === "missing" ? "#ef4444" : "var(--text-tertiary)" }}
                      >
                        {item.linkStatus === "missing" ? "Missing" : "Profile"}
                      </span>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex items-center justify-end gap-1">
                    <button
                      onClick={() => setEditingItem(item)}
                      className="p-1.5 rounded-lg transition-all opacity-60 hover:opacity-100"
                      style={{ color: "var(--text-secondary)", background: "var(--bg-hover)" }}
                      title="Edit description"
                    >
                      <Pencil size={13} />
                    </button>
                    {confirmDelete === item.stem ? (
                      <>
                        <button
                          onClick={() => handleRemove(item.stem)}
                          disabled={deleting}
                          className="p-1.5 rounded-lg transition-all"
                          style={{ color: "#fff", background: "#ef4444" }}
                          title="Confirm remove"
                        >
                          {deleting ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
                        </button>
                        <button
                          onClick={() => setConfirmDelete(null)}
                          className="p-1.5 rounded-lg transition-all"
                          style={{ color: "var(--text-tertiary)", background: "var(--bg-hover)" }}
                          title="Cancel"
                        >
                          <X size={13} />
                        </button>
                      </>
                    ) : (
                      <button
                        onClick={() => setConfirmDelete(item.stem)}
                        className="p-1.5 rounded-lg transition-all opacity-40 hover:opacity-100"
                        style={{ color: "#ef4444", background: "var(--bg-hover)" }}
                        title="Remove from list"
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* Description Editor Modal */}
      {editingItem && (
        <DescriptionEditor
          item={editingItem}
          onClose={() => setEditingItem(null)}
          onSaved={refetch}
        />
      )}
    </div>
  );
}
