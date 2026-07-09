"use client";

import { useState, useEffect, useMemo } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Activity,
  TrendingUp,
  TrendingDown,
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
  Clock,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import {
  getDashboardStats,
  getRecentSignals,
  DashboardStats,
  Signal,
} from "@/lib/api";
import { formatPrice, formatTimestamp } from "@/lib/utils";

const PIE_COLORS = {
  BUY: "var(--chart-1)",
  SELL: "var(--chart-4)",
};

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recentSignals, setRecentSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    let isFetching = false;

    async function fetchData() {
      if (isFetching) return;
      isFetching = true;

      try {
        const [dashStats, recent] = await Promise.all([
          getDashboardStats(),
          getRecentSignals(),
        ]);
        setStats(dashStats);
        setRecentSignals(recent);
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
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  const directionData = useMemo(() => {
    const buy = stats?.buy_count ?? 0;
    const sell = stats?.sell_count ?? 0;
    const data = [];
    if (buy > 0)
      data.push({ name: "Buy Signals", value: buy, color: PIE_COLORS.BUY });
    if (sell > 0)
      data.push({ name: "Sell Signals", value: sell, color: PIE_COLORS.SELL });
    return data;
  }, [stats]);

  // Hourly signal count for bar chart
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
    backgroundColor: "var(--popover)",
    border: "1px solid var(--border)",
    borderRadius: "8px",
    color: "var(--popover-foreground)",
  };

  if (loading) {
    return (
      <DashboardLayout>
        <div className="space-y-6 animate-pulse">
          <div className="h-8 w-48 bg-muted rounded-lg" />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div
                key={i}
                className="bg-card border border-border rounded-xl p-5 space-y-3"
              >
                <div className="h-3 w-20 bg-muted rounded" />
                <div className="h-7 w-16 bg-muted rounded" />
                <div className="h-3 w-24 bg-muted rounded" />
              </div>
            ))}
          </div>
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

  const statCards = [
    {
      label: "Total Signals",
      icon: Activity,
      iconColor: "text-chart-2",
      value: stats?.total_signals ?? 0,
      sub: "All time",
    },
    {
      label: "Last 24h",
      icon: Clock,
      iconColor: "text-chart-5",
      value: stats?.signals_24h ?? 0,
      sub: "Signals detected",
    },
    {
      label: "Buy Signals",
      icon: TrendingUp,
      iconColor: "text-chart-1",
      value: stats?.buy_count ?? 0,
      sub: "Bullish",
    },
    {
      label: "Sell Signals",
      icon: TrendingDown,
      iconColor: "text-chart-4",
      value: stats?.sell_count ?? 0,
      sub: "Bearish",
    },
  ];

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">
              Dashboard
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Supertrend 12/3.5 + 200 EMA + RSI(14) — 4H
            </p>
          </div>
          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span className="text-xs text-muted-foreground">
                Updated: {lastUpdated.toLocaleTimeString()}
              </span>
            )}
            <button
              onClick={() => window.location.reload()}
              className="inline-flex items-center gap-1.5 text-xs text-primary hover:text-primary/80 transition-colors"
            >
              <RefreshCw className="w-3 h-3" />
              Refresh
            </button>
          </div>
        </div>

        {/* Stat Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {statCards.map((card) => {
            const Icon = card.icon;
            return (
              <Card key={card.label}>
                <CardContent className="p-5">
                  <div className="flex items-center gap-2">
                    <Icon className={`w-4 h-4 ${card.iconColor}`} />
                    <p className="text-xs text-muted-foreground uppercase tracking-wide">
                      {card.label}
                    </p>
                  </div>
                  <p className="text-2xl font-bold mt-2 text-foreground">
                    {card.value}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {card.sub}
                  </p>
                </CardContent>
              </Card>
            );
          })}
        </div>

        {/* Charts Row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Hourly Activity */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Signals (Last 24h)</CardTitle>
            </CardHeader>
            <CardContent>
              {hourlyData.length === 0 ? (
                <div className="flex items-center justify-center h-48 text-muted-foreground">
                  No signals in the last 24 hours
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={220} minHeight={200}>
                  <BarChart data={hourlyData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                    <XAxis
                      dataKey="hour"
                      stroke="var(--muted-foreground)"
                      fontSize={11}
                    />
                    <YAxis
                      stroke="var(--muted-foreground)"
                      fontSize={11}
                      allowDecimals={false}
                    />
                    <Tooltip
                      contentStyle={tooltipStyle}
                      formatter={(value) => [value, "Signals"]}
                    />
                    <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                      {hourlyData.map((_, i) => (
                        <Cell key={i} fill="var(--chart-1)" />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Direction Distribution */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Buy vs Sell Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              {directionData.length === 0 ? (
                <div className="flex items-center justify-center h-48 text-muted-foreground">
                  No data yet
                </div>
              ) : (
                <>
                  <ResponsiveContainer width="100%" height={180} minHeight={150}>
                    <PieChart>
                      <Pie
                        data={directionData}
                        cx="50%"
                        cy="50%"
                        innerRadius={45}
                        outerRadius={75}
                        paddingAngle={3}
                        dataKey="value"
                      >
                        {directionData.map((entry, i) => (
                          <Cell key={i} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={tooltipStyle}
                        formatter={(value) => [`${value} signals`, ""]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="space-y-1.5 mt-2">
                    {directionData.map((d) => {
                      const total = directionData.reduce(
                        (sum, x) => sum + x.value,
                        0
                      );
                      const pct =
                        total > 0 ? ((d.value / total) * 100).toFixed(1) : "0.0";
                      return (
                        <div
                          key={d.name}
                          className="flex items-center justify-between"
                        >
                          <div className="flex items-center gap-2">
                            <div
                              className="w-2.5 h-2.5 rounded-full"
                              style={{ backgroundColor: d.color }}
                            />
                            <span className="text-xs text-muted-foreground">
                              {d.name}
                            </span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium text-foreground">
                              {d.value}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {pct}%
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Recent Signals */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Recent Signals</CardTitle>
          </CardHeader>
          <CardContent>
            {recentSignals.length === 0 ? (
              <div className="flex items-center justify-center h-32 text-muted-foreground">
                No recent signals
              </div>
            ) : (
              <div className="space-y-2">
                {recentSignals.slice(0, 10).map((sig) => {
                  const isBuy = sig.direction === "BUY";
                  return (
                    <div
                      key={sig.id}
                      className="flex items-center justify-between py-2 border-b border-border/50 last:border-0"
                    >
                      <div className="flex items-center gap-2">
                        {isBuy ? (
                          <ArrowUpRight className="w-4 h-4 text-chart-1" />
                        ) : (
                          <ArrowDownRight className="w-4 h-4 text-chart-4" />
                        )}
                        <div>
                          <p className="text-sm font-medium text-foreground">
                            {sig.symbol}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {formatTimestamp(sig.detected_at)}
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        <div className="text-right">
                          <p className="text-sm font-bold text-foreground">
                            {formatPrice(sig.price)}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            SL: {formatPrice(sig.sl)} | TP: {formatPrice(sig.tp)} | RSI: {sig.rsi.toFixed(1)}
                          </p>
                        </div>
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
                        <Badge
                          variant="outline"
                          className="text-[10px] border-slate-500/30 text-slate-400"
                        >
                          {sig.interval.toUpperCase()}
                        </Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </DashboardLayout>
  );
}
