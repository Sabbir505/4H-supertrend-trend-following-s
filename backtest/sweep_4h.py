"""4H parameter sweeps on the train split."""

import runner

# 1) Supertrend flip + trail exit (ride trends)
runner.sweep('4h', 'st_trail', {
    'st_period': [10, 12, 14, 20],
    'st_mult': [3.0, 3.5, 4.0],
    'trail_mult': [2.5, 3.5],
    'ema': [None, 200],
}, split='train')

# 2) Supertrend flip + asymmetric fixed exits
runner.sweep('4h', 'st_asym', {
    'st_period': [12, 20],
    'st_mult': [3.5],
    'ema': [200],
    'rsi': [14],
    'rsi_long': [55],
    'rsi_short': [45],
    'atr_min': [0.5],
    'atr_max': [5.0],
    'atr_period': [14],
    'sl_mult': [1.5],
    'tp_mult': [3.0, 4.5],
}, split='train')

# 3) Donchian breakout + trail
runner.sweep('4h', 'donchian', {
    'entry_n': [24, 42, 60],
    'trail_mult': [3.0, 5.0],
    'ema': [None, 200],
}, split='train')

# 4) EMA pullback
runner.sweep('4h', 'ema_pullback', {
    'ema_slow': [200],
    'ema_mid': [50],
    'ema_fast': [20],
    'sl_mult': [1.5],
    'tp_mult': [2.0, 3.0],
    'zone': [0.005, 0.01],
}, split='train')

# 5) MACD regime
runner.sweep('4h', 'macd_regime', {
    'ema': [None, 200],
    'sl_mult': [1.5],
    'tp_mult': [2.0, 3.0],
}, split='train')

print("4H SWEEPS COMPLETE")
