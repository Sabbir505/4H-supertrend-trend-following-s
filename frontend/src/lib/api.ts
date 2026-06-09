const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// Default timeout for API requests (ms)
const API_TIMEOUT = 10000;

export interface Signal {
  id: string;
  symbol: string;
  direction: "LONG" | "SHORT";
  strength?: "STRONG" | "STANDARD";
  entry: number;
  sl: number;
  tp1: number;
  tp2: number;
  tp3: number;
  tp4: number;
  rr1: number;
  rr2: number;
  rr3: number;
  rr_max: number;
  quality_score: number;
  fired_at: string;
  status: "OPEN" | "TP1" | "TP2" | "TP3" | "TP4" | "SL" | "BREAKEVEN" | "EXPIRED" | "WIN";
  outcome?: "WIN" | "LOSS" | "PARTIAL" | "BREAKEVEN" | "EXPIRED";
  closed_at?: string;
  max_rr_hit?: number;
  tp1_hit: boolean;
  tp2_hit: boolean;
  tp3_hit: boolean;
  tp4_hit: boolean;
  sl_hit: boolean;
  sl_at_breakeven?: boolean;
  sl_original?: number;
  minutes_to_close?: number;
  // Live data fields
  current_price?: number;
  pnl?: number;
  pnl_percent?: number;
}

export interface BacktestTrade {
  symbol: string;
  direction: string;
  entry: number;
  sl: number;
  tp1: number;
  tp2: number;
  tp3: number;
  tp4: number;
  sl_distance: number;
  entry_time: string;
  sl_original: number;
  exit_time?: string;
  exit_price?: number;
  outcome: string;
  rr_achieved?: number;
  bars_held?: number;
  quality_score: number;
  adx_at_entry: number;
  tp1_hit: boolean;
  tp2_hit: boolean;
  tp3_hit: boolean;
  sl_at_breakeven: boolean;
}

export interface BacktestResult {
  symbol: string;
  timeframe: string;
  period_months: number;
  total_trades: number;
  wins: number;
  losses: number;
  breakevens: number;
  win_rate: number;
  avg_rr: number;
  max_rr: number;
  total_rr: number;
  max_drawdown: number;
  avg_bars_held: number;
  long_trades: number;
  short_trades: number;
  long_win_rate: number;
  short_win_rate: number;
  tp1_rate: number;
  tp2_rate: number;
  tp3_rate: number;
  tp4_rate: number;
  breakeven_rate: number;
  any_tp_rate?: number;
  trades: BacktestTrade[];
}

export interface DashboardStats {
  total_signals: number;
  open_signals: number;
  closed_signals: number;
  win_rate: number;
  avg_quality_score: number;
  total_trades_backtest: number;
  total_backtest_wins: number;
  total_backtest_losses: number;
  overall_backtest_wr: number;
  total_rr: number;
}

export interface LiveTrade {
  id: string;
  symbol: string;
  direction: string;
  strength?: string;
  entry: number;
  current_price?: number;
  sl: number;
  tp1: number;
  tp2: number;
  tp3: number;
  tp4: number;
  rr_ratio: string;
  quality_score: number;
  status: string;
  time_ago: string;
  pnl?: number;
  tp1_progress?: number;
}

export interface AnalyticsSummary {
  direction_counts: { LONG: number; SHORT: number };
  strength_counts: { STRONG: number; STANDARD: number };
  outcome_distribution: Record<string, number>;
  symbol_performance: Array<{
    symbol: string;
    win_rate: number;
    total_trades: number;
    total_rr: number;
  }>;
  total_signals: number;
}

// ─── API Client ───────────────────────────────────────────────────────────────

async function fetchAPI<T>(endpoint: string): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT);

  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache"
      },
      signal: controller.signal,
    });
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }

    const data = await response.json();
    return data as T;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("API request timed out. Please check if the backend is running.");
    }
    throw error;
  }
}

// ─── Signal Endpoints ─────────────────────────────────────────────────────────

export async function getAllSignals(): Promise<Signal[]> {
  return fetchAPI<Signal[]>('/api/signals');
}

export async function getOpenSignals(): Promise<Signal[]> {
  return fetchAPI<Signal[]>('/api/signals/open');
}

export async function getClosedSignals(): Promise<Signal[]> {
  return fetchAPI<Signal[]>('/api/signals/closed');
}

export async function getSignalById(id: string): Promise<Signal> {
  return fetchAPI<Signal>(`/api/signals/${id}`);
}

// ─── Backtest Endpoints ───────────────────────────────────────────────────────

export async function getBacktestResults(): Promise<BacktestResult[]> {
  return fetchAPI<BacktestResult[]>('/api/backtest');
}

export async function getBacktestForSymbol(symbol: string): Promise<BacktestResult> {
  return fetchAPI<BacktestResult>(`/api/backtest/${symbol}`);
}

// ─── Dashboard Endpoints ────────────────────────────────────────────────────────

export async function getDashboardStats(): Promise<DashboardStats> {
  return fetchAPI<DashboardStats>('/api/dashboard/stats');
}

// ─── Live Trades Endpoints ────────────────────────────────────────────────────

export async function getLiveTrades(): Promise<LiveTrade[]> {
  return fetchAPI<LiveTrade[]>('/api/live-trades');
}

// ─── Analytics Endpoints ──────────────────────────────────────────────────────

export async function getAnalyticsSummary(): Promise<AnalyticsSummary> {
  return fetchAPI<AnalyticsSummary>('/api/analytics/summary');
}
