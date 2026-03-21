"use client";

import { useMemo } from "react";

interface Section {
  name: string;
  label: string;
  start_bar: number;
  end_bar?: number;
  length_bars?: number;
  energy: number;
}

interface StructureTimelineProps {
  sections: Section[];
  totalBars: number;
  energyCurve?: number[];
  onSectionClick?: (section: Section) => void;
  highlightSection?: string;
  compact?: boolean;
  label?: string;
}

// Energy → color mapping
function energyColor(energy: number): string {
  if (energy >= 0.8) return "#ff4444";
  if (energy >= 0.6) return "#f5a623";
  if (energy >= 0.4) return "#38bdf8";
  if (energy >= 0.2) return "#6366f1";
  return "#4b5563";
}

function energyBg(energy: number, opacity = 0.25): string {
  const hex = energyColor(energy).replace("#", "");
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${opacity})`;
}

export default function StructureTimeline({
  sections,
  totalBars,
  energyCurve,
  onSectionClick,
  highlightSection,
  compact = false,
  label,
}: StructureTimelineProps) {
  const height = compact ? 36 : 52;
  const curveHeight = 24;
  const totalHeight = energyCurve ? height + curveHeight + 4 : height;

  const normalizedSections = useMemo(() => {
    return sections.map((s) => ({
      ...s,
      end_bar: s.end_bar ?? s.start_bar + (s.length_bars ?? 0),
      length_bars: s.length_bars ?? (s.end_bar ? s.end_bar - s.start_bar : 0),
    }));
  }, [sections]);

  if (totalBars <= 0 || sections.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-xl"
        style={{
          height: totalHeight,
          background: "var(--bg-hover)",
          border: "1px solid var(--border)",
          color: "var(--text-tertiary)",
          fontSize: 11,
        }}
      >
        No structure detected
      </div>
    );
  }

  return (
    <div>
      {label && (
        <p className="text-[10px] font-bold uppercase tracking-wider text-text-tertiary mb-1.5">
          {label}
        </p>
      )}
      <svg
        width="100%"
        viewBox={`0 0 ${totalBars} ${totalHeight}`}
        preserveAspectRatio="none"
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--bg-hover)" }}
      >
        {/* Section bars */}
        {normalizedSections.map((section, i) => {
          const x = section.start_bar;
          const w = Math.max(section.length_bars, 1);
          const isHighlighted = highlightSection === section.name;
          const color = energyColor(section.energy);

          return (
            <g
              key={`${section.name}-${i}`}
              onClick={() => onSectionClick?.(section)}
              style={{ cursor: onSectionClick ? "pointer" : "default" }}
            >
              {/* Background fill */}
              <rect
                x={x}
                y={0}
                width={w}
                height={height}
                fill={energyBg(section.energy, isHighlighted ? 0.5 : 0.3)}
                stroke={color}
                strokeWidth={isHighlighted ? 0.5 : 0.15}
                rx={0.5}
              />
              {/* Energy indicator bar at bottom */}
              <rect
                x={x}
                y={height - 3}
                width={w}
                height={3}
                fill={color}
                opacity={0.8}
              />
              {/* Label text */}
              {w > 4 && (
                <text
                  x={x + w / 2}
                  y={compact ? height / 2 + 1 : height / 2 - 2}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill={color}
                  fontSize={compact ? 3 : 3.5}
                  fontWeight="700"
                  fontFamily="system-ui, sans-serif"
                >
                  {section.label}
                </text>
              )}
              {/* Bar count */}
              {!compact && w > 6 && (
                <text
                  x={x + w / 2}
                  y={height / 2 + 5}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fill="var(--text-tertiary)"
                  fontSize={2.5}
                  fontFamily="system-ui, sans-serif"
                  opacity={0.7}
                >
                  {section.length_bars} bars
                </text>
              )}
            </g>
          );
        })}

        {/* Energy curve overlay */}
        {energyCurve && energyCurve.length > 0 && (
          <g transform={`translate(0, ${height + 4})`}>
            {energyCurve.map((e, i) => (
              <rect
                key={i}
                x={i}
                y={curveHeight - e * curveHeight}
                width={0.8}
                height={e * curveHeight}
                fill={energyColor(e)}
                opacity={0.6}
                rx={0.1}
              />
            ))}
          </g>
        )}
      </svg>
    </div>
  );
}
