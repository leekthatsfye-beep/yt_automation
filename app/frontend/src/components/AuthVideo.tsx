"use client";

import { useState } from "react";
import { AlertCircle } from "lucide-react";
import { authedUrl } from "@/hooks/useApi";

interface AuthVideoProps {
  src: string;
  className?: string;
  poster?: string;
}

/**
 * Video component that streams via ?token= auth in the URL.
 * No blob download — instant playback with native browser streaming.
 */
export default function AuthVideo({ src, className, poster }: AuthVideoProps) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <div
        className="w-full aspect-video rounded-lg flex flex-col items-center justify-center gap-3"
        style={{ background: "var(--bg-primary)", border: "1px solid var(--border)" }}
      >
        <AlertCircle size={28} style={{ color: "var(--error)", opacity: 0.6 }} />
        <p className="text-xs font-medium" style={{ color: "var(--text-tertiary)" }}>
          Unable to load video
        </p>
      </div>
    );
  }

  return (
    <video
      src={authedUrl(src)}
      controls
      poster={poster}
      className={className}
      playsInline
      preload="metadata"
      style={{ borderRadius: 8 }}
      onError={() => setFailed(true)}
    />
  );
}
