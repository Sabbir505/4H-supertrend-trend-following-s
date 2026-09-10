"""Strategy library.

Each strategy: fn(df, params) -> (plans, flip_dir_or_None)
- df: closed-candle OHLCV for one symbol (index = open_time, plus close_time col)
- plans: list[TradePlan] entries evaluated on closed candles
- flip_dir: optional per-bar direction array for 'flip' exits

Strategies mirror the production baseline first, then the researched families:
trend-following (Supertrend trail, Donchian breakout, pullback, MACD regime)
for 4H; EMA-cross tuning, RSI(2)/Bollinger mean reversion, breakouts for 30m.
"""

import numpy as np
import pandas as pd

import engine
import indicators as ind


def _atr_frac(df, a, i):
    close = df['close'].iat[i]
    return a.iat[i] / close if close > 0 else np.nan


# ─────────────────────────── 4H strategies ───────────────────────────

def baseline_4h(df, p):
    """Production 4H system: Supertrend flip + EMA200 + RSI + ATR% band.
    NOTE: production places SL and TP both at rr*ATR -> 1:1 reward:risk."""
    st, dirv = ind.supertrend(df, p['st_period'], p['st_mult'])
    e = ind.ema(df['close'], p['ema'])
    r = ind.rsi(df['close'], p['rsi'])
    a = ind.atr(df, p.get('atr_period', 14))
    atr_pct = a / df['close'] * 100

    prev = dirv.shift(1)
    flip_long = (prev == -1) & (dirv == 1)
    flip_short = (prev == 1) & (dirv == -1)
    ok = (atr_pct >= p['atr_min']) & (atr_pct <= p['atr_max'])

    longs = flip_long & ok & (df['close'] > e) & (r > p['rsi_long'])
    shorts = flip_short & ok & (df['close'] < e) & (r < p['rsi_short'])

    rr = p['rr']
    plans = []
    for i in np.flatnonzero((longs | shorts).to_numpy()):
        af = _atr_frac(df, a, i)
        if np.isnan(af):
            continue
        plans.append(engine.TradePlan(
            idx=int(i), direction=1 if longs.iat[i] else -1,
            sl_frac=rr * af, tp_frac=rr * af, exit_mode='fixed'))
    return plans, None


