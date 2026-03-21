"use client";

interface WaveformProps {
  stem: string;
  width?: number;
  height?: number;
  barCount?: number;
  color?: string;
  activeColor?: string;
  active?: boolean;
}

function seedRandom(str: string): () => number {
  let seed = 0;
  for (let i = 0; i < str.length; i++) {
    seed = ((seed << 5) - seed + str.charCodeAt(i)) | 0;
  }
  return () => {
    seed = (seed * 16807 + 0) % 2147483647;
    return (seed & 0x7fffffff) / 0x7fffffff;
  };
}

export default function Waveform({
  stem,
  width = 120,
  height = 32,
  barCount = 24,
  color = "var(--text-tertiary)",
  activeColor = "var(--accent)",
  active = false,
}: WaveformProps) {
  const rand = seedRandom(stem);
  const gap = width / barCount;
  const barWidth = gap * 0.6;

  const bars: number[] = [];
  for (let i = 0; i < barCount; i++) {
    const center = barCount / 2;
    const dist = Math.abs(i - center) / center;
    const envelope = 1 - dist * 0.5;
    bars.push(rand() * envelope * 0.8 + 0.15);
  }

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="block"
    >
      {bars.map((h, i) => {
        const barH = h * height;
        const x = i * gap + (gap - barWidth) / 2;
        const y = (height - barH) / 2;
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={barWidth}
            height={barH}
            rx={barWidth / 2}
            fill={active ? activeColor : color}
            opacity={active ? 0.9 : 0.4}
          />
        );
      })}
    </svg>
  );
}
