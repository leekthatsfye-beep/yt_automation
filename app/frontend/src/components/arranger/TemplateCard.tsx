"use client";

import { Music, Clock, Layers, Zap } from "lucide-react";

interface Section {
  name: string;
  label: string;
  start_bar: number;
  length_bars?: number;
  energy: number;
  patterns?: string[];
}

interface Template {
  id: string;
  name: string;
  genre: string;
  description: string;
  total_bars: number;
  bpm_range: [number, number];
  sections: Section[];
  youtube_notes?: {
    target_duration_sec?: [number, number];
    first_drop_by_sec?: number;
    hook_in_first_sec?: number;
  };
}

interface TemplateCardProps {
  template: Template;
  selected: boolean;
  onSelect: (template: Template) => void;
}

const GENRE_COLORS: Record<string, string> = {
  trap: "#ff4444",
  drill: "#9333ea",
  rnb: "#f472b6",
  melodic: "#38bdf8",
  dark_trap: "#6b21a8",
};

function energyColor(energy: number): string {
  if (energy >= 0.8) return "#ff4444";
  if (energy >= 0.6) return "#f5a623";
  if (energy >= 0.4) return "#38bdf8";
  return "#4b5563";
}

export default function TemplateCard({ template, selected, onSelect }: TemplateCardProps) {
  const color = GENRE_COLORS[template.genre] ?? "var(--accent)";
  const dropCount = template.sections.filter((s) => s.energy >= 0.8).length;

  return (
    <button
      onClick={() => onSelect(template)}
      className="text-left p-4 rounded-2xl transition-all cursor-pointer w-full"
      style={{
        background: selected ? `${color}12` : "var(--bg-hover)",
        border: `1.5px solid ${selected ? `${color}50` : "var(--border)"}`,
        boxShadow: selected ? `0 0 20px ${color}15` : "none",
      }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span
            className="text-[9px] font-bold px-2 py-0.5 rounded-full uppercase"
            style={{ background: `${color}20`, color }}
          >
            {template.genre.replace("_", " ")}
          </span>
          <span className="text-sm font-bold text-foreground">{template.name}</span>
        </div>
        {selected && (
          <div
            className="w-5 h-5 rounded-full flex items-center justify-center"
            style={{ background: color }}
          >
            <Zap size={10} color="#fff" />
          </div>
        )}
      </div>

      {/* Description */}
      <p className="text-[10px] text-text-tertiary mb-3 line-clamp-2">{template.description}</p>

      {/* Mini timeline */}
      <div className="flex gap-px rounded-lg overflow-hidden mb-3" style={{ height: 16 }}>
        {template.sections.map((section, i) => {
          const bars = section.length_bars ?? 8;
          const widthPct = (bars / template.total_bars) * 100;
          return (
            <div
              key={i}
              className="relative"
              style={{
                width: `${widthPct}%`,
                background: energyColor(section.energy),
                opacity: 0.3 + section.energy * 0.5,
              }}
              title={`${section.label} (${bars} bars)`}
            >
              {widthPct > 12 && (
                <span
                  className="absolute inset-0 flex items-center justify-center text-[6px] font-bold text-white truncate px-0.5"
                  style={{ textShadow: "0 1px 2px rgba(0,0,0,0.5)" }}
                >
                  {section.label}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Stats */}
      <div className="flex items-center gap-3 text-[9px] text-text-tertiary">
        <span className="flex items-center gap-1">
          <Layers size={9} />
          {template.sections.length} sections
        </span>
        <span className="flex items-center gap-1">
          <Music size={9} />
          {template.total_bars} bars
        </span>
        <span className="flex items-center gap-1">
          <Clock size={9} />
          {template.bpm_range[0]}-{template.bpm_range[1]} BPM
        </span>
        {dropCount > 0 && (
          <span className="flex items-center gap-1" style={{ color: "#ff4444" }}>
            <Zap size={9} />
            {dropCount} drops
          </span>
        )}
      </div>
    </button>
  );
}
