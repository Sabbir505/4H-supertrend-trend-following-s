"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown, Search, Filter } from "lucide-react";
import { AreaChart, Area, ResponsiveContainer } from "recharts";
import { getAllSignals, Signal } from "@/lib/api";
import { calculateRR, formatPrice, outcomeColors } from "@/lib/utils";

const ITEMS_PER_PAGE = 15;

function StatCard({
  title,
  value,
  subtitle,
  sparkData,
  valueColor = "text-white",
}: {
  title: string;
  value: string;
  subtitle: string;
  sparkData: number[];
  valueColor?: string;
}) {
  const isPositive = sparkData.length >= 2 && sparkData[sparkData.length - 1] >= sparkData[sparkData.length - 2];
  const chartData = sparkData.map((v, i) => ({ v, i }));
  const chartColor = isPositive ? "#10b981" : "#ef4444";

  return (
    <Card className="bg-[#111827] border-[#1e293b]">
      <CardContent className="p-5">
        <p className="text-xs text-slate-500 uppercase tracking-wide">{title}</p>
        <p className={`text-2xl font-bold mt-1 ${valueColor}`}>{value}</p>
        <p className="text-xs text-slate-400 mt-0.5">{subtitle}</p>
        <div className="h-10 mt-2">
          <ResponsiveContainer width="100%" height={40}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id={`sparkGrad-${title.replace(/\s/g, "")}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={chartColor} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={chartColor} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="v"
                stroke={chartColor}
                strokeWidth={1.5}
                fill={`url(#sparkGrad-${title.replace(/\s/g, "")})`}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </CardContent>
    </Card>
  );
}

export default function TradeHistoryPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [filterOutcome, setFilterOutcome] = useState("ALL");
  const [filterDirection, setFilterDirection] = useState("ALL");
  const [filterStrength, setFilterStrength] = useState("ALL");

  useEffect(() => {
    let isMounted = true;

    async function fetchData() {
      try {
        const data = await getAllSignals();
        if (!isMounted) return;
        // Filter to only fully closed signals (TP1/TP2/TP3 are still partially open)
        const closedStatuses = ["TP4", "SL", "BREAKEVEN", "EXPIRED", "WIN"];
        const closed = data.filter((s) => closedStatuses.includes(s.status));
        setSignals(closed);
      } catch (err) {
        if (!isMounted) return;
        setError(err instanceof Error ? err.message : "Failed to fetch trade history");
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
      // Search
      if (searchQuery) {
        const q = searchQuery.toLowerCase();
        if (
          !s.symbol.toLowerCase().includes(q) &&
          !s.direction.toLowerCase().includes(q) &&
          !s.status.toLowerCase().includes(q) &&
          !s.id.toLowerCase().includes(q)
        ) {
          return false;
        }
      }
      // Outcome
      if (filterOutcome !== "ALL") {
        const outcomeMap: Record<string, string[]> = {
          WIN: ["TP1", "TP2", "TP3", "TP4", "WIN"],
          LOSS: ["SL"],
          BREAKEVEN: ["BREAKEVEN"],
          EXPIRED: ["EXPIRED"],
        };
        const matchStatuses = outcomeMap[filterOutcome] || [filterOutcome];
        if (!matchStatuses.includes(s.status)) return false;
      }
      // Direction
      if (filterDirection !== "ALL" && s.direction !== filterDirection) return false;
      // Strength
      if (filterStrength !== "ALL" && s.strength !== filterStrength) return false;
      return true;
    });
  }, [signals, searchQuery, filterOutcome, filterDirection, filterStrength]);

  // Stats from ALL closed signals (not filtered)
  const winCount = signals.filter((s) => ["TP1", "TP2", "TP3", "TP4", "WIN"].includes(s.status)).length;
  const lossCount = signals.filter((s) => s.status === "SL").length;
  const beCount = signals.filter((s) => s.status === "BREAKEVEN").length;
  const totalTrades = signals.length;
  const winRate = totalTrades > 0 ? ((winCount / (winCount + lossCount)) * 100).toFixed(1) : "0.0";
  // Bug fix: Single-pass calculation for RR stats (was O(2n))
  const { avgRR, totalRR } = useMemo(() => {
    const total = signals.reduce((sum, s) => sum + calculateRR(s), 0);
    return {
      avgRR: totalTrades > 0 ? (total / totalTrades).toFixed(2) : "0.00",
      totalRR: total.toFixed(2),
    };
  }, [signals, totalTrades]);

  // Paginate
  const totalPages = Math.max(1, Math.ceil(filteredSignals.length / ITEMS_PER_PAGE));
  const paginatedSignals = filteredSignals.slice((page - 1) * ITEMS_PER_PAGE, page * ITEMS_PER_PAGE);

  // Reset page when filters change (using a ref to track previous values)
  const prevFiltersRef = useRef({ searchQuery, filterOutcome, filterDirection, filterStrength });
  useEffect(() => {
    const prev = prevFiltersRef.current;
    if (
      prev.searchQuery !== searchQuery ||
      prev.filterOutcome !== filterOutcome ||
      prev.filterDirection !== filterDirection ||
      prev.filterStrength !== filterStrength
    ) {
      setPage(1);
      prevFiltersRef.current = { searchQuery, filterOutcome, filterDirection, filterStrength };
    }
  }, [searchQuery, filterOutcome, filterDirection, filterStrength]);

  // Get unique values for dropdowns from data
  const outcomes = ["ALL", "WIN", "LOSS", "BREAKEVEN", "EXPIRED"];
  const directions = ["ALL", "LONG", "SHORT"];
  const strengths = ["ALL", ...Array.from(new Set(signals.map((s) => s.strength).filter(Boolean) as string[]))];

  // Sparkline data for stat cards (last 7 data points - placeholder until real history is available)
  const winRateHistory = totalTrades > 0 ? [parseFloat(winRate)] : [0];
  const rrHistory = totalTrades > 0 ? [parseFloat(avgRR)] : [0];
  const tradeHistory = totalTrades > 0 ? [totalTrades] : [0];
  const totalRRHistory = totalTrades > 0 ? [parseFloat(totalRR)] : [0];

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">Trade History</h1>
            <p className="text-sm text-slate-400 mt-1">
              Review and analyze your past trading signals
            </p>
          </div>
          <div className="flex items-center gap-2 text-sm text-slate-400">
            <span>{filteredSignals.length} trades found</span>
          </div>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-4 gap-4">
          <StatCard
            title="Win Rate"
            value={`${winRate}%`}
            subtitle={`${winCount}W / ${lossCount}L / ${beCount}BE`}
            sparkData={winRateHistory}
            valueColor={parseFloat(winRate) >= 50 ? "text-emerald-400" : "text-red-400"}
          />
          <StatCard
            title="Avg RR"
            value={`${parseFloat(avgRR) >= 0 ? "+" : ""}${avgRR}`}
            subtitle="Average Risk-Reward"
            sparkData={rrHistory}
            valueColor={parseFloat(avgRR) >= 0 ? "text-emerald-400" : "text-red-400"}
          />
          <StatCard
            title="Total Trades"
            value={String(totalTrades)}
            subtitle="Completed Trades"
            sparkData={tradeHistory}
            valueColor="text-white"
          />
          <StatCard
            title="Total RR"
            value={`${parseFloat(totalRR) >= 0 ? "+" : ""}${totalRR}`}
            subtitle="Cumulative RR"
            sparkData={totalRRHistory}
            valueColor={parseFloat(totalRR) >= 0 ? "text-emerald-400" : "text-red-400"}
          />
        </div>

        {/* Filters */}
        <Card className="bg-[#111827] border-[#1e293b]">
          <CardContent className="p-4">
            <div className="flex items-center gap-4">
              {/* Search */}
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search by symbol, direction, status..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full bg-[#1e293b] border border-[#1e293b] rounded-lg pl-9 pr-4 py-2 text-sm text-white placeholder-slate-400 focus:outline-none focus:border-emerald-500/50"
                />
              </div>
              {/* Outcome */}
              <select
                value={filterOutcome}
                onChange={(e) => setFilterOutcome(e.target.value)}
                className="bg-[#1e293b] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500/50"
              >
                {outcomes.map((o) => (
                  <option key={o} value={o}>
                    {o === "ALL" ? "All Outcomes" : o}
                  </option>
                ))}
              </select>
              {/* Direction */}
              <select
                value={filterDirection}
                onChange={(e) => setFilterDirection(e.target.value)}
                className="bg-[#1e293b] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500/50"
              >
                {directions.map((d) => (
                  <option key={d} value={d}>
                    {d === "ALL" ? "All Directions" : d}
                  </option>
                ))}
              </select>
              {/* Strength */}
              <select
                value={filterStrength}
                onChange={(e) => setFilterStrength(e.target.value)}
                className="bg-[#1e293b] border border-[#1e293b] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500/50"
              >
                {strengths.map((s) => (
                  <option key={s} value={s}>
                    {s === "ALL" ? "All Strengths" : s}
                  </option>
                ))}
              </select>
              {/* Reset */}
              {(searchQuery || filterOutcome !== "ALL" || filterDirection !== "ALL" || filterStrength !== "ALL") && (
                <button
                  onClick={() => {
                    setSearchQuery("");
                    setFilterOutcome("ALL");
                    setFilterDirection("ALL");
                    setFilterStrength("ALL");
                  }}
                  className="text-sm text-emerald-400 hover:text-emerald-300 whitespace-nowrap"
                >
                  Clear Filters
                </button>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Trade Table */}
        <Card className="bg-[#111827] border-[#1e293b]">
          <CardContent className="p-0">
            {loading ? (
              <div className="animate-pulse p-5 space-y-4">
                {[...Array(8)].map((_, i) => (
                  <div key={i} className="flex items-center gap-4">
                    <div className="h-4 w-24 bg-[#1e293b] rounded" />
                    <div className="h-4 w-16 bg-[#1e293b] rounded" />
                    <div className="h-4 w-16 bg-[#1e293b] rounded" />
                    <div className="h-4 w-16 bg-[#1e293b] rounded" />
                    <div className="h-4 w-16 bg-[#1e293b] rounded" />
                    <div className="h-4 w-16 bg-[#1e293b] rounded" />
                    <div className="h-4 w-12 bg-[#1e293b] rounded" />
                    <div className="h-4 w-20 bg-[#1e293b] rounded" />
                  </div>
                ))}
              </div>
            ) : error ? (
              <div className="flex items-center justify-center h-64 text-red-400">
                Error: {error}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-[#1e293b]">
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-3 py-3">Symbol</th>
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-2 py-3">Direction</th>
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-2 py-3">Entry</th>
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-2 py-3">SL</th>
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-2 py-3">TP1</th>
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-2 py-3">TP2</th>
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-2 py-3">TP3</th>
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-2 py-3">TP4</th>
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-2 py-3">RR</th>
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-2 py-3">Quality</th>
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-2 py-3">Outcome</th>
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-2 py-3">Strength</th>
                      <th className="text-left text-xs text-slate-500 uppercase tracking-wide px-2 py-3">Closed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedSignals.length === 0 ? (
                      <tr>
                        <td colSpan={13} className="text-center py-12 text-slate-400">
                          No trades found matching your filters
                        </td>
                      </tr>
                    ) : (
                      paginatedSignals.map((signal) => {
                        const rr = calculateRR(signal);
                        const isLong = signal.direction === "LONG";
                        const closedDate = signal.closed_at
                          ? new Date(signal.closed_at).toLocaleDateString() + " " + new Date(signal.closed_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                          : "-";
                        const firedDate = signal.fired_at
                          ? new Date(signal.fired_at).toLocaleDateString() + " " + new Date(signal.fired_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                          : "-";

                        return (
                          <tr
                            key={signal.id}
                            className="border-b border-[#1e293b]/50 hover:bg-[#1e293b]/30 transition-colors"
                          >
                            <td className="px-3 py-2.5">
                              <span className="text-sm font-semibold text-white">{signal.symbol}</span>
                            </td>
                            <td className="px-2 py-2.5">
                              <Badge
                                variant="outline"
                                className={
                                  isLong
                                    ? "border-emerald-500/30 text-emerald-400 bg-emerald-500/10 text-xs"
                                    : "border-red-500/30 text-red-400 bg-red-500/10 text-xs"
                                }
                              >
                                {isLong ? <TrendingUp className="w-3 h-3 mr-1" /> : <TrendingDown className="w-3 h-3 mr-1" />}
                                {signal.direction}
                              </Badge>
                            </td>
                            <td className="px-2 py-2.5 text-xs text-white">{formatPrice(signal.entry)}</td>
                            <td className="px-2 py-2.5 text-xs text-red-400">{formatPrice(signal.sl)}</td>
                            <td className="px-2 py-2.5 text-xs text-emerald-400">{formatPrice(signal.tp1)}</td>
                            <td className="px-2 py-2.5 text-xs text-emerald-400">{formatPrice(signal.tp2)}</td>
                            <td className="px-2 py-2.5 text-xs text-emerald-400">{formatPrice(signal.tp3)}</td>
                            <td className="px-2 py-2.5 text-xs text-emerald-400">{formatPrice(signal.tp4)}</td>
                            <td className="px-2 py-2.5">
                              <span className={`text-xs font-bold ${rr > 0 ? "text-emerald-400" : rr < 0 ? "text-red-400" : "text-slate-400"}`}>
                                {rr > 0 ? "+" : ""}{rr.toFixed(2)}R
                              </span>
                            </td>
                            <td className="px-2 py-2.5">
                              <span className={`text-xs font-medium ${signal.quality_score >= 70 ? "text-emerald-400" : signal.quality_score >= 50 ? "text-amber-400" : "text-red-400"}`}>
                                {signal.quality_score.toFixed(1)}
                              </span>
                            </td>
                            <td className="px-2 py-2.5">
                              <Badge
                                variant="outline"
                                className={`${outcomeColors[signal.status] || outcomeColors.EXPIRED} text-xs`}
                              >
                                {signal.status}
                              </Badge>
                            </td>
                            <td className="px-2 py-2.5">
                              <Badge
                                variant="outline"
                                className={
                                  signal.strength === "STRONG"
                                    ? "border-purple-500/30 text-purple-400 bg-purple-500/10 text-xs"
                                    : "border-amber-500/30 text-amber-400 bg-amber-500/10 text-xs"
                                }
                              >
                                {signal.strength || "STANDARD"}
                              </Badge>
                            </td>
                            <td className="px-2 py-2.5 text-xs text-slate-400 whitespace-nowrap">
                              {closedDate !== "-" ? closedDate : firedDate}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between px-5 py-3 border-t border-[#1e293b]">
                <span className="text-sm text-slate-400">
                  Showing {(page - 1) * ITEMS_PER_PAGE + 1}-{Math.min(page * ITEMS_PER_PAGE, filteredSignals.length)} of {filteredSignals.length}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPage(Math.max(1, page - 1))}
                    disabled={page === 1}
                    className="px-3 py-1 text-sm bg-[#1e293b] rounded text-white disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[#2d3748]"
                  >
                    Previous
                  </button>
                  {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
                    let pageNum: number;
                    if (totalPages <= 5) {
                      pageNum = i + 1;
                    } else if (page <= 3) {
                      pageNum = i + 1;
                    } else if (page >= totalPages - 2) {
                      pageNum = totalPages - 4 + i;
                    } else {
                      pageNum = page - 2 + i;
                    }
                    return (
                      <button
                        key={pageNum}
                        onClick={() => setPage(pageNum)}
                        className={`px-3 py-1 text-sm rounded ${
                          page === pageNum
                            ? "bg-emerald-500 text-white"
                            : "bg-[#1e293b] text-white hover:bg-[#2d3748]"
                        }`}
                      >
                        {pageNum}
                      </button>
                    );
                  })}
                  <button
                    onClick={() => setPage(Math.min(totalPages, page + 1))}
                    disabled={page === totalPages}
                    className="px-3 py-1 text-sm bg-[#1e293b] rounded text-white disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[#2d3748]"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </DashboardLayout>
  );
}