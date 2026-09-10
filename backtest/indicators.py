"""Indicator library — mirrors the production scanner's math (Wilder ATR/RSI)
so backtests evaluate exactly what the live system computes."""

import numpy as np
import pandas as pd


def ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, prev_close = df['high'], df['low'], df['close'].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def supertrend(df: pd.DataFrame, atr_period: int = 12, mult: float = 3.5):
    """Returns (supertrend, direction) with direction 1=bullish, -1=bearish.
    Same algorithm as the production scanner."""
    a = atr(df, atr_period)
    hl2 = (df['high'] + df['low']) / 2.0
    prev_close = df['close'].shift(1)
    basic_upper = hl2 + mult * a
    basic_lower = hl2 - mult * a
    final_upper = basic_upper.copy()
    final_lower = basic_lower.copy()

    close = df['close'].to_numpy(copy=True)
    bu = basic_upper.to_numpy(copy=True)
    bl = basic_lower.to_numpy(copy=True)
    fu = final_upper.to_numpy(copy=True)
    fl = final_lower.to_numpy(copy=True)
    pc = prev_close.to_numpy()
    n = len(df)

    for i in range(1, n):
        if np.isnan(bu[i]) or np.isnan(fl[i - 1]):
            continue
        if bu[i] <= fl[i - 1] or (not np.isnan(pc[i - 1]) and pc[i - 1] > fu[i - 1]):
            fu[i] = bu[i]
        else:
            fu[i] = bu[i] if bu[i] < fu[i - 1] else fu[i - 1]
        if bl[i] >= fu[i - 1] or (not np.isnan(pc[i - 1]) and pc[i - 1] < fl[i - 1]):
            fl[i] = bl[i]
        else:
            fl[i] = bl[i] if bl[i] > fl[i - 1] else fl[i - 1]

    direction = np.full(n, np.nan)
    st = np.full(n, np.nan)
    if n > 0 and not np.isnan(fu[0]) and not np.isnan(fl[0]):
        direction[0] = 1 if close[0] >= fu[0] else -1
        st[0] = fu[0] if direction[0] == 1 else fl[0]
    for i in range(1, n):
        if np.isnan(direction[i - 1]) or np.isnan(st[i - 1]):
            if not np.isnan(fu[i]):
                direction[i] = 1 if close[i] >= fu[i] else -1
                st[i] = fu[i] if direction[i] == 1 else fl[i]
            continue
        if direction[i - 1] == 1 and close[i] < st[i - 1]:
            direction[i] = -1
            st[i] = fu[i]
        elif direction[i - 1] == -1 and close[i] > st[i - 1]:
            direction[i] = 1
            st[i] = fl[i]
        else:
            direction[i] = direction[i - 1]
            st[i] = fu[i] if direction[i] == -1 else fl[i]
    return pd.Series(st, index=df.index), pd.Series(direction, index=df.index)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig


def bollinger(close: pd.Series, period: int = 20, ndev: float = 2.0):
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std()
    return mid, mid + ndev * sd, mid - ndev * sd


def keltner(df: pd.DataFrame, period: int = 20, mult: float = 1.5):
    mid = ema(df['close'], period)
    rng = ema(atr(df, period), period)
    return mid, mid + mult * rng, mid - mult * rng


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ADX (trend strength, 0-100)."""
    up = df['high'].diff()
    down = -df['low'].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr_r = atr(df, 1)  # true range (period=1 -> raw TR smoothing)
    atr_s = tr_r.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_s
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_s
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean()


def htf_ema_series(htf_close: pd.Series, period: int) -> pd.Series:
    """EMA on the higher-timeframe close series (closed candles only)."""
    return ema(htf_close, period)
