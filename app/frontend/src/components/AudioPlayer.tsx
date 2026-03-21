"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Play, Pause, X, Volume2, VolumeX, Loader2, Music } from "lucide-react";
import { getFilesBase } from "@/hooks/useApi";
import { useAuthAudio } from "@/hooks/useAuthAudio";

export interface PlayingBeat {
  stem: string;
  title: string;
  artist: string;
  filename: string;
}

interface AudioPlayerProps {
  beat: PlayingBeat | null;
  onClose: () => void;
}

/* ── Mini Waveform Bars ──────────────────────────────── */

function MiniWaveform({ active, stem }: { active: boolean; stem: string }) {
  // Generate deterministic bars from stem
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

export default function AudioPlayer({ beat, onClose }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const progressRef = useRef<HTMLDivElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [muted, setMuted] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [hovering, setHovering] = useState(false);

  // Fetch audio with JWT auth
  const audioSrc = beat ? `${getFilesBase()}/beats/${beat.filename}` : null;
  const { blobUrl, loading: audioLoading } = useAuthAudio(audioSrc);

  // Create or update audio element when blob URL is ready
  useEffect(() => {
    if (!beat || !blobUrl) {
      if (!beat && audioRef.current) {
        audioRef.current.pause();
        audioRef.current.src = "";
        audioRef.current = null;
      }
      if (!beat) {
        setPlaying(false);
        setCurrentTime(0);
        setDuration(0);
        setLoaded(false);
      }
      return;
    }

    const audio = new Audio(blobUrl);
    audio.preload = "auto";

    audio.addEventListener("loadedmetadata", () => {
      setDuration(audio.duration);
      setLoaded(true);
    });

    audio.addEventListener("timeupdate", () => {
      setCurrentTime(audio.currentTime);
    });

    audio.addEventListener("ended", () => {
      setPlaying(false);
      setCurrentTime(0);
    });

    audio.addEventListener("error", () => {
      setPlaying(false);
      setLoaded(false);
    });

    // Stop previous audio
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
    }

    audioRef.current = audio;
    audio.play().then(() => setPlaying(true)).catch(() => setPlaying(false));

    return () => {
      audio.pause();
      audio.src = "";
    };
  }, [beat, blobUrl]);

  // Sync mute state
  useEffect(() => {
    if (audioRef.current) audioRef.current.muted = muted;
  }, [muted]);

  const togglePlay = useCallback(() => {
    if (!audioRef.current) return;
    if (playing) {
      audioRef.current.pause();
      setPlaying(false);
    } else {
      audioRef.current.play().then(() => setPlaying(true)).catch(() => {});
    }
  }, [playing]);

  const handleSeek = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!progressRef.current || !audioRef.current || !duration) return;
      const rect = progressRef.current.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      audioRef.current.currentTime = ratio * duration;
      setCurrentTime(ratio * duration);
    },
    [duration]
  );

  const handleClose = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    setPlaying(false);
    setCurrentTime(0);
    setDuration(0);
    onClose();
  }, [onClose]);

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  if (!beat) return null;

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0;

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-30 md:left-[240px]"
      style={{
        background: "linear-gradient(180deg, var(--bg-card) 0%, var(--bg-primary) 100%)",
        borderTop: "1px solid var(--border-light)",
        boxShadow: "0 -4px 30px rgba(0, 0, 0, 0.4)",
      }}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
    >
      {/* ── Progress Track ── */}
      <div
        ref={progressRef}
        className="group w-full cursor-pointer relative"
        style={{ height: hovering ? 6 : 3, transition: "height 0.15s ease" }}
        onClick={handleSeek}
      >
        {/* Track background */}
        <div
          className="absolute inset-0"
          style={{ background: "var(--border)" }}
        />
        {/* Filled progress */}
        <div
          className="absolute inset-y-0 left-0"
          style={{
            width: `${progress}%`,
            background: "var(--accent)",
            transition: "width 0.1s linear",
            boxShadow: playing ? "0 0 12px var(--accent-muted)" : "none",
          }}
        />
        {/* Scrub knob — visible on hover */}
        {hovering && duration > 0 && (
          <div
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 pointer-events-none"
            style={{
              left: `${progress}%`,
              width: 12,
              height: 12,
              borderRadius: "50%",
              background: "#fff",
              boxShadow: "0 0 6px rgba(0, 0, 0, 0.3), 0 0 10px var(--accent-muted)",
              transition: "opacity 0.15s ease",
            }}
          />
        )}
      </div>

      {/* ── Controls ── */}
      <div
        className="flex items-center gap-3 mx-auto"
        style={{ maxWidth: 1280, padding: "8px 20px" }}
      >
        {/* Album art / icon */}
        <div
          className="w-10 h-10 rounded-md flex items-center justify-center flex-shrink-0 overflow-hidden"
          style={{
            background: `linear-gradient(135deg, color-mix(in srgb, var(--accent) 20%, transparent), color-mix(in srgb, var(--accent) 5%, var(--bg-hover)))`,
            border: "1px solid var(--border)",
          }}
        >
          {playing ? (
            <MiniWaveform active={true} stem={beat.stem} />
          ) : (
            <Music size={16} style={{ color: "var(--accent)", opacity: 0.7 }} />
          )}
        </div>

        {/* Play/Pause — premium round button */}
        <button
          onClick={togglePlay}
          className="flex items-center justify-center rounded-full transition-all duration-200 flex-shrink-0 hover:scale-105 active:scale-95"
          style={{
            width: 40,
            height: 40,
            background: "var(--accent)",
            color: "#fff",
            boxShadow: playing
              ? "0 0 20px var(--accent-muted), 0 2px 8px rgba(0,0,0,0.3)"
              : "0 2px 8px rgba(0,0,0,0.3)",
          }}
          disabled={!loaded && !audioLoading}
        >
          {audioLoading ? (
            <Loader2 size={18} className="animate-spin" />
          ) : playing ? (
            <Pause size={18} fill="#fff" />
          ) : (
            <Play size={18} fill="#fff" style={{ marginLeft: 2 }} />
          )}
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
            style={{ color: "var(--text-tertiary)" }}
          >
            {beat.artist || "Unknown Artist"}
          </p>
        </div>

        {/* Time — accent colored current, dim total */}
        <div
          className="hidden sm:flex items-center gap-1 text-xs tabular-nums font-medium flex-shrink-0"
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          <span style={{ color: "var(--accent)" }}>
            {formatTime(currentTime)}
          </span>
          <span style={{ color: "var(--text-tertiary)", opacity: 0.5 }}>/</span>
          <span style={{ color: "var(--text-tertiary)" }}>
            {formatTime(duration)}
          </span>
        </div>

        {/* Volume toggle */}
        <button
          onClick={() => setMuted(!muted)}
          className="p-2 rounded-md transition-all duration-200 flex-shrink-0"
          style={{
            color: muted ? "var(--error)" : "var(--text-secondary)",
            background: muted ? "rgba(255, 69, 58, 0.1)" : "transparent",
          }}
          onMouseEnter={(e) => {
            if (!muted) e.currentTarget.style.background = "var(--bg-hover)";
          }}
          onMouseLeave={(e) => {
            if (!muted) e.currentTarget.style.background = "transparent";
          }}
        >
          {muted ? <VolumeX size={16} /> : <Volume2 size={16} />}
        </button>

        {/* Close */}
        <button
          onClick={handleClose}
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
    </div>
  );
}
