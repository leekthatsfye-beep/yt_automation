"use client";

import { useState } from "react";
import { X, Music, Film, Upload, CheckCircle2, ChevronLeft, Trash2, Loader2, AlertTriangle } from "lucide-react";
import { useFetch, api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import AuthImage from "@/components/AuthImage";
import { Skeleton } from "@/components/ui/skeleton";
import BeatMetadataTab from "./BeatMetadataTab";
import BeatSeoTab from "./BeatSeoTab";
import BeatRenderTab from "./BeatRenderTab";
import BeatSocialTab from "./BeatSocialTab";
import BeatStudioTab from "./BeatStudioTab";
import type { Beat } from "@/types/beat";

interface Props {
  stem: string;
  onClose: () => void;
  onBeatUpdated: () => void;
  onBeatDeleted?: () => void;
}

const TABS = [
  { id: "metadata", label: "Metadata" },
  { id: "seo", label: "SEO" },
  { id: "render", label: "Render" },
  { id: "social", label: "Social" },
  { id: "studio", label: "Studio" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function BeatEditorPanel({ stem, onClose, onBeatUpdated, onBeatDeleted }: Props) {
  const { data: beat, loading, refetch } = useFetch<Beat>(`/beats/${stem}`);
  const { toast } = useToast();
  const [activeTab, setActiveTab] = useState<TabId>("metadata");
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleUpdated = () => {
    refetch();
    onBeatUpdated();
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await api.del(`/beats/${stem}`);
      toast(`Deleted "${beat?.beat_name || stem}"`, "success");
      onClose();
      onBeatDeleted?.();
      onBeatUpdated();
    } catch {
      toast("Failed to delete beat", "error");
    } finally {
      setDeleting(false);
      setShowDeleteConfirm(false);
    }
  };

  if (loading || !beat) {
    return (
      <div className="h-full animate-slide-in-right flex flex-col" style={{ background: "var(--bg-secondary)" }}>
        <button
          onClick={onClose}
          className="flex lg:hidden items-center gap-1 px-4 py-2.5 text-sm font-semibold flex-shrink-0 cursor-pointer"
          style={{ color: "var(--accent)", borderBottom: "1px solid var(--border)" }}
        >
          <ChevronLeft size={16} />
          Back to Beats
        </button>
        <div className="p-5 space-y-4">
          <div className="flex items-center justify-between">
            <Skeleton className="h-6 w-48 rounded-lg" />
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-bg-hover transition-colors cursor-pointer text-text-tertiary">
              <X size={16} />
            </button>
          </div>
          <Skeleton className="h-16 w-full rounded-xl" />
          <div className="flex gap-2">
            {TABS.map((t) => <Skeleton key={t.id} className="h-8 w-20 rounded-lg" />)}
          </div>
          <Skeleton className="h-40 w-full rounded-xl" />
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col animate-slide-in-right" style={{ background: "var(--bg-secondary)" }}>
      {/* Mobile Back Button */}
      <button
        onClick={onClose}
        className="flex lg:hidden items-center gap-1 px-4 py-2.5 text-sm font-semibold flex-shrink-0 cursor-pointer"
        style={{ color: "var(--accent)", borderBottom: "1px solid var(--border)" }}
      >
        <ChevronLeft size={16} />
        Back to Beats
      </button>

      {/* Header */}
      <div className="flex-shrink-0 p-5 pb-0" style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-start justify-between gap-3 mb-4">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            {/* Thumbnail */}
            <div className="w-12 h-12 rounded-xl overflow-hidden flex-shrink-0" style={{ background: "var(--bg-hover)" }}>
              {beat.has_thumbnail ? (
                <AuthImage
                  src={`/files/output/${beat.stem}_thumb.jpg`}
                  alt={beat.beat_name || beat.stem}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <Music size={18} className="text-text-tertiary/40" />
                </div>
              )}
            </div>

            {/* Title + Status */}
            <div className="min-w-0">
              <h2 className="text-base font-semibold truncate text-foreground leading-tight" style={{ letterSpacing: "-0.02em" }}>
                {beat.beat_name || beat.stem}
              </h2>
              <div className="flex items-center gap-2 mt-1 overflow-hidden">
                <span className="text-[11px] text-text-tertiary flex-shrink-0">{beat.artist || "Unknown"}</span>
                <div className="flex items-center gap-1 flex-shrink-0">
                  {beat.rendered && (
                    <span className="inline-flex items-center gap-0.5 text-[9px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap" style={{ background: "var(--success-muted)", color: "var(--success)" }}>
                      <Film size={8} /> Rendered
                    </span>
                  )}
                  {beat.uploaded && (
                    <span className="inline-flex items-center gap-0.5 text-[9px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap" style={{ background: "var(--accent-muted)", color: "var(--accent)" }}>
                      <Upload size={8} /> Uploaded
                    </span>
                  )}
                  {beat.tags.length > 0 && (
                    <span className="inline-flex items-center gap-0.5 text-[9px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap" style={{ background: "var(--success-muted)", color: "var(--success)" }}>
                      <CheckCircle2 size={8} /> SEO
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1 flex-shrink-0">
            <button
              onClick={() => setShowDeleteConfirm(true)}
              className="p-1.5 rounded-lg transition-colors cursor-pointer flex-shrink-0"
              style={{ color: "var(--text-tertiary)" }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255, 69, 58, 0.1)"; e.currentTarget.style.color = "var(--error)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--text-tertiary)"; }}
              title="Delete beat"
            >
              <Trash2 size={14} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-bg-hover transition-colors cursor-pointer text-text-tertiary hover:text-foreground flex-shrink-0"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Delete Confirmation */}
        {showDeleteConfirm && (
          <div
            className="mx-0 mb-3 p-3 rounded-xl flex items-start gap-3"
            style={{
              background: "rgba(255, 69, 58, 0.08)",
              border: "1px solid rgba(255, 69, 58, 0.25)",
            }}
          >
            <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" style={{ color: "var(--error)" }} />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-semibold" style={{ color: "var(--error)" }}>
                Delete &ldquo;{beat.beat_name || beat.stem}&rdquo;?
              </p>
              <p className="text-[10px] mt-0.5" style={{ color: "var(--text-secondary)" }}>
                This removes the audio, metadata, rendered video, thumbnail, and all upload logs. Cannot be undone.
              </p>
              <div className="flex items-center gap-2 mt-2">
                <button
                  onClick={handleDelete}
                  disabled={deleting}
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5"
                  style={{ background: "var(--error)", color: "#fff", opacity: deleting ? 0.6 : 1 }}
                >
                  {deleting ? <Loader2 size={10} className="animate-spin" /> : <Trash2 size={10} />}
                  {deleting ? "Deleting..." : "Delete"}
                </button>
                <button
                  onClick={() => setShowDeleteConfirm(false)}
                  disabled={deleting}
                  className="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer"
                  style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-0.5 overflow-x-auto" style={{ scrollbarWidth: "none" }}>
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className="px-2.5 py-2 text-[11px] font-medium rounded-t-lg transition-all duration-150 cursor-pointer whitespace-nowrap flex-shrink-0"
              style={{
                color: activeTab === tab.id ? "var(--accent)" : "var(--text-tertiary)",
                background: activeTab === tab.id ? "var(--bg-card)" : "transparent",
                borderBottom: activeTab === tab.id ? "2px solid var(--accent)" : "2px solid transparent",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content — scrollable */}
      <div className="flex-1 overflow-y-auto p-5">
        {activeTab === "metadata" && <BeatMetadataTab beat={beat} onUpdated={handleUpdated} />}
        {activeTab === "seo" && <BeatSeoTab beat={beat} onUpdated={handleUpdated} />}
        {activeTab === "render" && <BeatRenderTab beat={beat} onUpdated={handleUpdated} />}
        {activeTab === "social" && <BeatSocialTab beat={beat} onUpdated={handleUpdated} />}
        {activeTab === "studio" && <BeatStudioTab beat={beat} onUpdated={handleUpdated} />}
      </div>
    </div>
  );
}
