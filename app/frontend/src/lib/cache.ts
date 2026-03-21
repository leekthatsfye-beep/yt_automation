/**
 * FY3 Cache Management
 * Handles automatic cache clearing on app updates and manual purge.
 */

const BUILD_KEY = "fy3-build-id";

/** Clear all browser caches: CacheStorage, Service Workers */
export async function clearAllCaches(): Promise<void> {
  try {
    // Clear CacheStorage (service worker / runtime caches)
    if ("caches" in window) {
      const names = await caches.keys();
      await Promise.all(names.map((n) => caches.delete(n)));
    }

    // Unregister any service workers
    if ("serviceWorker" in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map((r) => r.unregister()));
    }
  } catch {
    // Best effort — don't crash the app
  }
}

/** Get the current build fingerprint by checking the app shell */
async function fetchCurrentBuildId(): Promise<string | null> {
  try {
    // Fetch the manifest (stable URL, no hash in filename) with cache bypass
    const res = await fetch("/manifest.json", {
      method: "HEAD",
      cache: "no-store",
    });
    const etag = res.headers.get("etag") || res.headers.get("last-modified");
    if (etag) return etag;

    // Fallback: extract buildId from __NEXT_DATA__ if present in DOM
    const nd = document.getElementById("__NEXT_DATA__");
    if (nd?.textContent) {
      const parsed = JSON.parse(nd.textContent);
      if (parsed.buildId) return parsed.buildId;
    }

    return null;
  } catch {
    return null;
  }
}

/**
 * Check if the app has been updated since last visit.
 * If so, clear all caches and store the new build ID.
 * Returns true if caches were cleared.
 */
export async function checkAndClearOnUpdate(): Promise<boolean> {
  try {
    const currentBuild = await fetchCurrentBuildId();
    if (!currentBuild) return false;

    const savedBuild = localStorage.getItem(BUILD_KEY);
    if (savedBuild === currentBuild) return false;

    // New build detected — clear caches
    await clearAllCaches();
    localStorage.setItem(BUILD_KEY, currentBuild);

    // If this is the first visit (no saved build), don't reload
    if (!savedBuild) return false;

    return true; // Caches were cleared
  } catch {
    return false;
  }
}

/** Manual full cache purge — clears everything and reloads */
export async function purgeAndReload(): Promise<void> {
  // Clear all caches
  await clearAllCaches();

  // Clear localStorage cache keys (keep auth token and user prefs)
  const keysToKeep = ["fy3-token", "fy3-theme"];
  const allKeys: string[] = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && !keysToKeep.includes(key)) {
      allKeys.push(key);
    }
  }
  allKeys.forEach((k) => localStorage.removeItem(k));

  // Clear sessionStorage completely
  sessionStorage.clear();

  // Hard reload — bypass browser cache
  window.location.reload();
}

/** Get estimated cache size info for display */
export async function getCacheInfo(): Promise<{
  cacheNames: string[];
  totalEntries: number;
}> {
  const result = { cacheNames: [] as string[], totalEntries: 0 };
  try {
    if ("caches" in window) {
      const names = await caches.keys();
      result.cacheNames = names;
      for (const name of names) {
        const cache = await caches.open(name);
        const keys = await cache.keys();
        result.totalEntries += keys.length;
      }
    }
  } catch {
    // Ignore
  }
  return result;
}
