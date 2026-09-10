"""Long-window lab: validate the round-5 findings (Sunday filter, breadth
gate) over ~3 years (2023-10 -> 2026-09), strictly out-of-sample — no
parameter is re-tuned here.

Phases:
  python lab_long.py gen   — regenerate trade sets over the long window
  python lab_long.py eval  — overlays, folds, per-year, survivorship stats
  python lab_long.py both

Caveat (unfixable from cache): the universe is TODAY's top-100, so symbols
that died before 2026 are absent — long-horizon results carry survivorship
bias that grows with lookback. Quantified in eval.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BT = Path(__file__).parent
sys.path.insert(0, str(BT))
sys.path.insert(0, str(BT.parent))

LONG_START = pd.Timestamp("2023-10-01", tz="UTC")
LONG_END = pd.Timestamp("2026-09-01", tz="UTC")
FOLDS = [
    ("F1 23Q4-24Q1", "2023-10-01", "2024-04-01"),
    ("F2 24Q2-24Q3", "2024-04-01", "2024-10-01"),
    ("F3 24Q4-25Q1", "2024-10-01", "2025-04-01"),
    ("F4 25Q2-25Q3", "2025-04-01", "2025-10-01"),
    ("F5 25Q4-26Q1", "2025-10-01", "2026-04-01"),
    ("F6 26Q2-26Q3", "2026-04-01", "2026-09-01"),
]
YEARS = [("2024", "2024-01-01", "2025-01-01"),
         ("2025", "2025-01-01", "2026-01-01"),
         ("2026YTD", "2026-01-01", "2026-09-01")]
RISK = 0.01
BREADTH_THRESHOLD = 0.3
GATE = 0.15

PROD = dict(st_period=10, st_mult=3.5, trail_mult=3.5, ema=200,
            short_mode='btc_st', time_stop_bars=42,
            atr_min=0.5, atr_max=5.0)


def gen():
    import runner
    import strategies
    # runner binds BT_START/BT_END from dataset at import; rebind for the
    # long window (module globals — run() reads these names).
    runner.BT_START = LONG_START
    runner.BT_END = LONG_END
    strategies.REGISTRY['lab2_prod'] = strategies.st_trail
    strategies.REGISTRY['lab2_prod_sun'] = strategies.st_trail

    variants = {
        'lab2_prod': PROD,
        'lab2_prod_sun': {**PROD, 'days': [0, 1, 2, 3, 4, 5]},
    }
    from lab_eval import breadth_series  # warm cache reuse not needed; just gen
    for name, params in variants.items():
        m, _ = runner.run('4h', name, dict(params), split='full',
                          log=False, save_trades=True)
        print(f"{name} full n={m.get('trades')} ret={m.get('total_return_pct')}% "
              f"dd={m.get('max_dd_pct')}% sharpe={m.get('sharpe')}")


def portfolio(trades: pd.DataFrame, weights: np.ndarray) -> dict:
    if len(trades) == 0:
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
    gw = t.loc[wins, "net_r"].sum()
    gl = -t.loc[~wins, "net_r"].sum()
    return {"trades": int(len(t)), "ret": round((eq[-1] - 1) * 100, 1),
            "dd": round(dd * 100, 1), "sharpe": round(sharpe, 2),
            "avg_r": round(float(t["net_r"].mean()), 4),
            "pf": round(float(gw / gl), 2) if gl > 0 else float("inf"),
            "win": round(float(wins.mean()) * 100, 1)}


def evaluate(t: pd.DataFrame, label: str, windows, unit_risk: bool = False) -> list[dict]:
    entry = pd.DatetimeIndex(t["entry_time"])
    rows = []
    for wname, w0, w1 in windows:
        w0 = pd.Timestamp(w0)
        w1 = pd.Timestamp(w1)
        if w0.tzinfo is None:
            w0 = w0.tz_localize("UTC")
        if w1.tzinfo is None:
            w1 = w1.tz_localize("UTC")
        mask = (entry >= w0) & (entry < w1)
        sub = t[mask]
        if unit_risk:
            weights = np.ones(len(sub))
        else:
            weights = np.where(sub["breadth"] >= BREADTH_THRESHOLD, 1.0, 0.5)
        rows.append({"variant": label, "window": wname,
                     **portfolio(sub.reset_index(drop=True), weights)})
    return rows


def btc_regime() -> pd.Series:
    """BTC buy-hold return per fold, from the cached 4h series."""
    btc = pd.read_parquet(BT / "data_cache" / "4h" / "BTCUSDT.parquet",
                          columns=["close"])
    out = {}
    for name, w0, w1 in FOLDS + YEARS:
        a = btc.loc[(btc.index >= w0) & (btc.index < w1), "close"]
        out[name] = round(float(a.iloc[-1] / a.iloc[0] - 1) * 100, 1) if len(a) else None
    return out


def survivorship() -> dict:
    """How much of the long window each symbol actually traded."""
    stats = {"total": 0, "before_2023_10": 0, "before_2024": 0,
             "listed_2024_or_later": 0}
    earliest = []
    for f in sorted((BT / "data_cache" / "4h").glob("*.parquet")):
        df = pd.read_parquet(f, columns=["close"])
        stats["total"] += 1
        first = df.index[0]
        earliest.append((f.stem, first))
        if first < LONG_START:
            stats["before_2023_10"] += 1
        if first < pd.Timestamp("2024-01-01", tz="UTC"):
            stats["before_2024"] += 1
        else:
            stats["listed_2024_or_later"] += 1
    return stats


def eval_phase():
    from lab_eval import breadth_series
    breadth = breadth_series()
    windows = [("FULL", LONG_START, LONG_END)] + FOLDS + YEARS

    all_rows = []
    variants = {}
    for name in ("lab2_prod", "lab2_prod_sun"):
        f = BT / "results" / f"{name}_full.csv"
        t = pd.read_csv(f, parse_dates=["entry_time", "exit_time"])
        b = breadth.reindex(pd.DatetimeIndex(t["entry_time"]), method="ffill")
        t["breadth"] = b.to_numpy()
        variants[name] = t

    prod = variants["lab2_prod"]
    sun = variants["lab2_prod_sun"]

    all_rows += evaluate(prod, "prod (breadth sizing)", windows)
    all_rows += evaluate(sun, "prod + Sunday", windows)
    gate = prod[prod["breadth"] >= GATE]
    all_rows += evaluate(gate, f"prod + gate>={GATE}", windows)
    sg = sun[sun["breadth"] >= GATE]
    all_rows += evaluate(sg, f"prod + Sunday + gate>={GATE}", windows)
    all_rows += evaluate(prod, "prod unit-risk", windows, unit_risk=True)

    res = pd.DataFrame(all_rows)
    regime = btc_regime()
    surv = survivorship()

    print(f"\nsurvivorship: {surv}")
    print(f"  ({surv['before_2023_10']}/{surv['total']} symbols existed before "
          f"{LONG_START.date()}; the rest join mid-window; dead coins are "
          f"absent entirely — long-horizon returns are survivorship-flattered)")
    print("\nBTC buy-hold per window: " +
          ", ".join(f"{k}={v}%" for k, v in regime.items()))

    pd.set_option("display.width", 220)
    for label in ("prod unit-risk", "prod (breadth sizing)", "prod + Sunday",
                  f"prod + gate>={GATE}", f"prod + Sunday + gate>={GATE}"):
        sub = res[res["variant"] == label]
        print(f"\n=== {label} ===")
        print(sub[["window", "trades", "ret", "dd", "sharpe", "avg_r",
                   "pf", "win"]].to_string(index=False))

    res.to_csv(BT / "results" / "lab_long.csv", index=False)
    print("\nsaved results/lab_long.csv")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "both"
    if phase in ("gen", "both"):
        gen()
    if phase in ("eval", "both"):
        eval_phase()