def st_trail(df, p):
    """Supertrend flip entry, ride the trend: chandelier ATR trail + exit on
    opposite flip. Classic low-win-rate / big-winner profile. Both directions.

    Gates (independently configurable):
    - longs:  close > symbol EMA(p['ema']) when 'ema' set
    - shorts: p['short_mode']:
        'sym_ema'  close < symbol EMA (mirror of longs; default)
        'btc_ema'  close < BTC EMA200   (BTC bear regime)
        'btc_st'   BTC Supertrend(10,3.5) direction == -1
        'd_ema'    close < BTC daily EMA50
        'none'     no short gate (shorts fire on every bearish flip)
    - partials: [[r_mult, fraction], ...] scaled take-profits
    - time_stop_bars / breakeven_at_r: exit engineering
    - gate_st: require symbol's own 4H supertrend agreement (LTF use)
    - atr_min / atr_max: ATR% entry band in percent (live parity; None = off)
    """
    st, dirv = ind.supertrend(df, p['st_period'], p['st_mult'])
    prev = dirv.shift(1)
    flip_long = (prev == -1) & (dirv == 1)
    flip_short = (prev == 1) & (dirv == -1)
    conds_l = np.ones(len(df), dtype=bool)
    conds_s = np.ones(len(df), dtype=bool)

    e = ind.ema(df['close'], p['ema']) if p.get('ema') else None
    if e is not None:
        conds_l &= (df['close'] > e).to_numpy()
    short_mode = p.get('short_mode', 'sym_ema')
    if short_mode == 'sym_ema':
        if e is not None:
            conds_s &= (df['close'] < e).to_numpy()
    elif short_mode == 'btc_ema':
        conds_s &= (df['close'] < df['btc_ema200']).to_numpy()
    elif short_mode == 'btc_st':
        conds_s &= (df['btc_st_dir'] == -1).to_numpy()
    elif short_mode == 'd_ema':
        conds_s &= (df['close'] < df['btc_d_ema50']).to_numpy()
    elif short_mode == 'none':
        pass
    if p.get('gate_st'):
        conds_l &= (df['htf_st_dir'] == 1).to_numpy()
        conds_s &= (df['htf_st_dir'] == -1).to_numpy()
    if p.get('adx_min'):
        a_ = ind.adx(df, p.get('adx_period', 14))
        conds_l &= (a_ > p['adx_min']).to_numpy()
        conds_s &= (a_ > p['adx_min']).to_numpy()
    if p.get('rsi_long'):
        r = ind.rsi(df['close'], p.get('rsi_period', 14))
        conds_l &= (r > p['rsi_long']).to_numpy()
    if p.get('rsi_short'):
        r = ind.rsi(df['close'], p.get('rsi_period', 14))
        conds_s &= (r < p['rsi_short']).to_numpy()
    if p.get('short_st2'):
        _, d2 = ind.supertrend(df, p['short_st2'][0], p['short_st2'][1])
        conds_s &= (d2 == -1).to_numpy()
    if p.get('vol_mult'):
        vol_ma = df['volume'].rolling(20).mean()
        vol_ok = (df['volume'] > p['vol_mult'] * vol_ma).to_numpy()
        conds_l &= vol_ok
        conds_s &= vol_ok
    if p.get('days'):
        allowed = set(p['days'])
        day_ok = np.isin(df.index.dayofweek, list(allowed))
        conds_l &= day_ok
        conds_s &= day_ok
    if p.get('daily_ema'):
        d_close = df['close'].resample('1D').last().dropna()
        d_ema = ind.ema(d_close, p['daily_ema'])
        d_gate = (d_close > d_ema).astype(float)
        # map daily gate to 4h bars: use value of the last FULLY CLOSED daily candle
        gate_src = d_gate.copy()
        gate_src.index = gate_src.index + pd.Timedelta('1D')  # daily close time
        gate_src.index = gate_src.index.astype('datetime64[us, UTC]')
        left = pd.DataFrame({'ct': df['close_time']}).sort_values('ct')
        left['ct'] = left['ct'].astype('datetime64[us, UTC]')
        right = gate_src.rename('g').reset_index()
        right.columns = ['ct', 'g']
        mapped = pd.merge_asof(left, right.sort_values('ct'),
                               on='ct', direction='backward')['g'].to_numpy()
        conds_l &= (mapped == 1)
        conds_s &= (mapped == 0)
    a = ind.atr(df, p.get('atr_period', 14))
    # Optional ATR% entry band, mirroring the live scanner's filter
    # (config.py atr_min_pct / atr_max_pct). Off by default: the round-4
    # final config was validated without it, so enabling it here AND live
    # keeps the deployed system identical to the tested one.
    if p.get('atr_min') is not None or p.get('atr_max') is not None:
        atr_pct = a / df['close'] * 100
        if p.get('atr_min') is not None:
            conds_l &= (atr_pct >= p['atr_min']).to_numpy()
            conds_s &= (atr_pct >= p['atr_min']).to_numpy()
        if p.get('atr_max') is not None:
            conds_l &= (atr_pct <= p['atr_max']).to_numpy()
            conds_s &= (atr_pct <= p['atr_max']).to_numpy()
    flip_long &= conds_l
    flip_short &= conds_s

    plans = []
    for i in np.flatnonzero((flip_long | flip_short).to_numpy()):
        af = _atr_frac(df, a, i)
        if np.isnan(af) or af <= 0:
            continue
        plans.append(engine.TradePlan(
            idx=int(i), direction=1 if flip_long.iat[i] else -1,
            sl_frac=max(5 * af, 0.02), tp_frac=None, exit_mode='trail',
            trail_mult=p['trail_mult'], atr_entry=a.iat[i],
            time_stop_bars=p.get('time_stop_bars'),
            breakeven_at_r=p.get('breakeven_at_r'),
            partials=p.get('partials'),
            atr_pct=af))
    return plans, dirv.to_numpy()


def st_asym(df, p):
    """Supertrend flip with asymmetric exits: tight-ish SL, wide TP."""
    plans, flip_dir = baseline_4h(df, {**p, 'rr': p['sl_mult']})
    a = ind.atr(df, p.get('atr_period', 14))
    for plan, i in zip(plans, [pl.idx for pl in plans]):
        af = _atr_frac(df, a, i)
        plan.tp_frac = p['tp_mult'] * af
    return plans, None


