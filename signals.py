"""
Signal Engine v4 — Triple Confirmation Trend System (4-TP)
4-TP incremental closing system:
  - TP1 at 1.5x SL distance (1.5:1 RR) — close 40%
  - TP2 at 2.0x SL distance (2.0:1 RR) — close 30%
  - TP3 at 3.0x SL distance (3.0:1 RR) — close 20%
  - TP4 at 4.0x SL distance (4.0:1 RR) — close 10%
  - SL = 1.0x ATR (tighter stops)
  - ADX threshold 25
  - Volume > 1.2x MA
  - MACD uses histogram direction + min strength (ATR*0.1)
"""

import pandas as pd
import numpy as np
import logging
from config import Config

logger = logging.getLogger(__name__)


class SignalEngine:

    def __init__(self, config=None):
        """Initialize with config for TP/SL multipliers"""
        self.config = config or Config()

    # ─── Indicator Calculations ───────────────────────────────────────────────

    def ema(self, series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    def rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi_series = 100 - (100 / (1 + rs))
        # When avg_loss is 0 and avg_gain > 0, RSI = 100 (all gains)
        # When both are 0 (flat market), RSI should be 50 (neutral)
        flat_market = (avg_gain == 0) & (avg_loss == 0)
        rsi_series = rsi_series.where(~flat_market, 50)
        return rsi_series.fillna(100)

    def macd(self, series: pd.Series, fast=12, slow=26, signal=9):
        ema_fast = self.ema(series, fast)
        ema_slow = self.ema(series, slow)
        macd_line = ema_fast - ema_slow
        signal_line = self.ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    def atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df['high']
        low = df['low']
        prev_close = df['close'].shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ], axis=1).max(axis=1)
        return tr.ewm(com=period - 1, adjust=False).mean()

    def volume_ma(self, series: pd.Series, period: int = 20) -> pd.Series:
        return series.rolling(window=period).mean()

    def adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        Average Directional Index — measures trend STRENGTH (not direction)
        ADX > 25 = strong trend, worth trading
        ADX < 20 = choppy/sideways, avoid
        """
        high = df['high']
        low  = df['low']
        prev_high  = high.shift(1)
        prev_low   = low.shift(1)
        prev_close = df['close'].shift(1)

        # True Range
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs()
        ], axis=1).max(axis=1)

        # Directional movements
        up_move   = high - prev_high
        down_move = prev_low - low

        plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        plus_dm_s  = pd.Series(plus_dm,  index=df.index).ewm(com=period-1, adjust=False).mean()
        minus_dm_s = pd.Series(minus_dm, index=df.index).ewm(com=period-1, adjust=False).mean()
        atr_s      = tr.ewm(com=period-1, adjust=False).mean()

        plus_di  = 100 * plus_dm_s  / atr_s.replace(0, np.nan)
        minus_di = 100 * minus_dm_s / atr_s.replace(0, np.nan)

        di_sum = plus_di + minus_di
        dx = 100 * (plus_di - minus_di).abs() / di_sum.replace(0, np.nan)
        adx_series = dx.ewm(com=period-1, adjust=False).mean()
        # When both DI are 0, there's no directional movement = no trend
        return adx_series.fillna(0)

    # ─── Trend Bias (4H) ─────────────────────────────────────────────────────

    def get_trend_bias(self, df: pd.DataFrame) -> str:
        """
        Determines 4H trend bias: LONG, SHORT, or NEUTRAL
        EMA21/55 cross + RSI + ADX confirmation
        """
        close = df['close']
        ema21   = self.ema(close, 21)
        ema55   = self.ema(close, 55)
        rsi_val = self.rsi(close, 14)
        adx_val = self.adx(df, 14)

        last_ema21 = ema21.iloc[-1]
        last_ema55 = ema55.iloc[-1]
        last_rsi   = rsi_val.iloc[-1]
        last_adx   = adx_val.iloc[-1]

        # Require ADX > 20 on 4H for trend to be valid
        if last_adx < 20:
            return 'NEUTRAL'

        if last_ema21 > last_ema55 and last_rsi > 50:
            return 'LONG'
        elif last_ema21 < last_ema55 and last_rsi < 50:
            return 'SHORT'
        else:
            return 'NEUTRAL'

    # ─── Signal Generation (1H) ──────────────────────────────────────────────

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> dict | None:
        """
        Generates a trading signal from 1H candle data.
        4-TP system:
          - TP1 at 1.5x SL (1.5:1 RR), close 40%
          - TP2 at 2.0x SL (2.0:1 RR), close 30%
          - TP3 at 3.0x SL (3.0:1 RR), close 20%
          - TP4 at 4.0x SL (4.0:1 RR), close 10%
        """
        if len(df) < 60:
            return None

        close = df['close']

        # Calculate all indicators
        ema21  = self.ema(close, 21)
        ema55  = self.ema(close, 55)
        rsi_vals = self.rsi(close, 14)
        macd_line, signal_line, histogram = self.macd(close)
        atr_vals = self.atr(df, 14)
        vol_ma   = self.volume_ma(df['volume'], 20)
        adx_vals = self.adx(df, 14)

        # Current candle values
        price      = close.iloc[-1]
        last_rsi   = rsi_vals.iloc[-1]
        last_hist  = histogram.iloc[-1]
        last_ema21 = ema21.iloc[-1]
        last_ema55 = ema55.iloc[-1]
        last_atr   = atr_vals.iloc[-1]
        last_vol   = df['volume'].iloc[-1]
        last_vol_ma = vol_ma.iloc[-1]
        last_adx   = adx_vals.iloc[-1]

        # ── Volume validation (Bug #9 fix)──────────────────────
        if last_vol_ma <= 0:
            logger.warning(f"{symbol} Invalid volume MA (<=0), skipping signal")
            return None

        # ── FIX 1: ADX filter — only trade strong trends ──────────────────
        if last_adx < 25:
            return None

        # ── FIX 2: Volume confirmation — must be > 1.2x average ──────────
        vol_confirmed = last_vol > last_vol_ma * 1.2
        if not vol_confirmed:
            return None

        vol_ratio = last_vol / last_vol_ma

        # EMA direction
        ema_bullish = last_ema21 > last_ema55
        ema_bearish = last_ema21 < last_ema55

        # ── FIX 3: MACD histogram direction + strength (not cross-only) ────
        macd_bullish = last_hist > 0
        macd_bearish = last_hist < 0

        # Reject weak momentum — histogram must exceed ATR * 0.1
        hist_min_strength = last_atr * 0.1
        if macd_bullish and last_hist < hist_min_strength:
            macd_bullish = False
        if macd_bearish and abs(last_hist) < hist_min_strength:
            macd_bearish = False

        direction = None

        if (ema_bullish and
                40 < last_rsi < 80 and
                macd_bullish):
            direction = 'LONG'

        elif (ema_bearish and
              20 < last_rsi < 60 and
              macd_bearish):
            direction = 'SHORT'

        if direction is None:
            return None

        # ── SL/TP Calculation using config multipliers ─────────────────
        sl_distance = last_atr * self.config.atr_sl_multiplier

        # Validate ATR before using in calculations
        if sl_distance <= 0:
            logger.warning(f"{symbol}: Invalid SL distance ({sl_distance}), skipping signal")
            return None

        if direction == 'LONG':
            entry = price
            sl  = entry - sl_distance
            tp1 = entry + sl_distance * self.config.atr_tp1_multiplier
            tp2 = entry + sl_distance * self.config.atr_tp2_multiplier
            tp3 = entry + sl_distance * self.config.atr_tp3_multiplier
            tp4 = entry + sl_distance * self.config.atr_tp4_multiplier
        else:
            entry = price
            sl  = entry + sl_distance
            tp1 = entry - sl_distance * self.config.atr_tp1_multiplier
            tp2 = entry - sl_distance * self.config.atr_tp2_multiplier
            tp3 = entry - sl_distance * self.config.atr_tp3_multiplier
            tp4 = entry - sl_distance * self.config.atr_tp4_multiplier

        rr1   = round(abs(tp1 - entry) / abs(sl - entry), 2)
        rr2   = round(abs(tp2 - entry) / abs(sl - entry), 2)
        rr3   = round(abs(tp3 - entry) / abs(sl - entry), 2)
        rr_max = round(abs(tp4 - entry) / abs(sl - entry), 2)

        # ── Quality Score (v5: adjusted based on backtest data) ───────────────
        score = 0

        # Early ATR check before scoring
        if last_atr <= 0:
            logger.warning(f"{symbol}: ATR is {last_atr}, skipping signal (zero volatility)")
            return None

        # RSI quality: reward optimal range proximity
        # For LONG: ideal is 60-65 (strong but not overbought)
        # For SHORT: ideal is 35-40 (weak but not oversold)
        if direction == 'LONG':
            rsi_optimal = 62.5  # Sweet spot between 50-75
            rsi_dist = abs(last_rsi - rsi_optimal)
            score += max(0, 25 - rsi_dist * 1.5)  # Closer to 62.5 = higher score
        else:
            rsi_optimal = 37.5  # Sweet spot between 25-50
            rsi_dist = abs(last_rsi - rsi_optimal)
            score += max(0, 25 - rsi_dist * 1.5)

        # MACD histogram strength (not just direction)
        hist_strength = min(abs(last_hist) / last_atr * 10, 30)
        score += hist_strength  # Stronger histogram = higher score

        # Volume strength (increased weight - volume matters)
        score += min(vol_ratio * 15, 30)  # Up to 30 points for high volume

        # ADX trend quality (penalize extremely high ADX)
        # Backtest showed ADX ~27 performed best, ADX >40 worse
        if 25 <= last_adx <= 35:
            score += 20  # Optimal trend strength
        elif 35 < last_adx <= 45:
            score += 10  # Acceptable but strong
        else:
            score += 0   # Too weak or too strong = no bonus

        # Bug #37 fix: Validate signal data before returning
        if pd.isna(entry) or pd.isna(sl) or pd.isna(tp1) or pd.isna(tp2) or pd.isna(tp3) or pd.isna(tp4):
            logger.warning(f"{symbol}: Invalid signal data (NaN values), skipping")
            return None
        if not np.isfinite(entry) or not np.isfinite(sl) or not np.isfinite(tp1) or not np.isfinite(tp2) or not np.isfinite(tp3) or not np.isfinite(tp4):
            logger.warning(f"{symbol}: Invalid signal data (infinite values), skipping")
            return None
        if sl_distance <= 0:
            logger.warning(f"{symbol}: Invalid SL distance (<=0), skipping")
            return None

        def fmt(val):
            if val > 1000:    return round(val, 2)
            elif val > 10:    return round(val, 3)
            elif val > 1:     return round(val, 4)
            else:             return round(val, 6)

        return {
            'symbol':        symbol,
            'direction':     direction,
            'entry':         fmt(entry),
            'sl':            fmt(sl),
            'tp1':           fmt(tp1),
            'tp2':           fmt(tp2),
            'tp3':           fmt(tp3),
            'tp4':           fmt(tp4),
            'rr1':           rr1,
            'rr2':           rr2,
            'rr3':           rr3,
            'rr_max':        rr_max,
            'rsi':           round(last_rsi, 1),
            'adx':           round(last_adx, 1),
            'macd_direction': 'LONG' if last_hist > 0 else 'SHORT',  # Direction of MACD histogram
            'vol_confirmed': True,
            'vol_ratio':     round(vol_ratio, 2),
            'atr':           fmt(last_atr),
            'quality_score': min(round(score, 1), 100.0),
            'strength':      None,
            'four_h_confirmed': False,
        }