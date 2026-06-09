"use client";

import { useState, useEffect, useMemo } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Info, BarChart3, TrendingUp, TrendingDown, Target } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { getBacktestResults, BacktestResult } from "@/lib/api";
import { formatPrice } from "@/lib/utils";

const COLORS = ["#10b981", "#ef4444", "#f59e0b", "#6366f1", "#8b5cf6", "#ec4899"];

export default function BacktestPage() {
  const [results, setResults] = useState<BacktestResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const data = await getBacktestResults();
        setResults(data);
        if (data.length > 0 && !selectedSymbol) {
          setSelectedSymbol(data[0].symbol);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch backtest data");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  const selectedResult = useMemo(
    () => results.find((r) => r.symbol === selectedSymbol) ?? null,
    [results, selectedSymbol]
  );

  // Aggregate stats
  // Bug fix: Don't count breakevens as wins - match backend logic
  const totalTrades = results.reduce((sum, r) => sum + r.total_trades, 0);
  const totalWins = results.reduce((sum, r) => sum + r.wins, 0);
  const totalBreakevens = results.reduce((sum, r) => sum + r.breakevens, 0);
  const totalLosses = results.reduce((sum, r) => sum + r.losses, 0);
  const totalRR = results.reduce((sum, r) => sum + r.total_rr, 0);
  const overallWR = totalTrades > 0 ? ((totalWins / totalTrades) * 100).toFixed(1) : "0.0";
  const overallBE = totalTrades > 0 ? ((totalBreakevens / totalTrades) * 100).toFixed(1) : "0.0";

  // Symbol comparison chart data
  const symbolComparisonData = results.map((r) => ({
    symbol: r.symbol,
    winRate: r.win_rate,
    totalRR: parseFloat(r.total_rr.toFixed(2)),
    totalTrades: r.total_trades,
  }));

  // Win rate by symbol for bar chart
  const winRateChartData = results
    .sort((a, b) => b.win_rate - a.win_rate)
    .map((r) => ({
      symbol: r.symbol,
      winRate: r.win_rate,
      trades: r.total_trades,
    }));

  // Outcome distribution for selected result
  const selectedOutcomeData = selectedResult
    ? [
        { name: "Wins", value: selectedResult.wins, color: "#10b981" },
        { name: "Losses", value: selectedResult.losses, color: "#ef4444" },
        { name: "Breakevens", value: selectedResult.breakevens, color: "#f59e0b" },
      ].filter((d) => d.value > 0)
    : [];

  // Direction stats for selected result
  const directionData = selectedResult
    ? [
        { direction: "LONG", winRate: selectedResult.long_win_rate, trades: selectedResult.long_trades },
        { direction: "SHORT", winRate: selectedResult.short_win_rate, trades: selectedResult.short_trades },
      ]
    : [];

  if (loading) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center h-64">
          <div className="text-slate-400">Loading backtest data...</div>
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

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">Backtest Results</h1>
            <p className="text-sm text-slate-400 mt-1">
              Historical strategy performance across symbols
            </p>
          </div>
          {results.length > 0 && (
            <select
              value={selectedSymbol || ""}
              onChange={(e) => setSelectedSymbol(e.target.value)}
              className="bg-[#1e293b] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500/50"
            >
              {results.map((r) => (
                <option key={r.symbol} value={r.symbol}>
                  {r.symbol} ({r.timeframe})
                </option>
              ))}
            </select>
          )}
        </div>

        {results.length === 0 ? (
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="flex flex-col items-center justify-center py-16">
              <BarChart3 className="w-12 h-12 text-slate-500 mb-4" />
              <h2 className="text-lg font-semibold text-white mb-2">No Backtest Data Yet</h2>
              <p className="text-sm text-slate-400 text-center max-w-md">
                Backtest results will appear here once you run backtests. Run your backtest strategy to generate historical performance data.
              </p>
            </CardContent>
          </Card>
        ) : (
          <>
            {/* Top Stats */}
            <div className="grid grid-cols-5 gap-4">
              <Card className="bg-[#111827] border-[#1e293b]">
                <CardContent className="p-5">
                  <div className="flex items-center gap-2">
                    <BarChart3 className="w-4 h-4 text-blue-400" />
                    <p className="text-xs text-slate-500 uppercase">Total Trades</p>
                  </div>
                  <p className="text-2xl font-bold text-white mt-2">{totalTrades}</p>
                  <p className="text-xs text-slate-400 mt-0.5">{results.length} symbols tested</p>
                </CardContent>
              </Card>
              <Card className="bg-[#111827] border-[#1e293b]">
                <CardContent className="p-5">
                  <div className="flex items-center gap-2">
                    <Target className="w-4 h-4 text-emerald-400" />
                    <p className="text-xs text-slate-500 uppercase">Overall Win Rate</p>
                  </div>
                  <p className={`text-2xl font-bold mt-2 ${parseFloat(overallWR) >= 50 ? "text-emerald-400" : "text-red-400"}`}>
                    {overallWR}%
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">{totalWins}W / {totalLosses}L</p>
                </CardContent>
              </Card>
              <Card className="bg-[#111827] border-[#1e293b]">
                <CardContent className="p-5">
                  <div className="flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-purple-400" />
                    <p className="text-xs text-slate-500 uppercase">Total RR</p>
                  </div>
                  <p className={`text-2xl font-bold mt-2 ${totalRR >= 0 ? "text-emerald-400" : "text-red-400"}`}>
                    {totalRR >= 0 ? "+" : ""}{totalRR.toFixed(2)}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">Cumulative R-multiples</p>
                </CardContent>
              </Card>
              <Card className="bg-[#111827] border-[#1e293b]">
                <CardContent className="p-5">
                  <div className="flex items-center gap-2">
                    <TrendingDown className="w-4 h-4 text-red-400" />
                    <p className="text-xs text-slate-500 uppercase">Max Drawdown</p>
                  </div>
                  <p className="text-2xl font-bold text-red-400 mt-2">
                    {selectedResult ? `-${selectedResult.max_drawdown.toFixed(1)}R` : "N/A"}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">{selectedResult?.symbol ?? "Select a symbol"}</p>
                </CardContent>
              </Card>
              <Card className="bg-[#111827] border-[#1e293b]">
                <CardContent className="p-5">
                  <div className="flex items-center gap-2">
                    <Info className="w-4 h-4 text-amber-400" />
                    <p className="text-xs text-slate-500 uppercase">Avg Bars Held</p>
                  </div>
                  <p className="text-2xl font-bold text-white mt-2">
                    {selectedResult?.avg_bars_held?.toFixed(1) ?? "N/A"}
                  </p>
                  <p className="text-xs text-slate-400 mt-0.5">{selectedResult?.timeframe ?? "Select a symbol"}</p>
                </CardContent>
              </Card>
            </div>

            {/* Charts Row 1: Win Rate Comparison + Selected Symbol Details */}
            <div className="grid grid-cols-2 gap-6">
              {/* Symbol Win Rate Comparison */}
              <Card className="bg-[#111827] border-[#1e293b]">
                <CardContent className="p-5">
                  <div className="flex items-center gap-2 mb-4">
                    <h3 className="text-sm font-semibold text-white">Win Rate by Symbol</h3>
                  </div>
                  <ResponsiveContainer width="100%" height={280} minHeight={200}>
                    <BarChart data={winRateChartData}>
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
                        {winRateChartData.map((entry, i) => (
                          <Cell key={i} fill={entry.winRate >= 50 ? "#10b981" : "#ef4444"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              {/* Selected Symbol Details */}
              <Card className="bg-[#111827] border-[#1e293b]">
                <CardContent className="p-5">
                  <div className="flex items-center gap-2 mb-4">
                    <h3 className="text-sm font-semibold text-white">
                      {selectedResult ? `${selectedResult.symbol} Details` : "Select a Symbol"}
                    </h3>
                  </div>
                  {selectedResult ? (
                    <div className="space-y-4">
                      {/* Outcome Pie */}
                      <div className="flex items-center gap-4">
                        <ResponsiveContainer width="50%" height={160} minHeight={150}>
                          <PieChart>
                            <Pie
                              data={selectedOutcomeData}
                              cx="50%"
                              cy="50%"
                              innerRadius={35}
                              outerRadius={60}
                              paddingAngle={3}
                              dataKey="value"
                            >
                              {selectedOutcomeData.map((entry, i) => (
                                <Cell key={i} fill={entry.color} />
                              ))}
                            </Pie>
                            <Tooltip
                              contentStyle={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px" }}
                              labelStyle={{ color: "#f8fafc" }}
                        itemStyle={{ color: "#f8fafc" }}
                            />
                          </PieChart>
                        </ResponsiveContainer>
                        <div className="flex-1 space-y-2">
                          {selectedOutcomeData.map((d) => (
                            <div key={d.name} className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <div className="w-3 h-3 rounded-full" style={{ backgroundColor: d.color }} />
                                <span className="text-sm text-slate-300">{d.name}</span>
                              </div>
                              <span className="text-sm font-medium text-white">{d.value}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                      {/* Key metrics */}
                      <div className="grid grid-cols-2 gap-3">
                        <MetricRow label="Timeframe" value={selectedResult.timeframe} />
                        <MetricRow label="Period" value={`${selectedResult.period_months} months`} />
                        <MetricRow label="Win Rate" value={`${selectedResult.win_rate.toFixed(1)}%`} valueColor={selectedResult.win_rate >= 50 ? "text-emerald-400" : "text-red-400"} />
                        <MetricRow label="Avg RR" value={`${selectedResult.avg_rr.toFixed(2)}R`} valueColor={selectedResult.avg_rr >= 0 ? "text-emerald-400" : "text-red-400"} />
                        <MetricRow label="Max RR" value={`${selectedResult.max_rr.toFixed(2)}R`} valueColor="text-emerald-400" />
                        <MetricRow label="TP1 Rate" value={`${selectedResult.tp1_rate.toFixed(1)}%`} />
                        <MetricRow label="TP2 Rate" value={`${selectedResult.tp2_rate.toFixed(1)}%`} />
                        <MetricRow label="Breakeven Rate" value={`${selectedResult.breakeven_rate.toFixed(1)}%`} />
                        <MetricRow label="Long Win Rate" value={`${selectedResult.long_win_rate.toFixed(1)}%`} valueColor={selectedResult.long_win_rate >= 50 ? "text-emerald-400" : "text-red-400"} />
                        <MetricRow label="Short Win Rate" value={`${selectedResult.short_win_rate.toFixed(1)}%`} valueColor={selectedResult.short_win_rate >= 50 ? "text-emerald-400" : "text-red-400"} />
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center justify-center h-64 text-slate-400">
                      Select a symbol to view details
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            {/* Charts Row 2: Direction Performance + Total RR by Symbol */}
            <div className="grid grid-cols-2 gap-6">
              {/* Direction Performance */}
              <Card className="bg-[#111827] border-[#1e293b]">
                <CardContent className="p-5">
                  <div className="flex items-center gap-2 mb-4">
                    <h3 className="text-sm font-semibold text-white">Direction Performance</h3>
                  </div>
                  {selectedResult ? (
                    <>
                      <ResponsiveContainer width="100%" height={200} minHeight={150}>
                        <BarChart data={directionData}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                          <XAxis dataKey="direction" stroke="#64748b" fontSize={12} />
                          <YAxis stroke="#64748b" fontSize={12} domain={[0, 100]} />
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
                            {directionData.map((entry, i) => (
                              <Cell key={i} fill={entry.winRate >= 50 ? "#10b981" : "#ef4444"} />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                      <div className="flex items-center justify-center gap-6 mt-2">
                        {directionData.map((d) => (
                          <div key={d.direction} className="text-center">
                            <p className="text-xs text-slate-400">{d.direction}</p>
                            <p className={`text-sm font-bold ${d.winRate >= 50 ? "text-emerald-400" : "text-red-400"}`}>
                              {d.winRate.toFixed(1)}%
                            </p>
                            <p className="text-xs text-slate-500">{d.trades} trades</p>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="flex items-center justify-center h-48 text-slate-400">
                      Select a symbol to view direction stats
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Total RR by Symbol */}
              <Card className="bg-[#111827] border-[#1e293b]">
                <CardContent className="p-5">
                  <div className="flex items-center gap-2 mb-4">
                    <h3 className="text-sm font-semibold text-white">Total RR by Symbol</h3>
                  </div>
                  <ResponsiveContainer width="100%" height={280} minHeight={200}>
                    <BarChart data={symbolComparisonData.sort((a, b) => b.totalRR - a.totalRR)}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis dataKey="symbol" stroke="#64748b" fontSize={11} />
                      <YAxis stroke="#64748b" fontSize={11} />
                      <Tooltip
                        contentStyle={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px" }}
                        labelStyle={{ color: "#f8fafc" }}
                        itemStyle={{ color: "#f8fafc" }}
                        formatter={(value) => [`${Number(value) >= 0 ? "+" : ""}${value}R`, "Total RR"]}
                      />
                      <Bar dataKey="totalRR" name="Total RR" radius={[4, 4, 0, 0]}>
                        {symbolComparisonData.map((entry, i) => (
                          <Cell key={i} fill={entry.totalRR >= 0 ? "#10b981" : "#ef4444"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>
            </div>
          </>
        )}
      </div>
    </DashboardLayout>
  );
}

function MetricRow({
  label,
  value,
  valueColor = "text-white",
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="flex items-center justify-between py-1.5 px-2 bg-[#1e293b]/30 rounded">
      <span className="text-xs text-slate-400">{label}</span>
      <span className={`text-xs font-medium ${valueColor}`}>{value}</span>
    </div>
  );
}