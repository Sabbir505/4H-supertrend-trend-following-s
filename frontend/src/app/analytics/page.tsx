"use client";

import { useState, useEffect, useMemo } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Info } from "lucide-react";
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
  LineChart,
  Line,
  Legend,
} from "recharts";
import { getAllSignals, getAnalyticsSummary, Signal, AnalyticsSummary } from "@/lib/api";
import { calculateRR } from "@/lib/utils";

const COLORS = ["#10b981", "#ef4444", "#f59e0b", "#6366f1", "#8b5cf6", "#ec4899", "#14b8a6"];

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

function StatCard({
  title,
  value,
  subtitle,
  valueColor = "text-white",
}: {
  title: string;
  value: string;
  subtitle: string;
  valueColor?: string;
}) {
  return (
    <Card className="bg-[#111827] border-[#1e293b]">
      <CardContent className="p-5">
        <p className="text-xs text-slate-500 uppercase tracking-wide">{title}</p>
        <p className={`text-2xl font-bold mt-1 ${valueColor}`}>{value}</p>
        <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>
      </CardContent>
    </Card>
  );
}

export default function AnalyticsPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [analytics, setAnalytics] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterDirection, setFilterDirection] = useState("ALL");
  const [filterSymbol, setFilterSymbol] = useState("ALL");

  useEffect(() => {
    let isMounted = true;

    async function fetchData() {
      try {
        const [allSignals, analyticsData] = await Promise.all([
          getAllSignals().catch(() => []),
          getAnalyticsSummary().catch(() => null),
        ]);
        if (!isMounted) return;

        // Filter out OPEN and partial (TP1/TP2/TP3) signals for analytics — only fully closed trades
        const closedStatuses = ["TP4", "SL", "BREAKEVEN", "EXPIRED", "WIN"];
        const nonOpen = allSignals.filter((s: Signal) => closedStatuses.includes(s.status));
        setSignals(nonOpen);
        setAnalytics(analyticsData);
      } catch (err) {
        if (!isMounted) return;
        setError(err instanceof Error ? err.message : "Failed to fetch analytics");
      } finally {
        if (isMounted) setLoading(false);
      }
    }
    fetchData();

    // Auto-refresh every 30 seconds
    const interval = setInterval(fetchData, 30000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Apply filters
  const filteredSignals = useMemo(() => {
    return signals.filter((s) => {
      if (filterDirection !== "ALL" && s.direction !== filterDirection) return false;
      if (filterSymbol !== "ALL" && s.symbol !== filterSymbol) return false;
      return true;
    });
  }, [signals, filterDirection, filterSymbol]);

  // Derived data
  const uniqueSymbols = useMemo(() => ["ALL", ...Array.from(new Set(signals.map((s) => s.symbol)))], [signals]);

  // Outcome distribution from filtered signals
  // Group trades into 4 categories: Loss, Expired, Breakeven, Win
  const outcomeData = useMemo(() => {
    let loss = 0;
    let expired = 0;
    let breakeven = 0;
    let win = 0;
    filteredSignals.forEach((s) => {
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
  }, [filteredSignals]);

  // Direction performance
  const directionData = useMemo(() => {
    const directions = ["LONG", "SHORT"];
    return directions.map((dir) => {
      const dirSignals = filteredSignals.filter((s) => s.direction === dir);
      const wins = dirSignals.filter((s) => ["TP1", "TP2", "TP3", "TP4", "WIN"].includes(s.status)).length;
      const losses = dirSignals.filter((s) => s.status === "SL").length;
      const be = dirSignals.filter((s) => s.status === "BREAKEVEN").length;
      const expired = dirSignals.filter((s) => s.status === "EXPIRED").length;
      // Win rate excludes BE and EXPIRED (only counts wins and losses)
      const wr = (wins + losses) > 0 ? ((wins / (wins + losses)) * 100).toFixed(1) : "0.0";
      return { direction: dir, wins, losses, breakevens: be, expired, total: dirSignals.length, winRate: parseFloat(wr) };
    });
  }, [filteredSignals]);

  // Symbol performance from signals
  const symbolPerformance = useMemo(() => {
    const bySymbol: Record<string, { total: number; wins: number; losses: number; rr: number }> = {};
    filteredSignals.forEach((s) => {
      if (!bySymbol[s.symbol]) bySymbol[s.symbol] = { total: 0, wins: 0, losses: 0, rr: 0 };
      bySymbol[s.symbol].total++;
      if (["TP1", "TP2", "TP3", "TP4", "WIN"].includes(s.status)) bySymbol[s.symbol].wins++;
      if (s.status === "SL") bySymbol[s.symbol].losses++;
      bySymbol[s.symbol].rr += calculateRR(s);
    });
    return Object.entries(bySymbol)
      .map(([symbol, data]) => ({
        symbol,
        totalTrades: data.total,
        wins: data.wins,
        winRate: (data.wins + data.losses) > 0 ? parseFloat(((data.wins / (data.wins + data.losses)) * 100).toFixed(1)) : 0,
        totalRR: parseFloat(data.rr.toFixed(2)),
      }))
      .sort((a, b) => b.totalTrades - a.totalTrades);
  }, [filteredSignals]);

  // Strength performance
  const strengthData = useMemo(() => {
    const byStrength: Record<string, { total: number; wins: number; losses: number }> = {};
    filteredSignals.forEach((s) => {
      const str = s.strength || "STANDARD";
      if (!byStrength[str]) byStrength[str] = { total: 0, wins: 0, losses: 0 };
      byStrength[str].total++;
      if (["TP1", "TP2", "TP3", "TP4", "WIN"].includes(s.status)) byStrength[str].wins++;
      if (s.status === "SL") byStrength[str].losses++;
    });
    return Object.entries(byStrength).map(([strength, data]) => ({
      strength,
      total: data.total,
      wins: data.wins,
      winRate: (data.wins + data.losses) > 0 ? parseFloat(((data.wins / (data.wins + data.losses)) * 100).toFixed(1)) : 0,
    }));
  }, [filteredSignals]);

  // Time analysis: signals by day of week
  const dayOfWeekData = useMemo(() => {
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const counts: Record<string, { total: number; wins: number; losses: number }> = {};
    days.forEach((d) => (counts[d] = { total: 0, wins: 0, losses: 0 }));
    filteredSignals.forEach((s) => {
      try {
        const day = days[new Date(s.fired_at).getDay()];
        counts[day].total++;
        if (["TP1", "TP2", "TP3", "TP4", "WIN"].includes(s.status)) counts[day].wins++;
        if (s.status === "SL") counts[day].losses++;
      } catch {}
    });
    return days.map((day) => ({
      day,
      total: counts[day].total,
      wins: counts[day].wins,
      winRate: (counts[day].wins + counts[day].losses) > 0 ? parseFloat(((counts[day].wins / (counts[day].wins + counts[day].losses)) * 100).toFixed(1)) : 0,
    }));
  }, [filteredSignals]);

  // Stats
  const totalTrades = filteredSignals.length;
  const winCount = filteredSignals.filter((s) => ["TP1", "TP2", "TP3", "TP4", "WIN"].includes(s.status)).length;
  const lossCount = filteredSignals.filter((s) => s.status === "SL").length;
  const winRate = (winCount + lossCount) > 0 ? ((winCount / (winCount + lossCount)) * 100).toFixed(1) : "0.0";
  const avgQuality = totalTrades > 0
    ? (filteredSignals.reduce((sum, s) => sum + s.quality_score, 0) / totalTrades).toFixed(1)
    : "0.0";

  if (loading) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center h-64">
          <div className="text-slate-400">Loading analytics...</div>
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
            <h1 className="text-2xl font-bold text-white">Analytics</h1>
            <p className="text-sm text-slate-400 mt-1">
              Deep-dive into your trading performance metrics
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Direction filter */}
            <select
              value={filterDirection}
              onChange={(e) => setFilterDirection(e.target.value)}
              className="bg-[#1e293b] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500/50"
            >
              <option value="ALL">All Directions</option>
              <option value="LONG">LONG</option>
              <option value="SHORT">SHORT</option>
            </select>
            {/* Symbol filter */}
            <select
              value={filterSymbol}
              onChange={(e) => setFilterSymbol(e.target.value)}
              className="bg-[#1e293b] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500/50"
            >
              {uniqueSymbols.map((s) => (
                <option key={s} value={s}>
                  {s === "ALL" ? "All Symbols" : s}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Summary Stats */}
        <div className="grid grid-cols-4 gap-4">
          <StatCard
            title="Total Trades"
            value={String(totalTrades)}
            subtitle="Closed signals analyzed"
            valueColor="text-white"
          />
          <StatCard
            title="Win Rate"
            value={`${winRate}%`}
            subtitle={`${winCount} wins / ${lossCount} losses`}
            valueColor={parseFloat(winRate) >= 50 ? "text-emerald-400" : "text-red-400"}
          />
          <StatCard
            title="Avg Quality"
            value={avgQuality}
            subtitle="Average quality score"
            valueColor={parseFloat(avgQuality) >= 70 ? "text-emerald-400" : "text-amber-400"}
          />
          <StatCard
            title="Unique Symbols"
            value={String(uniqueSymbols.length - 1)}
            subtitle="Symbols traded"
            valueColor="text-blue-400"
          />
        </div>

        {/* Charts Row 1: Outcome Distribution + Direction Performance */}
        <div className="grid grid-cols-2 gap-6">
          {/* Outcome Distribution Pie */}
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2 mb-4">
                <h3 className="text-sm font-semibold text-white">Outcome Distribution</h3>
                <Info className="w-3.5 h-3.5 text-slate-500" />
              </div>
              {outcomeData.length === 0 ? (
                <div className="flex items-center justify-center h-64 text-slate-400">No data</div>
              ) : (
                <div className="flex items-center gap-4">
                  <ResponsiveContainer width="60%" height={220} minHeight={200}>
                    <PieChart>
                      <Pie
                        data={outcomeData}
                        cx="50%"
                        cy="50%"
                        innerRadius={50}
                        outerRadius={80}
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
                  <div className="flex-1 space-y-2">
                    {outcomeData.map((d) => (
                      <div key={d.name} className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: d.color }} />
                          <span className="text-sm text-slate-300">{d.name}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-white">{d.value}</span>
                          <span className="text-xs text-slate-500">
                            ({totalTrades > 0 ? ((d.value / totalTrades) * 100).toFixed(1) : 0}%)
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Direction Performance Bar */}
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2 mb-4">
                <h3 className="text-sm font-semibold text-white">Direction Performance</h3>
                <Info className="w-3.5 h-3.5 text-slate-500" />
              </div>
              <ResponsiveContainer width="100%" height={220} minHeight={200}>
                <BarChart data={directionData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="direction" stroke="#64748b" fontSize={12} />
                  <YAxis stroke="#64748b" fontSize={12} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px" }}
                    labelStyle={{ color: "#f8fafc" }}
                        itemStyle={{ color: "#f8fafc" }}
                  />
                  <Bar dataKey="wins" fill="#10b981" name="Wins" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="losses" fill="#ef4444" name="Losses" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="breakevens" fill="#f59e0b" name="Breakevens" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              <div className="flex items-center justify-center gap-6 mt-2">
                {directionData.map((d) => (
                  <div key={d.direction} className="text-center">
                    <p className="text-xs text-slate-400">{d.direction} Win Rate</p>
                    <p className={`text-sm font-bold ${d.winRate >= 50 ? "text-emerald-400" : "text-red-400"}`}>
                      {d.winRate}% ({d.total} trades)
                    </p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Charts Row 2: Symbol Performance + Day of Week */}
        <div className="grid grid-cols-2 gap-6">
          {/* Symbol Performance */}
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2 mb-4">
                <h3 className="text-sm font-semibold text-white">Symbol Performance</h3>
                <Info className="w-3.5 h-3.5 text-slate-500" />
              </div>
              {symbolPerformance.length === 0 ? (
                <div className="flex items-center justify-center h-64 text-slate-400">No data</div>
              ) : (
                <>
                  <ResponsiveContainer width="100%" height={220} minHeight={200}>
                    <BarChart data={symbolPerformance} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                      <XAxis type="number" stroke="#64748b" fontSize={12} />
                      <YAxis dataKey="symbol" type="category" stroke="#64748b" fontSize={11} width={70} />
                      <Tooltip
                        contentStyle={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px" }}
                        labelStyle={{ color: "#f8fafc" }}
                        itemStyle={{ color: "#f8fafc" }}
                        formatter={(value, name) => {
                          if (name === "winRate") return [`${value}%`, "Win Rate"];
                          return [value, name === "totalTrades" ? "Trades" : "Total RR"];
                        }}
                      />
                      <Bar dataKey="winRate" fill="#10b981" name="winRate" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                  <div className="grid grid-cols-3 gap-2 mt-3">
                    {symbolPerformance.slice(0, 6).map((s) => (
                      <div key={s.symbol} className="bg-[#1e293b]/50 rounded p-2">
                        <p className="text-xs text-slate-400">{s.symbol}</p>
                        <p className="text-sm font-bold text-white">{s.winRate}% WR</p>
                        <p className="text-xs text-slate-500">{s.totalTrades} trades | {s.totalRR >= 0 ? "+" : ""}{s.totalRR}R</p>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          {/* Day of Week Analysis */}
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2 mb-4">
                <h3 className="text-sm font-semibold text-white">Performance by Day</h3>
                <Info className="w-3.5 h-3.5 text-slate-500" />
              </div>
              <ResponsiveContainer width="100%" height={220} minHeight={200}>
                <BarChart data={dayOfWeekData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="day" stroke="#64748b" fontSize={12} />
                  <YAxis stroke="#64748b" fontSize={12} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px" }}
                    labelStyle={{ color: "#f8fafc" }}
                        itemStyle={{ color: "#f8fafc" }}
                  />
                  <Bar dataKey="wins" fill="#10b981" name="Wins" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="total" fill="#1e293b" name="Total" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              <div className="flex items-center justify-center gap-4 mt-2">
                <div className="flex items-center gap-1.5">
                  <div className="w-3 h-3 rounded bg-emerald-500" />
                  <span className="text-xs text-slate-400">Wins</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <div className="w-3 h-3 rounded bg-[#1e293b]" />
                  <span className="text-xs text-slate-400">Total</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Charts Row 3: Strength + Quality Distribution */}
        <div className="grid grid-cols-2 gap-6">
          {/* Strength Performance */}
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2 mb-4">
                <h3 className="text-sm font-semibold text-white">Strength vs Performance</h3>
                <Info className="w-3.5 h-3.5 text-slate-500" />
              </div>
              <ResponsiveContainer width="100%" height={220} minHeight={200}>
                <BarChart data={strengthData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="strength" stroke="#64748b" fontSize={12} />
                  <YAxis stroke="#64748b" fontSize={12} />
                  <Tooltip
                    contentStyle={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px" }}
                    labelStyle={{ color: "#f8fafc" }}
                        itemStyle={{ color: "#f8fafc" }}
                    formatter={(value, name) => {
                      if (name === "winRate") return [`${value}%`, "Win Rate"];
                      return [value, "Total Trades"];
                    }}
                  />
                  <Bar dataKey="total" fill="#6366f1" name="total" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="winRate" fill="#10b981" name="winRate" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              <div className="flex items-center justify-center gap-6 mt-2">
                {strengthData.map((s) => (
                  <div key={s.strength} className="text-center">
                    <p className="text-xs text-slate-400">{s.strength}</p>
                    <p className={`text-sm font-bold ${s.winRate >= 50 ? "text-emerald-400" : "text-red-400"}`}>
                      {s.winRate}% ({s.total})
                    </p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Quality Score Distribution */}
          <Card className="bg-[#111827] border-[#1e293b]">
            <CardContent className="p-5">
              <div className="flex items-center gap-2 mb-4">
                <h3 className="text-sm font-semibold text-white">Quality Score Distribution</h3>
                <Info className="w-3.5 h-3.5 text-slate-500" />
              </div>
              {filteredSignals.length === 0 ? (
                <div className="flex items-center justify-center h-64 text-slate-400">No data</div>
              ) : (
                <>
                  {(() => {
                    const ranges = [
                      { label: "0-25", min: 0, max: 25, color: "#ef4444" },
                      { label: "25-50", min: 25, max: 50, color: "#f59e0b" },
                      { label: "50-70", min: 50, max: 70, color: "#6366f1" },
                      { label: "70-85", min: 70, max: 85, color: "#10b981" },
                      { label: "85-100", min: 85, max: 101, color: "#059669" },
                    ];
                    const distData = ranges.map((r) => ({
                      range: r.label,
                      count: filteredSignals.filter((s) => s.quality_score >= r.min && s.quality_score < r.max).length,
                      color: r.color,
                    }));
                    return (
                      <>
                        <ResponsiveContainer width="100%" height={220} minHeight={200}>
                          <BarChart data={distData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                            <XAxis dataKey="range" stroke="#64748b" fontSize={12} />
                            <YAxis stroke="#64748b" fontSize={12} />
                            <Tooltip
                              contentStyle={{ backgroundColor: "#111827", border: "1px solid #1e293b", borderRadius: "8px" }}
                              labelStyle={{ color: "#f8fafc" }}
                        itemStyle={{ color: "#f8fafc" }}
                            />
                            <Bar dataKey="count" name="Trades" radius={[4, 4, 0, 0]}>
                              {distData.map((entry, i) => (
                                <Cell key={i} fill={entry.color} />
                              ))}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      </>
                    );
                  })()}
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </DashboardLayout>
  );
}