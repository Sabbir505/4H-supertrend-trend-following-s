import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"
import { Signal } from "./api";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Calculate the Risk-Reward (RR) for a given signal based on its status.
 * Uses the 4-TP incremental closing strategy (40/30/20/10).
 *
 * RR calculation rules:
 * - SL: -1R (full loss)
 * - EXPIRED: 0R
 * - BREAKEVEN: 40% at TP1 (rr1 * 0.4), remaining at breakeven = rr1 * 0.4
 * - TP1: 40% at TP1 = rr1 * 0.4
 * - TP2: 40% at TP1 + 30% at TP2 = rr1 * 0.4 + rr2 * 0.3
 * - TP3: 40% at TP1 + 30% at TP2 + 20% at TP3 = rr1 * 0.4 + rr2 * 0.3 + rr3 * 0.2
 * - TP4/WIN: Full blend = rr1 * 0.4 + rr2 * 0.3 + rr3 * 0.2 + rr_max * 0.1
 * - OPEN/other: 0 (not yet realized)
 */
export function calculateRR(signal: Signal): number {
  const rr1 = signal.rr1 || 1.5;
  const rr2 = signal.rr2 || 2.0;
  const rr3 = signal.rr3 ?? 3.0;  // Match backend default
  const rrMax = signal.rr_max ?? 4.0;  // Match backend default

  if (signal.status === "SL") {
    return -1;
  }

  if (signal.status === "EXPIRED") {
    return 0;
  }

  if (signal.status === "BREAKEVEN") {
    // Calculate based on which TPs were actually hit before breakeven
    let total = 0;
    if (signal.tp1_hit) total += rr1 * 0.40;
    if (signal.tp2_hit) total += rr2 * 0.30;
    if (signal.tp3_hit) total += rr3 * 0.20;
    if (signal.tp4_hit) total += rrMax * 0.10;
    return total;
  }

  if (signal.status === "TP1") {
    return rr1 * 0.40;
  }

  if (signal.status === "TP2") {
    return rr1 * 0.40 + rr2 * 0.30;
  }

  if (signal.status === "TP3") {
    return rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20;
  }

  if (signal.status === "TP4" || signal.status === "WIN") {
    return rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20 + rrMax * 0.10;
  }

  return 0;
}

/**
 * Format a price value for display.
 * Uses locale-aware formatting for large numbers, fixed decimals for small.
 */
export function formatPrice(price: number): string {
  if (price >= 1) return price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (price >= 0.01) return price.toFixed(4);
  return price.toFixed(6);
}

/**
 * Color mapping for signal outcomes.
 */
export const outcomeColors: Record<string, string> = {
  TP1: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  TP2: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  TP3: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  TP4: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  WIN: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
  SL: "bg-red-500/10 text-red-400 border-red-500/30",
  BREAKEVEN: "bg-amber-500/10 text-amber-400 border-amber-500/30",
  EXPIRED: "bg-slate-500/10 text-slate-400 border-slate-500/30",
};
