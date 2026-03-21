"use client";

import { useRef, useCallback } from "react";
import {
  Play,
  Pause,
  X,
  Volume2,
  VolumeX,
  SkipBack,
  SkipForward,
  Music,
  Loader2,
  AlertCircle,
  RotateCcw,
} from "lucide-react";
import { useGlobalAudio, globalAudio } from "@/hooks/useGlobalAudio";

/* ── Mini Waveform Bars ──────────────────────────────── */

function MiniWaveform({ active, stem }: { active: boolean; stem: string }) {
  const bars: number[] = [];
  let seed = 0;
  for (let i = 0; i < stem.length; i++) {
    seed = ((seed << 5) - seed + stem.charCodeAt(i)) | 0;
  }
  const rand = () => {
    seed = (seed * 16807 + 0) % 2147483647;
    return (seed & 0x7fffffff) / 0x7fffffff;
  };
  for (let i = 0; i < 5; i++) {
    bars.push(rand() * 0.6 + 0.3);
  }

  return (
    <div className="flex items-center gap-[2px] h-4">
      {bars.map((h, i) => (
        <div
          key={i}
          className="w-[3px] rounded-full transition-all duration-300"
          style={{
            height: `${h * 100}%`,
            background: active ? "var(--accent)" : "var(--text-tertiary)",
            animation: active
              ? `waveform-bounce 0.8s ease-in-out ${i * 0.1}s infinite alternate`
              : "none",
            opacity: active ? 1 : 0.5,
          }}
        />
      ))}
    </div>
  );
}

/* ── Format time ─────────────────────────────────────── */

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/* ── Global Audio Player ─────────────────────────────── */

