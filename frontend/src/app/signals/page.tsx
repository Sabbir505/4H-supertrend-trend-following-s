"use client";

import { useState, useEffect, useCallback } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
  Search,
  Activity,
  Zap,
  Clock,
} from "lucide-react";
import { getSignals, Signal, getKlines, KlineData } from "@/lib/api";
import { Sparkline } from "@/components/sparkline";
import { formatPrice, formatTimestamp } from "@/lib/utils";

const SOURCE_META: Record<string, { label: string; color: string; bg: string }> = {
  volume:    { label: "Volume",    color: "text-blue-400",    bg: "bg-blue-500/10 border-blue-500/20" },
  marketcap: { label: "Mkt Cap",   color: "text-amber-400",   bg: "bg-amber-500/10 border-amber-500/20" },
  both:      { label: "Both",      color: "text-purple-400",  bg: "bg-purple-500/10 border-purple-500/20" },
};

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [directionFilter, setDirectionFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [search, setSearch] = useState("");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [countdown, setCountdown] = useState(30);

  const fetchData = useCallback(async () => {
    try {
      const params: { direction?: string } = {};
      if (directionFilter) params.direction = directionFilter;
      const data = await getSignals(params);
      setSignals(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch signals");
    } finally {
      setLoading(false);
    }
  }, [directionFilter]);

  useEffect(() => {
    let cancelled = false;
    async function init() {
      setLoading(true);
      try {
        const params: { direction?: string } = {};
        if (directionFilter) params.direction = directionFilter;
        const data = await getSignals(params);
        if (!cancelled) {
          setSignals(data);
          setLoading(false);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to fetch signals");
          setLoading(false);
        }
      }
    }
    init();
    return () => { cancelled = true; };
  }, [directionFilter]);

  useEffect(() => {
    if (!autoRefresh) return;
    let fetching = false;
    let timer: ReturnType<typeof setTimeout>;

    const refreshCycle = async () => {
      if (fetching) return;
      fetching = true;
      try {
        await fetchData();
      } finally {
        setCountdown(30);
        fetching = false;
      }
    };

    const tick = () => {
      setCountdown((prev) => {
        if (prev <= 1) {
          refreshCycle();
          return 30;
        }
        return prev - 1;
      });
      timer = setTimeout(tick, 1000);
    };

    timer = setTimeout(tick, 1000);
    return () => clearTimeout(timer);
  }, [autoRefresh, fetchData]);

  // Price klines for card sparklines. Refetched on every signals refresh;
  // the backend serves them from a short TTL cache so Binance isn't hammered.
  const [klines, setKlines] = useState<Record<string, KlineData>>({});
  const [klinesReady, setKlinesReady] = useState(false);

  useEffect(() => {
    const symbols = Array.from(new Set(signals.map((s) => s.symbol)));
    if (symbols.length === 0) return;
    let cancelled = false;
    getKlines(symbols)
      .then((data) => {
        if (cancelled) return;
        setKlines((prev) => ({ ...prev, ...data }));
        setKlinesReady(true);
      })
      .catch(() => {
        /* sparklines are best-effort; cards fall back to a plain placeholder */
      });
    return () => { cancelled = true; };
  }, [signals]);

  const filtered = signals.filter((sig) => {
    if (search && !sig.symbol.toLowerCase().includes(search.toLowerCase())) return false;
    if (sourceFilter && sig.source !== sourceFilter) return false;
    return true;
  });

  const counts = {
    total: filtered.length,
    buy: filtered.filter((s) => s.direction === "BUY").length,
    sell: filtered.filter((s) => s.direction === "SELL").length,
  };

  if (loading) {
    return (
      <DashboardLayout>
        <div className="space-y-6 animate-pulse">
          <div className="h-9 w-56 bg-white/5 rounded-xl" />
          <div className="glass rounded-2xl h-80" />
        </div>
      </DashboardLayout>
    );
  }

  if (error) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center min-h-[60vh]">
          <div className="glass rounded-2xl p-8 text-center max-w-sm">
            <div className="w-12 h-12 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center mx-auto mb-4">
              <Activity className="w-5 h-5 text-red-400" />
            </div>
            <h3 className="text-foreground font-semibold mb-1">Connection Error</h3>
            <p className="text-sm text-muted-foreground">{error}</p>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 animate-fade-in-up">
          <div>
            <h1 className="text-2xl font-bold text-foreground">Supertrend Signals</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Supertrend 10/3.5 trend-ride · EMA200 longs · BTC-regime shorts · {`5×ATR`} initial stop · 3.5×ATR trail · 42-bar time stop
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Summary pills */}
            <div className="hidden md:flex items-center gap-2">
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg glass text-xs">
                <div className="w-1.5 h-1.5 rounded-full bg-muted-foreground" />
                <span className="text-muted-foreground">
                  {counts.total} signals
                </span>
              </div>
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg glass text-xs">
                <ArrowUpRight className="w-3 h-3 text-emerald-400" />
                <span className="text-emerald-400 font-medium">{counts.buy} buy</span>
              </div>
              <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg glass text-xs">
                <ArrowDownRight className="w-3 h-3 text-red-400" />
                <span className="text-red-400 font-medium">{counts.sell} sell</span>
              </div>
            </div>
            {/* Auto-refresh toggle */}
            <button
              onClick={() => setAutoRefresh(!autoRefresh)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg glass text-xs"
            >
              <div
                className={`w-1.5 h-1.5 rounded-full transition-colors ${
                  autoRefresh ? "bg-emerald-400 animate-pulse" : "bg-muted-foreground"
                }`}
              />
              <span className="text-muted-foreground">
                {autoRefresh ? `${countdown}s` : "Paused"}
              </span>
            </button>
            <button
              onClick={fetchData}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg glass hover:bg-white/[0.08] transition-all text-xs text-muted-foreground hover:text-foreground"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Refresh
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3 animate-fade-in-up stagger-1">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" />
            <input
              type="text"
              placeholder="Search symbol…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 pr-4 py-2 glass rounded-xl text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-cyan-500/30 transition-all w-44 focus:w-56"
            />
          </div>

          {/* Direction filter */}
          <Select
            value={directionFilter}
            onValueChange={(v) => setDirectionFilter(v ?? "")}
          >
            <SelectTrigger className="w-36">
              <SelectValue placeholder="All Directions" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">All Directions</SelectItem>
              <SelectItem value="BUY">Buy</SelectItem>
              <SelectItem value="SELL">Sell</SelectItem>
            </SelectContent>
          </Select>

          {/* Source filter */}
          <Select
            value={sourceFilter}
            onValueChange={(v) => setSourceFilter(v ?? "")}
          >
            <SelectTrigger className="w-36">
              <SelectValue placeholder="All Sources" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">All Sources</SelectItem>
              <SelectItem value="volume">Volume</SelectItem>
              <SelectItem value="marketcap">Mkt Cap</SelectItem>
              <SelectItem value="both">Both</SelectItem>
            </SelectContent>
          </Select>

          {/* Clear filters */}
          {(search || directionFilter || sourceFilter) && (
            <button
              onClick={() => { setSearch(""); setDirectionFilter(""); setSourceFilter(""); }}
              className="px-3 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors rounded-lg glass"
            >
              Clear filters
            </button>
          )}
        </div>

        {/* Signals Cards */}
        {filtered.length === 0 ? (
          <div className="glass rounded-2xl animate-fade-in-up stagger-2">
            <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
              <Zap className="w-10 h-10 mb-3 opacity-20" />
              <p className="text-sm font-medium">No signals found</p>
              <p className="text-xs mt-1 opacity-60">
                Try adjusting your filters
              </p>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 animate-fade-in-up stagger-2">
            {filtered.map((sig, idx) => {
              const isBuy = sig.direction === "BUY";
              const src = SOURCE_META[sig.source] ?? {
                label: sig.source,
                color: "text-muted-foreground",
                bg: "bg-white/5 border-white/10",
              };
              const k = klines[sig.symbol];
              const current = k?.current;
              // P&L vs entry: BUY profits when price rises, SELL when it falls.
              const pnlPct =
                current != null
                  ? (sig.direction === "BUY"
                      ? (current - sig.price) / sig.price
                      : (sig.price - current) / sig.price) * 100
                  : null;
              const inProfit = (pnlPct ?? 0) >= 0;
              const pnlColor =
                pnlPct == null
                  ? "text-muted-foreground"
                  : inProfit
                    ? "text-emerald-400"
                    : "text-red-400";
              return (
                <div
                  key={sig.id}
                  className="glass glass-hover rounded-2xl p-5 relative overflow-hidden animate-fade-in-up"
                  style={{ animationDelay: `${Math.min(idx, 15) * 30}ms` }}
                >
                  {/* Direction accent */}
                  <div
                    className={`absolute top-0 left-0 right-0 h-[3px] ${
                      isBuy
                        ? "bg-gradient-to-r from-emerald-400/70 via-emerald-400/20 to-transparent"
                        : "bg-gradient-to-r from-red-400/70 via-red-400/20 to-transparent"
                    }`}
                  />

                  {/* Card header: symbol + direction/interval */}
                  <div className="flex items-center justify-between gap-2 mb-4">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div
                        className={`w-8 h-8 rounded-xl flex items-center justify-center shrink-0 ${
                          isBuy
                            ? "bg-emerald-500/10 border border-emerald-500/20"
                            : "bg-red-500/10 border border-red-500/20"
                        }`}
                      >
                        {isBuy ? (
                          <ArrowUpRight className="w-4 h-4 text-emerald-400" />
                        ) : (
                          <ArrowDownRight className="w-4 h-4 text-red-400" />
                        )}
                      </div>
                      <span className="font-semibold text-foreground truncate">
                        {sig.symbol}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <Badge
                        variant="outline"
                        className={`text-[10px] font-bold ${
                          isBuy
                            ? "border-emerald-500/30 text-emerald-400 bg-emerald-500/5"
                            : "border-red-500/30 text-red-400 bg-red-500/5"
                        }`}
                      >
                        {isBuy ? "BUY" : "SELL"}
                      </Badge>
                      {sig.quality && (
                        <Badge
                          variant="outline"
                          title={sig.quality_reason}
                          className={`text-[10px] font-bold ${
                            sig.quality === "A"
                              ? "border-cyan-500/30 text-cyan-400 bg-cyan-500/5"
                              : sig.quality === "B"
                              ? "border-emerald-500/30 text-emerald-400 bg-emerald-500/5"
                              : sig.quality === "D"
                              ? "border-red-500/30 text-red-400 bg-red-500/5"
                              : "border-white/10 text-muted-foreground"
                          }`}
                        >
                          {sig.quality}
                        </Badge>
                      )}
                      <Badge
                        variant="outline"
                        className="text-[10px] border-white/10 text-muted-foreground"
                      >
                        {sig.interval.toUpperCase()}
                      </Badge>
                    </div>
                  </div>

                  {/* Price sparkline: green when in profit, red when in loss */}
                  <div className="flex items-center gap-3 mb-3.5">
                    <div className="flex-1 h-10 min-w-0">
                      {k ? (
                        <Sparkline
                          closes={k.closes}
                          entry={sig.price}
                          positive={inProfit}
                          className="w-full h-full"
                        />
                      ) : klinesReady ? (
                        <div className="h-full w-full rounded-xl bg-white/[0.02] border border-white/[0.04]" />
                      ) : (
                        <div className="h-full w-full rounded-xl bg-white/[0.03] animate-pulse" />
                      )}
                    </div>
                    <div className="text-right shrink-0 w-20">
                      <p className={`font-mono text-sm font-semibold ${pnlColor}`}>
                        {current != null ? formatPrice(current) : "—"}
                      </p>
                      <p className={`text-[11px] font-mono ${pnlColor} ${pnlPct == null ? "opacity-0" : ""}`}>
                        {pnlPct != null
                          ? `${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(2)}%`
                          : "0.00%"}
                      </p>
                    </div>
                  </div>

                  {/* Main metrics: Entry / SL / Risk */}
                  <div className="grid grid-cols-3 gap-2 mb-3.5">
                    <div className="rounded-xl bg-white/[0.03] border border-white/[0.05] px-3 py-2.5 min-w-0">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">
                        Entry
                      </p>
                      <p className="font-mono text-sm font-semibold text-foreground truncate">
                        {formatPrice(sig.price)}
                      </p>
                    </div>
                    <div className="rounded-xl bg-white/[0.03] border border-white/[0.05] px-3 py-2.5 min-w-0">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">
                        SL
                      </p>
                      <p className="font-mono text-sm font-semibold text-red-400/80 truncate">
                        {/* Initial Stop for 4H trend-ride, legacy SL for older rows */}
                        {formatPrice(sig.sl ?? sig.initial_stop ?? 0)}
                      </p>
                    </div>
                    <div className="rounded-xl bg-white/[0.03] border border-white/[0.05] px-3 py-2.5 min-w-0">
                      <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-0.5">
                        Risk %
                      </p>
                      <p className="font-mono text-sm font-semibold text-cyan-400 truncate">
                        {sig.risk_pct != null
                          ? `${sig.risk_pct.toFixed(1)}%`
                          : sig.risk_level ?? "—"}
                      </p>
                    </div>
                  </div>

                  {/* Secondary metrics: ATR / EMA200 */}
                  <div className="flex items-center justify-between gap-2 text-xs mb-3">
                    <span className="font-mono text-muted-foreground">
                      ATR%{" "}
                      <span className="text-foreground/80">
                        {sig.atr_pct.toFixed(2)}%
                      </span>
                    </span>
                    <span className="font-mono text-muted-foreground truncate">
                      EMA{" "}
                      <span className="text-foreground/80">
                        {formatPrice(sig.ema200 ?? 0)}
                      </span>
                    </span>
                  </div>

                  {/* Card footer: detected + source */}
                  <div className="flex items-center justify-between gap-2 pt-3 border-t border-white/[0.06]">
                    <span className="text-[11px] text-muted-foreground flex items-center gap-1.5 min-w-0">
                      <Clock className="w-3 h-3 shrink-0" />
                      <span className="truncate">
                        {formatTimestamp(sig.detected_at)}
                      </span>
                    </span>
                    <Badge
                      variant="outline"
                      className={`text-[10px] shrink-0 ${src.color} ${src.bg}`}
                    >
                      {src.label}
                    </Badge>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Footer info */}
        <p className="text-center text-xs text-muted-foreground">
          Showing {filtered.length} of {signals.length} signals
        </p>
      </div>
    </DashboardLayout>
  );
}