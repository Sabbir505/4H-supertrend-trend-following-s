"use client";

import { useState, useEffect, useCallback } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
  Search,
  TrendingUp,
} from "lucide-react";
import { getSignals, Signal } from "@/lib/api";
import { formatPrice, formatTimestamp } from "@/lib/utils";

const DIRECTION_OPTIONS = ["", "BUY", "SELL"] as const;
const SOURCE_OPTIONS = ["", "volume", "volatility", "both"] as const;

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
      setError(
        err instanceof Error ? err.message : "Failed to fetch signals"
      );
    } finally {
      setLoading(false);
    }
  }, [directionFilter]);

  // Initial fetch
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
          setError(
            err instanceof Error ? err.message : "Failed to fetch signals"
          );
          setLoading(false);
        }
      }
    }
    init();
    return () => {
      cancelled = true;
    };
  }, [directionFilter]);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;
    let fetching = false;
    const refreshCycle = async () => {
      if (fetching) return;
      fetching = true;
      await fetchData();
      setCountdown(30);
      fetching = false;
    };
    const interval = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          refreshCycle();
          return 30;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchData]);

  const filtered = signals.filter((sig) => {
    if (search && !sig.symbol.toLowerCase().includes(search.toLowerCase()))
      return false;
    if (sourceFilter && sig.source !== sourceFilter) return false;
    return true;
  });

  if (loading) {
    return (
      <DashboardLayout>
        <div className="space-y-6 animate-pulse">
          <div className="h-8 w-48 bg-muted rounded-lg" />
          <div className="h-64 bg-muted rounded-xl" />
        </div>
      </DashboardLayout>
    );
  }

  if (error) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center h-64">
          <div className="text-destructive">Error: {error}</div>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">
              Supertrend Signals
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Supertrend 12/3.5 + 200 EMA + RSI(14) — 4H — {filtered.length} total
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {/* Auto-refresh toggle */}
            <button
              onClick={() => setAutoRefresh(!autoRefresh)}
              className="flex items-center gap-2"
            >
              <span className="text-sm text-muted-foreground">Auto-refresh</span>
              <div
                className={`w-10 h-5 rounded-full relative cursor-pointer transition-colors ${
                  autoRefresh ? "bg-blue-500" : "bg-slate-600"
                }`}
              >
                <div
                  className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-all ${
                    autoRefresh ? "right-0.5" : "left-0.5"
                  }`}
                />
              </div>
            </button>
            {autoRefresh && (
              <span className="text-sm text-muted-foreground">{countdown}s</span>
            )}
            <button
              onClick={fetchData}
              className="flex items-center gap-2 px-3 py-2 bg-muted border border-border rounded-full text-sm text-foreground hover:bg-accent transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              Refresh
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search symbol..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 pr-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>
          <select
            value={directionFilter}
            onChange={(e) => setDirectionFilter(e.target.value)}
            className="px-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
          >
            <option value="">All Directions</option>
            {DIRECTION_OPTIONS.filter(Boolean).map((d) => (
              <option key={d} value={d}>
                {d === "BUY" ? "Buy" : "Sell"}
              </option>
            ))}
          </select>
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value)}
            className="px-3 py-2 bg-muted border border-border rounded-lg text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/20"
          >
            <option value="">All Sources</option>
            {SOURCE_OPTIONS.filter(Boolean).map((s) => (
              <option key={s} value={s}>
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </option>
            ))}
          </select>
        </div>

        {/* Table */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Signals</CardTitle>
          </CardHeader>
          <CardContent>
            {filtered.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-muted-foreground">
                No signals found
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left py-3 px-2 text-xs font-medium text-muted-foreground uppercase">
                        Symbol
                      </th>
                      <th className="text-left py-3 px-2 text-xs font-medium text-muted-foreground uppercase">
                        Direction
                      </th>
                      <th className="text-right py-3 px-2 text-xs font-medium text-muted-foreground uppercase">
                        Entry
                      </th>
                      <th className="text-right py-3 px-2 text-xs font-medium text-muted-foreground uppercase">
                        SL
                      </th>
                      <th className="text-right py-3 px-2 text-xs font-medium text-muted-foreground uppercase">
                        TP
                      </th>
                      <th className="text-right py-3 px-2 text-xs font-medium text-muted-foreground uppercase">
                        RSI
                      </th>
                      <th className="text-right py-3 px-2 text-xs font-medium text-muted-foreground uppercase">
                        ATR%
                      </th>
                      <th className="text-right py-3 px-2 text-xs font-medium text-muted-foreground uppercase">
                        EMA200
                      </th>
                      <th className="text-right py-3 px-2 text-xs font-medium text-muted-foreground uppercase">
                        Supertrend
                      </th>
                      <th className="text-center py-3 px-2 text-xs font-medium text-muted-foreground uppercase">
                        Interval
                      </th>
                      <th className="text-center py-3 px-2 text-xs font-medium text-muted-foreground uppercase">
                        Source
                      </th>
                      <th className="text-right py-3 px-2 text-xs font-medium text-muted-foreground uppercase">
                        Detected
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((sig) => {
                      const isBuy = sig.direction === "BUY";
                      return (
                        <tr
                          key={sig.id}
                          className="border-b border-border/50 hover:bg-muted/30 transition-colors"
                        >
                          <td className="py-3 px-2">
                            <div className="flex items-center gap-2">
                              {isBuy ? (
                                <ArrowUpRight className="w-3.5 h-3.5 text-chart-1" />
                              ) : (
                                <ArrowDownRight className="w-3.5 h-3.5 text-chart-4" />
                              )}
                              <span className="font-medium text-foreground">
                                {sig.symbol}
                              </span>
                            </div>
                          </td>
                          <td className="py-3 px-2">
                            <Badge
                              variant="outline"
                              className={`text-[10px] ${
                                isBuy
                                  ? "border-emerald-500/30 text-emerald-400"
                                  : "border-red-500/30 text-red-400"
                              }`}
                            >
                              {isBuy ? "Buy" : "Sell"}
                            </Badge>
                          </td>
                          <td className="py-3 px-2 text-right font-mono text-foreground">
                            {formatPrice(sig.price)}
                          </td>
                          <td className="py-3 px-2 text-right font-mono text-red-400/80">
                            {formatPrice(sig.sl)}
                          </td>
                          <td className="py-3 px-2 text-right font-mono text-emerald-400/80">
                            {formatPrice(sig.tp)}
                          </td>
                          <td className="py-3 px-2 text-right font-mono text-muted-foreground">
                            {sig.rsi.toFixed(1)}
                          </td>
                          <td className="py-3 px-2 text-right font-mono text-muted-foreground">
                            {sig.atr_pct.toFixed(2)}
                          </td>
                          <td className="py-3 px-2 text-right font-mono text-muted-foreground">
                            {formatPrice(sig.ema200)}
                          </td>
                          <td className="py-3 px-2 text-right font-mono text-muted-foreground">
                            {formatPrice(sig.supertrend_value)}
                          </td>
                          <td className="py-3 px-2 text-center">
                            <Badge
                              variant="outline"
                              className="text-[10px] border-slate-500/30 text-slate-400"
                            >
                              {sig.interval.toUpperCase()}
                            </Badge>
                          </td>
                          <td className="py-3 px-2 text-center">
                            <Badge
                              variant="outline"
                              className={`text-[10px] ${
                                sig.source === "both"
                                  ? "border-purple-500/30 text-purple-400"
                                  : sig.source === "volatility"
                                  ? "border-amber-500/30 text-amber-400"
                                  : "border-blue-500/30 text-blue-400"
                              }`}
                            >
                              {sig.source}
                            </Badge>
                          </td>
                          <td className="py-3 px-2 text-right text-muted-foreground text-xs">
                            {formatTimestamp(sig.detected_at)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </DashboardLayout>
  );
}
