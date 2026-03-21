"use client";

/**
 * Global task progress store.
 *
 * Listens to ALL WebSocket progress messages and stores them in a module-level
 * Map so state persists across page navigations (React component unmount/mount).
 *
 * Any page can read active tasks and subscribe to updates without losing state
 * when the user navigates away and comes back.
 */

import { useEffect, useState, useCallback } from "react";
import { useWebSocket, WSMessage } from "./useWebSocket";
import { api } from "./useApi";

export interface TaskProgress {
  taskId: string;
  phase: string;
  stem: string;
  pct: number;
  detail: string;
  updatedAt: number;
}

// ── Module-level store (persists across React renders & page navigations) ──

const _tasks = new Map<string, TaskProgress>();
const _listeners = new Set<() => void>();

function _notify() {
  _listeners.forEach((fn) => fn());
}

function _upsert(msg: WSMessage) {
  if (msg.type !== "progress" || !msg.phase) return;

  const taskId = (msg.taskId as string) || msg.phase;
  const pct = typeof msg.pct === "number" ? msg.pct : 0;
  const detail = typeof msg.detail === "string" ? msg.detail : "";

  _tasks.set(taskId, {
    taskId,
    phase: msg.phase as string,
    stem: (msg.stem as string) || "",
    pct,
    detail,
    updatedAt: Date.now(),
  });

  // Auto-remove completed tasks after 3 seconds
  if (pct >= 100) {
    setTimeout(() => {
      _tasks.delete(taskId);
      _notify();
    }, 3000);
  }

  _notify();
}

// Prune stale tasks (no update for 5 minutes = probably dead)
function _prune() {
  const cutoff = Date.now() - 5 * 60 * 1000;
  let changed = false;
  for (const [id, task] of _tasks) {
    if (task.updatedAt < cutoff && task.pct < 100) {
      _tasks.delete(id);
      changed = true;
    }
  }
  if (changed) _notify();
}

// ── Hook: useTaskProgress ──────────────────────────────────────────────

/**
 * Returns all active task progress entries.
 * Automatically subscribes to updates so the component re-renders
 * when any task's progress changes.
 *
 * Optional `phase` filter to only get tasks of a specific type.
 */
export function useTaskProgress(phase?: string) {
  const { lastMessage } = useWebSocket();
  const [, setTick] = useState(0);

  // Subscribe to store changes
  useEffect(() => {
    const listener = () => setTick((t) => t + 1);
    _listeners.add(listener);
    return () => { _listeners.delete(listener); };
  }, []);

  // Feed WebSocket messages into the store
  useEffect(() => {
    if (lastMessage) _upsert(lastMessage);
  }, [lastMessage]);

  // On mount, fetch active tasks from API to restore any running tasks
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const active = await api.get<Array<{
          id: string;
          type: string;
          stem: string;
          progress: number;
          detail: string;
        }>>("/tasks/active");
        if (cancelled || !active) return;
        for (const task of active) {
          _tasks.set(task.id, {
            taskId: task.id,
            phase: task.type,
            stem: task.stem,
            pct: task.progress,
            detail: task.detail,
            updatedAt: Date.now(),
          });
        }
        if (active.length > 0) _notify();
      } catch {
        // ignore — server might not be up yet
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Periodic pruning
  useEffect(() => {
    const interval = setInterval(_prune, 30_000);
    return () => clearInterval(interval);
  }, []);

  // Return filtered tasks
  const tasks = Array.from(_tasks.values());
  if (phase) return tasks.filter((t) => t.phase === phase);
  return tasks;
}

/**
 * Returns a single task's progress by phase name (e.g. "dj_analyze", "content_schedule").
 * Returns null if no task is running for that phase.
 */
export function usePhaseProgress(phase: string): TaskProgress | null {
  const tasks = useTaskProgress(phase);
  return tasks.length > 0 ? tasks[0] : null;
}

/**
 * Returns true if any task is actively running (pct < 100).
 */
export function useHasActiveTasks(): boolean {
  const tasks = useTaskProgress();
  return tasks.some((t) => t.pct < 100);
}
