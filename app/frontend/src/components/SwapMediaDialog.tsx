"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  ArrowLeftRight,
  Film,
  Image as ImageIcon,
  Check,
  Loader2,
  Clock,
  HardDrive,
  Monitor,
  Smartphone,
  Music,
  RotateCcw,
} from "lucide-react";
import { api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import SearchInput from "@/components/ui/SearchInput";
import AuthImage from "@/components/AuthImage";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

/* ── Types ── */

interface MediaItem {
  path: string;
  name: string;
  folder: string;
  size_mb: number;
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

interface SwapMediaDialogProps {
  open: boolean;
  currentFile: string;
  mediaType: "clip" | "image";
  affectedBeats: string[];
  onSwap?: () => void;
  onClose: () => void;
}

/* ── Component ── */

export default function SwapMediaDialog({
  open,
  currentFile,
  mediaType,
  affectedBeats,
  onSwap,
  onClose,
}: SwapMediaDialogProps) {
  const { toast } = useToast();

  const [media, setMedia] = useState<BrowseResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [reRender, setReRender] = useState(true);
  const [saving, setSaving] = useState(false);

  // Load browse data on open
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    setSelectedFile(null);
    setSearch("");
    api
      .get<BrowseResult>("/media/browse")
      .then(setMedia)
      .catch((err) => toast(`Failed to load media: ${err.message}`, "error"))
      .finally(() => setLoading(false));
  }, [open, toast]);

  // Filter items — only show same type as current, exclude current file
  const items = useMemo(() => {
    if (!media) return [];
    const list = mediaType === "clip" ? media.clips : media.images;
    let filtered = list.filter((i) => i.name !== currentFile);
    if (search.trim()) {
      const q = search.toLowerCase();
      filtered = filtered.filter((i) => i.name.toLowerCase().includes(q));
    }
    return filtered;
  }, [media, mediaType, currentFile, search]);

  // Swap action
  const handleSwap = useCallback(async () => {
    if (!selectedFile || affectedBeats.length === 0) return;
    setSaving(true);
    try {
      // Update assignment for each affected beat
      for (const stem of affectedBeats) {
        const body =
          mediaType === "clip"
            ? { clip: selectedFile, image: null }
            : { clip: null, image: selectedFile };
        await api.put(`/media/${stem}/assignment`, body);
      }

      toast(
        `Swapped ${currentFile} → ${selectedFile} for ${affectedBeats.length} beat${affectedBeats.length !== 1 ? "s" : ""}`,
        "success"
      );

      // Optionally queue re-renders
      if (reRender) {
        for (const stem of affectedBeats) {
          try {
            await api.post(`/render/${stem}`);
          } catch {
            // Non-critical — user can re-render manually
          }
        }
        if (affectedBeats.length > 0) {
          toast(`Queued re-render for ${affectedBeats.length} beat${affectedBeats.length !== 1 ? "s" : ""}`, "info");
        }
      }

      onSwap?.();
      onClose();
    } catch (e) {
      toast(`Swap failed: ${e instanceof Error ? e.message : "Unknown error"}`, "error");
    } finally {
      setSaving(false);
    }
  }, [selectedFile, affectedBeats, mediaType, currentFile, reRender, toast, onSwap, onClose]);

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-[95vw] sm:max-w-2xl max-h-[85vh] flex flex-col bg-bg-card border-border overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-foreground">
            <ArrowLeftRight size={18} className="text-accent" />
            Swap {mediaType === "clip" ? "Clip" : "Image"}
          </DialogTitle>
          <DialogDescription className="text-text-tertiary">
            Replace <strong className="text-foreground">{currentFile}</strong> across{" "}
            {affectedBeats.length} beat{affectedBeats.length !== 1 ? "s" : ""}
          </DialogDescription>
        </DialogHeader>

        {/* Affected beats */}
        {affectedBeats.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-1">
            {affectedBeats.map((stem) => (
              <span
                key={stem}
                className="inline-flex items-center gap-1 text-[10px] font-medium px-2 py-0.5 rounded-full"
                style={{ background: "var(--accent-muted)", color: "var(--accent)" }}
              >
                <Music size={9} />
                {stem.replace(/_/g, " ")}
              </span>
            ))}
          </div>
        )}

        {/* Search */}
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder={`Search ${mediaType === "clip" ? "clips" : "images"}...`}
          size="sm"
        />

        {/* Grid */}
        <div className="flex-1 overflow-y-auto min-h-0" style={{ maxHeight: "40vh" }}>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={24} className="animate-spin text-accent" />
            </div>
          ) : items.length === 0 ? (
            <div className="text-center py-12 text-text-tertiary text-sm">
              {search ? `No ${mediaType}s matching "${search}"` : `No other ${mediaType}s available`}
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {items.map((item) => {
                const isSelected = selectedFile === item.path;
                return (
                  <button
                    key={item.path}
                    onClick={() => setSelectedFile(isSelected ? null : item.path)}
                    className={`relative rounded-lg overflow-hidden text-left transition-all duration-200 group cursor-pointer ${
                      isSelected
                        ? "ring-2 ring-accent ring-offset-2 ring-offset-bg-card"
                        : "hover:ring-1 hover:ring-border-light"
                    }`}
                  >
                    <div className="aspect-video bg-muted relative overflow-hidden">
                      <AuthImage
                        src={`/files/images/${item.path}`}
                        alt={item.name}
                        className="w-full h-full object-cover"
                        fallback={
                          <div className="w-full h-full flex items-center justify-center bg-muted">
                            {mediaType === "clip" ? <Film size={20} className="text-text-tertiary" /> : <ImageIcon size={20} className="text-text-tertiary" />}
                          </div>
                        }
                      />
                      {isSelected && (
                        <div className="absolute top-1.5 right-1.5 w-6 h-6 rounded-full bg-accent flex items-center justify-center">
                          <Check size={14} className="text-white" strokeWidth={3} />
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
                    <div className="p-2 bg-bg-card border border-t-0 border-border rounded-b-lg">
                      <p className="text-xs font-medium truncate text-foreground">{item.name}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        {item.duration != null && item.duration > 0 && (
                          <span className="text-[10px] text-text-tertiary flex items-center gap-0.5">
                            <Clock size={8} />
                            {item.duration}s
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
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-3 border-t border-border">
          <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer select-none">
            <input
              type="checkbox"
              checked={reRender}
              onChange={(e) => setReRender(e.target.checked)}
              className="rounded accent-[var(--accent)]"
            />
            <RotateCcw size={12} />
            Re-render affected beats after swap
          </label>
          <div className="flex items-center gap-2">
            <Button onClick={onClose} variant="ghost" size="sm">
              Cancel
            </Button>
            <Button
              onClick={handleSwap}
              disabled={saving || !selectedFile}
              variant="default"
              size="sm"
            >
              {saving ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <ArrowLeftRight size={12} />
              )}
              {saving ? "Swapping..." : "Swap & Apply"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
