"use client";

import { Film, Upload, Clock } from "lucide-react";
import { Badge } from "@/components/ui/badge";

type StatusType = "rendered" | "uploaded" | "pending";

interface StatusBadgeProps {
  status: StatusType;
  size?: "sm" | "md";
}

const CONFIG: Record<
  StatusType,
  {
    label: string;
    icon: typeof Film;
    variant: "success" | "accent" | "warning";
  }
> = {
  rendered: {
    label: "Rendered",
    icon: Film,
    variant: "success",
  },
  uploaded: {
    label: "Uploaded",
    icon: Upload,
    variant: "accent",
  },
  pending: {
    label: "Pending",
    icon: Clock,
    variant: "warning",
  },
};

export default function StatusBadge({ status, size = "sm" }: StatusBadgeProps) {
  const { label, icon: Icon, variant } = CONFIG[status];
  const isSmall = size === "sm";

  return (
    <Badge
      variant={variant}
      className={isSmall ? "text-[10px] px-2 py-0 gap-1" : "text-[11px] px-2.5 py-0.5 gap-1"}
    >
      <Icon size={isSmall ? 10 : 12} strokeWidth={2} />
      {label}
    </Badge>
  );
}

export function getStatuses(beat: {
  rendered: boolean;
  uploaded: boolean;
}): StatusType[] {
  const statuses: StatusType[] = [];
  if (beat.uploaded) statuses.push("uploaded");
  if (beat.rendered && !beat.uploaded) statuses.push("rendered");
  if (!beat.rendered && !beat.uploaded) statuses.push("pending");
  return statuses;
}
