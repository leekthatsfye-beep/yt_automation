"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Monitor,
  Smartphone,
  Square,
  RectangleHorizontal,
  Loader2,
  Check,
  CheckCircle2,
  Zap,
  Film,
} from "lucide-react";
import { api, useFetch } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import { useWebSocket } from "@/hooks/useWebSocket";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import ProgressBar from "@/components/ProgressBar";

/* ---------- types ---------- */

interface DimensionPreset {
  width: number;
  height: number;
  label: string;
  platforms: string[];
}

interface PresetStatus {
  exists: boolean;
  size_mb?: number;
  label: string;
  platforms: string[];
}

interface DimensionStatus {
  stem: string;
  original: { exists: boolean; size_mb?: number };
  [key: string]: PresetStatus | { exists: boolean; size_mb?: number } | string;
}

interface DimensionConverterProps {
  stems: string[];
  open: boolean;
  onClose: () => void;
  onComplete?: () => void;
}

const PRESET_ICONS: Record<string, React.ReactNode> = {
  "9x16": <Smartphone size={20} />,
  "4x5": <RectangleHorizontal size={20} className="rotate-90" />,
  "1x1": <Square size={20} />,
};

const PRESET_COLORS: Record<string, string> = {
  "9x16": "text-purple-400",
  "4x5": "text-pink-400",
  "1x1": "text-blue-400",
};

/* ---------- component ---------- */

