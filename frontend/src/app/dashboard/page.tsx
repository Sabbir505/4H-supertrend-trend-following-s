"use client";

import { useState, useEffect, useMemo } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Target,
  BarChart3,
  Zap,
  Clock,
  ArrowUpRight,
  ArrowDownRight,
  RefreshCw,
} from "lucide-react";
import {
  AreaChart,
  Area,
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
  getOpenSignals,
  getClosedSignals,
  DashboardStats,
  Signal,
} from "@/lib/api";
import { calculateRR, formatPrice } from "@/lib/utils";

const outcomeColors: Record<string, string> = {
  Loss: "var(--chart-4)",
  Expired: "var(--chart-5)",
  Breakeven: "var(--chart-3)",
  Win: "var(--chart-1)",
};

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [openSignals, setOpenSignals] = useState<Signal[]>([]);
  const [closedSignals, setClosedSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    let isFetching = false;

    async function fetchData() {
      if (isFetching) return;
      isFetching = true;

      try {
        const [dashStats, open, closed] = await Promise.all([
          getDashboardStats(),
          getOpenSignals(),
          getClosedSignals(),
        ]);
        setStats(dashStats);
        setOpenSignals(open);
        setClosedSignals(closed);
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

  const outcomeData = useMemo(() => {
    let loss = 0;
    let expired = 0;
    let breakeven = 0;
    let win = 0;
    closedSignals.forEach((s) => {
      if (s.status === "SL") loss++;
      else if (s.status === "EXPIRED") expired++;
      else if (s.status === "BREAKEVEN") breakeven++;
      else if (["TP1", "TP2", "TP3", "TP4", "WIN"].includes(s.status)) win++;
    });
    const data = [];
    if (loss > 0) data.push({ name: "Loss", value: loss, color: outcomeColors.Loss });
    if (expired > 0) data.push({ name: "Expired", value: expired, color: outcomeColors.Expired });
    if (breakeven > 0) data.push({ name: "Breakeven", value: breakeven, color: outcomeColors.Breakeven });
    if (win > 0) data.push({ name: "Win", value: win, color: outcomeColors.Win });
    return data;
  }, [closedSignals]);

  const equityDataWithCumulative = useMemo(() => {
    const sortedClosed = [...closedSignals]
      .filter((s) => s.fired_at || s.closed_at)
      .sort((a, b) => {
        const dateA = a.closed_at || a.fired_at;
        const dateB = b.closed_at || b.fired_at;
        if (!dateA || !dateB) return 0;
        return new Date(dateA).getTime() - new Date(dateB).getTime();
      });
    const equityData = sortedClosed.map((s, index) => {
      const rr = calculateRR(s);
      const date = s.closed_at || s.fired_at;
      const tradeDate = date ? new Date(date) : new Date();
      return {
        date: tradeDate.toLocaleDateString("en-US", {
          month: "short",
          day: "numeric",
        }),
        time: tradeDate.toLocaleTimeString("en-US", {
          hour: "2-digit",
          minute: "2-digit",
        }),
        rr: parseFloat(rr.toFixed(2)),
        symbol: s.symbol,
        index: index + 1,
        status: s.status,
        tradeRR: rr,
      };
    });
    return equityData.reduce<{
      result: typeof equityData;
      runningTotal: number;
    }>(
      (acc, item) => {
        acc.runningTotal += item.tradeRR;
        acc.result.push({
          ...item,
          rr: parseFloat(acc.runningTotal.toFixed(2)),
        });
        return acc;
      },
      { result: [], runningTotal: 0 }
    ).result;
  }, [closedSignals]);

  if (loading) {
    return (
      <DashboardLayout>
        <div className="space-y-6 animate-pulse">
          <div className="h-8 w-48 bg-muted rounded-lg" />
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            {[...Array(5)].map((_, i) => (
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
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 bg-card border border-border rounded-xl p-5">
              <div className="h-4 w-40 bg-muted rounded mb-4" />
              <div className="h-64 bg-muted/50 rounded" />
            </div>
            <div className="bg-card border border-border rounded-xl p-5">
              <div className="h-4 w-36 bg-muted rounded mb-4" />
              <div className="h-48 bg-muted/50 rounded" />
            </div>
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

  const symbolStats: Record<
    string,
    { total: number; wins: number; losses: number }
  > = {};
  closedSignals.forEach((s) => {
    if (!symbolStats[s.symbol])
      symbolStats[s.symbol] = { total: 0, wins: 0, losses: 0 };
    symbolStats[s.symbol].total++;
    if (["TP1", "TP2", "TP3", "TP4", "WIN"].includes(s.status))
      symbolStats[s.symbol].wins++;
    if (s.status === "SL") symbolStats[s.symbol].losses++;
  });
  const symbolWinRateData = Object.entries(symbolStats)
    .map(([symbol, data]) => ({
      symbol,
      winRate:
        data.wins + data.losses > 0
          ? parseFloat(
              ((data.wins / (data.wins + data.losses)) * 100).toFixed(1)
            )
          : 0,
      total: data.total,
    }))
    .filter((s) => s.winRate > 0 || s.total >= 3)
    .sort((a, b) => b.winRate - a.winRate)
    .slice(0, 8);

  const recentSignals = [...closedSignals]
    .filter((s) => s.closed_at || s.fired_at)
    .sort((a, b) => {
      const dateA = a.closed_at || a.fired_at;
      const dateB = b.closed_at || b.fired_at;
      if (!dateA || !dateB) return 0;
      return new Date(dateB).getTime() - new Date(dateA).getTime();
    })
    .slice(0, 5);

  const totalRR =
    equityDataWithCumulative.length > 0
      ? equityDataWithCumulative[equityDataWithCumulative.length - 1].rr
      : 0;

  const tooltipStyle = {
    backgroundColor: "var(--popover)",
    border: "1px solid var(--border)",
    borderRadius: "8px",
    color: "var(--popover-foreground)",
  };

  const statCards = [
    {
      label: "Total Signals",
      icon: Activity,
      iconColor: "text-chart-2",
      value: stats?.total_signals ?? 0,
      sub: `${stats?.open_signals ?? 0} open`,
    },
    {
      label: "Win Rate",
      icon: Target,
      iconColor: "text-chart-1",
      value: `${stats?.win_rate?.toFixed(1) ?? "0.0"}%`,
      valueColor:
        (stats?.win_rate ?? 0) >= 50
          ? "text-chart-1"
          : (stats?.win_rate ?? 0) >= 25
          ? "text-chart-3"
          : "text-chart-4",
      sub: "From closed signals",
    },
    {
      label: "Avg Quality",
      icon: BarChart3,
      iconColor: "text-chart-5",
      value: stats?.avg_quality_score?.toFixed(1) ?? "0.0",
      valueColor:
        (stats?.avg_quality_score ?? 0) >= 70 ? "text-chart-1" : "text-chart-3",
      sub: "Quality score average",
    },
    {
      label: "Total RR",
      icon: Zap,
      iconColor: "text-chart-3",
      value: `${totalRR >= 0 ? "+" : ""}${totalRR.toFixed(2)}`,
      valueColor: totalRR >= 0 ? "text-chart-1" : "text-chart-4",
      sub: "Cumulative risk-reward",
    },
    {
      label: "Backtest WR",
      icon: Clock,
      iconColor: "text-chart-2",
      value: `${stats?.overall_backtest_wr?.toFixed(1) ?? "0.0"}%`,
      valueColor:
        (stats?.overall_backtest_wr ?? 0) >= 50
          ? "text-chart-1"
          : "text-muted-foreground",
      sub: `${stats?.total_trades_backtest ?? 0} backtest trades`,
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
              Trading signal overview and performance
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
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
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
                  <p
                    className={`text-2xl font-bold mt-2 ${
                      card.valueColor ?? "text-foreground"
                    }`}
                  >
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
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Equity Curve */}
          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">
                Equity Curve (Cumulative RR)
              </CardTitle>
            </CardHeader>
            <CardContent>
              {equityDataWithCumulative.length === 0 ? (
                <div className="flex items-center justify-center h-64 text-muted-foreground">
                  No closed trades yet
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={280} minHeight={200}>
                  <AreaChart data={equityDataWithCumulative}>
                    <defs>
                      <linearGradient
                        id="equityGrad"
                        x1="0"
                        y1="0"
                        x2="0"
                        y2="1"
                      >
                        <stop
                          offset="0%"
                          stopColor="var(--chart-1)"
                          stopOpacity={0.3}
                        />
                        <stop
                          offset="100%"
                          stopColor="var(--chart-1)"
                          stopOpacity={0}
                        />
                      </linearGradient>
                    </defs>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="var(--border)"
                    />
                    <XAxis
                      dataKey="date"
                      stroke="var(--muted-foreground)"
                      fontSize={11}
                    />
                    <YAxis
                      stroke="var(--muted-foreground)"
                      fontSize={11}
                    />
                    <Tooltip
                      contentStyle={tooltipStyle}
                      formatter={(value, name, props) => {
                        const payload = props?.payload;
                        if (payload) {
                          return [
                            `${payload.rr >= 0 ? "+" : ""}${payload.rr}R (Trade: ${payload.tradeRR >= 0 ? "+" : ""}${payload.tradeRR}R)`,
                            `${payload.symbol} - ${payload.status}`,
                          ];
                        }
                        return [value, name];
                      }}
                      labelFormatter={(label, payload) => {
                        if (payload && payload[0]) {
                          return `${payload[0].payload.date} ${payload[0].payload.time}`;
                        }
                        return label;
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="rr"
                      stroke="var(--chart-1)"
                      strokeWidth={2}
                      fill="url(#equityGrad)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Outcome Distribution */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Outcome Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              {outcomeData.length === 0 ? (
                <div className="flex items-center justify-center h-64 text-muted-foreground">
                  No closed trades yet
                </div>
              ) : (
                <>
                  <ResponsiveContainer
                    width="100%"
                    height={200}
                    minHeight={150}
                  >
                    <PieChart>
                      <Pie
                        data={outcomeData}
                        cx="50%"
                        cy="50%"
                        innerRadius={45}
                        outerRadius={75}
                        paddingAngle={3}
                        dataKey="value"
                      >
                        {outcomeData.map((entry, i) => (
                          <Cell key={i} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={tooltipStyle}
                        formatter={(value) => [`${value} trades`, ""]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="space-y-1.5 mt-2">
                    {outcomeData.map((d) => {
                      const total = outcomeData.reduce(
                        (sum, x) => sum + x.value,
                        0
                      );
                      const pct =
                        total > 0
                          ? ((d.value / total) * 100).toFixed(1)
                          : "0.0";
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

        {/* Bottom Row */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Symbol Win Rates */}
          <Card className="lg:col-span-2">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Symbol Win Rates</CardTitle>
            </CardHeader>
            <CardContent>
              {symbolWinRateData.length === 0 ? (
                <div className="flex items-center justify-center h-48 text-muted-foreground">
                  No closed trades yet
                </div>
              ) : (
                <ResponsiveContainer
                  width="100%"
                  height={220}
                  minHeight={200}
                >
                  <BarChart data={symbolWinRateData}>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="var(--border)"
                    />
                    <XAxis
                      dataKey="symbol"
                      stroke="var(--muted-foreground)"
                      fontSize={11}
                    />
                    <YAxis
                      stroke="var(--muted-foreground)"
                      fontSize={11}
                      domain={[0, 100]}
                    />
                    <Tooltip
                      contentStyle={tooltipStyle}
                      formatter={(value, name) => {
                        if (name === "winRate") return [`${value}%`, "Win Rate"];
                        return [value, "Trades"];
                      }}
                    />
                    <Bar
                      dataKey="winRate"
                      name="winRate"
                      radius={[4, 4, 0, 0]}
                    >
                      {symbolWinRateData.map((entry, i) => (
                        <Cell
                          key={i}
                          fill={
                            entry.winRate >= 50
                              ? "var(--chart-1)"
                              : "var(--chart-4)"
                          }
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Recent Trades */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Recent Trades</CardTitle>
            </CardHeader>
            <CardContent>
              {recentSignals.length === 0 ? (
                <div className="flex items-center justify-center h-48 text-muted-foreground">
                  No recent trades
                </div>
              ) : (
                <div className="space-y-2">
                  {recentSignals.map((signal) => {
                    const isWin = [
                      "TP1",
                      "TP2",
                      "TP3",
                      "TP4",
                      "WIN",
                    ].includes(signal.status);
                    const rr = calculateRR(signal);
                    return (
                      <div
                        key={signal.id}
                        className="flex items-center justify-between py-2 border-b border-border/50 last:border-0"
                      >
                        <div className="flex items-center gap-2">
                          {isWin ? (
                            <ArrowUpRight className="w-4 h-4 text-chart-1" />
                          ) : (
                            <ArrowDownRight className="w-4 h-4 text-chart-4" />
                          )}
                          <div>
                            <p className="text-sm font-medium text-foreground">
                              {signal.symbol}
                            </p>
                            <p className="text-xs text-muted-foreground">
                              {signal.direction} | Q:{" "}
                              {signal.quality_score.toFixed(0)}
                            </p>
                          </div>
                        </div>
                        <div className="text-right">
                          <p
                            className={`text-sm font-bold ${
                              rr > 0
                                ? "text-chart-1"
                                : rr < 0
                                ? "text-chart-4"
                                : "text-chart-3"
                            }`}
                          >
                            {rr > 0 ? "+" : ""}
                            {rr.toFixed(1)}R
                          </p>
                          <Badge
                            variant="outline"
                            className={`text-[10px] ${
                              isWin
                                ? "border-emerald-500/30 text-emerald-500 dark:text-emerald-400"
                                : signal.status === "BREAKEVEN"
                                ? "border-amber-500/30 text-amber-500 dark:text-amber-400"
                                : "border-red-500/30 text-red-500 dark:text-red-400"
                            }`}
                          >
                            {signal.status}
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
      </div>
    </DashboardLayout>
  );
}
