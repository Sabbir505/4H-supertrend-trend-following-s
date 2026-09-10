"""Evaluate the initial-stop sweep: apply deployed filters (breadth gate
0.15 + quality tiers A/B) and breadth-scaled risk at 0.5%/0.25%, then split
TRAIN (2023-10 -> 2025-04, tuning window) vs HOLDOUT (2025-04 -> 2026-09).

Usage:  python sweep_init_sl_eval.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

BT = Path(__file__).parent
sys.path.insert(0, str(BT))
sys.path.insert(0, str(BT.parent))

from lab_eval import breadth_series

TRAIN_END = pd.Timestamp("2025-04-01", tz="UTC")
RISK = 0.005
THRESH = 0.3

breadth = breadth_series()

def tier(r):
    if r["direction"] == "LONG":
        return "A" if r["breadth"] >= THRESH else "C"
    if r["symbol"] == "BTCUSDT":
        return "D"
    return "B" if (r["breadth"] < THRESH or r["breadth"] >= 0.5) else "C"

def stats(sub):
    order = np.argsort(pd.DatetimeIndex(sub["exit_time"]).to_numpy(), kind="stable")
    s = sub.iloc[order].reset_index(drop=True)
    w = np.where(s["breadth"].to_numpy() >= THRESH, 1.0, 0.5)
    eq = [1.0]
    for r, wf in zip(s["net_r"], w):
        eq.append(eq[-1] * (1 + RISK * wf * r))
    eq = np.array(eq)
    peak = np.maximum.accumulate(eq)
    dd = 100 * (1 - eq / peak).max()
    wins = s["net_r"] > 0
    gw = s.loc[wins, "net_r"].sum()
    gl = -s.loc[~wins, "net_r"].sum()
    daily = pd.Series(eq[1:], index=pd.DatetimeIndex(s["exit_time"])).resample("1D").last().ffill()
    dr = daily.pct_change().dropna()
    shp = float(dr.mean() / dr.std() * np.sqrt(365)) if len(dr) > 5 and dr.std() > 0 else 0.0
    return {"n": len(s), "win": round(100 * wins.mean(), 1),
            "avg_r": round(float(s["net_r"].mean()), 4),
            "pf": round(float(gw / gl), 2) if gl > 0 else None,
            "ret": round((eq[-1] - 1) * 100, 1), "dd": round(dd, 1),
            "sharpe": round(shp, 2)}

variants = sorted(BT.glob("results/lab_init_sl_*_full.csv"))
out_rows = []
for f in variants:
    t = pd.read_csv(f, parse_dates=["entry_time", "exit_time"])
    t["breadth"] = breadth.reindex(pd.DatetimeIndex(t["entry_time"]), method="ffill").to_numpy()
    t = t[t["breadth"] >= 0.15]
    t["tier"] = t.apply(tier, axis=1)
    t = t[t["tier"].isin(["A", "B"])]          # deployed QUALITY_FILTER=A,B
    tag = f.stem.replace("lab_init_sl_", "").replace("_full", "")
    toks = tag.split("_")
    mult = float(toks[0] + "." + toks[1])
    floor = float(toks[2] + "." + toks[3])
    for label, mask in (("train", pd.DatetimeIndex(t["entry_time"]) < TRAIN_END),
                        ("holdout", pd.DatetimeIndex(t["entry_time"]) >= TRAIN_END),
                        ("full3y", pd.DatetimeIndex(t["entry_time"]) >= pd.Timestamp("2023-10-01", tz="UTC"))):
        st = stats(t[mask])
        out_rows.append({"init_mult": float(mult), "floor": float(floor),
                         "window": label, **st})

res = pd.DataFrame(out_rows).sort_values(["init_mult", "floor", "window"])
pd.set_option("display.width", 200)
for (mult, floor), sub in res.groupby(["init_mult", "floor"]):
    print(f"\n=== init stop {mult}xATR, floor {floor} ===")
    print(sub[["window", "n", "win", "avg_r", "pf", "ret", "dd", "sharpe"]].to_string(index=False))

res.to_csv(BT / "results" / "sweep_init_sl_eval.csv", index=False)
print("\nsaved results/sweep_init_sl_eval.csv")
