"use client";

import { useState, useEffect, useMemo } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  Calendar,
  Newspaper,
  AlertTriangle,
  ExternalLink,
  Clock,
  RefreshCw,
  ChevronLeft,
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
    text: "text-muted-foreground",
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
          className={`w-[3px] h-3 rounded-sm ${i < count ? cfg.bar : "bg-muted"}`}
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
  const [dismissedAlert, setDismissedAlert] = useState<string | null>(null);
  const [newsFilter, setNewsFilter] = useState<"all" | "high-impact">("all");

  // macOS Calendar state
  const [currentMonth, setCurrentMonth] = useState(new Date());
  const [selectedDate, setSelectedDate] = useState<string | null>(null);

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

  // Group calendar events by date string
  const eventsByDate = useMemo(() => {
    const grouped: Record<string, EconomicEvent[]> = {};
    filteredCalendar.forEach((event) => {
      const dateKey = new Date(event.timestamp).toDateString();
      if (!grouped[dateKey]) grouped[dateKey] = [];
      grouped[dateKey].push(event);
    });
    return grouped;
  }, [filteredCalendar]);

  // Calendar grid helpers
  const getDaysInMonth = (year: number, month: number) =>
    new Date(year, month + 1, 0).getDate();
  const getFirstDayOfMonth = (year: number, month: number) =>
    new Date(year, month, 1).getDay();

  const calendarDays = useMemo(() => {
    const year = currentMonth.getFullYear();
    const month = currentMonth.getMonth();
    const daysInMonth = getDaysInMonth(year, month);
    const firstDay = getFirstDayOfMonth(year, month);
    const days: { date: Date; padding: boolean }[] = [];

    const prevMonthDays = getDaysInMonth(year, month - 1);
    for (let i = firstDay - 1; i >= 0; i--) {
      days.push({
        date: new Date(year, month - 1, prevMonthDays - i),
        padding: true,
      });
    }
    for (let i = 1; i <= daysInMonth; i++) {
      days.push({ date: new Date(year, month, i), padding: false });
    }
    const remaining = 42 - days.length;
    for (let i = 1; i <= remaining; i++) {
      days.push({ date: new Date(year, month + 1, i), padding: true });
    }
    return days;
  }, [currentMonth]);

  const weekDays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  // Auto-select today if it has events, otherwise first event date
  useEffect(() => {
    if (selectedDate) return;
    const today = new Date().toDateString();
    if (eventsByDate[today]?.length > 0) {
      setSelectedDate(today);
    } else {
      const firstDate = Object.keys(eventsByDate)[0];
      if (firstDate) setSelectedDate(firstDate);
    }
  }, [eventsByDate, selectedDate]);

  const selectedEvents = selectedDate ? eventsByDate[selectedDate] || [] : [];

  // Filter news
  const filteredNews = useMemo(() => {
    if (newsFilter === "high-impact") {
      return news.filter((n) => n.sentiment !== "neutral");
    }
    return news.slice(0, 8);
  }, [news, newsFilter]);

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
        <div className="space-y-6 animate-pulse">
          <div className="h-8 w-40 bg-muted rounded" />
          <div className="grid grid-cols-3 gap-6">
            <div className="col-span-2 bg-card border border-border rounded-xl p-5 space-y-4">
              <div className="h-4 w-36 bg-muted rounded" />
              {[...Array(5)].map((_, i) => (
                <div key={i} className="flex items-center gap-4">
                  <div className="h-4 w-20 bg-muted rounded" />
                  <div className="h-4 w-32 bg-muted rounded" />
                  <div className="h-4 w-16 bg-muted rounded" />
                </div>
              ))}
            </div>
            <div className="bg-card border border-border rounded-xl p-5 space-y-4">
              <div className="h-4 w-28 bg-muted rounded" />
              <div className="h-32 bg-muted/50 rounded" />
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
              <h1 className="text-lg font-semibold text-foreground">Market Intel</h1>
              <p className="text-xs text-muted-foreground">
                {Intl.DateTimeFormat().resolvedOptions().timeZone} · Next 14 days
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {lastUpdated && (
              <span className="text-xs text-muted-foreground">
                {lastUpdated.toLocaleTimeString()}
              </span>
            )}
            <button
              onClick={() => window.location.reload()}
              className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-muted rounded transition-colors"
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
              className="absolute top-2 right-2 text-muted-foreground hover:text-foreground/80"
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
                <p className="text-xs text-muted-foreground mt-1">
                  {uniqueAlerts.slice(0, 2).map((a, i) => (
                    <span key={a.event_id}>
                      {i > 0 && " · "}
                      <span className="text-foreground/80">{a.event_title}</span>
                      <span className="text-muted-foreground"> ({a.risk_adjustment})</span>
                    </span>
                  ))}
                  {uniqueAlerts.length > 2 && (
                    <span className="text-muted-foreground">
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
          <Filter className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-xs text-muted-foreground mr-1">Impact:</span>
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
                    : "bg-muted text-muted-foreground/70 border border-border"
                }`}
              >
                <ImpactBars impact={impact} />
                {cfg.label}
              </button>
            );
          })}
          <span className="text-xs text-muted-foreground/70 ml-2">
            {filteredCalendar.length} events
          </span>
        </div>

        {/* ═══════════════════════════════════════════════════════════════
            MAIN LAYOUT: CALENDAR (2/3) + SIDEBAR (1/3)
           ═══════════════════════════════════════════════════════════════ */}
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
          {/* LEFT COLUMN: Economic Calendar (2/3 width) */}
          <div className="xl:col-span-2 space-y-4">
            <Card className="bg-card border-border overflow-hidden">
              <CardHeader className="border-b border-border bg-card py-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Calendar className="w-4 h-4 text-emerald-400" />
                    <CardTitle className="text-sm font-semibold text-foreground">
                      Economic Calendar
                    </CardTitle>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() =>
                        setCurrentMonth(
                          new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1)
                        )
                      }
                      className="p-1 text-muted-foreground hover:text-foreground hover:bg-muted rounded transition-colors"
                    >
                      <ChevronLeft className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => setCurrentMonth(new Date())}
                      className="px-2 py-1 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted rounded transition-colors"
                    >
                      Today
                    </button>
                    <button
                      onClick={() =>
                        setCurrentMonth(
                          new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1)
                        )
                      }
                      className="p-1 text-muted-foreground hover:text-foreground hover:bg-muted rounded transition-colors"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="p-0">
                {/* macOS-style Calendar */}
                <div className="p-4">
                  {/* Month / Year header */}
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-lg font-semibold text-foreground">
                      {currentMonth.toLocaleDateString("en-US", {
                        month: "long",
                        year: "numeric",
                      })}
                    </h2>
                    <span className="text-xs text-muted-foreground">
                      {filteredCalendar.length} events
                    </span>
                  </div>

                  {/* Weekday headers */}
                  <div className="grid grid-cols-7 mb-2">
                    {weekDays.map((day) => (
                      <div
                        key={day}
                        className="text-center text-[11px] font-medium text-muted-foreground py-1"
                      >
                        {day}
                      </div>
                    ))}
                  </div>

                  {/* Calendar grid */}
                  <div className="grid grid-cols-7 gap-px bg-border rounded-lg border border-border overflow-hidden">
                    {calendarDays.map(({ date, padding }, idx) => {
                      const dateKey = date.toDateString();
                      const isToday = dateKey === new Date().toDateString();
                      const isSelected = selectedDate === dateKey;
                      const dayEvents = eventsByDate[dateKey] || [];
                      const hasHigh = dayEvents.some((e) => e.impact === "HIGH");
                      const hasMedium = dayEvents.some((e) => e.impact === "MEDIUM");
                      const hasLow = dayEvents.some((e) => e.impact === "LOW");

                      return (
                        <button
                          key={idx}
                          onClick={() => setSelectedDate(dateKey)}
                          className={cn(
                            "min-h-[80px] p-1.5 text-left flex flex-col justify-between transition-colors",
                            padding
                              ? "bg-muted/30 text-muted-foreground/50"
                              : "bg-card hover:bg-muted/50 text-foreground"
                          )}
                        >
                          <div className="flex items-start justify-between">
                            <span
                              className={cn(
                                "text-xs font-medium w-6 h-6 flex items-center justify-center rounded-full",
                                isToday
                                  ? "bg-emerald-500 text-white"
                                  : isSelected && !padding
                                  ? "bg-primary text-primary-foreground"
                                  : ""
                              )}
                            >
                              {date.getDate()}
                            </span>
                            {dayEvents.length > 0 && (
                              <span className="text-[9px] text-muted-foreground">
                                {dayEvents.length}
                              </span>
                            )}
                          </div>

                          {/* Event indicators */}
                          {!padding && dayEvents.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1 content-end">
                              {hasHigh && (
                                <div className="h-1.5 w-1.5 rounded-full bg-rose-500" />
                              )}
                              {hasMedium && (
                                <div className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                              )}
                              {hasLow && (
                                <div className="h-1.5 w-1.5 rounded-full bg-slate-400" />
                              )}
                              {dayEvents.length > 3 && (
                                <span className="text-[8px] text-muted-foreground leading-none">
                                  +{dayEvents.length - 3}
                                </span>
                              )}
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Selected day event list */}
                <div className="border-t border-border bg-card">
                  <div className="px-4 py-2 border-b border-border bg-muted/50 flex items-center justify-between">
                    <span className="text-xs font-semibold text-foreground">
                      {selectedDate ? formatDate(selectedDate) : "Select a date"}
                    </span>
                    {selectedDate && (
                      <span className="text-[11px] text-muted-foreground">
                        {selectedEvents.length} event{selectedEvents.length !== 1 ? "s" : ""}
                      </span>
                    )}
                  </div>

                  <div className="max-h-[280px] overflow-y-auto">
                    {selectedEvents.length === 0 ? (
                      <div className="p-6 text-center text-muted-foreground text-sm">
                        {selectedDate
                          ? "No events on this date"
                          : "Select a date to view events"}
                      </div>
                    ) : (
                      selectedEvents.map((event) => {
                        const cfg =
                          impactConfig[event.impact as keyof typeof impactConfig];
                        const affectsMe = uniqueAlerts.some(
                          (a) => a.event_id === event.id
                        );
                        return (
                          <div
                            key={event.id}
                            className={`grid grid-cols-[70px_50px_1fr_50px_70px_70px_70px] gap-2 px-4 py-2.5 border-b border-border/30 hover:bg-muted/30 transition-colors items-center ${
                              event.impact === "HIGH" ? "bg-rose-500/[0.03]" : ""
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
                                    ? "text-foreground font-medium"
                                    : "text-muted-foreground"
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
                                  : "text-muted-foreground"
                              }`}
                            >
                              {event.currency}
                            </span>

                            {/* Event Name */}
                            <div className="flex items-center gap-1.5 min-w-0">
                              <span
                                className={`text-xs truncate ${
                                  event.impact === "HIGH"
                                    ? "text-foreground font-medium"
                                    : "text-foreground/90"
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
                                  event.actual
                                    ? "text-foreground"
                                    : "text-muted-foreground/70"
                                }`}
                              >
                                {event.actual || "—"}
                              </span>
                            </div>

                            {/* Forecast */}
                            <div className="text-right">
                              <span className="text-[11px] font-mono tabular-nums text-muted-foreground">
                                {event.forecast || "—"}
                              </span>
                            </div>

                            {/* Previous */}
                            <div className="text-right">
                              <span className="text-[11px] font-mono tabular-nums text-muted-foreground/70">
                                {event.previous || "—"}
                              </span>
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Bottom: Token Events */}
            <Card className="bg-card border-border">
              <CardHeader className="border-b border-border bg-card py-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <TrendingUp className="w-4 h-4 text-purple-400" />
                    <CardTitle className="text-sm font-semibold text-foreground">
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
                <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-muted">
                  {tokenEvents.length === 0 ? (
                    <div className="col-span-2 p-6 text-center text-muted-foreground text-sm">
                      No upcoming token events
                    </div>
                  ) : (
                    tokenEvents.slice(0, 4).map((event) => {
                      const cfg =
                        impactConfig[event.impact as keyof typeof impactConfig];
                      return (
                        <div
                          key={event.id}
                          className={`flex items-center gap-3 p-3 bg-card hover:bg-muted transition-colors ${
                            event.impact === "HIGH" ? "border-l-2 border-l-rose-500" : ""
                          }`}
                        >
                          {/* Token icon placeholder */}
                          <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center flex-shrink-0">
                            <span className="text-[10px] font-bold text-foreground">
                              {event.token.slice(0, 3)}
                            </span>
                          </div>

                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-semibold text-foreground">
                                {event.token}
                              </span>
                              <span
                                className={`text-[9px] px-1 py-0.5 rounded ${cfg.bg} ${cfg.text}`}
                              >
                                {event.impact}
                              </span>
                            </div>
                            <p className="text-[11px] text-muted-foreground truncate">
                              {event.description}
                            </p>
                            <p className="text-[10px] text-muted-foreground mt-0.5">
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
            <Card className="bg-card border-border h-full max-h-[680px]">
              <CardHeader className="border-b border-border bg-card py-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Newspaper className="w-4 h-4 text-blue-400" />
                    <CardTitle className="text-base font-semibold text-foreground">
                      Latest News
                    </CardTitle>
                  </div>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setNewsFilter("all")}
                      className={`px-2.5 py-1 rounded text-xs transition-colors ${
                        newsFilter === "all"
                          ? "bg-muted text-foreground"
                          : "text-muted-foreground hover:text-foreground/80"
                      }`}
                    >
                      All
                    </button>
                    <button
                      onClick={() => setNewsFilter("high-impact")}
                      className={`px-2.5 py-1 rounded text-xs transition-colors ${
                        newsFilter === "high-impact"
                          ? "bg-amber-500/20 text-amber-400"
                          : "text-muted-foreground hover:text-foreground/80"
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
                    <div className="p-6 text-center text-muted-foreground text-sm">
                      No news available
                    </div>
                  ) : (
                    <div className="divide-y divide-border/50">
                      {filteredNews.map((item) => (
                        <div
                          key={item.id}
                          className="p-4 hover:bg-muted/30 transition-colors"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <h4 className="text-sm text-foreground/90 leading-snug line-clamp-2 flex-1">
                              {item.title}
                            </h4>
                            {item.sentiment && (
                              <span
                                className={`text-sm font-bold flex-shrink-0 ${
                                  item.sentiment === "positive"
                                    ? "text-emerald-400"
                                    : item.sentiment === "negative"
                                    ? "text-rose-400"
                                    : "text-muted-foreground"
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
                          <div className="flex items-center gap-2 mt-2">
                            <span className="text-xs text-muted-foreground font-medium uppercase">
                              {item.source}
                            </span>
                            <span className="text-xs text-muted-foreground/70">·</span>
                            <span className="text-xs text-muted-foreground">
                              {formatTimeAgo(item.published_at)}
                            </span>
                          </div>
                          {item.currencies.length > 0 && (
                            <div className="flex items-center gap-1.5 mt-2">
                              {item.currencies.slice(0, 3).map((c) => (
                                <span
                                  key={c}
                                  className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded"
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
                              className="inline-flex items-center gap-1 mt-3 text-xs text-blue-400 hover:text-blue-300 transition-colors"
                            >
                              Read <ExternalLink className="w-3 h-3" />
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