export default function GlobalAudioPlayer() {
  const {
    beat,
    isPlaying,
    isLoading,
    currentTime,
    duration,
    isMuted,
    error,
    toggle,
    seekRatio,
    toggleMute,
    close,
    skip,
  } = useGlobalAudio();

  const progressRef = useRef<HTMLDivElement>(null);

  const handleSeek = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!progressRef.current || !duration) return;
      const rect = progressRef.current.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      seekRatio(ratio);
    },
    [duration, seekRatio]
  );

  const handleRetry = useCallback(() => {
    if (beat) {
      globalAudio.play({ ...beat });
    }
  }, [beat]);

  if (!beat) return null;

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-30 md:left-[240px]"
      style={{
        background:
          "linear-gradient(180deg, var(--bg-card) 0%, var(--bg-primary) 100%)",
        borderTop: "1px solid var(--border-light)",
        boxShadow: "0 -4px 30px rgba(0, 0, 0, 0.4)",
      }}
    >
      {/* ── Progress Track ── */}
      <div
        ref={progressRef}
        className="group w-full cursor-pointer relative"
        style={{ height: 3, transition: "height 0.15s ease" }}
        onClick={handleSeek}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLDivElement).style.height = "6px";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLDivElement).style.height = "3px";
        }}
      >
        <div
          className="absolute inset-0"
          style={{ background: "var(--border)" }}
        />
        <div
          className="absolute inset-y-0 left-0"
          style={{
            width: `${progress}%`,
            background: error ? "var(--error)" : "var(--accent)",
            transition: "width 0.1s linear",
            boxShadow: isPlaying ? "0 0 12px var(--accent-muted)" : "none",
          }}
        />
        {/* Loading shimmer */}
        {isLoading && (
          <div
            className="absolute inset-0"
            style={{
              background: "linear-gradient(90deg, transparent, var(--accent-muted), transparent)",
              animation: "shimmer 1.5s infinite",
            }}
          />
        )}
      </div>

      {/* ── Controls ── */}
      <div
        className="flex items-center gap-2 sm:gap-3 mx-auto"
        style={{ maxWidth: 1280, padding: "8px 16px" }}
      >
        {/* Album art / waveform */}
        <div
          className="w-9 h-9 sm:w-10 sm:h-10 rounded-md flex items-center justify-center flex-shrink-0 overflow-hidden"
          style={{
            background:
              "linear-gradient(135deg, color-mix(in srgb, var(--accent) 20%, transparent), color-mix(in srgb, var(--accent) 5%, var(--bg-hover)))",
            border: "1px solid var(--border)",
          }}
        >
          {isLoading ? (
            <Loader2 size={16} className="animate-spin" style={{ color: "var(--accent)" }} />
          ) : error ? (
            <AlertCircle size={16} style={{ color: "var(--error)" }} />
          ) : isPlaying ? (
            <MiniWaveform active={true} stem={beat.stem} />
          ) : (
            <Music
              size={16}
              style={{ color: "var(--accent)", opacity: 0.7 }}
            />
          )}
        </div>

        {/* Skip back */}
        <button
          onClick={() => skip(-10)}
          className="hidden sm:flex p-1.5 rounded-md transition-all duration-200 flex-shrink-0"
          style={{ color: "var(--text-secondary)" }}
          title="Back 10s"
        >
          <SkipBack size={14} />
        </button>

        {/* Play/Pause */}
        <button
          onClick={error ? handleRetry : toggle}
          className="flex items-center justify-center rounded-full transition-all duration-200 flex-shrink-0 hover:scale-105 active:scale-95"
          style={{
            width: 36,
            height: 36,
            background: error ? "var(--error)" : "var(--accent)",
            color: "#fff",
            boxShadow: isPlaying
              ? "0 0 20px var(--accent-muted), 0 2px 8px rgba(0,0,0,0.3)"
              : "0 2px 8px rgba(0,0,0,0.3)",
          }}
        >
          {isLoading ? (
            <Loader2 size={16} className="animate-spin" />
          ) : error ? (
            <RotateCcw size={14} />
          ) : isPlaying ? (
            <Pause size={16} fill="#fff" />
          ) : (
            <Play size={16} fill="#fff" style={{ marginLeft: 2 }} />
          )}
        </button>

        {/* Skip forward */}
        <button
          onClick={() => skip(10)}
          className="hidden sm:flex p-1.5 rounded-md transition-all duration-200 flex-shrink-0"
          style={{ color: "var(--text-secondary)" }}
          title="Forward 10s"
        >
          <SkipForward size={14} />
        </button>

        {/* Beat info */}
        <div className="flex-1 min-w-0">
          <p
            className="text-sm font-semibold truncate leading-tight"
            style={{ color: "var(--text-primary)" }}
          >
            {beat.title || beat.stem}
          </p>
          <p
            className="text-[11px] truncate mt-0.5"
            style={{ color: error ? "var(--error)" : "var(--text-tertiary)" }}
          >
            {error || (beat.artist || "Unknown Artist")}
          </p>
        </div>

        {/* Time */}
        <div
          className="hidden sm:flex items-center gap-1 text-xs tabular-nums font-medium flex-shrink-0"
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          <span style={{ color: "var(--accent)" }}>
            {formatTime(currentTime)}
          </span>
          <span style={{ color: "var(--text-tertiary)", opacity: 0.5 }}>
            /
          </span>
          <span style={{ color: "var(--text-tertiary)" }}>
            {formatTime(duration)}
          </span>
        </div>

        {/* Volume toggle */}
        <button
          onClick={toggleMute}
          className="p-2 rounded-md transition-all duration-200 flex-shrink-0"
          style={{
            color: isMuted ? "var(--error)" : "var(--text-secondary)",
            background: isMuted ? "rgba(255, 69, 58, 0.1)" : "transparent",
          }}
        >
          {isMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
        </button>

        {/* Close */}
        <button
          onClick={close}
          className="p-2 rounded-md transition-all duration-200 flex-shrink-0"
          style={{ color: "var(--text-tertiary)" }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--bg-hover)";
            e.currentTarget.style.color = "var(--text-primary)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "transparent";
            e.currentTarget.style.color = "var(--text-tertiary)";
          }}
        >
          <X size={16} />
        </button>
      </div>

      {/* Animations */}
      <style>{`
        @keyframes waveform-bounce {
          0% { height: 25%; }
          100% { height: 100%; }
        }
        @keyframes shimmer {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }
      `}</style>
    </div>
  );
}
