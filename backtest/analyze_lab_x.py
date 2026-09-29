"""Round-6 robustness analysis for lab_x variants.

1. Re-simulate the key variants and save trade lists
2. Paired per-trade net_r diff vs prod (same entries, different exits)
3. Cost stress (+50%/+100% round-trip costs)
4. Six 6-month folds (round-5b convention)
5. Worst-month profile
6. Stop->reclaim forward-return study (why re-entry variants fail)

Usage:  python analyze_lab_x.py
"""

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

BT = Path(__file__).parent
sys.path.insert(0, str(BT))
sys.path.insert(0, str(BT.parent))

import indicators as ind
from lab_x import (CACHE, TRAIN_END, RISK_FULL, BREADTH_THRESHOLD,
                   breadth_series, btc_st_series, build_plans, load_symbol,
                   simulate, portfolio)

RUNS = (
    ("prod", {}),
    ("close_stop", {"stop_mode": "close"}),
    ("close_stop_d", {"stop_mode": "close_disaster", "disaster_mult": 6.0,
                      "disaster_cap": 0.12}),
    ("close_stop_roll", {"stop_mode": "close", "trail_atr": "rolling"}),
    ("close_stop_d_roll", {"stop_mode": "close_disaster",
                           "disaster_mult": 6.0, "disaster_cap": 0.12,
                           "trail_atr": "rolling"}),
    ("flip_only", {"stop_mode": "none"}),
)


