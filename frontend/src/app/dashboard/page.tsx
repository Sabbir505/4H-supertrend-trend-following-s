"use client";

import { useState, useEffect, useMemo } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import { Badge } from "@/components/ui/badge";
import {
  Activity,
  TrendingUp,
  TrendingDown,
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
  Clock,
  BarChart3,
  PieChart,
  TrendingUpIcon,
  Zap,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart as RePieChart,
  Pie,
  Cell,
} from "recharts";
import {
  getDashboardStats,
  getRecentSignals,
  getScannerStatus,
  DashboardStats,
  Signal,
  ScannerStatus,
} from "@/lib/api";
import { formatPrice, formatTimestamp } from "@/lib/utils";

function timeAgo(iso: string, now: Date): string {
  const diff = Math.floor((now.getTime() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recentSignals, setRecentSignals] = useState<Signal[]>([]);
  const [scannerStatus, setScannerStatus] = useState<ScannerStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [now, setNow] = useState<Date>(new Date());

  useEffect(() => {
    let isFetching = false;

    async function fetchData() {
      if (isFetching) return;
      isFetching = true;

      try {
        const [dashStats, recent, scanStatus] = await Promise.all([
          getDashboardStats(),
          getRecentSignals(),
          getScannerStatus().catch(() => null),
        ]);
        setStats(dashStats);
        setRecentSignals(recent);
        setScannerStatus(scanStatus);
        setLastUpdated(new Date());
        setError(null);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to fetch dashboard data"
        );
      } finally {
        setLoading(false);
        isFetching = false;
      }
    }

    fetchData();
    const interval = setInterval(() => {
      if (autoRefresh) fetchData();
    }, 30000);
    return () => clearInterval(interval);
  }, [autoRefresh]);

  useEffect(() => {
    const tick = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(tick);
  }, []);

  const directionData = useMemo(() => {
    const buy = stats?.buy_count ?? 0;
    const sell = stats?.sell_count ?? 0;
    if (buy === 0 && sell === 0) return [];
    return [
      { name: "Buy Signals", value: buy, color: "#10b981" },
      { name: "Sell Signals", value: sell, color: "#ef4444" },
    ];
  }, [stats]);

  const hourlyData = useMemo(() => {
    const counts: Record<string, number> = {};
    recentSignals.forEach((sig) => {
      try {
        const date = new Date(sig.detected_at);
        const hour = date.toLocaleTimeString("en-US", {
          hour: "2-digit",
          minute: "2-digit",
        });
        counts[hour] = (counts[hour] || 0) + 1;
      } catch {
        // skip
      }
    });
    return Object.entries(counts)
      .map(([hour, count]) => ({ hour, count }))
      .sort((a, b) => a.hour.localeCompare(b.hour));
  }, [recentSignals]);

  const tooltipStyle = {
    backgroundColor: "rgba(10, 15, 35, 0.9)",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    borderRadius: "12px",
    color: "#e2e8f0",
    backdropFilter: "blur(12px)",
    boxShadow: "0 8px 24px rgba(0,0,0,0.3)",
  };

  const statCards = [
    {
      label: "Total Signals",
      icon: Activity,
      accent: "accent-neutral",
      value: stats?.total_signals ?? 0,
      sub: "All time",
      delay: "stagger-1",
    },
    {
      label: "Last 24 Hours",
      icon: Clock,
      accent: "accent-neutral",
      value: stats?.signals_24h ?? 0,
      sub: "Signals detected",
      delay: "stagger-2",
    },
    {
      label: "Buy Signals",
      icon: TrendingUp,
      accent: "accent-buy",
      value: stats?.buy_count ?? 0,
      sub: "Bullish setups",
      delay: "stagger-3",
    },
    {
      label: "Sell Signals",
      icon: TrendingDown,
      accent: "accent-sell",
      value: stats?.sell_count ?? 0,
      sub: "Bearish setups",
      delay: "stagger-4",
    },
  ];

  if (loading) {
    return (
      <DashboardLayout>
        <div className="space-y-6 animate-pulse">
          <div className="h-9 w-52 bg-white/5 rounded-xl" />
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div
                key={i}
                className="glass rounded-2xl p-5 h-28"
              />
            ))}
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="glass rounded-2xl h-72" />
            <div className="glass rounded-2xl h-72" />
          </div>
          <div className="glass rounded-2xl h-64" />
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
        <div
          className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 animate-fade-in-up"
        >
          <div>
            <h1 className="text-2xl font-bold text-foreground">
              Dashboard
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              Supertrend 10/3.5 trend-ride · EMA200 longs · BTC-regime shorts · 4H
            </p>
          </div>
          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span className="text-xs text-muted-foreground hidden sm:block">
                Updated {lastUpdated.toLocaleTimeString()}
              </span>
            )}
            {/* Last Run box */}
            <div className="glass rounded-xl px-3 py-2 hidden md:flex items-center gap-3">
              <div className="flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5 text-cyan-400" />
                <span className="text-[10px] uppercase tracking-wider font-semibold text-muted-foreground">
                  Last Run
                </span>
              </div>
              <div className="flex items-center gap-3 text-xs">
                <div>
                  <span className="text-muted-foreground">4H </span>
                  <span className="font-mono font-semibold text-foreground">
                    {scannerStatus?.scan_4h ? timeAgo(scannerStatus.scan_4h, now) : "—"}
                  </span>
                </div>
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
                {autoRefresh ? "Live" : "Paused"}
              </span>
            </button>
            <button
              onClick={() => window.location.reload()}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg glass hover:bg-white/[0.08] transition-all text-xs text-muted-foreground hover:text-foreground"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Refresh
            </button>
          </div>
        </div>

        {/* Stat Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {statCards.map((card) => {
            const Icon = card.icon;
            return (
              <div
                key={card.label}
                className={`glass rounded-2xl p-5 animate-fade-in-up opacity-0 ${card.delay}`}
              >
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <div className="w-8 h-8 rounded-xl bg-white/[0.06] flex items-center justify-center">
                      <Icon className="w-4 h-4 text-muted-foreground" />
                    </div>
                    <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium">
                      {card.label}
                    </p>
                  </div>
                </div>
                <p className="text-3xl font-bold text-foreground mb-1">
                  {card.value.toLocaleString()}
                </p>
                <p className="text-xs text-muted-foreground">{card.sub}</p>
                {/* Subtle bottom glow bar */}
                <div
                  className={`mt-3 h-0.5 rounded-full ${
                    card.accent === "accent-buy"
                      ? "bg-gradient-to-r from-emerald-500/40 to-transparent"
                      : card.accent === "accent-sell"
                      ? "bg-gradient-to-r from-red-500/40 to-transparent"
                      : "bg-gradient-to-r from-cyan-500/40 to-transparent"
                  }`}
                />
              </div>
            );
          })}
        </div>

        {/* Charts Row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Signals Over Time */}
          <div className="glass rounded-2xl p-5 animate-fade-in-up opacity-0 stagger-5">
            <div className="flex items-center gap-2 mb-4">
              <BarChart3 className="w-4 h-4 text-muted-foreground" />
              <h3 className="text-sm font-semibold text-foreground">
                Signals — Last 24 Hours
              </h3>
            </div>
            {hourlyData.length === 0 ? (
              <div className="flex items-center justify-center h-48 text-muted-foreground text-sm">
                No signals in the last 24 hours
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={hourlyData} barCategoryGap="30%">
                  <defs>
                    <linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#06b6d4" stopOpacity={0.8} />
                      <stop offset="100%" stopColor="#06b6d4" stopOpacity={0.3} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="rgba(255,255,255,0.04)"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="hour"
                    stroke="rgba(255,255,255,0.3)"
                    fontSize={11}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    stroke="rgba(255,255,255,0.3)"
                    fontSize={11}
                    allowDecimals={false}
                    tickLine={false}
                    axisLine={false}
                    width={28}
                  />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    formatter={(value) => [value, "Signals"]}
                    cursor={{ fill: "rgba(255,255,255,0.03)" }}
                  />
                  <Bar dataKey="count" fill="url(#barGrad)" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Buy vs Sell Distribution */}
          <div className="glass rounded-2xl p-5 animate-fade-in-up opacity-0 stagger-6">
            <div className="flex items-center gap-2 mb-4">
              <PieChart className="w-4 h-4 text-muted-foreground" />
              <h3 className="text-sm font-semibold text-foreground">
                Buy vs Sell Distribution
              </h3>
            </div>
            {directionData.length === 0 ? (
              <div className="flex items-center justify-center h-48 text-muted-foreground text-sm">
                No data yet
              </div>
            ) : (
              <div className="flex items-center gap-4">
                <ResponsiveContainer width="50%" height={180}>
                  <RePieChart>
                    <Pie
                      data={directionData}
                      cx="50%"
                      cy="50%"
                      innerRadius={48}
                      outerRadius={78}
                      paddingAngle={4}
                      dataKey="value"
                      stroke="none"
                    >
                      {directionData.map((entry, i) => (
                        <Cell
                          key={i}
                          fill={entry.color}
                          style={{
                            filter: `drop-shadow(0 0 8px ${entry.color}50)`,
                          }}
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={tooltipStyle}
                      formatter={(value) => [`${value} signals`, ""]}
                    />
                  </RePieChart>
                </ResponsiveContainer>
                <div className="flex-1 space-y-3">
                  {directionData.map((d) => {
                    const total = directionData.reduce(
                      (sum, x) => sum + x.value,
                      0
                    );
                    const pct =
                      total > 0 ? ((d.value / total) * 100).toFixed(1) : "0.0";
                    return (
                      <div key={d.name}>
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <div
                              className="w-2.5 h-2.5 rounded-full"
                              style={{ backgroundColor: d.color }}
                            />
                            <span className="text-xs text-muted-foreground">
                              {d.name}
                            </span>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="text-sm font-bold text-foreground">
                              {d.value}
                            </span>
                            <span className="text-xs text-muted-foreground w-10 text-right">
                              {pct}%
                            </span>
                          </div>
                        </div>
                        {/* Progress bar */}
                        <div className="h-1 rounded-full bg-white/[0.06] overflow-hidden">
                          <div
                            className="h-full rounded-full transition-all duration-700"
                            style={{
                              width: `${pct}%`,
                              backgroundColor: d.color,
                              boxShadow: `0 0 8px ${d.color}60`,
                            }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Recent Signals */}
        <div className="glass rounded-2xl animate-fade-in-up opacity-0 stagger-6">
          <div className="px-5 pt-5 pb-3 border-b border-white/[0.06]">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <TrendingUpIcon className="w-4 h-4 text-muted-foreground" />
                <h3 className="text-sm font-semibold text-foreground">
                  Recent Signals
                </h3>
              </div>
              <Badge
                variant="outline"
                className="text-[10px] border-white/10 text-muted-foreground"
              >
                {recentSignals.length} total
              </Badge>
            </div>
          </div>
          <div className="p-5">
            {recentSignals.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 text-muted-foreground">
                <Activity className="w-8 h-8 mb-2 opacity-30" />
                <p className="text-sm">No recent signals detected</p>
              </div>
            ) : (
              <div className="space-y-1">
                {recentSignals.slice(0, 12).map((sig) => {
                  const isBuy = sig.direction === "BUY";
                  return (
                    <div
                      key={sig.id}
                      className="glass-table-row flex items-center justify-between px-4 py-3 rounded-xl"
                    >
                      <div className="flex items-center gap-3">
                        <div
                          className={`w-8 h-8 rounded-xl flex items-center justify-center ${
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
                        <div>
                          <p className="text-sm font-semibold text-foreground">
                            {sig.symbol}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {formatTimestamp(sig.detected_at)}
                          </p>
                        </div>
                      </div>

                      {/* Price info */}
                      <div className="hidden sm:flex items-center gap-6">
                        <div className="text-right">
                          <p className="text-xs text-muted-foreground">Entry</p>
                          <p className="text-sm font-mono font-semibold text-foreground">
                            {formatPrice(sig.price)}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="text-xs text-muted-foreground">SL</p>
                          <p className="text-sm font-mono text-red-400/80">
                            {formatPrice(sig.sl ?? sig.initial_stop ?? 0)}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="text-xs text-muted-foreground">Risk</p>
                          <p className="text-sm font-mono text-cyan-400 font-semibold">
                            {sig.risk_pct != null
                              ? `${sig.risk_pct.toFixed(1)}%`
                              : sig.risk_level ?? "—"}
                          </p>
                        </div>
                        <div className="text-right">
                          <p className="text-xs text-muted-foreground">ATR%</p>
                          <p className="text-sm font-mono text-muted-foreground">
                            {sig.atr_pct.toFixed(2)}%
                          </p>
                        </div>
                      </div>

                      {/* Badges */}
                      <div className="flex items-center gap-2">
                        <Badge
                          variant="outline"
                          className={`text-[10px] font-semibold ${
                            isBuy
                              ? "border-emerald-500/30 text-emerald-400 bg-emerald-500/5"
                              : "border-red-500/30 text-red-400 bg-red-500/5"
                          }`}
                        >
                          {isBuy ? "BUY" : "SELL"}
                        </Badge>
                        <Badge
                          variant="outline"
                          className="text-[10px] border-white/10 text-muted-foreground"
                        >
                          {sig.interval.toUpperCase()}
                        </Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}