def donchian(df, p):
    """Donchian channel breakout with ATR trail (Turtle-style)."""
    n = p['entry_n']
    upper = df['high'].shift(1).rolling(n).max()
    lower = df['low'].shift(1).rolling(n).min()
    a = ind.atr(df, p.get('atr_period', 14))
    atr_pct = a / df['close'] * 100
    ok = (atr_pct >= p.get('atr_min', 0.4)) & (atr_pct <= p.get('atr_max', 8.0))
    longs = (df['close'] > upper) & ok
    shorts = (df['close'] < lower) & ok
    if p.get('ema'):
        e = ind.ema(df['close'], p['ema'])
        longs &= df['close'] > e
    if p.get('short_mode') == 'btc_st':
        shorts &= df['btc_st_dir'] == -1
    elif p.get('short_mode') == 'sym_ema' or p.get('short_mode') is None:
        if p.get('ema'):
            shorts &= df['close'] < ind.ema(df['close'], p['ema'])

    plans = []
    for i in np.flatnonzero((longs | shorts).to_numpy()):
        af = _atr_frac(df, a, i)
        if np.isnan(af) or af <= 0:
            continue
        plans.append(engine.TradePlan(
            idx=int(i), direction=1 if longs.iat[i] else -1,
            sl_frac=max(4 * af, 0.015), tp_frac=None, exit_mode='trail',
            trail_mult=p['trail_mult'], atr_entry=a.iat[i], atr_pct=af))
    return plans, None


def ema_pullback(df, p):
    """Trend regime + pullback to fast EMA + resumption entry."""
    slow = ind.ema(df['close'], p['ema_slow'])
    mid = ind.ema(df['close'], p['ema_mid'])
    fast = ind.ema(df['close'], p['ema_fast'])
    a = ind.atr(df, 14)
    up = (df['close'] > slow) & (mid > slow)
    dn = (df['close'] < slow) & (mid < slow)
    crossed_up = (df['close'] > fast) & (df['close'].shift(1) <= fast.shift(1))
    crossed_dn = (df['close'] < fast) & (df['close'].shift(1) >= fast.shift(1))
    # touched the fast EMA zone recently (pullback happened)
    near = (df['low'].rolling(4).min() <= fast * (1 + p.get('zone', 0.005)))
    near_dn = (df['high'].rolling(4).max() >= fast * (1 - p.get('zone', 0.005)))
    longs = up & crossed_up & near
    shorts = dn & crossed_dn & near_dn

    plans = []
    for i in np.flatnonzero((longs | shorts).to_numpy()):
        af = _atr_frac(df, a, i)
        if np.isnan(af) or af <= 0:
            continue
        plans.append(engine.TradePlan(
            idx=int(i), direction=1 if longs.iat[i] else -1,
            sl_frac=p['sl_mult'] * af, tp_frac=p['tp_mult'] * af,
            exit_mode='fixed'))
    return plans, None


def macd_regime(df, p):
    """MACD signal cross inside a trending regime (line above/below zero)."""
    line, sig = ind.macd(df['close'], 12, 26, 9)
    a = ind.atr(df, 14)
    up = line > 0
    dn = line < 0
    cross_up = (line > sig) & (line.shift(1) <= sig.shift(1))
    cross_dn = (line < sig) & (line.shift(1) >= sig.shift(1))
    if p.get('ema'):
        e = ind.ema(df['close'], p['ema'])
        up &= df['close'] > e
        dn &= df['close'] < e
    longs = up & cross_up
    shorts = dn & cross_dn

    plans = []
    for i in np.flatnonzero((longs | shorts).to_numpy()):
        af = _atr_frac(df, a, i)
        if np.isnan(af) or af <= 0:
            continue
        plans.append(engine.TradePlan(
            idx=int(i), direction=1 if longs.iat[i] else -1,
            sl_frac=p['sl_mult'] * af, tp_frac=p['tp_mult'] * af,
            exit_mode='fixed'))
    return plans, None


# ─────────────────────────── 30m strategies ───────────────────────────

