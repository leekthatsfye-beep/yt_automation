"use client";

import { useState, useEffect, useCallback } from "react";

export interface AppSettings {
  defaultPrivacy: string;
  artistName: string;
  autoRender: boolean;
  autoUpload: boolean;
  autopilot: boolean;
}

const STORAGE_KEY = "fy3-settings";

const DEFAULTS: AppSettings = {
  defaultPrivacy: "unlisted",
  artistName: "BiggKutt8",
  autoRender: false,
  autoUpload: false,
  autopilot: false,
};

function loadSettings(): AppSettings {
  if (typeof window === "undefined") return { ...DEFAULTS };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return { ...DEFAULTS, ...parsed };
    }
  } catch {
    // Corrupted storage, use defaults
  }
  return { ...DEFAULTS };
}

function saveSettings(settings: AppSettings): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Storage full or unavailable
  }
}

export function useSettings() {
  const [settings, setSettings] = useState<AppSettings>(DEFAULTS);
  const [loaded, setLoaded] = useState(false);

  // Load from localStorage on mount
  useEffect(() => {
    setSettings(loadSettings());
    setLoaded(true);
  }, []);

  const updateSetting = useCallback(
    <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => {
      setSettings((prev) => {
        const next = { ...prev, [key]: value };
        saveSettings(next);
        return next;
      });
    },
    []
  );

  return { settings, updateSetting, loaded };
}
