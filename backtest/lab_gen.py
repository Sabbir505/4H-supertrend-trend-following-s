"""Research lab — trade generation.

Generates the trade sets used by lab_eval.py (overlays/folds are computed
there without re-simulating). Registered under lab_* names so the shared
results/ CSVs from prior research are never clobbered.

Usage:  python lab_gen.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import runner
import strategies

# Same function object; lab_* aliases only control the results/ CSV filename.
strategies.REGISTRY['lab_prod'] = strategies.st_trail
strategies.REGISTRY['lab_prod_sun'] = strategies.st_trail

PROD = dict(st_period=10, st_mult=3.5, trail_mult=3.5, ema=200,
            short_mode='btc_st', time_stop_bars=42,
            atr_min=0.5, atr_max=5.0)

VARIANTS = {
    'lab_prod': PROD,
    'lab_prod_sun': {**PROD, 'days': [0, 1, 2, 3, 4, 5]},   # no-Sunday filter
}

for name, params in VARIANTS.items():
    for split in ('train', 'valid', 'full'):
        m, trades = runner.run('4h', name, dict(params), split=split,
                               log=False, save_trades=True)
        print(f"{name} {split:5s} n={m.get('trades')} ret={m.get('total_return_pct')}% "
              f"dd={m.get('max_dd_pct')}% sharpe={m.get('sharpe')}")
print("DONE")
