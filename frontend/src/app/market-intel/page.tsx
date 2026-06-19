"use client";

import { useState, useEffect, useMemo } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Calendar,
  Newspaper,
  AlertTriangle,
  ExternalLink,
  Clock,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  X,
  Filter,
  TrendingUp,
  Globe,
} from "lucide-react";
import {
  getEconomicCalendar,
  getCryptoNews,
  getTokenEvents,
  getImpactAnalysis,
  getOpenSignals,
  EconomicEvent,
  CryptoNews,
  TokenEvent,
  ImpactCorrelation,
} from "@/lib/api";

// ─── Formatters ────────────────────────────────────────────────────────────────

function formatDate(dateStr: string): string {
  const date = new Date(dateStr);
  const today = new Date();
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);

  if (date.toDateString() === today.toDateString()) return "Today";
  if (date.toDateString() === tomorrow.toDateString()) return "Tomorrow";

  return date.toLocaleDateString("en-US", {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
}

function formatShortDate(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatTime(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

function formatTimeAgo(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHrs = Math.floor(diffMs / 3600000);
  if (diffMins < 1) return "Now";
  if (diffMins < 60) return `${diffMins}m`;
  if (diffHrs < 24) return `${diffHrs}h`;
  const diffDays = Math.floor(diffHrs / 24);
  return `${diffDays}d`;
}

// ─── Impact configuration ────────────────────────────────────────────────────

const impactConfig = {
  HIGH: {
    label: "High",
    bar: "bg-rose-500",
    text: "text-rose-400",
    bg: "bg-rose-500/10",
    border: "border-rose-500/30",
    glow: "shadow-rose-500/20",
  },
  MEDIUM: {
    label: "Medium",
    bar: "bg-amber-400",
    text: "text-amber-400",
    bg: "bg-amber-500/10",
    border: "border-amber-500/30",
    glow: "shadow-amber-500/20",
  },
  LOW: {
    label: "Low",
    bar: "bg-slate-500",
    text: "text-slate-400",
    bg: "bg-slate-500/10",
    border: "border-slate-500/30",
    glow: "",
  },
};

function ImpactBars({ impact }: { impact: string }) {
  const count = impact === "HIGH" ? 3 : impact === "MEDIUM" ? 2 : 1;
  const cfg = impactConfig[impact as keyof typeof impactConfig] || impactConfig.LOW;
  return (
    <div className="flex items-center gap-[2px]" title={cfg.label}>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className={`w-[3px] h-3 rounded-sm ${i < count ? cfg.bar : "bg-slate-700"}`}
        />
      ))}
    </div>
  );
}

// ─── Component ─────────────────────────────────────────────────────────────────

