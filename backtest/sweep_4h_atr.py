"""
Sweep ATR% floor and ceiling for baseline_4h on 4H timeframe.
Logs each run to backtest/experiments/experiments.csv (runner.run does this automatically).
Run: python backtest/sweep_4h_atr.py
"""

import sys
import os

_proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_bt   = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _proj)
sys.path.insert(0, _bt)

from backtest import runner

# Splits matching the rest of the backtest ledger
SPLITS = {
    "train": ("2023-01-01", "2024-01-01"),
    "valid": ("2024-01-01", "2025-08-01"),
    "full":  ("2023-01-01", "2025-08-01"),
}

# ATR% floor sweep (keep max fixed at 5.0)
ATR_FLOORS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5]

# ATR% ceiling sweep (keep floor fixed at 0.5)
ATR_CEILINGS = [3.0, 4.0, 5.0, 6.0, 7.0]

BASE_PARAMS = {
    "st_period": 12,
    "st_mult": 3.5,
    "ema": 200,
    "rsi": 14,
    "rsi_long": 55,
    "rsi_short": 45,
    "rr": 1.5,
}

run = 0
print(f"{'#':>4} {'atr_min':>7} {'atr_max':>7} {'split':>6}  {'net %':>8}  {'win%':>6}  {'trades':>7}  {'PF':>5}  {'sharpe':>7}  {'maxDD':>6}")
print("-" * 95)

for split_name, (start, end) in SPLITS.items():
    # ── Floor sweep: vary atr_min, fixed atr_max=5.0 ──────────────────────────
    for atr_min in ATR_FLOORS:
        params = {**BASE_PARAMS, "atr_min": atr_min, "atr_max": 5.0}
        try:
            metrics, trades = runner.run(
                timeframe="4h",
                strategy_name="baseline_4h",
                params=params,
                split=split_name,
                log=True,
                symbols=None,
                save_trades=False,
            )
            m = metrics or {}
            net    = m.get("total_return_pct", 0) or 0
            win    = m.get("win_rate", 0)
            n      = m.get("trades", 0)
            pf     = m.get("profit_factor", 0)
            sharpe = m.get("sharpe", 0)
            maxdd  = m.get("max_dd_pct", 0)
            run += 1
            print(f"{run:>4} {atr_min:>7.1f} {5.0:>7.1f} {split_name:>6}  {net:>+8.2f}  {win:>6.1f}  {n:>7}  {pf:>5.2f}  {sharpe:>+7.2f}  {maxdd:>6.1f}")
        except Exception as e:
            print(f"  ! floor {atr_min} split {split_name} failed: {e}")

    # ── Ceiling sweep: fixed atr_min=0.5, vary atr_max ────────────────────────
    for atr_max in ATR_CEILINGS:
        params = {**BASE_PARAMS, "atr_min": 0.5, "atr_max": atr_max}
        try:
            metrics, trades = runner.run(
                timeframe="4h",
                strategy_name="baseline_4h",
                params=params,
                split=split_name,
                log=True,
                symbols=None,
                save_trades=False,
            )
            m = metrics or {}
            net    = m.get("total_return_pct", 0) or 0
            win    = m.get("win_rate", 0)
            n      = m.get("trades", 0)
            pf     = m.get("profit_factor", 0)
            sharpe = m.get("sharpe", 0)
            maxdd  = m.get("max_dd_pct", 0)
            run += 1
            print(f"{run:>4} {0.5:>7.1f} {atr_max:>7.1f} {split_name:>6}  {net:>+8.2f}  {win:>6.1f}  {n:>7}  {pf:>5.2f}  {sharpe:>+7.2f}  {maxdd:>6.1f}")
        except Exception as e:
            print(f"  ! ceiling {atr_max} split {split_name} failed: {e}")

print(f"\nDone: {run} runs complete, see backtest/experiments/experiments.csv")
