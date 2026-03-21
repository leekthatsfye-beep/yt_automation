"use client";

import { useState } from "react";
import { AlertCircle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { authedUrl } from "@/hooks/useApi";

interface VideoPreviewModalProps {
  stem: string | null;
  title?: string;
  onClose: () => void;
}

/**
 * Video preview modal — streams MP4 directly via ?token= auth.
 * No blob download; instant playback with native browser streaming.
 */
export default function VideoPreviewModal({
  stem,
  title,
  onClose,
}: VideoPreviewModalProps) {
  const [error, setError] = useState(false);

  const videoSrc = stem ? authedUrl(`/files/output/${stem}.mp4`) : null;

  return (
    <Dialog
      open={!!stem}
      onOpenChange={(open) => {
        if (!open) {
          setError(false);
          onClose();
        }
      }}
    >
      <DialogContent
        className="sm:max-w-3xl p-0 overflow-hidden"
        style={{
          background: "var(--bg-card-solid, var(--bg-card))",
          border: "1px solid var(--border-light)",
          boxShadow: "0 24px 80px rgba(0, 0, 0, 0.6), 0 0 40px rgba(0, 0, 0, 0.3)",
        }}
      >
        <DialogHeader className="px-6 pt-5 pb-0">
          <DialogTitle
            className="text-foreground truncate text-lg font-bold"
            style={{ color: "var(--text-primary)" }}
          >
            {title || stem}
          </DialogTitle>
        </DialogHeader>
        <div className="px-4 pb-4 pt-3">
          {error ? (
            <div
              className="w-full flex items-center justify-center rounded-lg"
              style={{
                aspectRatio: "16/9",
                background: "var(--bg-primary)",
                border: "1px solid var(--border)",
              }}
            >
              <div className="flex flex-col items-center gap-3">
                <AlertCircle size={28} style={{ color: "var(--error)", opacity: 0.6 }} />
                <span className="text-xs font-medium" style={{ color: "var(--text-tertiary)" }}>
                  Unable to load video
                </span>
              </div>
            </div>
          ) : videoSrc ? (
            <video
              key={stem}
              src={videoSrc}
              controls
              autoPlay
              playsInline
              className="w-full rounded-lg"
              style={{
                maxHeight: "60vh",
                background: "#000",
              }}
              onError={() => setError(true)}
            />
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
