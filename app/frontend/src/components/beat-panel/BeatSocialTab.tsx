"use client";

import { useState, useEffect, useRef } from "react";
import { Share2, Loader2, CheckCircle2 } from "lucide-react";
import { api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import { useWebSocket } from "@/hooks/useWebSocket";
import type { Beat } from "@/types/beat";

interface Props {
  beat: Beat;
  onUpdated: () => void;
}

const PLATFORMS = [
  { id: "shorts", label: "YouTube Shorts", icon: "▶", color: "#ff0000" },
  { id: "tiktok", label: "TikTok", icon: "♪", color: "#00f2ea" },
  { id: "ig", label: "Instagram", icon: "📷", color: "#e1306c" },
];

type UploadState = "idle" | "starting" | "uploading" | "done" | "error";

interface PlatformState {
  state: UploadState;
  taskId?: string;
  pct: number;
  detail: string;
}

const INITIAL: PlatformState = { state: "idle", pct: 0, detail: "" };

export default function BeatSocialTab({ beat, onUpdated }: Props) {
  const { toast } = useToast();
  const { lastMessage } = useWebSocket();
  const [selectedPlatforms, setSelectedPlatforms] = useState<Set<string>>(new Set());
  const [platforms, setPlatforms] = useState<Record<string, PlatformState>>({
    shorts: { ...INITIAL },
    tiktok: { ...INITIAL },
    ig: { ...INITIAL },
  });

  // Track active task IDs so we can filter WS messages
  const activeTaskIds = useRef<Map<string, string>>(new Map()); // taskId → platformId

  // Listen for WebSocket progress updates
  useEffect(() => {
    if (!lastMessage) return;
    const data = typeof lastMessage === "string" ? JSON.parse(lastMessage) : lastMessage;
    const taskId = data.taskId || data.task_id;
    if (!taskId || !activeTaskIds.current.has(taskId)) return;

    const platformId = activeTaskIds.current.get(taskId)!;
    const pct = data.pct ?? data.progress ?? 0;
    const detail = data.detail || data.message || "";
    const isDone = pct >= 100;
    const isError = detail.toLowerCase().startsWith("error");

    setPlatforms((prev) => ({
      ...prev,
      [platformId]: {
        state: isError ? "error" : isDone ? "done" : "uploading",
        taskId,
        pct: isDone ? 100 : pct,
        detail,
      },
    }));

    if (isDone) {
      activeTaskIds.current.delete(taskId);
      toast(`Posted to ${PLATFORMS.find((p) => p.id === platformId)?.label}!`, "success");
      onUpdated();
    } else if (isError) {
      activeTaskIds.current.delete(taskId);
      toast(`Failed: ${detail.replace(/^Error:\s*/i, "")}`, "error");
    }
  }, [lastMessage]);

  const togglePlatform = (id: string) => {
    setSelectedPlatforms((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handlePost = async (platformId: string) => {
    if (!beat.rendered) {
      toast("Beat must be rendered first", "error");
      return;
    }

    const busy = platforms[platformId]?.state;
    if (busy === "starting" || busy === "uploading") return;

    setPlatforms((prev) => ({
      ...prev,
      [platformId]: { state: "starting", pct: 0, detail: "Starting upload..." },
    }));

    try {
      const data = (await api.post(`/social/${platformId}/${beat.stem}`)) as {
        task_id?: string;
        status?: string;
      };

      if (data.task_id) {
        // Background task started — track via WebSocket
        activeTaskIds.current.set(data.task_id, platformId);
        setPlatforms((prev) => ({
          ...prev,
          [platformId]: {
            state: "uploading",
            taskId: data.task_id,
            pct: 0,
            detail: "Upload in progress...",
          },
        }));
        toast(
          `${PLATFORMS.find((p) => p.id === platformId)?.label} upload started`,
          "info"
        );
      } else {
        // Synchronous success (unlikely but handle it)
        setPlatforms((prev) => ({
          ...prev,
          [platformId]: { state: "done", pct: 100, detail: "Published!" },
        }));
        toast(
          `Posted to ${PLATFORMS.find((p) => p.id === platformId)?.label}`,
          "success"
        );
        onUpdated();
      }
    } catch {
      setPlatforms((prev) => ({
        ...prev,
        [platformId]: { state: "error", pct: 0, detail: "Upload failed" },
      }));
      toast(
        `Failed to post to ${PLATFORMS.find((p) => p.id === platformId)?.label}`,
        "error"
      );
    }
  };

  const handlePostAll = async () => {
    for (const pid of selectedPlatforms) {
      await handlePost(pid);
    }
  };

  if (!beat.rendered) {
    return (
      <div className="text-center py-12">
        <div
          className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-4"
          style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
        >
          <Share2 size={22} className="text-text-tertiary" />
        </div>
        <p className="text-sm font-medium text-text-secondary">Render Required</p>
        <p className="text-xs text-text-tertiary mt-1">
          This beat must be rendered before posting to social platforms.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* Platform Selection */}
      <div>
        <p className="text-xs font-semibold uppercase tracking-wider text-text-tertiary mb-3">
          Select Platforms
        </p>
        <div className="space-y-2">
          {PLATFORMS.map((p) => {
            const ps = platforms[p.id] || INITIAL;
            const isSelected = selectedPlatforms.has(p.id);
            const isDone = ps.state === "done";
            const isBusy = ps.state === "starting" || ps.state === "uploading";

            return (
              <button
                key={p.id}
                onClick={() => togglePlatform(p.id)}
                className="w-full flex items-center gap-3 p-3 rounded-xl transition-all duration-200 cursor-pointer"
                style={{
                  background: isSelected ? `${p.color}10` : "var(--bg-hover)",
                  border: `1px solid ${isSelected ? `${p.color}40` : "var(--border)"}`,
                }}
              >
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center text-sm"
                  style={{ background: `${p.color}20`, color: p.color }}
                >
                  {p.icon}
                </div>
                <span className="flex-1 text-left text-sm font-medium text-foreground">
                  {p.label}
                </span>
                {isDone ? (
                  <CheckCircle2 size={16} style={{ color: "var(--success)" }} />
                ) : isBusy ? (
                  <Loader2 size={16} className="animate-spin" style={{ color: p.color }} />
                ) : (
                  <div
                    className="w-5 h-5 rounded-md border-2 flex items-center justify-center"
                    style={{
                      borderColor: isSelected ? p.color : "var(--border-light)",
                      background: isSelected ? p.color : "transparent",
                    }}
                  >
                    {isSelected && <span className="text-white text-[10px]">✓</span>}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Post Individual */}
      <div className="space-y-2">
        {PLATFORMS.map((p) => {
          const ps = platforms[p.id] || INITIAL;
          const isDone = ps.state === "done";
          const isBusy = ps.state === "starting" || ps.state === "uploading";
          const isError = ps.state === "error";

          return (
            <div key={p.id}>
              <button
                onClick={() => handlePost(p.id)}
                disabled={isBusy || isDone}
                className="w-full py-2.5 rounded-xl text-xs font-semibold flex items-center justify-center gap-2 transition-all duration-200 cursor-pointer"
                style={{
                  background: isDone
                    ? "var(--success-muted)"
                    : isError
                      ? "rgba(255,59,48,0.08)"
                      : `${p.color}15`,
                  color: isDone
                    ? "var(--success)"
                    : isError
                      ? "#ff3b30"
                      : p.color,
                  border: `1px solid ${isDone ? "var(--success)30" : isError ? "rgba(255,59,48,0.2)" : `${p.color}30`}`,
                  opacity: isBusy ? 0.7 : 1,
                }}
              >
                {isBusy ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : isDone ? (
                  <CheckCircle2 size={13} />
                ) : (
                  <Share2 size={13} />
                )}
                {ps.state === "starting"
                  ? "Starting..."
                  : ps.state === "uploading"
                    ? `Uploading ${ps.pct}%`
                    : isDone
                      ? "Posted"
                      : isError
                        ? "Retry"
                        : `Post to ${p.label}`}
              </button>

              {/* Progress bar for active uploads */}
              {isBusy && ps.pct > 0 && (
                <div className="mt-1 h-1 rounded-full overflow-hidden" style={{ background: `${p.color}15` }}>
                  <div
                    className="h-full rounded-full transition-all duration-500"
                    style={{ width: `${ps.pct}%`, background: p.color }}
                  />
                </div>
              )}
              {isBusy && ps.detail && (
                <p className="text-[10px] text-text-tertiary mt-0.5 text-center">{ps.detail}</p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
