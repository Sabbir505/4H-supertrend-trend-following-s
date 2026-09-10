"use client";

import { useId } from "react";

interface SparklineProps {
  closes: number[];
  /** Reference price (signal entry) drawn as a dashed level line. */
  entry?: number;
  /** Drives stroke/fill color: green for profit, red for loss. */
  positive: boolean;
  className?: string;
}

const UP_COLOR = "#34d399"; // emerald-400
const DOWN_COLOR = "#f87171"; // red-400

/**
 * Lightweight price sparkline. Rendered as SVG with preserveAspectRatio="none"
 * so it stretches to its container; vector-effect keeps the stroke width
 * uniform despite the non-uniform scale.
 */
export function Sparkline({ closes, entry, positive, className }: SparklineProps) {
  const gradientId = useId();

  if (!closes || closes.length < 2) return null;

  const W = 100;
  const H = 32;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  // Pad the vertical range slightly so the line doesn't clip at the edges.
  const pad = (max - min || min || 1) * 0.08;
  const lo = min - pad;
  const span = max + pad - lo || 1;

  const points = closes.map((c, i) => {
    const x = (i / (closes.length - 1)) * W;
    const y = H - ((c - lo) / span) * H;
    return { x, y };
  });
  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(" ");
  const areaPath = `${linePath} L${W},${H} L0,${H} Z`;

  const color = positive ? UP_COLOR : DOWN_COLOR;

  // Entry level line, only when it falls inside the visible window.
  let entryY: number | null = null;
  if (entry != null && entry >= lo && entry <= max + pad) {
    entryY = H - ((entry - lo) / span) * H;
  }

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={className}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradientId})`} />
      <path
        d={linePath}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      {entryY != null && (
        <line
          x1="0"
          x2={W}
          y1={entryY.toFixed(2)}
          y2={entryY.toFixed(2)}
          stroke="rgba(255,255,255,0.28)"
          strokeWidth="1"
          strokeDasharray="3 3"
          vectorEffect="non-scaling-stroke"
        />
      )}
    </svg>
  );
}
