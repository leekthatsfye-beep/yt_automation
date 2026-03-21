"use client";

import { Progress } from "@/components/ui/progress";

interface ProgressBarProps {
  progress: number; // 0-100
  label?: string;
  status?: "queued" | "rendering" | "complete" | "error";
}

export default function ProgressBar({ progress, label, status }: ProgressBarProps) {
  const clamped = Math.min(100, Math.max(0, progress));

  const statusColor = (() => {
    switch (status) {
      case "complete":
        return "text-success";
      case "error":
        return "text-error";
      case "queued":
        return "text-text-tertiary";
      default:
        return "text-accent";
    }
  })();

  const indicatorClass = (() => {
    switch (status) {
      case "complete":
        return "[&>div]:bg-success";
      case "error":
        return "[&>div]:bg-error";
      case "queued":
        return "[&>div]:bg-text-tertiary";
      default:
        return "[&>div]:bg-accent";
    }
  })();

  return (
    <div className="w-full">
      {/* Label row */}
      {(label || status) && (
        <div className="flex items-center justify-between mb-1.5">
          {label && (
            <span className="text-xs font-medium truncate text-muted-foreground">
              {label}
            </span>
          )}
          <span className={`text-xs font-medium tabular-nums ${statusColor}`}>
            {status === "queued" ? "Queued" : `${Math.round(clamped)}%`}
          </span>
        </div>
      )}

      {/* Progress track */}
      <div className="relative">
        <Progress
          value={clamped}
          className={`h-1.5 ${indicatorClass}`}
        />

        {/* Shimmer animation for active rendering */}
        {status === "rendering" && clamped < 100 && (
          <div
            className="absolute inset-0 rounded-full overflow-hidden pointer-events-none"
          >
            <div
              className="h-full w-full"
              style={{
                background: "linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.15) 50%, transparent 100%)",
                animation: "shimmer 1.5s infinite",
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
