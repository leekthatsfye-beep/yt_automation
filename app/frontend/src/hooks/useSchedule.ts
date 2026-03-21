"use client";

import { useCallback } from "react";
import { useFetch, api } from "@/hooks/useApi";

/* ── Types ────────────────────────────────────────────────────────────── */

export interface ScheduleSettings {
  daily_yt_count: number;
  yt_times_est: string[];
  buffer_warning_days: number;
  autopilot_enabled: boolean;
}

export interface QueueEntry {
  stem: string;
  added_at: string;
  priority: number;
}

export interface ScheduleSlot {
  slot: string;       // UTC ISO datetime
  slot_est: string;   // Formatted EST string
  stem: string | null;
}

export interface ScheduleData {
  queue: QueueEntry[];
  settings: ScheduleSettings;
  slots: ScheduleSlot[];
  buffer_days: number;
  queue_length: number;
}

interface LaunchResult {
  stem: string;
  status: "scheduled" | "error" | "skipped";
  scheduledAt?: string;
  slot_est?: string;
  videoId?: string;
  url?: string;
  reason?: string;
}

interface LaunchResponse {
  results: LaunchResult[];
  scheduled: number;
  errors: number;
  skipped: number;
}

/* ── Hook ─────────────────────────────────────────────────────────────── */

export function useSchedule() {
  const { data, loading, error, refetch } = useFetch<ScheduleData>("/schedule");

  const addToQueue = useCallback(
    async (stems: string[], priority = 0) => {
      const result = await api.post<{ added: string[]; skipped: string[]; queue_length: number }>(
        "/schedule/queue",
        { stems, priority }
      );
      refetch();
      return result;
    },
    [refetch]
  );

  const removeFromQueue = useCallback(
    async (stem: string) => {
      const result = await api.del<{ removed: boolean; queue_length: number }>(
        `/schedule/queue/${stem}`
      );
      refetch();
      return result;
    },
    [refetch]
  );

  const reorderQueue = useCallback(
    async (stems: string[]) => {
      const result = await api.put<{ queue_length: number }>(
        "/schedule/queue/reorder",
        { stems }
      );
      refetch();
      return result;
    },
    [refetch]
  );

  const updateSettings = useCallback(
    async (settings: Partial<ScheduleSettings>) => {
      const result = await api.put<ScheduleSettings>("/schedule/settings", settings);
      refetch();
      return result;
    },
    [refetch]
  );

  const launchSchedule = useCallback(
    async (count: number) => {
      const result = await api.post<LaunchResponse>("/schedule/launch", { count });
      refetch();
      return result;
    },
    [refetch]
  );

  return {
    schedule: data,
    queue: data?.queue ?? [],
    settings: data?.settings ?? null,
    slots: data?.slots ?? [],
    bufferDays: data?.buffer_days ?? 0,
    queueLength: data?.queue_length ?? 0,
    loading,
    error,
    refetch,
    addToQueue,
    removeFromQueue,
    reorderQueue,
    updateSettings,
    launchSchedule,
  };
}
