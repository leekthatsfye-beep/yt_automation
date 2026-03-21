"use client";

import { Store, ExternalLink, DollarSign } from "lucide-react";
import type { Beat } from "@/types/beat";

interface Props {
  beat: Beat;
  onUpdated: () => void;
}

export default function BeatStudioTab({ beat }: Props) {
  return (
    <div className="space-y-5">
      {/* Store Listing Info */}
      <div className="text-center py-8">
        <div
          className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-4"
          style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
        >
          <Store size={22} className="text-text-tertiary" />
        </div>
        <p className="text-sm font-medium text-text-secondary">Store & Marketplace</p>
        <p className="text-xs text-text-tertiary mt-1 max-w-xs mx-auto">
          Manage listings for this beat on Airbit, BeatStars, and other platforms from the Settings page.
        </p>
      </div>

      {/* Beat Status Summary */}
      <div className="space-y-2">
        <div
          className="flex items-center justify-between p-3 rounded-xl"
          style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
        >
          <span className="text-xs font-medium text-text-secondary">Stem</span>
          <span className="text-xs font-mono text-text-tertiary">{beat.stem}</span>
        </div>
        <div
          className="flex items-center justify-between p-3 rounded-xl"
          style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
        >
          <span className="text-xs font-medium text-text-secondary">File</span>
          <span className="text-xs font-mono text-text-tertiary">{beat.filename}</span>
        </div>
        {beat.bpm && (
          <div
            className="flex items-center justify-between p-3 rounded-xl"
            style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
          >
            <span className="text-xs font-medium text-text-secondary">BPM</span>
            <span className="text-xs font-mono text-text-tertiary">{beat.bpm}</span>
          </div>
        )}
        {beat.key && (
          <div
            className="flex items-center justify-between p-3 rounded-xl"
            style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}
          >
            <span className="text-xs font-medium text-text-secondary">Key</span>
            <span className="text-xs font-mono text-text-tertiary">{beat.key}</span>
          </div>
        )}
      </div>
    </div>
  );
}