def baseline_30m(df, p):
    """Production 30m system: EMA22/55 cross + EMA100 + 4h EMA50 filter.
    SL = TP = rr*ATR -> 1:1 reward:risk."""
    fast = ind.ema(df['close'], p['fast'])
    slow = ind.ema(df['close'], p['slow'])
    trend = ind.ema(df['close'], p['trend'])
    htf = df[f'htf_ema{p["htf_ema"]}']
    a = ind.atr(df, p.get('atr_period', 14))

    cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    cross_dn = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    c = df['close']
    longs = cross_up & (c > trend) & (c > htf)
    shorts = cross_dn & (c < trend) & (c < htf)

    rr = p['rr']
    plans = []
    for i in np.flatnonzero((longs | shorts).to_numpy()):
        af = _atr_frac(df, a, i)
        if np.isnan(af):
            continue
        plans.append(engine.TradePlan(
            idx=int(i), direction=1 if longs.iat[i] else -1,
            sl_frac=rr * af, tp_frac=rr * af, exit_mode='fixed'))
    return plans, None


def emacross_tune(df, p):
    """Tuned EMA cross: configurable MAs, optional HTF filter, asymmetric RR."""
    fast = ind.ema(df['close'], p['fast'])
    slow = ind.ema(df['close'], p['slow'])
    trend = ind.ema(df['close'], p['trend'])
    c = df['close']
    a = ind.atr(df, p.get('atr_period', 14))
    atr_pct = a / c * 100
    ok = (atr_pct >= p.get('atr_min', 0.15)) & (atr_pct <= p.get('atr_max', 3.0))

    cross_up = (fast > slow) & (fast.shift(1) <= slow.shift(1))
    cross_dn = (fast < slow) & (fast.shift(1) >= slow.shift(1))
    longs = cross_up & (c > trend) & ok
    shorts = cross_dn & (c < trend) & ok
    if p.get('htf_ema'):
        htf = df[f'htf_ema{p["htf_ema"]}']
        longs &= c > htf
        shorts &= c < htf

    plans = []
    for i in np.flatnonzero((longs | shorts).to_numpy()):
        af = _atr_frac(df, a, i)
        if np.isnan(af) or af <= 0:
            continue
        plans.append(engine.TradePlan(
            idx=int(i), direction=1 if longs.iat[i] else -1,
            sl_frac=p['sl_mult'] * af, tp_frac=p['tp_mult'] * af,
            exit_mode='fixed'))
    return plans, None


def rsi2_mr(df, p):
    """Connors-style RSI(2): buy sharp dips inside an uptrend, sell rips in a
    downtrend (higher-TF filter). Fixed asymmetric exits."""
    r = ind.rsi(df['close'], p['rsi_period'])
    trend = ind.ema(df['close'], p.get('trend', 200))
    htf = df[f'htf_ema{p.get("htf_ema", 50)}']
    a = ind.atr(df, 14)
    c = df['close']
    longs = (c > trend) & (c > htf) & (r < p['buy_th'])
    shorts = (c < trend) & (c < htf) & (r > p['sell_th'])

    plans = []
    for i in np.flatnonzero((longs | shorts).to_numpy()):
        af = _atr_frac(df, a, i)
        if np.isnan(af) or af <= 0:
            continue
        plans.append(engine.TradePlan(
            idx=int(i), direction=1 if longs.iat[i] else -1,
            sl_frac=p['sl_mult'] * af, tp_frac=p['tp_mult'] * af,
            exit_mode='fixed'))
    return plans, None


def bb_mr(df, p):
    """Bollinger mean reversion: tag of the lower band in an uptrend, exit at
    the mid band (dynamic TP), mirrored short."""
    mid, upper, lower = ind.bollinger(df['close'], p['period'], p['ndev'])
    htf = df[f'htf_ema{p.get("htf_ema", 50)}']
    a = ind.atr(df, 14)
    c = df['close']
    longs = (df['low'] < lower) & (c > htf)
    shorts = (df['high'] > upper) & (c < htf)

    plans = []
    for i in np.flatnonzero((longs | shorts).to_numpy()):
        af = _atr_frac(df, a, i)
        if np.isnan(af) or af <= 0:
            continue
        d = 1 if longs.iat[i] else -1
        # TP at mid band (relative to next open ~ close), min 0.3 ATR
        tp_frac = max((mid.iat[i] / c.iat[i] - 1) * d, 0.3 * af)
        plans.append(engine.TradePlan(
            idx=int(i), direction=d,
            sl_frac=p['sl_mult'] * af, tp_frac=tp_frac, exit_mode='fixed'))
    return plans, None


