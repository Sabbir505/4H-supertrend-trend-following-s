"use client";

import { useState, useEffect, useMemo } from "react";
import { DashboardLayout } from "@/components/dashboard-layout";
import { Badge } from "@/components/ui/badge";
import {
  Activity,
  FlaskConical,
  TrendingUp,
  RefreshCw,
  BarChart3,
  XCircle,
  CheckCircle2,
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
  ReferenceLine,
} from "recharts";
import {
  getBacktestResults,
  BacktestResults,
} from "@/lib/api";

const SERIES_COLORS = {
  final: "#22d3ee", // cyan
  base: "#a78bfa", // violet
  baseline: "#f87171", // red
  btc: "#64748b", // slate
};

function StatCard({
  label,
  value,
  sub,
  tone = "neutral",
  delay = "",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "neutral" | "good" | "bad";
  delay?: string;
}) {
  const toneClass =
    tone === "good"
      ? "text-emerald-400"
      : tone === "bad"
      ? "text-red-400"
      : "text-foreground";
  return (
    <div className={`glass rounded-2xl p-5 animate-fade-in-up opacity-0 ${delay}`}>
      <p className="text-xs text-muted-foreground uppercase tracking-wider font-medium mb-3">
        {label}
      </p>
      <p className={`text-3xl font-bold mb-1 ${toneClass}`}>{value}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function fmt(v?: number | null, digits = 1, suffix = ""): string {
  if (v === undefined || v === null) return "—";
  return `${v > 0 ? "+" : ""}${v.toFixed(digits)}${suffix}`;
}

export default function BacktestPage() {
  const [data, setData] = useState<BacktestResults | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async (showLoading: boolean) => {
    if (showLoading) setLoading(true);
    try {
      setData(await getBacktestResults());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await getBacktestResults();
        if (!cancelled) {
          setData(res);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Failed to load");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const full = data?.metrics.full;
  const tooltipStyle = {
    backgroundColor: "rgba(10, 15, 35, 0.9)",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    borderRadius: "12px",
    color: "#e2e8f0",
    fontSize: "12px",
  };

  const summary = useMemo(() => {
    if (!full?.final) return null;
    return [
      {
        label: "Total Return",
        value: fmt(full.final.total_return_pct, 0, "%"),
        sub: `baseline ${fmt(full.baseline?.total_return_pct, 0, "%")} · BTC hold`,
        tone: (full.final.total_return_pct ?? 0) > 0 ? "good" : "bad",
      },
      {
        label: "Max Drawdown",
        value: fmt(-(full.final.max_dd_pct ?? 0), 1, "%"),
        sub: `baseline ${fmt(-(full.baseline?.max_dd_pct ?? 0), 1, "%")}`,
        tone: "neutral",
      },
      {
        label: "Sharpe Ratio",
        value: fmt(full.final.sharpe, 2),
        sub: `baseline ${fmt(full.baseline?.sharpe, 2)}`,
        tone: "good",
      },
      {
        label: "Profit Factor",
        value: fmt(full.final.profit_factor, 2),
        sub: `${full.final.trades ?? 0} trades · WR ${fmt(full.final.win_rate, 1, "%")}`,
        tone: "neutral",
      },
    ];
  }, [full]);

  if (loading) {
    return (
      <DashboardLayout>
        <div className="space-y-6 animate-pulse">
          <div className="h-9 w-64 bg-white/5 rounded-xl" />
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="glass rounded-2xl p-5 h-28" />
            ))}
          </div>
          <div className="glass rounded-2xl h-96" />
        </div>
      </DashboardLayout>
    );
  }

  if (error || !data) {
    return (
      <DashboardLayout>
        <div className="flex items-center justify-center min-h-[60vh]">
          <div className="glass rounded-2xl p-8 text-center max-w-sm">
            <div className="w-12 h-12 rounded-full bg-red-500/10 border border-red-500/20 flex items-center justify-center mx-auto mb-4">
              <Activity className="w-5 h-5 text-red-400" />
            </div>
            <h3 className="text-foreground font-semibold mb-1">Failed to load</h3>
            <p className="text-sm text-muted-foreground">{error}</p>
            <button
              onClick={() => fetchData(true)}
              className="mt-4 px-4 py-2 rounded-lg glass text-xs text-muted-foreground hover:text-foreground"
            >
              Retry
            </button>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  const windows: { key: "train" | "valid" | "full"; label: string }[] = [
    { key: "train", label: "Train · Mar 1 – Jul 15" },
    { key: "valid", label: "Holdout · Jul 16 – Aug 31" },
    { key: "full", label: "Full 6 Months" },
  ];

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 animate-fade-in-up">
          <div>
            <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
              <FlaskConical className="w-6 h-6 text-cyan-400" />
              Backtest
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              {data.config.name} · {data.config.params.period} · 166 symbols
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Badge variant="outline" className="text-[10px] border-white/10 text-muted-foreground">
              generated {new Date(data.generated_at).toLocaleDateString()}
            </Badge>
            <button
              onClick={() => fetchData(true)}
              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg glass hover:bg-white/[0.08] transition-all text-xs text-muted-foreground hover:text-foreground"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Refresh
            </button>
          </div>
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {summary?.map((s, i) => (
            <StatCard
              key={s.label}
              label={s.label}
              value={s.value}
              sub={s.sub}
              tone={s.tone as "good" | "bad" | "neutral"}
              delay={`stagger-${i + 1}`}
            />
          ))}
        </div>

        {/* Equity curve */}
        <div className="glass rounded-2xl p-5 animate-fade-in-up opacity-0 stagger-3">
          <div className="flex items-center gap-2 mb-1">
            <TrendingUp className="w-4 h-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold text-foreground">
              Equity Curve — Full 6 Months (deployed risk 0.5%/0.25% per trade)
            </h3>
          </div>
          <p className="text-xs text-muted-foreground mb-4">
            Final = round-4 config + Sunday skip + breadth gate ≥ 0.15 · baseline = old 1:1 RR
            production system · series indexed to 100
          </p>
          <ResponsiveContainer width="100%" height={340}>
            <LineChart data={data.equity} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
              <XAxis
                dataKey="date"
                stroke="rgba(255,255,255,0.3)"
                fontSize={11}
                tickLine={false}
                axisLine={false}
                minTickGap={48}
              />
              <YAxis
                stroke="rgba(255,255,255,0.3)"
                fontSize={11}
                tickLine={false}
                axisLine={false}
                width={52}
                tickFormatter={(v) => `${v}%`}
              />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v}%`} />
              <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" />
              <Line type="monotone" dataKey="final" name="Final strategy" stroke={SERIES_COLORS.final} strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="baseline" name="Production baseline" stroke={SERIES_COLORS.baseline} strokeWidth={1.5} dot={false} />
              <Line type="monotone" dataKey="btc_hold" name="BTC buy & hold" stroke={SERIES_COLORS.btc} strokeWidth={1.5} strokeDasharray="4 4" dot={false} />
            </LineChart>
          </ResponsiveContainer>
          <div className="flex flex-wrap items-center gap-4 mt-2 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: SERIES_COLORS.final }} /> Final strategy</span>
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: SERIES_COLORS.baseline }} /> Production baseline</span>
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full" style={{ background: SERIES_COLORS.btc }} /> BTC buy &amp; hold</span>
          </div>
        </div>

        {/* Drawdown + folds */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="glass rounded-2xl p-5 animate-fade-in-up opacity-0 stagger-4">
            <div className="flex items-center gap-2 mb-4">
              <BarChart3 className="w-4 h-4 text-muted-foreground" />
              <h3 className="text-sm font-semibold text-foreground">
                Final Strategy — Drawdown
              </h3>
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <AreaChart data={data.drawdown} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
                <defs>
                  <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#ef4444" stopOpacity={0.35} />
                    <stop offset="100%" stopColor="#ef4444" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" vertical={false} />
                <XAxis dataKey="date" stroke="rgba(255,255,255,0.3)" fontSize={11} tickLine={false} axisLine={false} minTickGap={48} />
                <YAxis stroke="rgba(255,255,255,0.3)" fontSize={11} tickLine={false} axisLine={false} width={40} tickFormatter={(v) => `${v}%`} />
                <Tooltip contentStyle={tooltipStyle} formatter={(v) => `${v}%`} />
                <Area type="monotone" dataKey="dd" name="Drawdown" stroke="#ef4444" strokeWidth={1.5} fill="url(#ddGrad)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          <div className="glass rounded-2xl p-5 animate-fade-in-up opacity-0 stagger-4">
            <div className="flex items-center gap-2 mb-4">
              <BarChart3 className="w-4 h-4 text-muted-foreground" />
              <h3 className="text-sm font-semibold text-foreground">
                Walk-Forward Folds &amp; Cost Stress
              </h3>
            </div>
            <div className="space-y-2 mb-5">
              {data.folds.map((f) => (
                <div key={f.name} className="flex items-center justify-between glass-table-row rounded-xl px-4 py-2.5">
                  <span className="text-xs text-muted-foreground">{f.name}</span>
                  <div className="flex items-center gap-4 text-sm font-mono">
                    <span className={f.return_pct > 0 ? "text-emerald-400" : "text-red-400"}>
                      {fmt(f.return_pct, 1, "%")}
                    </span>
                    <span className="text-muted-foreground text-xs">DD {fmt(f.dd_pct, 1, "%")}</span>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mb-2">Round-trip cost stress (full period)</p>
            <div className="space-y-2">
              {data.cost_stress.map((c) => (
                <div key={c.label} className="flex items-center justify-between glass-table-row rounded-xl px-4 py-2.5">
                  <span className="text-xs text-muted-foreground">{c.label}</span>
                  <div className="flex items-center gap-4 text-sm font-mono">
                    <span className="text-emerald-400">{fmt(c.return_pct, 0, "%")}</span>
                    <span className="text-muted-foreground text-xs">PF {fmt(c.pf, 2)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Window comparison */}
        <div className="glass rounded-2xl overflow-hidden animate-fade-in-up opacity-0 stagger-5">
          <div className="px-5 pt-5 pb-3 border-b border-white/[0.06]">
            <h3 className="text-sm font-semibold text-foreground">
              Window Comparison — Baseline vs Base Config vs Final
            </h3>
            <p className="text-xs text-muted-foreground mt-1">
              baseline = production system (1:1 RR) · base = round-4 config + breadth-scaled risk ·
              final = deployed: + Sunday skip, gate ≥ 0.15, 0.5%/0.25% risk
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="glass-table-header">
                  {["Window", "Strategy", "Return", "Max DD", "Sharpe", "PF", "Trades", "Win rate", "Avg R"].map((h) => (
                    <th key={h} className="text-left py-3 px-4 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {windows.map((w) =>
                  (["baseline", "base", "final"] as const).map((s, i) => {
                    const m = data.metrics[w.key][s];
                    const name =
                      s === "baseline" ? "Production baseline" : s === "base" ? "Base config" : "Deployed (v2.1)";
                    return (
                      <tr key={`${w.key}-${s}`} className="glass-table-row">
                        <td className="py-3 px-4 text-muted-foreground whitespace-nowrap">
                          {i === 0 ? w.label : ""}
                        </td>
                        <td className="py-3 px-4">
                          <span className={s === "final" ? "text-cyan-400 font-semibold" : "text-foreground"}>
                            {name}
                          </span>
                        </td>
                        <td className="py-3 px-4 font-mono">
                          <span className={(m.total_return_pct ?? 0) > 0 ? "text-emerald-400" : "text-red-400"}>
                            {fmt(m.total_return_pct, 1, "%")}
                          </span>
                        </td>
                        <td className="py-3 px-4 font-mono text-red-400/80">{fmt(-(m.max_dd_pct ?? 0), 1, "%")}</td>
                        <td className="py-3 px-4 font-mono">{fmt(m.sharpe, 2)}</td>
                        <td className="py-3 px-4 font-mono">{fmt(m.profit_factor, 2)}</td>
                        <td className="py-3 px-4 font-mono text-muted-foreground">{m.trades ?? "—"}</td>
                        <td className="py-3 px-4 font-mono text-muted-foreground">{fmt(m.win_rate, 1, "%")}</td>
                        <td className="py-3 px-4 font-mono text-muted-foreground">{fmt(m.avg_r, 3)}</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Config + rounds */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="glass rounded-2xl p-5 animate-fade-in-up opacity-0 stagger-6">
            <div className="flex items-center gap-2 mb-4">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              <h3 className="text-sm font-semibold text-foreground">Deployed Configuration</h3>
            </div>
            <div className="space-y-2.5">
              {Object.entries(data.config.params).map(([k, v]) => (
                <div key={k} className="flex items-start justify-between gap-4 text-xs">
                  <span className="text-muted-foreground capitalize whitespace-nowrap">{k.replace(/_/g, " ")}</span>
                  <span className="text-foreground text-right font-medium">{v}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="glass rounded-2xl p-5 animate-fade-in-up opacity-0 stagger-6">
            <div className="flex items-center gap-2 mb-4">
              <FlaskConical className="w-4 h-4 text-cyan-400" />
              <h3 className="text-sm font-semibold text-foreground">Research Rounds — 500+ experiments</h3>
            </div>
            <div className="space-y-3">
              {data.rounds.map((r) => (
                <div key={r.round} className="glass-table-row rounded-xl px-4 py-3">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant="outline" className="text-[10px] border-cyan-500/30 text-cyan-400 bg-cyan-500/5">
                      {r.round}
                    </Badge>
                    <span className="text-xs font-semibold text-foreground">{r.title}</span>
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed">{r.result}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Rejected ideas */}
        <div className="glass rounded-2xl p-5 animate-fade-in-up opacity-0 stagger-6">
          <div className="flex items-center gap-2 mb-4">
            <XCircle className="w-4 h-4 text-red-400/80" />
            <h3 className="text-sm font-semibold text-foreground">
              Tested &amp; Rejected — so we never re-test blind
            </h3>
          </div>
          <div className="space-y-2">
            {data.rejected.map((r) => (
              <div key={r.idea} className="flex items-start justify-between gap-4 glass-table-row rounded-xl px-4 py-2.5">
                <span className="text-xs text-foreground font-medium">{r.idea}</span>
                <span className="text-xs text-muted-foreground text-right">{r.reason}</span>
              </div>
            ))}
          </div>
        </div>

        <p className="text-center text-xs text-muted-foreground">
          Backtests are historical simulations with 0.16% round-trip costs, next-open entries and
          conservative SL-first fills — past performance does not guarantee future results.
        </p>
      </div>
    </DashboardLayout>
  );
}
