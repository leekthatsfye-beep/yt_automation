"use client";

import { useState, useEffect, useCallback } from "react";

const BASE = "/api";
const RETRY_ATTEMPTS = 3;

/** Base URL for static files served by FastAPI (beats, output, studio). */
export function getFilesBase(): string {
  return "/files";
}

/**
 * Build a streamable URL with JWT token in query param.
 * Native <video>/<audio> elements can't send Authorization headers,
 * so we pass the token as ?token=xxx for direct streaming.
 */
export function authedUrl(path: string): string {
  const token = typeof window !== "undefined" ? localStorage.getItem("fy3-token") : null;
  const sep = path.includes("?") ? "&" : "?";
  return token ? `${path}${sep}token=${token}` : path;
}

const RETRY_BASE_DELAY = 1000;

function isRetryable(error: unknown, status?: number): boolean {
  if (error instanceof TypeError) return true; // network failure
  if (status && [502, 503, 504].includes(status)) return true; // gateway errors
  return false;
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function getAuthHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("fy3-token");
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = {
    method,
    headers: getAuthHeaders(),
  };
  if (body) opts.body = JSON.stringify(body);

  let lastError: Error | null = null;

  for (let attempt = 0; attempt < RETRY_ATTEMPTS; attempt++) {
    try {
      const res = await fetch(`${BASE}${path}`, opts);

      // Handle auth failure — clear token and redirect to login
      if (res.status === 401) {
        if (typeof window !== "undefined") {
          localStorage.removeItem("fy3-token");
          window.location.href = "/login";
        }
        throw new Error("Session expired");
      }

      if (!res.ok) {
        if (isRetryable(null, res.status) && attempt < RETRY_ATTEMPTS - 1) {
          await sleep(RETRY_BASE_DELAY * Math.pow(2, attempt));
          continue;
        }
        // Try to extract detail from JSON error response
        let detail = `${res.status} ${res.statusText}`;
        try {
          const errBody = await res.json();
          if (errBody?.detail) detail = errBody.detail;
        } catch { /* ignore parse errors */ }
        throw new Error(detail);
      }
      return res.json();
    } catch (err) {
      lastError = err as Error;
      if (isRetryable(err) && attempt < RETRY_ATTEMPTS - 1) {
        await sleep(RETRY_BASE_DELAY * Math.pow(2, attempt));
        continue;
      }
      throw err;
    }
  }

  throw lastError ?? new Error("Request failed");
}

export function useFetch<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(!!path);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(() => {
    if (!path) return;
    setLoading(true);
    setError(null);
    request<T>("GET", path)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [path]);

  useEffect(() => {
    if (!path) { setData(null); setLoading(false); return; }
    refetch();
  }, [path, refetch]);

  // Auto-refetch when connection is restored
  useEffect(() => {
    const handleReconnected = () => refetch();
    window.addEventListener("fy3:reconnected", handleReconnected);
    return () => window.removeEventListener("fy3:reconnected", handleReconnected);
  }, [refetch]);

  /** Alias for refetch — matches SWR naming convention */
  const mutate = refetch;

  return { data, loading, error, refetch, mutate };
}

/** Upload FormData (multipart) — no Content-Type header (browser sets boundary). */
async function uploadRequest<T>(path: string, formData: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("fy3-token");
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (res.status === 401) {
    if (typeof window !== "undefined") {
      localStorage.removeItem("fy3-token");
      window.location.href = "/login";
    }
    throw new Error("Session expired");
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const errBody = await res.json();
      if (errBody?.detail) detail = errBody.detail;
    } catch { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
  upload: <T>(path: string, formData: FormData) => uploadRequest<T>(path, formData),
};
