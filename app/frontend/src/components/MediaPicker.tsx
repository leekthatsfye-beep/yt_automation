"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  Film,
  Image as ImageIcon,
  Upload,
  Check,
  Loader2,
  FolderOpen,
  X,
  Monitor,
  Smartphone,
  Clock,
  HardDrive,
} from "lucide-react";
import { api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import SearchInput from "@/components/ui/SearchInput";
import AuthImage from "@/components/AuthImage";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

/* ---------- types ---------- */

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

interface Assignment {
  stem: string;
  clip: string | null;
  image: string | null;
  source: string;
}

interface MediaPickerProps {
  stem: string;
  open: boolean;
  onClose: () => void;
  onAssign?: (clip: string | null, image: string | null) => void;
  currentClip?: string | null;
  currentImage?: string | null;
}

/* ---------- component ---------- */

export default function MediaPicker({
  stem,
  open,
  onClose,
  onAssign,
  currentClip,
  currentImage,
}: MediaPickerProps) {
  const { toast: showToast } = useToast();

  // Browse data
  const [media, setMedia] = useState<BrowseResult | null>(null);
  const [loadingMedia, setLoadingMedia] = useState(false);

  // Selection
  const [selectedClip, setSelectedClip] = useState<string | null>(currentClip ?? null);
  const [selectedImage, setSelectedImage] = useState<string | null>(currentImage ?? null);
  const [mediaType, setMediaType] = useState<"clips" | "images">("clips");
  const [search, setSearch] = useState("");

  // Upload
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Saving
  const [saving, setSaving] = useState(false);

  // Load browse data when opening
  useEffect(() => {
    if (!open) return;
    setLoadingMedia(true);
    api
      .get<BrowseResult>("/media/browse")
      .then((data) => setMedia(data))
      .catch((err) => showToast(`Failed to load media: ${err.message}`, "error"))
      .finally(() => setLoadingMedia(false));
  }, [open, showToast]);

  // Reset selections on open
  useEffect(() => {
    if (open) {
      setSelectedClip(currentClip ?? null);
      setSelectedImage(currentImage ?? null);
      setSearch("");
    }
  }, [open, currentClip, currentImage]);

  // Filter media items by search
  const filteredItems = useCallback(() => {
    if (!media) return [];
    const items = mediaType === "clips" ? media.clips : media.images;
    if (!search.trim()) return items;
    const q = search.toLowerCase();
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        item.path.toLowerCase().includes(q) ||
        item.folder.toLowerCase().includes(q)
    );
  }, [media, mediaType, search]);

  // Handle file upload
  const handleUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      setUploading(true);
      setUploadProgress("Uploading...");

      try {
        const formData = new FormData();
        formData.append("file", file);

        const token = localStorage.getItem("fy3-token");
        const res = await fetch("/api/media/upload", {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: formData,
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: "Upload failed" }));
          throw new Error(err.detail || "Upload failed");
        }

        const result = await res.json();
        showToast(
          `Uploaded ${result.name}${result.compressed ? " (auto-compressed)" : ""}`,
          "success"
        );

        // Auto-select the uploaded file
        if (result.type === "clip") {
          setSelectedClip(result.path);
          setSelectedImage(null);
          setMediaType("clips");
        } else {
          setSelectedImage(result.path);
          setSelectedClip(null);
          setMediaType("images");
        }

        // Refresh browse data
        const refreshed = await api.get<BrowseResult>("/media/browse");
        setMedia(refreshed);
      } catch (err) {
        showToast(
          `Upload failed: ${err instanceof Error ? err.message : "Unknown error"}`,
          "error"
        );
      } finally {
        setUploading(false);
        setUploadProgress("");
        if (fileInputRef.current) fileInputRef.current.value = "";
      }
    },
    [showToast]
  );

  // Save assignment
  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      await api.put(`/media/${stem}/assignment`, {
        clip: selectedClip,
        image: selectedImage,
      });
      showToast(`Media assigned to ${stem}`, "success");
      onAssign?.(selectedClip, selectedImage);
      onClose();
    } catch (err) {
      showToast(
        `Failed to save: ${err instanceof Error ? err.message : "Unknown error"}`,
        "error"
      );
    } finally {
      setSaving(false);
    }
  }, [stem, selectedClip, selectedImage, onAssign, onClose, showToast]);

  // Clear assignment
  const handleClear = useCallback(async () => {
    setSaving(true);
    try {
      await api.put(`/media/${stem}/assignment`, { clip: null, image: null });
      showToast(`Media assignment cleared for ${stem}`, "success");
      setSelectedClip(null);
      setSelectedImage(null);
      onAssign?.(null, null);
      onClose();
    } catch (err) {
      showToast(
        `Failed to clear: ${err instanceof Error ? err.message : "Unknown error"}`,
        "error"
      );
    } finally {
      setSaving(false);
    }
  }, [stem, onAssign, onClose, showToast]);

  const items = filteredItems();
  const hasAssignment = selectedClip || selectedImage;

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-[95vw] sm:max-w-3xl max-h-[90vh] flex flex-col bg-bg-card border-border overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-foreground">
            <Film size={18} className="text-accent" />
            Choose Media for {stem}
          </DialogTitle>
          <DialogDescription className="text-text-tertiary">
            Select a video clip or image to use as the background for this render
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="browse" className="flex-1 min-h-0 flex flex-col">
          <TabsList className="bg-muted">
            <TabsTrigger value="browse" className="gap-1.5">
              <FolderOpen size={13} /> Browse Server
            </TabsTrigger>
            <TabsTrigger value="upload" className="gap-1.5">
              <Upload size={13} /> Upload New
            </TabsTrigger>
          </TabsList>

          {/* ======= Browse Tab ======= */}
          <TabsContent value="browse" className="flex-1 min-h-0 flex flex-col gap-3">
            {/* Media type toggle + search */}
            <div className="flex flex-col sm:flex-row gap-2">
              <div className="flex bg-muted rounded-lg p-0.5 flex-shrink-0">
                <button
                  onClick={() => setMediaType("clips")}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                    mediaType === "clips"
                      ? "bg-accent text-white shadow-sm"
                      : "text-text-tertiary hover:text-foreground"
                  }`}
                >
                  <Film size={12} className="inline mr-1" />
                  Clips ({media?.clips.length ?? 0})
                </button>
                <button
                  onClick={() => setMediaType("images")}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                    mediaType === "images"
                      ? "bg-accent text-white shadow-sm"
                      : "text-text-tertiary hover:text-foreground"
                  }`}
                >
                  <ImageIcon size={12} className="inline mr-1" />
                  Images ({media?.images.length ?? 0})
                </button>
              </div>
              <SearchInput
                value={search}
                onChange={setSearch}
                placeholder="Search media..."
                size="sm"
                className="flex-1"
              />
            </div>

            {/* Media grid */}
            <div className="flex-1 overflow-y-auto min-h-0" style={{ maxHeight: "45vh" }}>
              {loadingMedia ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 size={24} className="animate-spin text-accent" />
                </div>
              ) : items.length === 0 ? (
                <div className="text-center py-12 text-text-tertiary text-sm">
                  {search ? `No ${mediaType} matching "${search}"` : `No ${mediaType} found`}
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
                  {items.map((item) => {
                    const isSelected =
                      mediaType === "clips"
                        ? selectedClip === item.path
                        : selectedImage === item.path;

                    return (
                      <button
                        key={item.path}
                        onClick={() => {
                          if (mediaType === "clips") {
                            setSelectedClip(isSelected ? null : item.path);
                            setSelectedImage(null);
                          } else {
                            setSelectedImage(isSelected ? null : item.path);
                            setSelectedClip(null);
                          }
                        }}
                        className={`relative rounded-lg overflow-hidden text-left transition-all duration-200 group ${
                          isSelected
                            ? "ring-2 ring-accent ring-offset-2 ring-offset-bg-card"
                            : "hover:ring-1 hover:ring-border-light"
                        }`}
                      >
                        {/* Preview */}
                        <div className="aspect-video bg-muted relative overflow-hidden">
                          {mediaType === "clips" && item.path.endsWith(".mp4") ? (
                            <AuthImage
                              src={`/files/images/${item.path}`}
                              alt={item.name}
                              className="w-full h-full object-cover"
                              fallback={
                                <div className="w-full h-full flex items-center justify-center bg-muted">
                                  <Film size={24} className="text-text-tertiary" />
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

                          {/* Selection checkmark */}
                          {isSelected && (
                            <div className="absolute top-1.5 right-1.5 w-6 h-6 rounded-full bg-accent flex items-center justify-center">
                              <Check size={14} className="text-white" strokeWidth={3} />
                            </div>
                          )}

                          {/* Orientation badge */}
                          {item.orientation && (
                            <div className="absolute bottom-1.5 left-1.5">
                              <Badge
                                variant="secondary"
                                className="text-[9px] px-1.5 py-0 bg-black/60 text-white border-none gap-1"
                              >
                                {item.orientation === "portrait" ? (
                                  <Smartphone size={9} />
                                ) : (
                                  <Monitor size={9} />
                                )}
                                {item.orientation}
                              </Badge>
                            </div>
                          )}
                        </div>

                        {/* Info */}
                        <div className="p-2 bg-bg-card border border-t-0 border-border rounded-b-lg">
                          <p className="text-xs font-medium truncate text-foreground">
                            {item.name}
                          </p>
                          <div className="flex items-center gap-2 mt-0.5">
                            {item.resolution && item.resolution !== "unknown" && (
                              <span className="text-[10px] text-text-tertiary">
                                {item.resolution}
                              </span>
                            )}
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
                          {item.folder && (
                            <span className="text-[10px] text-accent">{item.folder}/</span>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </TabsContent>

          {/* ======= Upload Tab ======= */}
          <TabsContent value="upload" className="flex-1">
            <div className="flex flex-col items-center justify-center py-12 gap-4">
              <div className="w-20 h-20 rounded-lg bg-accent-muted flex items-center justify-center">
                <Upload size={32} className="text-accent" />
              </div>
              <div className="text-center">
                <p className="text-sm font-medium text-foreground mb-1">
                  Upload from device
                </p>
                <p className="text-xs text-text-tertiary max-w-xs">
                  Select a video clip (.mp4, .mov) or image (.jpg, .png) from your Photos or Files.
                  Large files are auto-compressed.
                </p>
              </div>

              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,video/mp4,video/quicktime"
                onChange={handleUpload}
                className="hidden"
              />

              <Button
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                variant="default"
                size="lg"
              >
                {uploading ? (
                  <>
                    <Loader2 size={14} className="animate-spin" />
                    {uploadProgress || "Uploading..."}
                  </>
                ) : (
                  <>
                    <FolderOpen size={14} />
                    Choose File
                  </>
                )}
              </Button>
            </div>
          </TabsContent>
        </Tabs>

        {/* ======= Footer ======= */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-3 border-t border-border">
          <div className="flex items-center gap-2 text-xs text-text-tertiary min-w-0">
            {hasAssignment ? (
              <>
                <Check size={12} className="text-accent flex-shrink-0" />
                <span className="truncate">
                  Selected: <strong className="text-foreground">{selectedClip || selectedImage}</strong>
                </span>
              </>
            ) : (
              <span>No media selected (will use auto-pick)</span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {(currentClip || currentImage) && (
              <Button
                onClick={handleClear}
                disabled={saving}
                variant="ghost"
                size="sm"
                className="text-error hover:bg-error-muted"
              >
                <X size={12} />
                Clear
              </Button>
            )}
            <Button onClick={onClose} variant="ghost" size="sm">
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={saving}
              variant="default"
              size="sm"
            >
              {saving ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Check size={12} />
              )}
              {saving ? "Saving..." : "Assign Media"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
