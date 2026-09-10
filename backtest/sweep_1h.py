"""1H parameter sweeps on the train split."""

import runner

# 1) Supertrend trail — the 4H winner, on 1h bars
runner.sweep('1h', 'st_trail', {
    'st_period': [12, 20, 30],
    'st_mult': [3.0, 3.5, 4.0],
    'trail_mult': [2.5, 3.5],
    'ema': [None, 200],
}, split='train')

# 2) Donchian breakout
runner.sweep('1h', 'donchian', {
    'entry_n': [48, 96, 168],
    'trail_mult': [3.0, 5.0],
    'ema': [None, 200],
}, split='train')

# 3) EMA cross with 4h EMA50 HTF filter (1h analog of the 30m system)
runner.sweep('1h', 'emacross_tune', {
    'fast': [12, 22],
    'slow': [48, 55],
    'trend': [100, 200],
    'sl_mult': [1.0],
    'tp_mult': [1.5, 3.0],
    'htf_ema': [50],
}, split='train')

# 4) RSI(2) mean reversion with 4h filter
runner.sweep('1h', 'rsi2_mr', {
    'rsi_period': [2],
    'buy_th': [10],
    'sell_th': [90],
    'trend': [200],
    'htf_ema': [50],
    'sl_mult': [1.5],
    'tp_mult': [2.0],
}, split='train')

# 5) Short Donchian breakout
runner.sweep('1h', 'breakout_30m', {
    'entry_n': [48, 96],
    'trail_mult': [2.5],
    'ema': [200],
}, split='train')

print("1H SWEEPS COMPLETE")
