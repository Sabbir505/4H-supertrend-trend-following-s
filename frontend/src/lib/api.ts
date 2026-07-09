const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "";
const API_TIMEOUT = 10000;

export interface Signal {
  id: string;
  symbol: string;
  direction: "BUY" | "SELL";
  price: number;        // entry
  ema200: number;
  rsi: number;
  atr: number;
  atr_pct: number;
  supertrend_value: number;
  sl: number;
  tp: number;
  rr: number;
  interval: "4h";
  detected_at: string;
  source: "volume" | "volatility" | "both";
  alerted: boolean;
}

export interface DashboardStats {
  total_signals: number;
  signals_24h: number;
  buy_count: number;
  sell_count: number;
  by_interval: Record<string, number>;
}

// ─── API Client ────────────────────────────────────────────────────

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
