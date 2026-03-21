"use client";

import { useMemo } from "react";
import { authedUrl } from "@/hooks/useApi";

/**
 * Returns an authed URL for audio streaming via ?token= query param.
 * No blob download — instant playback with native browser streaming.
 */
export function useAuthAudio(src: string | null): {
  blobUrl: string | null;
  loading: boolean;
  error: boolean;
} {
  const url = useMemo(() => (src ? authedUrl(src) : null), [src]);

  return { blobUrl: url, loading: false, error: false };
}