export default function MarketIntelPage() {
  const [calendar, setCalendar] = useState<EconomicEvent[]>([]);
  const [news, setNews] = useState<CryptoNews[]>([]);
  const [tokenEvents, setTokenEvents] = useState<TokenEvent[]>([]);
  const [impactAnalysis, setImpactAnalysis] = useState<ImpactCorrelation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Filters
  const [selectedImpacts, setSelectedImpacts] = useState<Set<string>>(
    new Set(["HIGH", "MEDIUM"])
  );
  const [expandedDates, setExpandedDates] = useState<Set<string>>(new Set());
  const [dismissedAlert, setDismissedAlert] = useState<string | null>(null);
  const [newsFilter, setNewsFilter] = useState<"all" | "high-impact">("all");

  useEffect(() => {
    async function fetchData() {
      try {
        const [cal, newsData, events, impact] = await Promise.all([
          getEconomicCalendar(),
          getCryptoNews(),
          getTokenEvents(),
          getImpactAnalysis(),
        ]);
        setCalendar(cal);
        setNews(newsData);
        setTokenEvents(events);
        setImpactAnalysis(impact);
        setLastUpdated(new Date());
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to fetch market intel");
      } finally {
        setLoading(false);
      }
    }
    fetchData();
    const interval = setInterval(fetchData, 300000);
    return () => clearInterval(interval);
  }, []);

  // Filter calendar
  const filteredCalendar = useMemo(
    () => calendar.filter((e) => selectedImpacts.has(e.impact)),
    [calendar, selectedImpacts]
  );

  // Group calendar by date
  const calendarByDate = useMemo(() => {
    const grouped: Record<string, EconomicEvent[]> = {};
    filteredCalendar.forEach((event) => {
      const date = new Date(event.timestamp).toDateString();
      if (!grouped[date]) grouped[date] = [];
      grouped[date].push(event);
    });
    return grouped;
  }, [filteredCalendar]);

  // Filter news
  const filteredNews = useMemo(() => {
    if (newsFilter === "high-impact") {
      return news.filter((n) => n.sentiment !== "neutral");
    }
    return news.slice(0, 8);
  }, [news, newsFilter]);

  // Auto-expand today
  useEffect(() => {
    const dates = Object.keys(calendarByDate);
    if (dates.length > 0) {
      const today = new Date().toDateString();
      const defaultExpanded = dates.find((d) => d === today) || dates[0];
      setExpandedDates((prev) =>
        prev.size === 0 ? new Set([defaultExpanded]) : prev
      );
    }
  }, [calendarByDate]);

  const toggleDate = (date: string) => {
    setExpandedDates((prev) => {
      const next = new Set(prev);
      next.has(date) ? next.delete(date) : next.add(date);
      return next;
    });
  };

  const toggleImpact = (impact: string) => {
    setSelectedImpacts((prev) => {
      const next = new Set(prev);
      if (next.has(impact)) {
        if (next.size > 1) next.delete(impact);
      } else {
        next.add(impact);
      }
      return next;
    });
  };

  // Deduplicate alerts
  const uniqueAlerts = useMemo(() => {
    const seen = new Set<string>();
    return impactAnalysis.filter((a) => {
      if (seen.has(a.event_id)) return false;
      seen.add(a.event_id);
      return true;
    });
  }, [impactAnalysis]);

  const hasHighImpactEvents = tokenEvents.some((e) => e.impact === "HIGH");

  if (loading) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center h-64">
          <div className="text-slate-400">Loading market intel...</div>
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
      <div className="space-y-4">
        {/* ═══════════════════════════════════════════════════════════════
            HEADER ROW
           ═══════════════════════════════════════════════════════════════ */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Globe className="w-5 h-5 text-emerald-400" />
            <div>
              <h1 className="text-lg font-semibold text-white">Market Intel</h1>
              <p className="text-xs text-slate-500">
                {Intl.DateTimeFormat().resolvedOptions().timeZone} · Next 14 days
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span className="text-xs text-slate-500">
                {lastUpdated.toLocaleTimeString()}
              </span>
            )}
            <button
              onClick={() => window.location.reload()}
              className="p-1.5 text-slate-400 hover:text-white hover:bg-slate-800 rounded transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* ═══════════════════════════════════════════════════════════════
            IMPACT ALERT BANNER
           ═══════════════════════════════════════════════════════════════ */}
        {uniqueAlerts.length > 0 && uniqueAlerts[0].event_id !== dismissedAlert && (
          <div className="relative bg-gradient-to-r from-amber-500/10 via-amber-500/5 to-transparent border border-amber-500/20 rounded-lg p-3">
            <button
              onClick={() => setDismissedAlert(uniqueAlerts[0].event_id)}
              className="absolute top-2 right-2 text-slate-500 hover:text-slate-300"
            >
              <X className="w-3.5 h-3.5" />
            </button>
            <div className="flex items-start gap-3">
              <div className="p-1.5 bg-amber-500/10 rounded-lg">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-sm font-medium text-amber-400">
                  Events affecting your {uniqueAlerts[0].affected_symbols.length} open positions
                </h3>
                <p className="text-xs text-slate-400 mt-1">
                  {uniqueAlerts.slice(0, 2).map((a, i) => (
                    <span key={a.event_id}>
                      {i > 0 && " · "}
                      <span className="text-slate-300">{a.event_title}</span>
                      <span className="text-slate-500"> ({a.risk_adjustment})</span>
                    </span>
                  ))}
                  {uniqueAlerts.length > 2 && (
                    <span className="text-slate-500">
                      {" "}+ {uniqueAlerts.length - 2} more
                    </span>
                  )}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* ═══════════════════════════════════════════════════════════════
            IMPACT FILTER CHIPS
           ═══════════════════════════════════════════════════════════════ */}
        <div className="flex items-center gap-2">
          <Filter className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-xs text-slate-500 mr-1">Impact:</span>
          {(["HIGH", "MEDIUM", "LOW"] as const).map((impact) => {
            const cfg = impactConfig[impact];
            const active = selectedImpacts.has(impact);
            return (
              <button
                key={impact}
                onClick={() => toggleImpact(impact)}
                className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-medium transition-all ${
                  active
                    ? `${cfg.bg} ${cfg.text} border ${cfg.border}`
                    : "bg-slate-800 text-slate-600 border border-slate-700"
                }`}
              >
                <ImpactBars impact={impact} />
                {cfg.label}
              </button>
            );
          })}
          <span className="text-xs text-slate-600 ml-2">
            {filteredCalendar.length} events
          </span>
        </div>

        {/* ═══════════════════════════════════════════════════════════════
            MAIN LAYOUT: CALENDAR (2/3) + SIDEBAR (1/3)
           ═══════════════════════════════════════════════════════════════ */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          {/* LEFT COLUMN: Economic Calendar (2/3 width) */}
          <div className="xl:col-span-2 space-y-4">
            <Card className="bg-[#141824] border-[#1e293b] overflow-hidden">
              <CardHeader className="border-b border-[#1e293b] bg-[#111318] py-3">
                <div className="flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-emerald-400" />
                  <CardTitle className="text-sm font-semibold text-white">
                    Economic Calendar
                  </CardTitle>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                {/* Table Header */}
                <div className="grid grid-cols-[80px_50px_1fr_50px_70px_70px_70px] gap-2 px-4 py-2 bg-[#0d1117] border-b border-[#1e293b] text-[10px] text-slate-500 uppercase tracking-wider font-medium">
                  <div>Time</div>
                  <div>Curr</div>
                  <div>Event</div>
                  <div className="text-center">Imp</div>
                  <div className="text-right">Act</div>
                  <div className="text-right">Fore</div>
                  <div className="text-right">Prev</div>
                </div>

                {/* Table Body */}
                <div className="max-h-[480px] overflow-y-auto">
                  {Object.entries(calendarByDate).length === 0 ? (
                    <div className="p-8 text-center text-slate-400 text-sm">
                      No events match filters
                    </div>
                  ) : (
                    Object.entries(calendarByDate).map(([date, events]) => {
                      const isExpanded = expandedDates.has(date);
                      const isToday =
                        new Date(date).toDateString() === new Date().toDateString();
                      return (
                        <div key={date}>
                          {/* Date Header */}
                          <button
                            onClick={() => toggleDate(date)}
                            className={`w-full flex items-center gap-2 px-4 py-2 border-b border-[#1e293b] hover:bg-[#1a1f2e] transition-colors ${
                              isToday ? "bg-[#1e2533]/50" : "bg-[#111318]"
                            }`}
                          >
                            {isExpanded ? (
                              <ChevronDown className="w-3.5 h-3.5 text-slate-500" />
                            ) : (
                              <ChevronRight className="w-3.5 h-3.5 text-slate-500" />
                            )}
                            <span
                              className={`text-xs font-semibold ${
                                isToday ? "text-white" : "text-slate-300"
                              }`}
                            >
                              {formatDate(date)}
                            </span>
                            {isToday && (
                              <span className="px-1.5 py-0.5 bg-emerald-500/10 text-emerald-400 text-[9px] rounded font-medium">
                                TODAY
                              </span>
                            )}
                            <span className="text-[11px] text-slate-600">
                              {events.length}
                            </span>
                          </button>

                          {/* Event Rows */}
                          {isExpanded &&
                            events.map((event) => {
                              const cfg =
                                impactConfig[event.impact as keyof typeof impactConfig];
                              const affectsMe = uniqueAlerts.some(
                                (a) => a.event_id === event.id
                              );
                              return (
                                <div
                                  key={event.id}
                                  className={`grid grid-cols-[80px_50px_1fr_50px_70px_70px_70px] gap-2 px-4 py-2.5 border-b border-[#1e293b]/30 hover:bg-[#1a1f2e]/30 transition-colors items-center ${
                                    event.impact === "HIGH"
                                      ? "bg-rose-500/[0.03]"
                                      : ""
                                  }`}
                                >
                                  {/* Time */}
                                  <div className="flex items-center gap-1.5">
                                    {event.impact === "HIGH" && (
                                      <div className="w-1 h-4 bg-rose-500 rounded-full" />
                                    )}
                                    <span
                                      className={`text-[11px] tabular-nums ${
                                        event.impact === "HIGH"
                                          ? "text-white font-medium"
                                          : "text-slate-400"
                                      }`}
                                    >
                                      {formatTime(event.timestamp)}
                                    </span>
                                  </div>

                                  {/* Currency */}
                                  <span
                                    className={`text-[10px] font-bold text-center ${
                                      event.currency === "USD"
                                        ? "text-blue-400"
                                        : event.currency === "EUR"
                                        ? "text-indigo-400"
                                        : "text-slate-400"
                                    }`}
                                  >
                                    {event.currency}
                                  </span>

                                  {/* Event Name */}
                                  <div className="flex items-center gap-1.5 min-w-0">
                                    <span
                                      className={`text-xs truncate ${
                                        event.impact === "HIGH"
                                          ? "text-white font-medium"
                                          : "text-slate-200"
                                      }`}
                                    >
                                      {event.title}
                                    </span>
                                    {affectsMe && (
                                      <div
                                        className="w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0"
                                        title="Affects your positions"
                                      />
                                    )}
                                  </div>

                                  {/* Impact */}
                                  <div className="flex justify-center">
                                    <ImpactBars impact={event.impact} />
                                  </div>

                                  {/* Actual */}
                                  <div className="text-right">
                                    <span
                                      className={`text-[11px] font-mono tabular-nums ${
                                        event.actual ? "text-white" : "text-slate-600"
                                      }`}
                                    >
                                      {event.actual || "—"}
                                    </span>
                                  </div>

                                  {/* Forecast */}
                                  <div className="text-right">
                                    <span className="text-[11px] font-mono tabular-nums text-slate-500">
                                      {event.forecast || "—"}
                                    </span>
                                  </div>

                                  {/* Previous */}
                                  <div className="text-right">
                                    <span className="text-[11px] font-mono tabular-nums text-slate-600">
                                      {event.previous || "—"}
                                    </span>
                                  </div>
                                </div>
                              );
                            })}
                        </div>
                      );
                    })
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Bottom: Token Events */}
            <Card className="bg-[#141824] border-[#1e293b]">
              <CardHeader className="border-b border-[#1e293b] bg-[#111318] py-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-purple-400" />
                    <CardTitle className="text-sm font-semibold text-white">
                      Token Events
                    </CardTitle>
                  </div>
                  {hasHighImpactEvents && (
                    <span className="text-[10px] text-rose-400">
                      High impact events upcoming
                    </span>
                  )}
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-[#1e293b]">
                  {tokenEvents.length === 0 ? (
                    <div className="col-span-2 p-6 text-center text-slate-400 text-sm">
                      No upcoming token events
                    </div>
                  ) : (
                    tokenEvents.slice(0, 4).map((event) => {
                      const cfg =
                        impactConfig[event.impact as keyof typeof impactConfig];
                      return (
                        <div
                          key={event.id}
                          className={`flex items-center gap-3 p-3 bg-[#141824] hover:bg-[#1a1f2e] transition-colors ${
                            event.impact === "HIGH" ? "border-l-2 border-l-rose-500" : ""
                          }`}
                        >
                          {/* Token icon placeholder */}
                          <div className="w-8 h-8 rounded-lg bg-slate-700/50 flex items-center justify-center flex-shrink-0">
                            <span className="text-[10px] font-bold text-white">
                              {event.token.slice(0, 3)}
                            </span>
                          </div>

                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-semibold text-white">
                                {event.token}
                              </span>
                              <span
                                className={`text-[9px] px-1 py-0.5 rounded ${cfg.bg} ${cfg.text}`}
                              >
                                {event.impact}
                              </span>
                            </div>
                            <p className="text-[11px] text-slate-400 truncate">
                              {event.description}
                            </p>
                            <p className="text-[10px] text-slate-500 mt-0.5">
                              {formatShortDate(event.timestamp)} · {event.event_type}
                            </p>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </CardContent>
            </Card>
          </div>

          {/* RIGHT COLUMN: News Sidebar (1/3 width) */}
          <div className="space-y-4">
            <Card className="bg-[#141824] border-[#1e293b] h-full max-h-[680px]">
              <CardHeader className="border-b border-[#1e293b] bg-[#111318] py-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Newspaper className="w-4 h-4 text-blue-400" />
                    <CardTitle className="text-sm font-semibold text-white">
                      Latest News
                    </CardTitle>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setNewsFilter("all")}
                      className={`px-2 py-0.5 rounded text-[10px] transition-colors ${
                        newsFilter === "all"
                          ? "bg-slate-700 text-white"
                          : "text-slate-500 hover:text-slate-300"
                      }`}
                    >
                      All
                    </button>
                    <button
                      onClick={() => setNewsFilter("high-impact")}
                      className={`px-2 py-0.5 rounded text-[10px] transition-colors ${
                        newsFilter === "high-impact"
                          ? "bg-amber-500/20 text-amber-400"
                          : "text-slate-500 hover:text-slate-300"
                      }`}
                    >
                      Impact
                    </button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                <div className="max-h-[620px] overflow-y-auto">
                  {filteredNews.length === 0 ? (
                    <div className="p-6 text-center text-slate-400 text-sm">
                      No news available
                    </div>
                  ) : (
                    <div className="divide-y divide-[#1e293b]/40">
                      {filteredNews.map((item) => (
                        <div
                          key={item.id}
                          className="p-3 hover:bg-[#1a1f2e]/30 transition-colors"
                        >
                          <div className="flex items-start justify-between gap-2">
                            <h4 className="text-xs text-slate-200 leading-snug line-clamp-2 flex-1">
                              {item.title}
                            </h4>
                            {item.sentiment && (
                              <span
                                className={`text-xs font-bold flex-shrink-0 ${
                                  item.sentiment === "positive"
                                    ? "text-emerald-400"
                                    : item.sentiment === "negative"
                                    ? "text-rose-400"
                                    : "text-slate-400"
                                }`}
                              >
                                {item.sentiment === "positive"
                                  ? "+"
                                  : item.sentiment === "negative"
                                  ? "−"
                                  : "•"}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-2 mt-1.5">
                            <span className="text-[10px] text-slate-500 font-medium uppercase">
                              {item.source}
                            </span>
                            <span className="text-[10px] text-slate-600">·</span>
                            <span className="text-[10px] text-slate-500">
                              {formatTimeAgo(item.published_at)}
                            </span>
                          </div>
                          {item.currencies.length > 0 && (
                            <div className="flex items-center gap-1 mt-1.5">
                              {item.currencies.slice(0, 3).map((c) => (
                                <span
                                  key={c}
                                  className="text-[9px] text-slate-400 bg-slate-800 px-1 py-0.5 rounded"
                                >
                                  {c}
                                </span>
                              ))}
                            </div>
                          )}
                          {item.url && (
                            <a
                              href={item.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 mt-2 text-[10px] text-blue-400 hover:text-blue-300 transition-colors"
                            >
                              Read <ExternalLink className="w-2.5 h-2.5" />
                            </a>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
