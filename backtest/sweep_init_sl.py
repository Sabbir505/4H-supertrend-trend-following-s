"""Sweep the INITIAL STOP multiplier (and floor) for st_trail on the full
3-year window. Round-5d research: the 5xATR initial stop was never swept on
its own. Tuning is read on TRAIN (2023-10 -> 2025-04); 2025-04 -> 2026-09 is
holdout. Deployed config otherwise: band 0.5-5.0, Sunday skip, trail 3.5,
btc_st shorts, time stop 42.

Usage:  python sweep_init_sl.py
"""

import sys
from pathlib import Path

import pandas as pd

BT = Path(__file__).parent
sys.path.insert(0, str(BT))
sys.path.insert(0, str(BT.parent))

import runner
import strategies

runner.BT_START = pd.Timestamp("2023-10-01", tz="UTC")
runner.BT_END = pd.Timestamp("2026-09-01", tz="UTC")

strategies.REGISTRY["lab_init_sl"] = strategies.st_trail

BASE = dict(st_period=10, st_mult=3.5, trail_mult=3.5, ema=200,
            short_mode="btc_st", time_stop_bars=42,
            atr_min=0.5, atr_max=5.0, days=[0, 1, 2, 3, 4, 5])

GRID = [(m, f) for m in (2.0, 2.5, 3.0, 3.5, 4.0, 5.0) for f in (0.02,)
        + ((0.03,) if m in (2.0, 2.5, 3.0, 3.5) else ())]
# also: no floor at all
GRID += [(5.0, 0.005), (3.5, 0.005)]

rows = []
for mult, floor in GRID:
    name = f"lab_init_sl_{str(mult).replace('.', '_')}_{str(floor).replace('.', '_')}"
    strategies.REGISTRY[name] = strategies.st_trail
    params = {**BASE, "init_mult": mult, "init_floor": floor}
    m, trades = runner.run("4h", name, dict(params), split="full",
                           log=False, save_trades=True)
    tdf = trades if trades is not None else []
    rows.append({"init_mult": mult, "init_floor": floor,
                 "trades": m.get("trades"), "win": m.get("win_rate"),
                 "avg_r": m.get("avg_r"), "pf": m.get("profit_factor"),
                 "ret": m.get("total_return_pct"), "dd": m.get("max_dd_pct"),
                 "sharpe": m.get("sharpe")})
    print(f"init={mult}xATR floor={floor}: n={m.get('trades')} "
          f"win={m.get('win_rate')}% avgR={m.get('avg_r')} "
          f"PF={m.get('profit_factor')} ret={m.get('total_return_pct')}% "
          f"dd={m.get('max_dd_pct')}% sharpe={m.get('sharpe')}")

out = BT / "results" / "sweep_init_sl.csv"
pd.DataFrame(rows).to_csv(out, index=False)
print(f"saved {out}")
