"use client";

import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";

interface StatCardProps {
  icon: LucideIcon;
  value: number | string;
  label: string;
  loading?: boolean;
  accentColor?: string;
  href?: string;
}

export default function StatCard({
  icon: Icon,
  value,
  label,
  loading,
  accentColor,
  href,
}: StatCardProps) {
  const color = accentColor || "var(--accent)";

  const inner = (
    <>
      {/* Background glow blob */}
      <div className="stat-glow" style={{ background: color }} />

      {/* Gradient overlay on hover */}
      <div
        className="absolute inset-0 rounded-lg opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"
        style={{
          background: `radial-gradient(ellipse at top left, ${color}15, transparent 60%)`,
        }}
      />

      <div className="relative z-10">
        {/* Icon */}
        <div className="flex items-center justify-between mb-4">
          <div
            className="w-11 h-11 rounded-lg flex items-center justify-center transition-all duration-200"
            style={{
              background: `${color}15`,
              boxShadow: `0 0 0 0 ${color}00`,
            }}
          >
            <Icon size={20} style={{ color }} strokeWidth={1.8} />
          </div>
          {/* Decorative sparkle */}
          <div
            className="w-1.5 h-1.5 rounded-full opacity-0 group-hover:opacity-60 transition-all duration-500"
            style={{ background: color, boxShadow: `0 0 6px ${color}` }}
          />
        </div>

        {loading ? (
          <div className="space-y-2.5">
            <Skeleton className="h-9 w-16 rounded-lg" />
            <Skeleton className="h-4 w-24 rounded-md" />
          </div>
        ) : (
          <>
            <p
              className="text-3xl font-bold tracking-tight text-foreground animate-counter"
              style={{ fontVariantNumeric: "tabular-nums" }}
            >
              {value}
            </p>
            <p className="text-[13px] mt-1.5 font-medium text-muted-foreground">
              {label}
            </p>
          </>
        )}
      </div>
    </>
  );

  if (href) {
    return (
      <Link href={href} prefetch={false} className="stat-card p-5 group block cursor-pointer">
        {inner}
      </Link>
    );
  }

  return (
    <div className="stat-card p-5 group">
      {inner}
    </div>
  );
}
