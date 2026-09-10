"""30m parameter sweeps on the train split."""

import runner

# 1) Tuned EMA cross: asymmetric RR, optional HTF filter
runner.sweep('30m', 'emacross_tune', {
    'fast': [9, 22],
    'slow': [40, 55],
    'trend': [100, 200],
    'sl_mult': [1.0],
    'tp_mult': [1.5, 3.0],
    'htf_ema': [50, None],
}, split='train')

# 2) Connors RSI(2) mean reversion with trend + HTF filter
runner.sweep('30m', 'rsi2_mr', {
    'rsi_period': [2],
    'buy_th': [5, 10, 15],
    'sell_th': [85, 90, 95],
    'trend': [200],
    'htf_ema': [50],
    'sl_mult': [1.5],
    'tp_mult': [2.0],
}, split='train')

# 3) Bollinger mean reversion
runner.sweep('30m', 'bb_mr', {
    'period': [20],
    'ndev': [2.0, 2.5],
    'sl_mult': [1.0, 1.5],
    'htf_ema': [50],
}, split='train')

# 4) Donchian breakout with trail
runner.sweep('30m', 'breakout_30m', {
    'entry_n': [32, 48, 96],
    'trail_mult': [1.5, 2.5],
    'ema': [None, 200],
}, split='train')

# 5) Keltner breakout
runner.sweep('30m', 'keltner_break', {
    'period': [20],
    'mult': [1.5, 2.0],
    'ema': [200],
    'trail_mult': [2.0],
}, split='train')

print("30M SWEEPS COMPLETE")
