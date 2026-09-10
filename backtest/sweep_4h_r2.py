"""Round 2: confluence (BTC regime), exit engineering (partials, time-stop,
break-even), squeeze breakout — 4H train window."""

import runner

BASE = dict(st_period=10, st_mult=3.5, trail_mult=3.5, ema=200)

# 1) BTC regime confluence
# NOTE: st_trail reads this gate via `short_mode`; valid values are
# 'btc_ema', 'btc_st', 'd_ema'. An earlier version passed a nonexistent
# `btc_filter` param, so those runs silently used the default symbol-EMA
# short gate and the printed labels were wrong.
for f in ('btc_ema', 'btc_st', 'd_ema'):
    p = {**BASE, 'short_mode': f}
    m, _ = runner.run('4h', 'st_trail', p, split='train', log=True)
    print('BTC-GATE', f, '->', {k: m[k] for k in
          ('trades', 'win_rate', 'avg_r', 'profit_factor', 'max_dd_pct')})

# 2) Multi-TP scaled exits (both directions, remainder trails)
for partials in ([[1.0, 0.5]], [[1.5, 0.5]], [[1.0, 0.5], [2.0, 0.25]], [[2.0, 0.33]]):
    p = {**BASE, 'partials': partials}
    m, _ = runner.run('4h', 'st_trail', p, split='train', log=True)
    print('PARTIALS', partials, '->', {k: m[k] for k in
          ('trades', 'win_rate', 'avg_r', 'profit_factor', 'max_dd_pct')})

# 3) Time stop + break-even (chop-bleed control)
for ts in (21, 42):
    p = {**BASE, 'time_stop_bars': ts}
    m, _ = runner.run('4h', 'st_trail', p, split='train', log=True)
    print('TIME-STOP', ts, '->', {k: m[k] for k in
          ('trades', 'win_rate', 'avg_r', 'profit_factor', 'max_dd_pct')})
for be in (1.0, 1.5):
    p = {**BASE, 'breakeven_at_r': be}
    m, _ = runner.run('4h', 'st_trail', p, split='train', log=True)
    print('BREAKEVEN', be, '->', {k: m[k] for k in
          ('trades', 'win_rate', 'avg_r', 'profit_factor', 'max_dd_pct')})

# 4) Best combos: BTC gate + partials
for f, partials in (('btc_ema', [[1.5, 0.5]]), ('btc_st', [[1.5, 0.5]]),
                    ('btc_ema', [[1.0, 0.5], [2.0, 0.25]])):
    p = {**BASE, 'short_mode': f, 'partials': partials}
    m, _ = runner.run('4h', 'st_trail', p, split='train', log=True)
    print('COMBO', f, partials, '->', {k: m[k] for k in
          ('trades', 'win_rate', 'avg_r', 'profit_factor', 'max_dd_pct')})

# 5) Squeeze breakout (new family)
runner.sweep('4h', 'squeeze_break', {
    'trail_mult': [2.5, 3.5],
    'ema': [None, 200],
    'kc_mult': [1.5],
}, split='train')

print("ROUND-2 4H COMPLETE")
