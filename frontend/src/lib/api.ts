const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
const API_TIMEOUT = 10000;

export interface Signal {
  id: string;
  symbol: string;
  direction: "BUY" | "SELL";
  price: number;        // entry
  atr: number;
  atr_pct: number;
  interval: "4h" | "30m";
  detected_at: string;
  source: "volume" | "marketcap" | "both";
  alerted: boolean;

  // Legacy RR-based fields (pre round-4 rows only)
  sl?: number;
  tp?: number;
  rr?: number;
  rsi?: number;

  // 4H Supertrend trend-ride fields (always present on new-format rows)
  ema200?: number;
  supertrend_value?: number;
  candle_time?: string;
  strategy?: string;
  breadth?: number;
  risk_level?: string;
  risk_pct?: number;
  initial_stop?: number;
  // Round-5b quality tier: A best … D worst (empty on legacy rows)
  quality?: "A" | "B" | "C" | "D";
  quality_reason?: string;
}

export interface DashboardStats {
  total_signals: number;
  signals_24h: number;
  buy_count: number;
  sell_count: number;
  by_interval: Record<string, number>;
}

export interface ScannerStatus {
  scan_4h: string | null;
  scan_stale?: boolean;  // populated by /api/health
  status?: string;       // populated by /api/health
  server_time?: string;  // populated by /api/health
}

export interface VirtualTrade {
  symbol: string;
  direction: "BUY" | "SELL";
  entry: number;
  exit: number;
  exit_reason: "stop" | "flip" | "time";
  gross_r: number;
  net_r: number;
  bars_held: number;
  entry_time: string;
  exit_time: string;
  risk_level?: string;
  strategy?: string;
}

export async function getVirtualTrades(): Promise<VirtualTrade[]> {
  return fetchAPI<VirtualTrade[]>("/api/trades");
}

export async function getOpenPositions(): Promise<VirtualTrade[]> {
  return fetchAPI<VirtualTrade[]>("/api/positions");
}

// ─── Backtest results (static export) ──────────────────────────────

export interface BacktestWindowMetrics {
  trades?: number;
  win_rate?: number;
  avg_r?: number;
  profit_factor?: number;
  total_return_pct?: number;
  max_dd_pct?: number;
  sharpe?: number;
}

export interface BacktestResults {
  generated_at: string;
  config: {
    name: string;
    params: Record<string, string>;
  };
  metrics: Record<
    "train" | "valid" | "full",
    { baseline: BacktestWindowMetrics; base: BacktestWindowMetrics; final: BacktestWindowMetrics }
  >;
  equity: { date: string; final: number; baseline: number; btc_hold: number }[];
  drawdown: { date: string; dd: number }[];
  cost_stress: { label: string; return_pct: number; pf: number }[];
  folds: { name: string; return_pct: number; dd_pct: number }[];
  rounds: { round: string; title: string; result: string }[];
  rejected: { idea: string; reason: string }[];
}

export async function getBacktestResults(): Promise<BacktestResults> {
  const res = await fetch("/data/backtest_results.json");
  if (!res.ok) throw new Error(`Failed to load backtest results: ${res.status}`);
  return res.json();
}

// ─── API Client ────────────────────────────────────────────────────

async function fetchAPI<T>(endpoint: string, timeoutMs = API_TIMEOUT): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

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

    return response.json() as Promise<T>;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("API request timed out. Please check if the backend is running.");
    }
    throw error;
  }
}

// ─── Signal Endpoints ──────────────────────────────────────────────

export async function getSignals(params?: {
  interval?: string;
  direction?: string;
}): Promise<Signal[]> {
  const searchParams = new URLSearchParams();
  if (params?.interval) searchParams.set("interval", params.interval);
  if (params?.direction) searchParams.set("direction", params.direction);
  const query = searchParams.toString();
  return fetchAPI<Signal[]>(`/api/signals${query ? `?${query}` : ""}`);
}

export async function getRecentSignals(): Promise<Signal[]> {
  return fetchAPI<Signal[]>("/api/signals/recent");
}

export async function getDashboardStats(): Promise<DashboardStats> {
  return fetchAPI<DashboardStats>("/api/dashboard/stats");
}

export async function getScannerStatus(): Promise<ScannerStatus> {
  return fetchAPI<ScannerStatus>("/api/scanner/status");
}

export interface Health {
  status: string;
  last_scan: string | null;
  scan_stale: boolean;
  server_time: string;
}

export async function getHealth(): Promise<Health> {
  return fetchAPI<Health>("/api/health");
}

// ─── Price klines (sparklines) ─────────────────────────────────────

export interface KlineData {
  closes: number[];
  current: number;
}

export async function getKlines(
  symbols: string[],
  interval = "1h",
  limit = 168,
): Promise<Record<string, KlineData>> {
  const searchParams = new URLSearchParams({
    symbols: symbols.join(","),
    interval,
    limit: String(limit),
  });
  // First load can fetch dozens of symbols upstream; allow extra time.
  return fetchAPI<Record<string, KlineData>>(`/api/klines?${searchParams}`, 30000);
}