def main():
    t0 = time.time()
    breadth = breadth_series()
    btc = btc_st_series()
    symbols = sorted(p.stem for p in CACHE.glob("*.parquet"))

    data = {}
    for sym in symbols:
        df, btc_dir, bk = load_symbol(sym, breadth, btc)
        plans, dirv = build_plans(df, btc_dir, bk)
        atr_arr = ind.atr(df, 14).to_numpy()
        data[sym] = (df, plans, dirv, atr_arr)
    bmap = {}
    for sym, (_, plans, _, _) in data.items():
        for p in plans:
            bmap[(sym, p["idx"])] = p["breadth"]
    print(f"loaded in {time.time()-t0:.0f}s")

    trades_by_variant = {}
    for name, cfg in RUNS:
        rows = []
        for sym, (df, plans, dirv, atr_arr) in data.items():
            for tr in simulate(df, plans, dirv, atr_arr=atr_arr, **cfg):
                tr["symbol"] = sym
                tr["orig_time"] = df.index[tr["orig_idx"] + 1]
                tr["breadth"] = bmap.get((sym, tr["orig_idx"]), 0.3)
                rows.append(tr)
        trades_by_variant[name] = pd.DataFrame(rows)
        print(f"  {name}: {len(rows)} trades")

    prod = trades_by_variant["prod"]
    print("\n=== paired per-trade net_r diff vs prod (same entries) ===")
    for name, tdf in trades_by_variant.items():
        if name == "prod":
            continue
        m = prod.merge(tdf, on=["symbol", "orig_idx", "orig_time", "direction"],
                       suffixes=("_p", "_v"))
        d = m["net_r_v"] - m["net_r_p"]
        se = d.std() / np.sqrt(len(d))
        print(f"{name:18s} n_pairs={len(d)}  mean_diff={d.mean():+.4f}R  "
              f"t={d.mean()/se:+.1f}  median={d.median():+.4f}  "
              f"pct_better={(d>0).mean()*100:.0f}%")

    print("\n=== cost stress (extra round-trip cost as multiples of current) ===")
    # net_r = gross_r - COST_RT/sl_frac, so k extra round trips is
    # net_r' = net_r - k * (gross_r - net_r)
    for name, tdf in trades_by_variant.items():
        w = np.where(tdf["breadth"] >= BREADTH_THRESHOLD, 1.0, 0.5)
        cells = []
        for k in (0.0, 0.5, 1.0, 2.0):
            t2 = tdf.copy()
            t2["net_r"] = t2["net_r"] - k * (t2["gross_r"] - t2["net_r"])
            m = portfolio(t2, w, RISK_FULL)
            cells.append(f"+{k:.1f}x: {m['ret']:+.0f}%/dd{m['dd']:.0f}%/"
                         f"srp{m['sharpe']:.2f}")
        print(f"{name:18s} " + " | ".join(cells))

    print("\n=== six 6-month folds (round-5b convention), ret%/dd%/sharpe ===")
    folds = [("F1 23Q4", "2023-10-01", "2024-04-01"),
             ("F2 24H1", "2024-04-01", "2024-10-01"),
             ("F3 24H2", "2024-10-01", "2025-04-01"),
             ("F4 25H1", "2025-04-01", "2025-10-01"),
             ("F5 25H2", "2025-10-01", "2026-04-01"),
             ("F6 26H2", "2026-04-01", "2026-10-01")]
    fold_wins = {n: 0 for n in trades_by_variant}
    for fname, f0, f1 in folds:
        line = []
        sharpes = {}
        for name, tdf in trades_by_variant.items():
            et = pd.DatetimeIndex(tdf["entry_time"])
            mask = (et >= pd.Timestamp(f0, tz="UTC")) & \
                   (et < pd.Timestamp(f1, tz="UTC"))
            w = np.where(tdf["breadth"] >= BREADTH_THRESHOLD, 1.0, 0.5)
            m = portfolio(tdf[mask].reset_index(drop=True),
                          w[mask], RISK_FULL)
            sharpes[name] = m["sharpe"]
            line.append(f"{name} {m['ret']:+.0f}/{m['dd']:.0f}/{m['sharpe']:.2f}")
        best = max(sharpes, key=sharpes.get)
        fold_wins[best] += 1
        print(f"{fname}: " + " | ".join(line))
    print("fold sharpe wins:", fold_wins)

    print("\n=== worst 4 months per variant (monthly return %, @0.5% risk) ===")
    for name, tdf in trades_by_variant.items():
        w = np.where(tdf["breadth"] >= BREADTH_THRESHOLD, 1.0, 0.5)
        order = np.argsort(pd.DatetimeIndex(tdf["exit_time"]).to_numpy(),
                           kind="stable")
        t = tdf.iloc[order].reset_index(drop=True)
        ww = np.asarray(w)[order]
        eq = [1.0]
        times = []
        for r, rf, xtm in zip(t["net_r"], ww, t["exit_time"]):
            eq.append(eq[-1] * (1.0 + RISK_FULL * rf * r))
            times.append(xtm)
        s = pd.Series(np.diff(eq), index=pd.DatetimeIndex(times))
        monthly = s.groupby(s.index.to_period("M")).sum() * 100
        worst = monthly.nsmallest(4)
        print(f"{name:18s} " +
              " ".join(f"{idx}:{v:+.1f}" for idx, v in worst.items()))

    # ── stop->reclaim study: what happens after prod's wick stop-outs? ──
    print("\n=== after a prod stop-out with ST still agreeing (forward) ===")
    stops = prod[prod["exit_reason"] == "stop"]
    fwd_stats = []
    for _, tr in stops.iterrows():
        df = data[tr["symbol"]][0]
        dirv = data[tr["symbol"]][2]
        xi = df.index.get_indexer([pd.Timestamp(tr["exit_time"])])
        xi = xi[0]
        if xi < 0 or xi >= len(df) - 1:
            continue
        d = 1 if tr["direction"] == "LONG" else -1
        if dirv[xi] != d:
            continue
        lvl = tr["exit_lvl"]
        px_stop = float(tr["exit"])
        row = {"symbol": tr["symbol"], "exit_time": tr["exit_time"]}
        # reclaim within 6 bars?
        rec = None
        for kk in range(xi + 1, min(xi + 7, len(df))):
            back = df["close"].iat[kk] > lvl if d == 1 else \
                df["close"].iat[kk] < lvl
            if back:
                rec = kk - xi
                break
        row["reclaim_6bars"] = rec is not None
        for h in (6, 12, 24):
            j = min(xi + h, len(df) - 1)
            row[f"fwd{h}"] = d * (df["close"].iat[j] / px_stop - 1.0)
        # to the opposite flip (the flip_only exit)
        j = xi + 1
        while j < len(df) and dirv[j] == d:
            j += 1
        j = min(j, len(df) - 1)
        row["to_flip"] = d * (df["close"].iat[j] / px_stop - 1.0)
        row["bars_to_flip"] = j - xi
        fwd_stats.append(row)
    fs = pd.DataFrame(fwd_stats)
    print(f"stop-outs with ST still agreeing: {len(fs)} of {len(stops)} "
          f"({len(fs)/len(stops)*100:.0f}%)")
    print(f"reclaimed the stop level within 6 bars: "
          f"{fs['reclaim_6bars'].mean()*100:.0f}%")
    for col in ("fwd6", "fwd12", "fwd24", "to_flip"):
        v = fs[col]
        print(f"{col:10s} mean={v.mean()*100:+.2f}%  median={v.median()*100:+.2f}%  "
              f"pos={(v>0).mean()*100:.0f}%")
    fs.to_csv(BT / "results" / "lab_x_reclaim_study.csv", index=False)
    print("saved results/lab_x_reclaim_study.csv")

    # save trade lists for the report
    out = BT / "results"
    for name, tdf in trades_by_variant.items():
        tdf.to_csv(out / f"lab_x_trades_{name}.csv", index=False)
    print("saved trade lists")


if __name__ == "__main__":
    main()
