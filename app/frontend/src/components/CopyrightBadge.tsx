"use client";

import { Shield, ShieldAlert, ShieldCheck, Flag, HelpCircle } from "lucide-react";

type Risk = "safe" | "caution" | "danger" | "flagged" | "unknown";

interface CopyrightBadgeProps {
  risk: Risk;
  reasons?: string[];
  size?: "sm" | "md";
}

const CONFIG: Record<Risk, { label: string; color: string; bg: string; Icon: typeof Shield }> = {
  safe:    { label: "Safe",    color: "#22c55e", bg: "rgba(34,197,94,0.15)",  Icon: ShieldCheck },
  caution: { label: "Caution", color: "#eab308", bg: "rgba(234,179,8,0.15)",  Icon: ShieldAlert },
  danger:  { label: "Danger",  color: "#ef4444", bg: "rgba(239,68,68,0.15)",  Icon: ShieldAlert },
  flagged: { label: "Flagged", color: "#ef4444", bg: "rgba(239,68,68,0.15)",  Icon: Flag },
  unknown: { label: "Unknown", color: "#6b7280", bg: "rgba(107,114,128,0.15)", Icon: HelpCircle },
};

export default function CopyrightBadge({ risk, reasons = [], size = "sm" }: CopyrightBadgeProps) {
  const { label, color, bg, Icon } = CONFIG[risk] || CONFIG.unknown;
  const iconSize = size === "sm" ? 12 : 14;
  const textSize = size === "sm" ? "text-[10px]" : "text-xs";
  const px = size === "sm" ? "px-1.5 py-0.5" : "px-2 py-1";

  return (
    <span
      className={`inline-flex items-center gap-1 ${px} rounded-full font-semibold ${textSize} cursor-default`}
      style={{ color, background: bg }}
      title={reasons.length > 0 ? reasons.join("\n") : label}
    >
      <Icon size={iconSize} />
      {label}
    </span>
  );
}
