"use client";

import { useState, useEffect } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Upload,
  RefreshCw,
  X,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { authedUrl, api } from "@/hooks/useApi";

interface UploadPreviewModalProps {
  stem: string | null;
  onClose: () => void;
  onUploaded?: (stem: string, videoUrl: string) => void;
}

interface PreviewData {
  stem: string;
  title: string;
  artist: string;
  bpm?: number;
  key?: string;
  already_uploaded: boolean;
  rendered: boolean;
  has_thumbnail: boolean;
  thumb_url: string;
  video_url: string;
}

type Step = "preview" | "confirm" | "uploading" | "done" | "error";

export default function UploadPreviewModal({
  stem: initialStem,
  onClose,
  onUploaded,
}: UploadPreviewModalProps) {
  const [stem, setStem] = useState(initialStem);
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [step, setStep] = useState<Step>("preview");
  const [privacy, setPrivacy] = useState<"public" | "unlisted" | "private">("public");
  const [scheduleAt, setScheduleAt] = useState("");
  const [bumping, setBumping] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadMessage, setUploadMessage] = useState("");
  const [youtubeUrl, setYoutubeUrl] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  // Reset when stem changes (new modal open)
  useEffect(() => {
    if (!initialStem) return;
    setStem(initialStem);
    setPreview(null);
    setStep("preview");
    setPrivacy("public");
    setScheduleAt("");
    setBumping(false);
    setUploadProgress(0);
    setUploadMessage("");
    setYoutubeUrl("");
    setErrorMsg("");
  }, [initialStem]);

  // Fetch preview data whenever stem changes
  useEffect(() => {
    if (!stem) return;
    setLoadingPreview(true);
    api
      .get<PreviewData>(`/youtube/upload-preview/${stem}`)
      .then((data) => {
        setPreview(data);
        setLoadingPreview(false);
      })
      .catch(() => {
        setLoadingPreview(false);
        setErrorMsg("Failed to load beat preview.");
        setStep("error");
      });
  }, [stem]);

  const handleClose = () => {
    if (step === "uploading") return; // block close during upload
    onClose();
  };

  const handleBump = async () => {
    if (!stem) return;
    setBumping(true);
    try {
      const res = await api.post<{ old_stem: string; new_stem: string }>(
        `/youtube/rebump/${stem}`
      );
      setStem(res.new_stem); // triggers preview re-fetch for new stem
      setStep("preview");
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : "Rebump failed");
      setStep("error");
    } finally {
      setBumping(false);
    }
  };

  const handleUpload = async () => {
    if (!stem) return;
    setStep("uploading");
    setUploadProgress(5);
    setUploadMessage("Starting upload...");

    try {
      const body: { privacy: string; scheduleAt?: string } = { privacy };
      if (scheduleAt) body.scheduleAt = new Date(scheduleAt).toISOString();

      setUploadProgress(20);
      setUploadMessage("Uploading to YouTube...");

      const res = await api.post<{ url?: string; videoId?: string }>(
        `/youtube/upload/${stem}`,
        body
      );

      setUploadProgress(100);
      setUploadMessage("Upload complete!");
      setYoutubeUrl(res.url || "");
      setStep("done");
      if (onUploaded && stem) onUploaded(stem, res.url || "");
    } catch (e: unknown) {
      setErrorMsg(e instanceof Error ? e.message : "Upload failed");
      setStep("error");
    }
  };

  const isOpen = !!initialStem;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => { if (!open) handleClose(); }}>
      <DialogContent
        className="sm:max-w-2xl p-0 overflow-hidden"
        style={{
          background: "var(--bg-card-solid, var(--bg-card))",
          border: "1px solid var(--border-light)",
          boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
        }}
      >
        <DialogHeader className="px-6 pt-5 pb-0 flex-row items-start justify-between">
          <DialogTitle
            className="text-foreground text-base font-bold truncate pr-4"
            style={{ color: "var(--text-primary)" }}
          >
            {step === "done"
              ? "Uploaded!"
              : step === "uploading"
              ? "Uploading..."
              : step === "error"
              ? "Error"
              : preview?.title || stem || "Upload Preview"}
          </DialogTitle>
          {step !== "uploading" && (
            <button
              onClick={handleClose}
              className="shrink-0 p-1 rounded-md transition-colors cursor-pointer"
              style={{ color: "var(--text-tertiary)" }}
            >
              <X size={16} />
            </button>
          )}
        </DialogHeader>

        <div className="px-6 pb-6 pt-4 space-y-4">

          {/* ── Loading state ── */}
          {loadingPreview && (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={24} className="animate-spin" style={{ color: "var(--accent)" }} />
            </div>
          )}

          {/* ── Preview step ── */}
          {!loadingPreview && step === "preview" && preview && (
            <>
              {/* Thumbnail + Video side by side */}
              <div className="grid grid-cols-2 gap-3">
                {/* Thumbnail */}
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider mb-1.5" style={{ color: "var(--text-tertiary)" }}>
                    Thumbnail
                  </p>
                  {preview.has_thumbnail ? (
                    <img
                      src={authedUrl(preview.thumb_url)}
                      alt={preview.title}
                      className="w-full rounded-lg object-cover"
                      style={{ aspectRatio: "16/9", background: "var(--bg-hover)" }}
                    />
                  ) : (
                    <div
                      className="w-full rounded-lg flex items-center justify-center text-xs"
                      style={{ aspectRatio: "16/9", background: "var(--bg-hover)", color: "var(--text-tertiary)" }}
                    >
                      No thumbnail
                    </div>
                  )}
                </div>

                {/* Video preview */}
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider mb-1.5" style={{ color: "var(--text-tertiary)" }}>
                    Video
                  </p>
                  {preview.rendered ? (
                    <video
                      key={stem}
                      src={authedUrl(preview.video_url)}
                      controls
                      autoPlay
                      muted
                      playsInline
                      className="w-full rounded-lg"
                      style={{ aspectRatio: "16/9", background: "#000", objectFit: "contain" }}
                    />
                  ) : (
                    <div
                      className="w-full rounded-lg flex items-center justify-center text-xs"
                      style={{ aspectRatio: "16/9", background: "var(--bg-hover)", color: "var(--text-tertiary)" }}
                    >
                      Not rendered
                    </div>
                  )}
                </div>
              </div>

              {/* Beat info */}
              <div className="flex items-center gap-3 flex-wrap">
                <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  {preview.artist}
                </span>
                {preview.bpm && (
                  <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}>
                    {preview.bpm} BPM
                  </span>
                )}
                {preview.key && (
                  <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}>
                    {preview.key}
                  </span>
                )}
                <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                  {stem}
                </span>
              </div>

              {/* Already-uploaded warning */}
              {preview.already_uploaded && (
                <div
                  className="flex items-start gap-3 p-3 rounded-xl"
                  style={{ background: "rgba(255, 190, 50, 0.08)", border: "1px solid rgba(255,190,50,0.25)" }}
                >
                  <AlertTriangle size={15} className="shrink-0 mt-0.5" style={{ color: "#ffbe32" }} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold" style={{ color: "#ffbe32" }}>
                      Already uploaded to YouTube
                    </p>
                    <p className="text-[11px] mt-0.5" style={{ color: "var(--text-secondary)" }}>
                      Bump to a new version with a slightly varied title so YouTube won&apos;t flag it.
                    </p>
                    <button
                      onClick={handleBump}
                      disabled={bumping}
                      className="mt-2 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer"
                      style={{ background: "rgba(255,190,50,0.15)", color: "#ffbe32", opacity: bumping ? 0.6 : 1 }}
                    >
                      {bumping ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
                      {bumping ? "Bumping..." : "Bump to new version"}
                    </button>
                  </div>
                </div>
              )}

              {/* CTA */}
              {!preview.already_uploaded && preview.rendered && (
                <button
                  onClick={() => setStep("confirm")}
                  className="w-full py-2.5 rounded-xl text-sm font-bold flex items-center justify-center gap-2 transition-all cursor-pointer"
                  style={{ background: "var(--accent)", color: "#fff" }}
                >
                  <Upload size={14} />
                  Looks good — continue to upload
                </button>
              )}
            </>
          )}

          {/* ── Confirm / options step ── */}
          {step === "confirm" && preview && (
            <>
              <div className="space-y-3">
                {/* Privacy */}
                <div>
                  <label className="block text-xs font-semibold mb-1.5" style={{ color: "var(--text-secondary)" }}>
                    Privacy
                  </label>
                  <div className="flex gap-2">
                    {(["public", "unlisted", "private"] as const).map((p) => (
                      <button
                        key={p}
                        onClick={() => setPrivacy(p)}
                        className="flex-1 py-2 rounded-lg text-xs font-semibold capitalize transition-all cursor-pointer"
                        style={{
                          background: privacy === p ? "var(--accent)" : "var(--bg-hover)",
                          color: privacy === p ? "#fff" : "var(--text-secondary)",
                          border: privacy === p ? "1px solid var(--accent)" : "1px solid transparent",
                        }}
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Schedule */}
                <div>
                  <label className="block text-xs font-semibold mb-1.5" style={{ color: "var(--text-secondary)" }}>
                    Schedule (optional)
                  </label>
                  <input
                    type="datetime-local"
                    value={scheduleAt}
                    onChange={(e) => setScheduleAt(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                    style={{
                      background: "var(--bg-hover)",
                      border: "1px solid var(--border)",
                      color: "var(--text-primary)",
                    }}
                  />
                  {scheduleAt && (
                    <p className="text-[10px] mt-1" style={{ color: "var(--text-tertiary)" }}>
                      Will upload as Private with scheduled publish time (YouTube requirement)
                    </p>
                  )}
                </div>

                {/* Stem confirmation */}
                <div
                  className="px-3 py-2.5 rounded-lg text-xs"
                  style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
                >
                  Uploading as: <span className="font-mono font-semibold" style={{ color: "var(--text-primary)" }}>{stem}</span>
                  <span className="ml-2" style={{ color: "var(--text-tertiary)" }}>"{preview.title}"</span>
                </div>
              </div>

              <div className="flex gap-2">
                <button
                  onClick={() => setStep("preview")}
                  className="flex-1 py-2.5 rounded-xl text-sm font-semibold transition-all cursor-pointer"
                  style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
                >
                  Back
                </button>
                <button
                  onClick={handleUpload}
                  className="flex-1 py-2.5 rounded-xl text-sm font-bold flex items-center justify-center gap-2 transition-all cursor-pointer"
                  style={{ background: "var(--accent)", color: "#fff" }}
                >
                  <Upload size={14} />
                  Upload to YouTube
                </button>
              </div>
            </>
          )}

          {/* ── Uploading progress ── */}
          {step === "uploading" && (
            <div className="py-8 space-y-4">
              <div className="flex items-center justify-center">
                <Loader2 size={32} className="animate-spin" style={{ color: "var(--accent)" }} />
              </div>
              <div>
                <div className="flex justify-between text-xs mb-1.5" style={{ color: "var(--text-secondary)" }}>
                  <span>{uploadMessage}</span>
                  <span>{uploadProgress}%</span>
                </div>
                <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "var(--bg-hover)" }}>
                  <div
                    className="h-full rounded-full transition-all duration-700"
                    style={{ width: `${uploadProgress}%`, background: "var(--accent)" }}
                  />
                </div>
              </div>
            </div>
          )}

          {/* ── Done ── */}
          {step === "done" && (
            <div className="py-6 space-y-4 text-center">
              <CheckCircle2 size={40} className="mx-auto" style={{ color: "var(--success)" }} />
              <div>
                <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                  Successfully uploaded to YouTube
                </p>
                {youtubeUrl && (
                  <a
                    href={youtubeUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs mt-1 underline block"
                    style={{ color: "var(--accent)" }}
                  >
                    {youtubeUrl}
                  </a>
                )}
              </div>
              <button
                onClick={onClose}
                className="mx-auto px-6 py-2.5 rounded-xl text-sm font-semibold transition-all cursor-pointer"
                style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
              >
                Close
              </button>
            </div>
          )}

          {/* ── Error ── */}
          {step === "error" && (
            <div className="py-6 space-y-4 text-center">
              <AlertTriangle size={32} className="mx-auto" style={{ color: "var(--error)" }} />
              <p className="text-sm font-semibold" style={{ color: "var(--error)" }}>
                {errorMsg || "Something went wrong"}
              </p>
              <div className="flex gap-2 justify-center">
                <button
                  onClick={() => { setStep("preview"); setErrorMsg(""); }}
                  className="px-4 py-2 rounded-xl text-xs font-semibold cursor-pointer"
                  style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
                >
                  Try again
                </button>
                <button
                  onClick={onClose}
                  className="px-4 py-2 rounded-xl text-xs font-semibold cursor-pointer"
                  style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}
                >
                  Close
                </button>
              </div>
            </div>
          )}

        </div>
      </DialogContent>
    </Dialog>
  );
}