def breakout_30m(df, p):
    """Short-term Donchian breakout with ATR trail + optional EMA regime."""
    n = p['entry_n']
    upper = df['high'].shift(1).rolling(n).max()
    lower = df['low'].shift(1).rolling(n).min()
    a = ind.atr(df, 14)
    atr_pct = a / df['close'] * 100
    ok = (atr_pct >= p.get('atr_min', 0.15)) & (atr_pct <= p.get('atr_max', 3.0))
    longs = (df['close'] > upper) & ok
    shorts = (df['close'] < lower) & ok
    if p.get('ema'):
        e = ind.ema(df['close'], p['ema'])
        longs &= df['close'] > e
        shorts &= df['close'] < e

    plans = []
    for i in np.flatnonzero((longs | shorts).to_numpy()):
        af = _atr_frac(df, a, i)
        if np.isnan(af) or af <= 0:
            continue
        plans.append(engine.TradePlan(
            idx=int(i), direction=1 if longs.iat[i] else -1,
            sl_frac=max(3 * af, 0.008), tp_frac=None, exit_mode='trail',
            trail_mult=p['trail_mult'], atr_entry=a.iat[i]))
    return plans, None


def keltner_break(df, p):
    """Keltner channel breakout with trend filter."""
    mid, upper, lower = ind.keltner(df, p['period'], p['mult'])
    e = ind.ema(df['close'], p.get('ema', 200))
    a = ind.atr(df, 14)
    longs = (df['close'] > upper) & (df['close'] > e)
    shorts = (df['close'] < lower) & (df['close'] < e)

    plans = []
    for i in np.flatnonzero((longs | shorts).to_numpy()):
        af = _atr_frac(df, a, i)
        if np.isnan(af) or af <= 0:
            continue
        plans.append(engine.TradePlan(
            idx=int(i), direction=1 if longs.iat[i] else -1,
            sl_frac=max(3 * af, 0.008), tp_frac=None, exit_mode='trail',
            trail_mult=p['trail_mult'], atr_entry=a.iat[i]))
    return plans, None


def squeeze_break(df, p):
    """Volatility squeeze: Bollinger inside Keltner compresses, trade the
    release breakout in either direction. Trail exit."""
    mid_b, up_b, lo_b = ind.bollinger(df['close'], 20, 2.0)
    mid_k, up_k, lo_k = ind.keltner(df, 20, p.get('kc_mult', 1.5))
    a = ind.atr(df, 14)
    squeeze = (up_b < up_k) & (lo_b > lo_k)
    rel_up = squeeze.shift(1).fillna(False) & (df['close'] > up_b)
    rel_dn = squeeze.shift(1).fillna(False) & (df['close'] < lo_b)
    if p.get('ema'):
        e = ind.ema(df['close'], p['ema'])
        rel_up &= df['close'] > e
        rel_dn &= df['close'] < e
    atr_pct = a / df['close'] * 100
    ok = (atr_pct >= p.get('atr_min', 0.4)) & (atr_pct <= p.get('atr_max', 8.0))
    longs = rel_up & ok
    shorts = rel_dn & ok

    plans = []
    for i in np.flatnonzero((longs | shorts).to_numpy()):
        af = _atr_frac(df, a, i)
        if np.isnan(af) or af <= 0:
            continue
        plans.append(engine.TradePlan(
            idx=int(i), direction=1 if longs.iat[i] else -1,
            sl_frac=max(4 * af, 0.015), tp_frac=None, exit_mode='trail',
            trail_mult=p['trail_mult'], atr_entry=a.iat[i], atr_pct=af))
    return plans, None


REGISTRY = {
    'baseline_4h': baseline_4h,
    'st_trail': st_trail,
    'st_asym': st_asym,
    'donchian': donchian,
    'ema_pullback': ema_pullback,
    'macd_regime': macd_regime,
    'squeeze_break': squeeze_break,
    'baseline_30m': baseline_30m,
    'emacross_tune': emacross_tune,
    'rsi2_mr': rsi2_mr,
    'bb_mr': bb_mr,
    'breakout_30m': breakout_30m,
    'keltner_break': keltner_break,
}
