"use client";

import { useState, useEffect, useCallback } from "react";

export type Theme = "midnight" | "studio" | "frost" | "neon" | "ember" | "moss" | "ocean" | "sunset";

export const THEMES: { id: Theme; label: string; color: string }[] = [
  { id: "midnight", label: "Midnight", color: "#0a84ff" },
  { id: "studio", label: "Studio", color: "#ff9f0a" },
  { id: "frost", label: "Frost", color: "#0071e3" },
  { id: "neon", label: "Neon", color: "#bf5af2" },
  { id: "ember", label: "Ember", color: "#ff375f" },
  { id: "moss", label: "Moss", color: "#30d158" },
  { id: "ocean", label: "Ocean", color: "#64d2ff" },
  { id: "sunset", label: "Sunset", color: "#ff6b6b" },
];

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>("midnight");

  useEffect(() => {
    const saved = localStorage.getItem("fy3-theme") as Theme | null;
    if (saved && THEMES.some((t) => t.id === saved)) {
      setThemeState(saved);
      document.documentElement.setAttribute("data-theme", saved);
    }
  }, []);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    localStorage.setItem("fy3-theme", t);
    document.documentElement.setAttribute("data-theme", t);
  }, []);

  return { theme, setTheme, themes: THEMES };
}
