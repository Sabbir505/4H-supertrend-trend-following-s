"use client";

import { useState, useEffect, useMemo } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown, Activity, Target, BarChart3, Zap, Clock, ArrowUpRight, ArrowDownRight } from "lucide-react";
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
import { getDashboardStats, getOpenSignals, getClosedSignals, DashboardStats, Signal } from "@/lib/api";
import { calculateRR, formatPrice } from "@/lib/utils";

const COLORS = ["#10b981", "#ef4444", "#f59e0b", "#6366f1", "#8b5cf6"];

const outcomeColors: Record<string, string> = {
  "TP1 Hit": "#10b981",
  "TP2 Hit": "#10b981",
  "TP3 Hit": "#10b981",
  "TP4 Hit": "#10b981",
  TP1: "#10b981",
  TP2: "#10b981",
  TP3: "#10b981",
  TP4: "#10b981",
  WIN: "#10b981",
  SL: "#ef4444",
  BREAKEVEN: "#f59e0b",
  EXPIRED: "#6366f1",
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
        setError(err instanceof Error ? err.message : "Failed to fetch dashboard data");
      } finally {
        setLoading(false);
        isFetching = false;
      }
    }

    fetchData();

    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  // Compute outcome distribution from closed signals
  // Group trades into 4 categories: Loss, Expired, Breakeven, Win
  const outcomeData = useMemo(() => {
    let loss = 0;
    let expired = 0;
    let breakeven = 0;
    let win = 0;
    closedSignals.forEach((s) => {
      if (s.status === "SL") {
        loss++;
      } else if (s.status === "EXPIRED") {
        expired++;
      } else if (s.status === "BREAKEVEN") {
        breakeven++;
      } else if (["TP1", "TP2", "TP3", "TP4", "WIN"].includes(s.status)) {
        win++;
      }
    });
    const data = [];
    if (loss > 0) data.push({ name: "Loss", value: loss, color: "#ef4444" });
    if (expired > 0) data.push({ name: "Expired", value: expired, color: "#6366f1" });
    if (breakeven > 0) data.push({ name: "Breakeven", value: breakeven, color: "#f59e0b" });
    if (win > 0) data.push({ name: "Win", value: win, color: "#10b981" });
    return data;
  }, [closedSignals]);

  // Compute equity curve from closed signals (cumulative RR)
  // 4-TP incremental closing strategy (40/30/20/10)
  const equityDataWithCumulative = useMemo(() => {
    const sortedClosed = [...closedSignals]
      .filter(s => s.fired_at || s.closed_at) // Filter out entries with no valid date
      .sort(
        (a, b) => {
          const dateA = a.closed_at || a.fired_at;
          const dateB = b.closed_at || b.fired_at;
          if (!dateA || !dateB) return 0;
          return new Date(dateA).getTime() - new Date(dateB).getTime();
        }
      );
    const equityData = sortedClosed.map((s, index) => {
      const rr = calculateRR(s);
      const date = s.closed_at || s.fired_at;
      const tradeDate = date ? new Date(date) : new Date();
      return {
        date: tradeDate.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
        time: tradeDate.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
        rr: parseFloat(rr.toFixed(2)),
        symbol: s.symbol,
        index: index + 1, // Trade number
        status: s.status,
        tradeRR: rr,
      };
    });
    // Calculate cumulative RR using reduce (avoids mutating variables during render)
    return equityData.reduce<{ result: typeof equityData; runningTotal: number }>(
      (acc, item) => {
        acc.runningTotal += item.tradeRR;
        acc.result.push({ ...item, rr: parseFloat(acc.runningTotal.toFixed(2)) });
        return acc;
      },
      { result: [], runningTotal: 0 }
    ).result;
  }, [closedSignals]);

  if (loading) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center h-64">
          <div className="text-slate-400">Loading dashboard...</div>
        </div>
      </DashboardLayout>
    );
  }

  if (error) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center h-64">
          <div className="text-red-400">Error: {error}</div>
        </div>
      </DashboardLayout>
    );
  }

  // Compute symbol stats from closed signals
  const symbolStats: Record<string, { total: number; wins: number; losses: number }> = {};
  closedSignals.forEach((s) => {
    if (!symbolStats[s.symbol]) symbolStats[s.symbol] = { total: 0, wins: 0, losses: 0 };
    symbolStats[s.symbol].total++;
    if (["TP1", "TP2", "TP3", "TP4", "WIN"].includes(s.status)) symbolStats[s.symbol].wins++;
    if (s.status === "SL") symbolStats[s.symbol].losses++;
  });
  const symbolWinRateData = Object.entries(symbolStats)
    .map(([symbol, data]) => ({
      symbol,
      winRate: (data.wins + data.losses) > 0 ? parseFloat(((data.wins / (data.wins + data.losses)) * 100).toFixed(1)) : 0,
      total: data.total,
    }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 8);

  // Recent signals (latest 5)
  const recentSignals = [...closedSignals]
    .filter(s => s.closed_at || s.fired_at)
    .sort((a, b) => {
      const dateA = a.closed_at || a.fired_at;
      const dateB = b.closed_at || b.fired_at;
      if (!dateA || !dateB) return 0;
      const timeA = new Date(dateA).getTime();
      const timeB = new Date(dateB).getTime();
      if (isNaN(timeA) || isNaN(timeB)) return 0;
      return timeB - timeA;
    })
    .slice(0, 5);

  // Compute total RR from closed signals (consistent with equity curve)
  // Use API total_rr if available, otherwise fall back to equity curve calculation
  const totalRR = stats?.total_rr ?? (equityDataWithCumulative.length > 0 ? equityDataWithCumulative[equityDataWithCumulative.length - 1].rr : 0);

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">Dashboard</h1>
            <p className="text-sm text-slate-400 mt-1">Trading signal overview and performance</p>
          </div>
          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span className="text-xs text-slate-500">
                Updated: {lastUpdated.toLocaleTimeString()}
              </span>
            )}
            <button
              onClick={() => window.location.reload()}
              className="text-xs text-emerald-400 hover:text-emerald-300"
            >
              Refresh
            </button>
          </div>
        </div>

        {/* Top Stats */}
        <div className="grid grid-cols-5 gap-4">
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2">
                <Activity className="w-4 h-4 text-blue-400" />
                <p className="text-xs text-slate-500 uppercase">Total Signals</p>
              </div>
              <p className="text-2xl font-bold text-white mt-2">{stats?.total_signals ?? 0}</p>
              <p className="text-xs text-slate-400 mt-0.5">{stats?.open_signals ?? 0} open</p>
            </CardContent>
          </Card>
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2">
                <Target className="w-4 h-4 text-emerald-400" />
                <p className="text-xs text-slate-500 uppercase">Win Rate</p>
              </div>
              <p className={`text-2xl font-bold mt-2 ${(stats?.win_rate ?? 0) >= 50 ? "text-emerald-400" : "text-red-400"}`}>
                {stats?.win_rate?.toFixed(1) ?? "0.0"}%
              </p>
              <p className="text-xs text-slate-400 mt-0.5">From closed signals</p>
            </CardContent>
          </Card>
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-purple-400" />
                <p className="text-xs text-slate-500 uppercase">Avg Quality</p>
              </div>
              <p className={`text-2xl font-bold mt-2 ${(stats?.avg_quality_score ?? 0) >= 70 ? "text-emerald-400" : "text-amber-400"}`}>
                {stats?.avg_quality_score?.toFixed(1) ?? "0.0"}
              </p>
              <p className="text-xs text-slate-400 mt-0.5">Quality score average</p>
            </CardContent>
          </Card>
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2">
                <Zap className="w-4 h-4 text-amber-400" />
                <p className="text-xs text-slate-500 uppercase">Total RR</p>
              </div>
              <p className={`text-2xl font-bold mt-2 ${totalRR >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                {totalRR >= 0 ? "+" : ""}{totalRR.toFixed(2)}
              </p>
              <p className="text-xs text-slate-400 mt-0.5">Cumulative risk-reward</p>
            </CardContent>
          </Card>
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2">
                <Clock className="w-4 h-4 text-cyan-400" />
                <p className="text-xs text-slate-500 uppercase">Backtest WR</p>
              </div>
              <p className={`text-2xl font-bold mt-2 ${(stats?.overall_backtest_wr ?? 0) >= 50 ? "text-emerald-400" : "text-slate-400"}`}>
                {stats?.overall_backtest_wr?.toFixed(1) ?? "0.0"}%
              </p>
              <p className="text-xs text-slate-400 mt-0.5">{stats?.total_trades_backtest ?? 0} backtest trades</p>
            </CardContent>
          </Card>
        </div>

        {/* Charts Row */}
        <div className="grid grid-cols-3 gap-6">
          {/* Equity Curve */}
          <Card className="bg-[#111827] border-[#1e293b] col-span-2">
            <CardContent className="p-5">
              <div className="flex items-center gap-2 mb-4">
                <h3 className="text-sm font-semibold text-white">Equity Curve (Cumulative RR)</h3>
              </div>
              {equityDataWithCumulative.length === 0 ? (
                <div className="flex items-center justify-center h-64 text-slate-400">
                  No closed trades yet
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={280} minHeight={200}>
                  <AreaChart data={equityDataWithCumulative}>
                    <defs>
                      <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                        <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="date" stroke="#64748b" fontSize={11} />
                    <YAxis stroke="#64748b" fontSize={11} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px" }}
                      labelStyle={{ color: "#f8fafc" }}
                      itemStyle={{ color: "#f8fafc" }}
                      formatter={(value, name, props) => {
                        const payload = props?.payload;
                        if (payload) {
                          return [
                            `${payload.rr >= 0 ? "+" : ""}${payload.rr}R (Trade: ${payload.tradeRR >= 0 ? "+" : ""}${payload.tradeRR}R)`,
                            `${payload.symbol} - ${payload.status}`
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
                      stroke="#10b981"
                      strokeWidth={2}
                      fill="url(#equityGrad)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Outcome Distribution */}
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2 mb-4">
                <h3 className="text-sm font-semibold text-white">Outcome Distribution</h3>
              </div>
              {outcomeData.length === 0 ? (
                <div className="flex items-center justify-center h-64 text-slate-400">
                  No closed trades yet
                </div>
              ) : (
                <>
                  <ResponsiveContainer width="100%" height={200} minHeight={150}>
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
                        contentStyle={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px" }}
                        labelStyle={{ color: "#f8fafc" }}
                        itemStyle={{ color: "#f8fafc" }}
                        formatter={(value) => [`${value} trades`, ""]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="space-y-1.5 mt-2">
                    {outcomeData.map((d) => {
                      const total = outcomeData.reduce((sum, x) => sum + x.value, 0);
                      const pct = total > 0 ? ((d.value / total) * 100).toFixed(1) : "0.0";
                      return (
                        <div key={d.name} className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: d.color }} />
                            <span className="text-xs text-slate-300">{d.name}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium text-white">{d.value}</span>
                            <span className="text-xs text-slate-500">{pct}%</span>
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

        {/* Bottom Row: Symbol Win Rate + Recent Trades */}
        <div className="grid grid-cols-3 gap-6">
          {/* Symbol Win Rates */}
          <Card className="bg-[#111827] border-[#1e293b] col-span-2">
            <CardContent className="p-5">
              <div className="flex items-center gap-2 mb-4">
                <h3 className="text-sm font-semibold text-white">Symbol Win Rates</h3>
              </div>
              {symbolWinRateData.length === 0 ? (
                <div className="flex items-center justify-center h-48 text-slate-400">
                  No closed trades yet
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={220} minHeight={200}>
                  <BarChart data={symbolWinRateData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                    <XAxis dataKey="symbol" stroke="#64748b" fontSize={11} />
                    <YAxis stroke="#64748b" fontSize={11} domain={[0, 100]} />
                    <Tooltip
                      contentStyle={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px" }}
                      labelStyle={{ color: "#f8fafc" }}
                        itemStyle={{ color: "#f8fafc" }}
                      formatter={(value, name) => {
                        if (name === "winRate") return [`${value}%`, "Win Rate"];
                        return [value, "Trades"];
                      }}
                    />
                    <Bar dataKey="winRate" name="winRate" radius={[4, 4, 0, 0]}>
                      {symbolWinRateData.map((entry, i) => (
                        <Cell key={i} fill={entry.winRate >= 50 ? "#10b981" : "#ef4444"} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Recent Trades */}
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2 mb-4">
                <h3 className="text-sm font-semibold text-white">Recent Trades</h3>
              </div>
              {recentSignals.length === 0 ? (
                <div className="flex items-center justify-center h-48 text-slate-400">
                  No recent trades
                </div>
              ) : (
                <div className="space-y-3">
                  {recentSignals.map((signal) => {
                    const isWin = ["TP1", "TP2", "TP3", "TP4", "WIN"].includes(signal.status);
                    const rr = calculateRR(signal);
                    return (
                      <div
                        key={signal.id}
                        className="flex items-center justify-between py-2 border-b border-[#1e293b]/50 last:border-0"
                      >
                        <div className="flex items-center gap-2">
                          {isWin ? (
                            <ArrowUpRight className="w-4 h-4 text-emerald-400" />
                          ) : (
                            <ArrowDownRight className="w-4 h-4 text-red-400" />
                          )}
                          <div>
                            <p className="text-sm font-medium text-white">{signal.symbol}</p>
                            <p className="text-xs text-slate-500">
                              {signal.direction} | Q: {signal.quality_score.toFixed(0)}
                            </p>
                          </div>
                        </div>
                        <div className="text-right">
                          <p className={`text-sm font-bold ${rr > 0 ? "text-emerald-400" : rr < 0 ? "text-red-400" : "text-amber-400"}`}>
                            {rr > 0 ? "+" : ""}{rr.toFixed(1)}R
                          </p>
                          <Badge
                            variant="outline"
                            className={`text-[10px] ${
                              isWin
                                ? "border-emerald-500/30 text-emerald-400"
                                : signal.status === "BREAKEVEN"
                                ? "border-amber-500/30 text-amber-400"
                                : "border-red-500/30 text-red-400"
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