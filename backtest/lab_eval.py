"""Research lab — overlay/fold evaluation over pre-generated trade sets.

Everything here is post-processing on trade lists: the compounding math
mirrors metrics.compute_metrics (exit-time order, daily Sharpe x sqrt(365)).
Breadth is computed causally: breadth_known[t] uses only bars that closed
BEFORE bar t opens (i.e., what a scan at time t would actually see).

Usage:  python lab_eval.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BT = Path(__file__).parent
sys.path.insert(0, str(BT))
sys.path.insert(0, str(BT.parent))

import indicators as ind

CACHE = BT / "data_cache" / "4h"
BT_START = pd.Timestamp("2026-03-01", tz="UTC")
BT_END = pd.Timestamp("2026-09-01", tz="UTC")
TRAIN_END = pd.Timestamp("2026-07-16", tz="UTC")
FOLDS = [("F1", "2026-03-01", "2026-05-01"),
         ("F2", "2026-05-01", "2026-07-01"),
         ("F3", "2026-07-01", "2026-09-01")]
RISK = 0.01
BREADTH_THRESHOLD = 0.3


# ── breadth (causal) ─────────────────────────────────────────────────────

def breadth_series() -> pd.Series:
    """Fraction of the universe above its own EMA200 per 4H bar, shifted one
    bar so breadth_known[t] only uses candles closed before t opens."""
    closes, above = {}, {}
    for f in sorted(CACHE.glob("*.parquet")):
        df = pd.read_parquet(f, columns=["close"])
        e = ind.ema(df["close"], 200)
        closes[f.stem] = df["close"]
        above[f.stem] = (df["close"] > e).astype(float)
    above_df = pd.DataFrame(above)
    n = above_df.notna().sum(axis=1)
    raw = above_df.sum(axis=1) / n.replace(0, np.nan)
    return raw.shift(1).dropna()   # shift: what a scan at t actually knows


# ── portfolio math (mirrors metrics.compute_metrics) ─────────────────────

def portfolio(trades: pd.DataFrame, weights: np.ndarray) -> dict:
    if trades.empty:
        return {"trades": 0, "ret": 0.0, "dd": 0.0, "sharpe": 0.0,
                "avg_r": 0.0, "pf": 0.0, "win": 0.0}
    # weights are aligned to the INPUT row order — reorder them together with
    # the trades (exit-time sort must not shuffle risk multipliers).
    order = np.argsort(pd.DatetimeIndex(trades["exit_time"]).to_numpy(),
                       kind="stable")
    t = trades.iloc[order].reset_index(drop=True)
    weights = np.asarray(weights)[order]
    eq = [1.0]
    for r, rf in zip(t["net_r"], weights):
        eq.append(eq[-1] * (1.0 + RISK * rf * r))
    eq = np.array(eq)
    peak = np.maximum.accumulate(eq)
    dd = float((1.0 - eq / peak).max())
    s = pd.Series(eq[1:], index=pd.DatetimeIndex(t["exit_time"]))
    daily = s.resample("1D").last().ffill()
    dr = daily.pct_change().dropna()
    sharpe = float(dr.mean() / dr.std() * np.sqrt(365)) if dr.std() > 0 else 0.0
    wins = t["net_r"] > 0
    gw, gl = t.loc[wins, "net_r"].sum(), -t.loc[~wins, "net_r"].sum()
    return {"trades": int(len(t)), "ret": round((eq[-1] - 1) * 100, 1),
            "dd": round(dd * 100, 1),
            "sharpe": round(sharpe, 2),
            "avg_r": round(float(t["net_r"].mean()), 4),
            "pf": round(float(gw / gl), 2) if gl > 0 else float("inf"),
            "win": round(float(wins.mean()) * 100, 1)}


def evaluate(trades: pd.DataFrame, breadth: pd.Series,
             weights: np.ndarray, label: str) -> list[dict]:
    """Full-window, train/valid, and fold metrics for one weighted variant."""
    out = []
    entry = pd.DatetimeIndex(pd.to_datetime(trades["entry_time"]))
    windows = [("full", trades, np.ones(len(trades), bool))]
    windows.append(("train", trades, entry < TRAIN_END))
    windows.append(("valid", trades, entry >= TRAIN_END))
    for fname, f0, f1 in FOLDS:
        m0 = (entry >= pd.Timestamp(f0, tz="UTC")) & \
             (entry < pd.Timestamp(f1, tz="UTC"))
        windows.append((fname, trades, m0))
    rows = []
    for wname, sub, mask in windows:
        if mask.sum() == 0:
            rows.append({"variant": label, "window": wname, "trades": 0,
                         "ret": 0.0, "dd": 0.0, "sharpe": 0.0, "avg_r": 0.0,
                         "pf": 0.0, "win": 0.0})
            continue
        m = portfolio(sub[mask].reset_index(drop=True), weights[mask])
        rows.append({"variant": label, "window": wname, **m})
    return rows


def main():
    breadth = breadth_series()
    print(f"breadth series: {len(breadth)} bars, "
          f"mean={breadth.mean():.3f}, min={breadth.min():.3f}")

    variants = {}
    for name in ("lab_prod", "lab_prod_sun"):
        f = BT / "results" / f"{name}_full.csv"
        t = pd.read_csv(f, parse_dates=["entry_time", "exit_time"])
        b = breadth.reindex(pd.DatetimeIndex(t["entry_time"]), method="ffill")
        t["breadth"] = b.to_numpy()
        t["is_sunday"] = pd.DatetimeIndex(t["entry_time"]).dayofweek == 6
        variants[name] = t

    prod = variants["lab_prod"]
    sun = variants["lab_prod_sun"]     # Sunday filter at flip-candle, runner convention
    atr_pct = prod["atr_pct"].clip(lower=0.1)

    unit = np.ones(len(prod))
    breadth_w = np.where(prod["breadth"] >= BREADTH_THRESHOLD, 1.0, 0.5)
    vol_w = (2.0 / atr_pct).clip(0.4, 2.5).to_numpy()
    vol_w = vol_w / vol_w.mean()
    sun_w = np.where(sun["breadth"] >= BREADTH_THRESHOLD, 1.0, 0.5)

    rows = []
    rows += evaluate(prod, breadth, unit, "prod unit-risk (no overlay)")
    rows += evaluate(prod, breadth, breadth_w, "prod + breadth sizing  [TRUE PROD]")
    rows += evaluate(prod, breadth, breadth_w * vol_w, "prod + breadth sizing + vol-target")
    rows += evaluate(prod, breadth, vol_w, "prod + vol-target only")
    rows += evaluate(sun, breadth, np.ones(len(sun)), "prod + Sunday filter")
    rows += evaluate(sun, breadth, sun_w, "prod + Sunday + breadth sizing")

    # breadth as an ENTRY GATE (drop low-breadth trades entirely), on sizing
    for gate in (0.15, 0.20, 0.25, 0.30):
        mask = prod["breadth"] >= gate
        g = prod[mask]
        gw = np.where(g["breadth"] >= BREADTH_THRESHOLD, 1.0, 0.5)
        rows += evaluate(g, breadth, gw, f"prod + breadth GATE>={gate} + sizing")

    # gate threshold sensitivity (is 0.15 a spike or a plateau?)
    for gate in (0.10, 0.12, 0.18):
        mask = prod["breadth"] >= gate
        g = prod[mask]
        gw = np.where(g["breadth"] >= BREADTH_THRESHOLD, 1.0, 0.5)
        rows += evaluate(g, breadth, gw, f"prod + breadth GATE>={gate} + sizing")

    # combined: Sunday filter + gate + sizing
    for gate in (0.10, 0.15, 0.20):
        sg = sun[sun["breadth"] >= gate]
        sw = np.where(sg["breadth"] >= BREADTH_THRESHOLD, 1.0, 0.5)
        rows += evaluate(sg, breadth, sw, f"Sunday + GATE>={gate} + sizing")

    # cost stress: net_r = gross_r - k*COST_RT/sl_dist and sl_dist falls out
    # of the two columns: COST_RT/sl_dist = gross_r - net_r -> net_r' =
    # gross_r - k*(gross_r - net_r). Valid for any k.
    def cost_scaled(t: pd.DataFrame, k: float) -> pd.DataFrame:
        t = t.copy()
        t["net_r"] = t["gross_r"] - k * (t["gross_r"] - t["net_r"])
        return t

    stress_sets = [
        ("prod + breadth sizing  [TRUE PROD]", prod, breadth_w),
        ("prod + Sunday + breadth sizing", sun, sun_w),
    ]
    for gate in (0.15,):
        g = prod[prod["breadth"] >= gate]
        gw = np.where(g["breadth"] >= BREADTH_THRESHOLD, 1.0, 0.5)
        stress_sets.append((f"prod + GATE>={gate} + sizing", g, gw))
    for gate in (0.15,):
        sg = sun[sun["breadth"] >= gate]
        sw = np.where(sg["breadth"] >= BREADTH_THRESHOLD, 1.0, 0.5)
        stress_sets.append((f"Sunday + GATE>={gate} + sizing", sg, sw))

    for label, tset, w in stress_sets:
        for k, klabel in ((1.0, ""), (2.0, " 2x costs"), (3.0, " 3x costs")):
            tk = cost_scaled(tset, k)
            rows += evaluate(tk, breadth, w, f"{label}{klabel}")

    res = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    order = ["prod unit-risk (no overlay)", "prod + breadth sizing  [TRUE PROD]",
             "prod + Sunday filter", "prod + Sunday + breadth sizing",
             "prod + breadth sizing + vol-target", "prod + vol-target only",
             "prod + breadth GATE>=0.10 + sizing", "prod + breadth GATE>=0.12 + sizing",
             "prod + breadth GATE>=0.15 + sizing", "prod + breadth GATE>=0.18 + sizing",
             "prod + breadth GATE>=0.20 + sizing",
             "prod + breadth GATE>=0.25 + sizing",
             "Sunday + GATE>=0.10 + sizing", "Sunday + GATE>=0.15 + sizing",
             "Sunday + GATE>=0.20 + sizing",
             "prod + breadth sizing  [TRUE PROD] 2x costs",
             "prod + Sunday + breadth sizing 2x costs",
             "prod + GATE>=0.15 + sizing 2x costs",
             "Sunday + GATE>=0.15 + sizing 2x costs",
             "prod + breadth sizing  [TRUE PROD] 3x costs",
             "prod + Sunday + breadth sizing 3x costs",
             "prod + GATE>=0.15 + sizing 3x costs",
             "Sunday + GATE>=0.15 + sizing 3x costs"]
    for v in order:
        sub = res[res["variant"] == v]
        print(f"\n=== {v} ===")
        print(sub[["window", "trades", "ret", "dd", "sharpe", "avg_r", "pf", "win"]]
              .to_string(index=False))

    res.to_csv(BT / "results" / "lab_overlays.csv", index=False)
    print("\nsaved results/lab_overlays.csv")


if __name__ == "__main__":
    main()
