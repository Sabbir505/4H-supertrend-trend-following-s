"""
Sweep ATR% floor on st_trail (production strategy) without modifying
the production code.  Wraps st_trail, adds an ATR% gate, and injects
the wrapper into the REGISTRY temporarily.

Run:  python backtest/sweep_st_trail_atr.py
"""

import sys
import os

_proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_bt   = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _proj)
sys.path.insert(0, _bt)

import strategies
from strategies import st_trail
import runner as runner_mod

# ── Sweep config ─────────────────────────────────────────────────────────
# 0.0 = no filter (baseline equivalent), then progressive floors
ATR_FLOORS   = [0.0, 0.4, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0]
ATR_CEILINGS = [5.0, 4.0, 3.0]

# Production st_trail params (best from existing ledger)
BASE_PARAMS = {
    "st_period": 10,
    "st_mult": 3.5,
    "ema": 200,
    "trail_mult": 3.5,
    "short_mode": "btc_st",
    "time_stop_bars": 42,
    "days": [0, 1, 2, 3, 4, 5],
}

# ── Wrapper: st_trail + ATR% gate ────────────────────────────────────────
def make_st_trail_atr(atr_min, atr_max):
    """Return a strategy function that wraps st_trail with an ATR% band."""
    def _strat(df, p):
        plans, flip_dir = st_trail(df, p)
        if atr_min <= 0 and atr_max >= 100:
            return plans, flip_dir
        filtered = [
            pl for pl in plans
            if pl.atr_pct * 100 >= atr_min and pl.atr_pct * 100 <= atr_max
        ]
        return filtered, flip_dir
    return _strat


# ── Run sweep ────────────────────────────────────────────────────────────
header = (f"{'#':>4} {'atr_min':>7} {'atr_max':>7} {'split':>6}  "
          f"{'net%':>8}  {'win%':>6}  {'trades':>7}  {'PF':>5}  "
          f"{'sharpe':>7}  {'avgR':>6}  {'maxDD':>6}")
print(header)
print("-" * 100)

run = 0
sweep_name = "st_trail_atr"

for atr_min in ATR_FLOORS:
    for atr_max in ATR_CEILINGS:
        if atr_min > atr_max:
            continue

        strat_fn = make_st_trail_atr(atr_min, atr_max)
        tag = f"{sweep_name}_min{atr_min}_max{atr_max}"
        strategies.REGISTRY[tag] = strat_fn

        params = {**BASE_PARAMS, "atr_min": atr_min, "atr_max": atr_max}

        for split_name in ["train", "valid", "full"]:
            try:
                m, trades_df = runner_mod.run(
                    "4h", tag, params,
                    split=split_name, log=True, save_trades=False,
                )
                net    = m.get("total_return_pct", 0) or 0
                win    = m.get("win_rate", 0)
                n      = m.get("trades", 0)
                pf     = m.get("profit_factor", 0)
                sharpe = m.get("sharpe", 0)
                avg_r  = m.get("avg_r", 0)
                maxdd  = m.get("max_dd_pct", 0)
                run += 1
                print(f"{run:>4} {atr_min:>7.1f} {atr_max:>7.1f} {split_name:>6}  "
                      f"{net:>+8.2f}  {win:>6.1f}  {n:>7}  {pf:>5.2f}  "
                      f"{sharpe:>+7.2f}  {avg_r:>+6.2f}  {maxdd:>6.1f}")
            except Exception as e:
                print(f"  ! min={atr_min} max={atr_max} "
                      f"split={split_name} failed: {e}")

        del strategies.REGISTRY[tag]

print(f"\nDone: {run} runs complete, see backtest/experiments/experiments.csv")
