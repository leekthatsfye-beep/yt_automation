"use client";

import { useCallback, useMemo } from "react";
import { useFetch, api } from "./useApi";

// ── Types ──────────────────────────────────────────────────────────────

export interface StoreCredentials {
  connected: boolean;
  email: string;
  api_key_set?: boolean;
  store_url: string;
  connected_at?: string;
  platform: string;
}

export interface DefaultPricing {
  basic_license: number;
  premium_license: number;
  exclusive_license: number;
  currency: string;
}

export interface PlatformStatus {
  listed: boolean;
  listing_id: string | null;
  uploaded_at: string | null;
  url?: string | null;
}

export interface BeatListing {
  stem: string;
  title: string;
  description: string;
  tags: string[];
  bpm: number;
  key: string;
  genre: string;
  mood: string;
  pricing: {
    basic_license: number;
    premium_license: number;
    exclusive_license: number;
  };
  platforms: {
    airbit: PlatformStatus;
    beatstars: PlatformStatus;
  };
  filename: string;
  has_thumbnail: boolean;
  updated_at?: string;
}

export interface ListingsResponse {
  listings: BeatListing[];
  total: number;
  genres: string[];
  moods: string[];
  keys: string[];
}

// ── Stable defaults (defined outside component to avoid re-creation) ──

const EMPTY_LISTINGS: BeatListing[] = [];
const EMPTY_STRINGS: string[] = [];
const DEFAULT_PRICING: DefaultPricing = {
  basic_license: 29.99,
  premium_license: 49.99,
  exclusive_license: 299.99,
  currency: "USD",
};

// ── Hook ───────────────────────────────────────────────────────────────

interface UseStoresOptions {
  /** Skip fetching all listings (useful for settings page that only needs pricing/credentials) */
  skipListings?: boolean;
}

export function useStores(options?: UseStoresOptions) {
  const skipListings = options?.skipListings ?? false;

  const {
    data: listingsData,
    loading,
    error,
    refetch,
  } = useFetch<ListingsResponse>(skipListings ? null : "/stores/listings");

  const {
    data: pricingData,
    refetch: refetchPricing,
  } = useFetch<DefaultPricing>("/stores/pricing");

  const listings = listingsData?.listings ?? EMPTY_LISTINGS;
  const genres = listingsData?.genres ?? EMPTY_STRINGS;
  const moods = listingsData?.moods ?? EMPTY_STRINGS;
  const keys = listingsData?.keys ?? EMPTY_STRINGS;
  const pricing = pricingData ?? DEFAULT_PRICING;

  // ── Actions ──────────────────────────────────────────────────

  const getListing = useCallback(
    (stem: string) => api.get<BeatListing>(`/stores/listings/${stem}`),
    []
  );

  const saveListing = useCallback(
    async (stem: string, data: Partial<BeatListing>) => {
      const result = await api.put<BeatListing>(`/stores/listings/${stem}`, data);
      refetch();
      return result;
    },
    [refetch]
  );

  const savePricing = useCallback(
    async (data: Partial<DefaultPricing>) => {
      const result = await api.put<{ status: string; pricing: DefaultPricing }>(
        "/stores/pricing",
        data
      );
      refetchPricing();
      return result;
    },
    [refetchPricing]
  );

  const saveCredentials = useCallback(
    async (platform: string, creds: { email: string; api_key: string; store_url: string }) => {
      return api.post<{ status: string }>(`/stores/credentials/${platform}`, creds);
    },
    []
  );

  const disconnectStore = useCallback(
    async (platform: string) => {
      return api.del<{ status: string }>(`/stores/credentials/${platform}`);
    },
    []
  );

  const uploadToStore = useCallback(
    async (platform: string, stem: string) => {
      return api.post<{ status: string; task_id: string }>(
        `/stores/upload/${platform}/${stem}`
      );
    },
    []
  );

  const bulkUpload = useCallback(
    async (platform: string, stems: string[]) => {
      return api.post<{ status: string; tasks: { stem: string; task_id: string }[]; count: number }>(
        `/stores/upload/${platform}/bulk`,
        { stems }
      );
    },
    []
  );

  const getCredentials = useCallback(
    (platform: string) => api.get<StoreCredentials>(`/stores/credentials/${platform}`),
    []
  );

  return {
    listings,
    pricing,
    genres,
    moods,
    keys,
    loading,
    error,
    refetch,
    getListing,
    saveListing,
    savePricing,
    saveCredentials,
    disconnectStore,
    uploadToStore,
    bulkUpload,
    getCredentials,
  };
}
