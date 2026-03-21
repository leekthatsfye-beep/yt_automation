"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Film, Upload, Youtube, Loader2, CheckCircle2, ExternalLink, ImagePlus, Palette, Play, X, Image as ImageIcon } from "lucide-react";
import { api, useFetch } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useSettings } from "@/hooks/useSettings";
import AuthImage from "@/components/AuthImage";
import AuthVideo from "@/components/AuthVideo";
import MediaPicker from "@/components/MediaPicker";
import VideoPreviewModal from "@/components/VideoPreviewModal";
import type { Beat } from "@/types/beat";

interface Props {
  beat: Beat;
  onUpdated: () => void;
}

interface MediaAssignment {
  clip: string | null;
  image: string | null;
  clip_label?: string;
  image_label?: string;
}

export default function BeatRenderTab({ beat, onUpdated }: Props) {
  const { toast } = useToast();
  const { lastMessage } = useWebSocket();
  const { settings } = useSettings();

  const [rendering, setRendering] = useState(false);
  const [renderProgress, setRenderProgress] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [mediaPickerOpen, setMediaPickerOpen] = useState(false);
  const [videoPreviewStem, setVideoPreviewStem] = useState<string | null>(null);
  const [thumbUploading, setThumbUploading] = useState(false);
  const [thumbKey, setThumbKey] = useState(0); // cache-buster for thumbnail reload
  const [dragOver, setDragOver] = useState(false);
  const thumbInputRef = useRef<HTMLInputElement>(null);

  // Fetch current media assignment
  const { data: mediaAssignment, refetch: refetchMedia } = useFetch<MediaAssignment>(
    `/media/${beat.stem}/assignment`
  );

  // Listen for WebSocket progress
  useEffect(() => {
    if (!lastMessage || lastMessage.type !== "progress") return;
    if (typeof lastMessage.taskId === "string" && lastMessage.taskId.includes(beat.stem)) {
      if (lastMessage.phase === "render") {
        setRenderProgress(lastMessage.pct ?? 0);
        if (lastMessage.pct === 100) {
          setTimeout(() => { setRendering(false); setRenderProgress(0); onUpdated(); }, 500);
        }
      }
      if (lastMessage.phase === "upload" && lastMessage.pct === 100) {
        setTimeout(() => { setUploading(false); onUpdated(); }, 500);
      }
    }
  }, [lastMessage, beat.stem, onUpdated]);

  const handleRender = async () => {
    setRendering(true);
    setRenderProgress(0);
    try {
      await api.post(`/render/${beat.stem}`);
      toast("Render started", "info");
    } catch {
      toast("Failed to start render", "error");
      setRendering(false);
    }
  };

  const handleUpload = async () => {
    setUploading(true);
    try {
      await api.post(`/youtube/upload/${beat.stem}`, { privacy: settings.defaultPrivacy || "unlisted" });
      toast("Upload started", "info");
    } catch {
      toast("Failed to start upload", "error");
      setUploading(false);
    }
  };

  const handleMediaAssigned = useCallback(() => {
    refetchMedia();
    toast("Media updated", "success");
  }, [refetchMedia, toast]);

  const uploadThumbnail = useCallback(async (file: File) => {
    if (!file.type.startsWith("image/")) {
      toast("Please select an image file", "error");
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      toast("Image must be under 20MB", "error");
      return;
    }
    setThumbUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      await api.upload(`/beats/${beat.stem}/upload-thumbnail`, form);
      setThumbKey((k) => k + 1); // bust image cache
      toast("Thumbnail updated", "success");
      onUpdated();
    } catch {
      toast("Failed to upload thumbnail", "error");
    } finally {
      setThumbUploading(false);
    }
  }, [beat.stem, toast, onUpdated]);

  const handleThumbDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadThumbnail(file);
  }, [uploadThumbnail]);

  const handleThumbFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadThumbnail(file);
    e.target.value = ""; // reset so same file can be re-uploaded
  }, [uploadThumbnail]);

  const currentMediaLabel = mediaAssignment?.clip
    ? `Clip: ${mediaAssignment.clip_label || mediaAssignment.clip}`
    : mediaAssignment?.image
    ? `Image: ${mediaAssignment.image_label || mediaAssignment.image}`
    : "Auto-pick (default)";

  return (
    <div className="space-y-5">
      {/* ── Media Assignment ────────────────────────────────────── */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-tertiary mb-2">
          Render Media
        </p>
        <div
          className="flex items-center gap-3 p-3 rounded-xl cursor-pointer transition-all duration-200"
          style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
          onClick={() => setMediaPickerOpen(true)}
        >
          <div className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
            style={{ background: "rgba(var(--accent-rgb, 99,102,241), 0.15)" }}>
            <Palette size={16} className="text-accent" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-foreground truncate">{currentMediaLabel}</p>
            <p className="text-[10px] text-text-tertiary">Click to choose clip or image for render</p>
          </div>
          <ImagePlus size={16} className="text-text-tertiary flex-shrink-0" />
        </div>
      </div>

      {/* ── Video Preview ─────────────────────────────────────────── */}
      {beat.rendered && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">Rendered Video</p>
            <button
              className="text-[10px] text-accent font-semibold cursor-pointer flex items-center gap-1"
              onClick={() => setVideoPreviewStem(beat.stem)}
            >
              <Play size={10} /> Full Preview
            </button>
          </div>
          <div className="rounded-xl overflow-hidden" style={{ border: "1px solid var(--border)" }}>
            <AuthVideo
              src={`/files/output/${beat.stem}.mp4`}
              className="w-full"
            />
          </div>
        </div>
      )}

      {/* ── Thumbnail ──────────────────────────────────────────────── */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">Thumbnail</p>
          <button
            onClick={() => thumbInputRef.current?.click()}
            disabled={thumbUploading}
            className="text-[10px] font-semibold cursor-pointer flex items-center gap-1 px-2 py-1 rounded-md transition-colors"
            style={{ color: "var(--accent)", background: "var(--accent-muted)" }}
          >
            {thumbUploading ? <Loader2 size={10} className="animate-spin" /> : <Upload size={10} />}
            {thumbUploading ? "Uploading..." : "Upload"}
          </button>
        </div>
        <input
          ref={thumbInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={handleThumbFileChange}
        />
        {beat.has_thumbnail ? (
          <div
            className="rounded-xl overflow-hidden relative group cursor-pointer"
            style={{
              border: dragOver ? "2px dashed var(--accent)" : "1px solid var(--border)",
              background: dragOver ? "var(--accent-muted)" : undefined,
            }}
            onClick={() => thumbInputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleThumbDrop}
          >
            <AuthImage
              key={thumbKey}
              src={`/files/output/${beat.stem}_thumb.jpg?v=${thumbKey}`}
              alt={`${beat.beat_name || beat.stem} thumbnail`}
              className="w-full"
            />
            {/* Hover overlay */}
            <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
              <Upload size={18} className="text-white" />
              <span className="text-white text-xs font-semibold">Replace thumbnail</span>
            </div>
            {dragOver && (
              <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
                <span className="text-white text-sm font-semibold">Drop to upload</span>
              </div>
            )}
          </div>
        ) : (
          <div
            className="rounded-xl flex flex-col items-center justify-center gap-2 py-8 cursor-pointer transition-all"
            style={{
              border: dragOver ? "2px dashed var(--accent)" : "2px dashed var(--border)",
              background: dragOver ? "var(--accent-muted)" : "var(--bg-hover)",
            }}
            onClick={() => thumbInputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleThumbDrop}
          >
            <ImageIcon size={24} style={{ color: "var(--text-tertiary)", opacity: 0.5 }} />
            <p className="text-xs font-medium" style={{ color: "var(--text-tertiary)" }}>
              {dragOver ? "Drop to upload" : "Drop image or click to upload"}
            </p>
            <p className="text-[10px]" style={{ color: "var(--text-tertiary)", opacity: 0.6 }}>
              FY3 logo will be stamped automatically
            </p>
          </div>
        )}
      </div>

      {/* ── Render & Upload Actions ──────────────────────────────── */}
      <div className="space-y-3">
        {/* Render Button */}
        <button
          onClick={handleRender}
          disabled={rendering}
          className="w-full py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all duration-200 cursor-pointer"
          style={{
            background: beat.rendered
              ? "var(--bg-hover)"
              : "linear-gradient(135deg, var(--success), #00a848)",
            color: beat.rendered ? "var(--text-secondary)" : "#fff",
            opacity: rendering ? 0.6 : 1,
            border: beat.rendered ? "1px solid var(--border)" : "none",
            boxShadow: !beat.rendered ? "0 4px 16px rgba(0, 211, 98, 0.3)" : "none",
          }}
        >
          {rendering ? (
            <><Loader2 size={15} className="animate-spin" /> Rendering... {renderProgress}%</>
          ) : beat.rendered ? (
            <><Film size={15} /> Re-render Video</>
          ) : (
            <><Film size={15} /> Render 16:9 Video</>
          )}
        </button>

        {/* Render Progress Bar */}
        {rendering && (
          <div className="h-2 rounded-full overflow-hidden" style={{ background: "var(--bg-hover)" }}>
            <div
              className="h-full rounded-full transition-all duration-300"
              style={{
                width: `${renderProgress}%`,
                background: "var(--success)",
                boxShadow: "0 0 12px var(--success)",
              }}
            />
          </div>
        )}

        {/* Upload to YouTube */}
        {beat.rendered && (
          <button
            onClick={handleUpload}
            disabled={uploading || beat.uploaded}
            className="w-full py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all duration-200 cursor-pointer"
            style={{
              background: beat.uploaded
                ? "var(--success-muted)"
                : "linear-gradient(135deg, #ff0000, #cc0000)",
              color: beat.uploaded ? "var(--success)" : "#fff",
              opacity: uploading ? 0.6 : 1,
              border: beat.uploaded ? "1px solid var(--success)30" : "none",
              boxShadow: !beat.uploaded ? "0 4px 16px rgba(255, 0, 0, 0.2)" : "none",
            }}
          >
            {uploading ? (
              <><Loader2 size={15} className="animate-spin" /> Uploading to YouTube...</>
            ) : beat.uploaded ? (
              <><CheckCircle2 size={15} /> Uploaded to YouTube</>
            ) : (
              <><Youtube size={15} /> Upload to YouTube</>
            )}
          </button>
        )}

        {/* YouTube Link */}
        {beat.youtube?.url && (
          <a
            href={beat.youtube.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-xs text-accent hover:underline py-2"
          >
            <ExternalLink size={12} /> View on YouTube
          </a>
        )}
      </div>

      {/* ── Status Summary ─────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3">
        <div className="p-3 rounded-xl text-center" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
          <div className="w-8 h-8 rounded-lg flex items-center justify-center mx-auto mb-2" style={{ background: beat.rendered ? "var(--success-muted)" : "var(--bg-card)" }}>
            <Film size={14} style={{ color: beat.rendered ? "var(--success)" : "var(--text-tertiary)" }} />
          </div>
          <p className="text-[11px] font-semibold" style={{ color: beat.rendered ? "var(--success)" : "var(--text-tertiary)" }}>
            {beat.rendered ? "Rendered" : "Not Rendered"}
          </p>
        </div>
        <div className="p-3 rounded-xl text-center" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
          <div className="w-8 h-8 rounded-lg flex items-center justify-center mx-auto mb-2" style={{ background: beat.uploaded ? "var(--success-muted)" : "var(--bg-card)" }}>
            <Upload size={14} style={{ color: beat.uploaded ? "var(--success)" : "var(--text-tertiary)" }} />
          </div>
          <p className="text-[11px] font-semibold" style={{ color: beat.uploaded ? "var(--success)" : "var(--text-tertiary)" }}>
            {beat.uploaded ? "Uploaded" : "Not Uploaded"}
          </p>
        </div>
      </div>

      {/* ── Media Picker Dialog ────────────────────────────────────── */}
      <MediaPicker
        stem={beat.stem}
        open={mediaPickerOpen}
        onClose={() => setMediaPickerOpen(false)}
        onAssign={handleMediaAssigned}
        currentClip={mediaAssignment?.clip ?? null}
        currentImage={mediaAssignment?.image ?? null}
      />

      {/* ── Video Preview Modal ────────────────────────────────────── */}
      <VideoPreviewModal
        stem={videoPreviewStem}
        title={beat.beat_name || beat.stem}
        onClose={() => setVideoPreviewStem(null)}
      />
    </div>
  );
}