export default function DimensionConverter({
  stems,
  open,
  onClose,
  onComplete,
}: DimensionConverterProps) {
  const { toast: showToast } = useToast();
  const { lastMessage } = useWebSocket();

  // Available presets
  const { data: presets } = useFetch<Record<string, DimensionPreset>>(
    open ? "/convert/presets" : null
  );

  // Selected presets
  const [selectedPresets, setSelectedPresets] = useState<Set<string>>(new Set(["9x16", "4x5", "1x1"]));

  // Status for each stem
  const [statuses, setStatuses] = useState<Record<string, DimensionStatus>>({});
  const [loadingStatus, setLoadingStatus] = useState(false);

  // Converting
  const [converting, setConverting] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressDetail, setProgressDetail] = useState("");

  // Fetch dimension status for all stems
  useEffect(() => {
    if (!open || stems.length === 0) return;
    setLoadingStatus(true);

    Promise.allSettled(
      stems.map((stem) => api.get<DimensionStatus>(`/convert/status/${stem}`))
    )
      .then((results) => {
        const newStatuses: Record<string, DimensionStatus> = {};
        results.forEach((r, i) => {
          if (r.status === "fulfilled") {
            newStatuses[stems[i]] = r.value;
          }
        });
        setStatuses(newStatuses);
      })
      .finally(() => setLoadingStatus(false));
  }, [open, stems]);

  // Listen for WebSocket progress
  useEffect(() => {
    if (!lastMessage || !taskId) return;

    if (
      lastMessage.type === "progress" &&
      lastMessage.taskId === taskId
    ) {
      setProgress(lastMessage.pct ?? 0);
      setProgressDetail(lastMessage.detail ?? "");

      if (lastMessage.pct === 100) {
        setConverting(false);
        setTaskId(null);
        showToast("Conversion complete!", "success");

        // Refresh statuses
        Promise.allSettled(
          stems.map((stem) => api.get<DimensionStatus>(`/convert/status/${stem}`))
        ).then((results) => {
          const newStatuses: Record<string, DimensionStatus> = {};
          results.forEach((r, i) => {
            if (r.status === "fulfilled") {
              newStatuses[stems[i]] = r.value;
            }
          });
          setStatuses(newStatuses);
        });

        onComplete?.();
      }
    }

    if (
      lastMessage.type === "convert_complete" ||
      lastMessage.type === "convert_bulk_complete"
    ) {
      setConverting(false);
      setTaskId(null);

      // Refresh statuses
      Promise.allSettled(
        stems.map((stem) => api.get<DimensionStatus>(`/convert/status/${stem}`))
      ).then((results) => {
        const newStatuses: Record<string, DimensionStatus> = {};
        results.forEach((r, i) => {
          if (r.status === "fulfilled") {
            newStatuses[stems[i]] = r.value;
          }
        });
        setStatuses(newStatuses);
      });

      onComplete?.();
    }
  }, [lastMessage, taskId, stems, onComplete, showToast]);

  // Toggle preset selection
  const togglePreset = useCallback((key: string) => {
    setSelectedPresets((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // Start conversion
  const handleConvert = useCallback(async () => {
    if (selectedPresets.size === 0) {
      showToast("Select at least one preset", "error");
      return;
    }

    setConverting(true);
    setProgress(0);
    setProgressDetail("Starting...");

    try {
      const presetList = Array.from(selectedPresets);

      if (stems.length === 1) {
        const result = await api.post<{ task_id: string }>(`/convert/${stems[0]}`, {
          presets: presetList,
        });
        setTaskId(result.task_id);
      } else {
        const result = await api.post<{ task_id: string }>("/convert/bulk", {
          stems,
          presets: presetList,
        });
        setTaskId(result.task_id);
      }
    } catch (err) {
      setConverting(false);
      showToast(
        `Conversion failed: ${err instanceof Error ? err.message : "Unknown error"}`,
        "error"
      );
    }
  }, [stems, selectedPresets, showToast]);

  // Count how many conversions are needed (not already done)
  const countNeeded = useCallback(() => {
    let needed = 0;
    for (const stem of stems) {
      const status = statuses[stem];
      if (!status) {
        needed += selectedPresets.size;
        continue;
      }
      for (const preset of selectedPresets) {
        const ps = status[preset] as PresetStatus | undefined;
        if (!ps || !ps.exists) needed++;
      }
    }
    return needed;
  }, [stems, statuses, selectedPresets]);

  const presetKeys = presets ? Object.keys(presets) : ["9x16", "4x5", "1x1"];
  const needed = countNeeded();

  return (
    <Dialog open={open} onOpenChange={(v) => !v && !converting && onClose()}>
      <DialogContent className="sm:max-w-xl bg-bg-card border-border">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-foreground">
            <Monitor size={18} className="text-accent" />
            Convert Dimensions
          </DialogTitle>
          <DialogDescription className="text-text-tertiary">
            Convert {stems.length} {stems.length === 1 ? "video" : "videos"} to social media aspect ratios
          </DialogDescription>
        </DialogHeader>

        {/* ======= Preset Cards ======= */}
        <div className="grid grid-cols-3 gap-3 mt-2">
          {presetKeys.map((key) => {
            const preset = presets?.[key];
            const isSelected = selectedPresets.has(key);
            const label = preset?.label ?? key;
            const platforms = preset?.platforms ?? [];

            // Check how many stems already have this preset
            let existCount = 0;
            for (const stem of stems) {
              const ps = statuses[stem]?.[key] as PresetStatus | undefined;
              if (ps?.exists) existCount++;
            }
            const allDone = existCount === stems.length;

            return (
              <button
                key={key}
                onClick={() => togglePreset(key)}
                disabled={converting}
                className={`relative rounded-lg p-4 text-center transition-all duration-200 border ${
                  isSelected
                    ? "border-accent bg-accent/5 ring-1 ring-accent"
                    : "border-border bg-muted/30 hover:border-border-light"
                } ${converting ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
              >
                {/* Selection indicator */}
                {isSelected && (
                  <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-accent flex items-center justify-center">
                    <Check size={12} className="text-white" strokeWidth={3} />
                  </div>
                )}

                {/* Icon */}
                <div className={`mb-2 ${PRESET_COLORS[key] ?? "text-accent"}`}>
                  {PRESET_ICONS[key] ?? <Monitor size={20} />}
                </div>

                {/* Label */}
                <p className="text-sm font-semibold text-foreground">{label}</p>

                {/* Dimensions */}
                <p className="text-[10px] text-text-tertiary mt-0.5">
                  {preset?.width ?? "?"}x{preset?.height ?? "?"}
                </p>

                {/* Platforms */}
                <div className="flex flex-wrap gap-1 justify-center mt-2">
                  {platforms.map((p) => (
                    <Badge
                      key={p}
                      variant="secondary"
                      className="text-[9px] px-1.5 py-0"
                    >
                      {p}
                    </Badge>
                  ))}
                </div>

                {/* Done status */}
                {allDone && (
                  <div className="mt-2">
                    <Badge variant="success" className="text-[9px] px-1.5 py-0 gap-0.5">
                      <CheckCircle2 size={8} />
                      Done
                    </Badge>
                  </div>
                )}
                {existCount > 0 && !allDone && (
                  <div className="mt-2">
                    <Badge variant="accent" className="text-[9px] px-1.5 py-0">
                      {existCount}/{stems.length}
                    </Badge>
                  </div>
                )}
              </button>
            );
          })}
        </div>

        {/* ======= Selected beats list ======= */}
        {stems.length > 1 && (
          <div className="mt-3">
            <p className="text-xs text-text-tertiary mb-2">
              {stems.length} beats selected:
            </p>
            <div className="flex flex-wrap gap-1.5 max-h-20 overflow-y-auto">
              {stems.map((s) => (
                <Badge key={s} variant="secondary" className="text-[10px] gap-1">
                  <Film size={9} />
                  {s}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* ======= Progress ======= */}
        {converting && (
          <div className="mt-3">
            <div className="flex items-center gap-2 mb-2">
              <Loader2 size={14} className="animate-spin text-accent" />
              <span className="text-xs text-text-tertiary">{progressDetail}</span>
            </div>
            <ProgressBar progress={progress} status="rendering" />
          </div>
        )}

        {/* ======= Footer ======= */}
        <div className="flex items-center justify-between pt-3 border-t border-border mt-2">
          <div className="text-xs text-text-tertiary">
            {needed > 0 ? (
              <span>{needed} conversion{needed > 1 ? "s" : ""} needed</span>
            ) : (
              <span className="text-success flex items-center gap-1">
                <CheckCircle2 size={12} />
                All presets already converted
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              onClick={onClose}
              disabled={converting}
              variant="ghost"
              size="sm"
            >
              {converting ? "Running..." : "Close"}
            </Button>
            <Button
              onClick={handleConvert}
              disabled={converting || selectedPresets.size === 0}
              variant="default"
              size="sm"
            >
              {converting ? (
                <>
                  <Loader2 size={12} className="animate-spin" />
                  Converting...
                </>
              ) : (
                <>
                  <Zap size={12} />
                  Convert {needed > 0 ? `(${needed})` : ""}
                </>
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
