"""
CryptoScanner — Fetches top 100 symbols by volume and volatility from Binance
and detects Supertrend signals on the 4H timeframe with 200 EMA, RSI(14),
and ATR% volatility filters.
"""

import requests
import pandas as pd
import numpy as np
import logging
import time
from datetime import datetime, timezone
from config import Config

logger = logging.getLogger(__name__)


class CryptoScanner:
    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.binance_base_url
        self._symbol_cache = []
        self._cache_time = 0
        self._cache_ttl = 3600  # Refresh symbol list every 1H
        self._futures_symbols = None  # Cached futures symbol set

    def _get_futures_symbols(self) -> dict:
        """Fetch available symbols from Binance Futures API.
        Returns a dict mapping spot base names to their futures symbol name.
        e.g. {'PEPE': '1000PEPEUSDT', 'BTC': 'BTCUSDT'}
        """
        if self._futures_symbols is not None and hasattr(self, '_futures_cache_time'):
            if time.time() - self._futures_cache_time < 3600:
                return self._futures_symbols
        try:
            url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            self._futures_symbols = {}
            for s in data.get('symbols', []):
                if s.get('status') == 'TRADING' and s['symbol'].endswith('USDT'):
                    futures_sym = s['symbol']
                    futures_base = futures_sym.replace('USDT', '')
                    self._futures_symbols[futures_base] = futures_sym
                    if futures_base.startswith('1000'):
                        spot_base = futures_base.replace('1000', '', 1)
                        if spot_base not in self._futures_symbols:
                            self._futures_symbols[spot_base] = futures_sym
            self._futures_cache_time = time.time()
            logger.info(f"Futures symbol map loaded: {len(self._futures_symbols)} entries")
            return self._futures_symbols
        except Exception as e:
            logger.warning(f"Failed to fetch futures symbols: {e}, using empty filter")
            if self._futures_symbols is None:
                self._futures_symbols = {}
            self._futures_cache_time = time.time()
            return self._futures_symbols

    def _is_futures_available(self, spot_symbol: str) -> bool:
        """Check if a spot symbol has a futures equivalent."""
        futures_map = self._get_futures_symbols()
        if not futures_map:
            return True
        base = spot_symbol.replace('USDT', '')
        return base in futures_map

    def get_futures_symbol(self, spot_symbol: str) -> str:
        """Get the correct futures symbol name for a spot symbol."""
        futures_map = self._get_futures_symbols()
        base = spot_symbol.replace('USDT', '')
        if base in futures_map:
            return futures_map[base]
        return spot_symbol

    def _is_valid_pair(self, symbol: str) -> bool:
        """Check if a symbol is a valid crypto pair (not stable/forex/low-liq)."""
        if not symbol.endswith('USDT'):
            return False
        if not self._is_futures_available(symbol):
            return False
        if symbol in self.config.forex_pairs:
            return False
        base = symbol.replace('USDT', '')
        if base in self.config.stable_coins:
            return False
        if symbol in self.config.excluded_pairs:
            return False
        return True

    def get_top_100_symbols(self) -> list:
        """Returns top 100 USDT pairs by 24h quote volume, excluding stablecoins."""
        now = time.time()
        if self._symbol_cache and (now - self._cache_time) < self._cache_ttl:
            return self._symbol_cache

        try:
            url = f"{self.base_url}/api/v3/ticker/24hr"
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            tickers = response.json()

            usdt_pairs = []
            for t in tickers:
                symbol = t['symbol']
                if not self._is_valid_pair(symbol):
                    continue
                try:
                    volume = float(t['quoteVolume'])
                    usdt_pairs.append((symbol, volume))
                except (ValueError, KeyError):
                    continue

            usdt_pairs.sort(key=lambda x: x[1], reverse=True)
            top_symbols = [s[0] for s in usdt_pairs[:self.config.top_n_coins]]

            self._symbol_cache = top_symbols
            self._cache_time = now

            logger.info(f"Symbol list refreshed: {len(top_symbols)} symbols")
            return top_symbols

        except Exception as e:
            logger.error(f"Failed to fetch symbols: {e}")
            return self._symbol_cache

    def get_top_100_by_volatility(self) -> list:
        """
        Returns top 100 USDT pairs sorted by ATR volatility (highest first).
        Uses 1D candles to calculate ATR(14) as percentage of price.
        Excludes stablecoins and forex pairs.
        """
        try:
            # Get all USDT tickers first
            url = f"{self.base_url}/api/v3/ticker/24hr"
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            tickers = response.json()

            valid_pairs = []
            for t in tickers:
                symbol = t['symbol']
                if self._is_valid_pair(symbol):
                    try:
                        last_price = float(t['lastPrice'])
                        if last_price > 0:
                            valid_pairs.append((symbol, last_price))
                    except (ValueError, KeyError):
                        continue

            # Calculate volatility for each pair
            volatility_data = []
            lookback = self.config.volatility_lookback

            for symbol, last_price in valid_pairs:
                try:
                    df = self.fetch_candles(symbol, '1d', limit=max(lookback + 5, 20))
                    if df is None or len(df) < lookback:
                        continue

                    close = df['close']
                    # Calculate ATR(14) as percentage of price for comparability
                    high = df['high']
                    low = df['low']
                    prev_close = close.shift(1)
                    tr = pd.concat([
                        high - low,
                        (high - prev_close).abs(),
                        (low - prev_close).abs()
                    ], axis=1).max(axis=1)
                    atr = tr.ewm(com=lookback - 1, adjust=False).mean().iloc[-1]
                    if atr <= 0 or last_price <= 0:
                        continue
                    volatility_pct = (atr / last_price) * 100
                    volatility_data.append((symbol, volatility_pct, last_price))

                    time.sleep(0.05)  # Rate limit protection

                except Exception as e:
                    logger.debug(f"Volatility calc error for {symbol}: {e}")
                    continue

            volatility_data.sort(key=lambda x: x[1], reverse=True)
            top_symbols = [s[0] for s in volatility_data[:self.config.top_n_coins]]

            if top_symbols:
                logger.info(
                    f"Top {len(top_symbols)} by volatility (range: "
                    f"{volatility_data[0][1]:.2f}% - {volatility_data[-1][1]:.2f}%)"
                )

            return top_symbols

        except Exception as e:
            logger.error(f"Failed to fetch volatility symbols: {e}")
            return []

    def get_combined_symbols(self) -> list[str]:
        """Get deduplicated list of volume top-100 and volatility top-100."""
        volume_symbols = self.get_top_100_symbols()
        volatility_symbols = self.get_top_100_by_volatility()

        seen = set()
        combined = []
        for sym in volume_symbols:
            if sym not in seen:
                seen.add(sym)
                combined.append(sym)
        for sym in volatility_symbols:
            if sym not in seen:
                seen.add(sym)
                combined.append(sym)

        return combined

    def _get_symbol_source(self, symbol: str, volume_list: list, volatility_list: list) -> str:
        """Determine which scanner list(s) a symbol belongs to."""
        in_volume = symbol in volume_list
        in_volatility = symbol in volatility_list
        if in_volume and in_volatility:
            return "both"
        if in_volume:
            return "volume"
        if in_volatility:
            return "volatility"
        return "unknown"

    # ─── Indicator helpers ──────────────────────────────────────────────────

    @staticmethod
    def compute_atr(df: pd.DataFrame, period: int = 12) -> pd.Series:
        """Wilder-style ATR via ewm(com=period-1). df must have high/low/close."""
        high = df['high']
        low = df['low']
        prev_close = df['close'].shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ], axis=1).max(axis=1)
        return tr.ewm(com=period - 1, adjust=False).mean()

    @staticmethod
    def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Wilder's RSI via ewm(alpha=1/period)."""
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    @staticmethod
    def compute_supertrend(
        df: pd.DataFrame,
        atr_period: int = 12,
        multiplier: float = 3.5
    ) -> pd.DataFrame:
        """
        Compute Supertrend. Returns df augmented with columns:
        'atr', 'supertrend', 'supertrend_dir' (1=bullish, -1=bearish).
        Bullish = supertrend below price (support); bearish = above (resistance).
        """
        atr = CryptoScanner.compute_atr(df, atr_period)
        hl2 = (df['high'] + df['low']) / 2.0

        # Final upper/lower bands (with close-of-previous-period clamp)
        prev_close = df['close'].shift(1)
        basic_upper = hl2 + multiplier * atr
        basic_lower = hl2 - multiplier * atr

        final_upper = basic_upper.copy()
        final_lower = basic_lower.copy()

        n = len(df)
        # Vectorized iterative computation — bands carry forward and clamp
        for i in range(1, n):
            # Upper band: stays same if basic_upper <= prev final_lower OR prev close > prev final_upper;
            #             else basic_upper if basic_upper < prev final_lower else prev final_upper
            if basic_upper.iloc[i] <= final_lower.iloc[i - 1] or prev_close.iloc[i - 1] > final_upper.iloc[i - 1]:
                final_upper.iloc[i] = basic_upper.iloc[i]
            else:
                final_upper.iloc[i] = basic_upper.iloc[i] if basic_upper.iloc[i] < final_upper.iloc[i - 1] else final_upper.iloc[i - 1]

            # Lower band: stays same if basic_lower >= prev final_upper OR prev close < prev final_lower;
            #             else basic_lower if basic_lower > prev final_upper else prev final_lower
            if basic_lower.iloc[i] >= final_upper.iloc[i - 1] or prev_close.iloc[i - 1] < final_lower.iloc[i - 1]:
                final_lower.iloc[i] = basic_lower.iloc[i]
            else:
                final_lower.iloc[i] = basic_lower.iloc[i] if basic_lower.iloc[i] > final_lower.iloc[i - 1] else final_lower.iloc[i - 1]

        # Supertrend and direction
        supertrend = pd.Series(index=df.index, dtype=float)
        direction = pd.Series(index=df.index, dtype=int)

        # Seed with first valid value
        if n > 0:
            direction.iloc[0] = 1 if df['close'].iloc[0] >= final_upper.iloc[0] else -1
            supertrend.iloc[0] = final_upper.iloc[0] if direction.iloc[0] == 1 else final_lower.iloc[0]

        for i in range(1, n):
            close_i = df['close'].iloc[i]
            prev_dir = direction.iloc[i - 1]
            prev_st = supertrend.iloc[i - 1]

            # Switch to upper (resistance → bearish) when close crosses below prev supertrend
            if prev_dir == 1 and close_i < prev_st:
                direction.iloc[i] = -1
                supertrend.iloc[i] = final_upper.iloc[i]
            # Switch to lower (support → bullish) when close crosses above prev supertrend
            elif prev_dir == -1 and close_i > prev_st:
                direction.iloc[i] = 1
                supertrend.iloc[i] = final_lower.iloc[i]
            else:
                direction.iloc[i] = prev_dir
                # Trailing: supertrend = upper if bearish, lower if bullish (clamped band)
                supertrend.iloc[i] = final_upper.iloc[i] if prev_dir == -1 else final_lower.iloc[i]

        out = df.copy()
        out['atr'] = atr
        out['supertrend'] = supertrend
        out['supertrend_dir'] = direction
        return out

    def check_supertrend_signals(
        self,
        symbols: list,
        interval: str = '4h',
        atr_period: int = 12,
        multiplier: float = 3.5,
        ema_period: int = 200,
        rsi_period: int = 14,
        rsi_long: float = 55.0,
        rsi_short: float = 45.0,
        min_atr_pct: float = 0.5,
        max_atr_pct: float = 5.0,
        rr_mult: float = 1.5,
        candle_limit: int = 300,
    ) -> list:
        """
        Scan symbols for Supertrend flips on the just-closed 4H candle,
        filtered by 200 EMA, RSI(14), and ATR% volatility range.

        Returns list of signal dicts with: symbol, direction (BUY|SELL),
        price (entry), ema200, rsi, atr, atr_pct, supertrend_value, sl, tp,
        rr, interval, detected_at, source.
        """
        signals = []

        volume_list = self.get_top_100_symbols()
        volatility_list = self.get_top_100_by_volatility()

        ema_warmup = max(ema_period * 3, candle_limit)  # ensure enough history
        fetch_limit = max(candle_limit, ema_warmup)

        for symbol in symbols:
            try:
                df = self.fetch_candles(symbol, interval, limit=fetch_limit)
                if df is None or len(df) < fetch_limit:
                    continue

                df = self.compute_supertrend(df, atr_period, multiplier)
                ema200 = df['close'].ewm(span=ema_period, adjust=False).mean()
                rsi = self.compute_rsi(df['close'], rsi_period)

                # Last closed candle (fetch_candles already trims the live one)
                i = len(df) - 1
                close_i = df['close'].iloc[i]
                st_i = df['supertrend'].iloc[i]
                dir_i = df['supertrend_dir'].iloc[i]
                prev_dir = df['supertrend_dir'].iloc[i - 1] if i >= 1 else 0
                atr_i = df['atr'].iloc[i]
                ema200_i = ema200.iloc[i]
                rsi_i = rsi.iloc[i]

                if any(pd.isna(x) for x in [close_i, st_i, dir_i, atr_i, ema200_i, rsi_i, prev_dir]):
                    continue
                if atr_i <= 0 or close_i <= 0:
                    continue

                atr_pct = (atr_i / close_i) * 100.0

                # Volatility filter
                if atr_pct < min_atr_pct or atr_pct > max_atr_pct:
                    continue

                # Detect flip on this candle
                flipped_bullish = prev_dir == -1 and dir_i == 1
                flipped_bearish = prev_dir == 1 and dir_i == -1

                direction = None
                if flipped_bullish and close_i > ema200_i and rsi_i > rsi_long:
                    direction = 'BUY'
                elif flipped_bearish and close_i < ema200_i and rsi_i < rsi_short:
                    direction = 'SELL'

                if direction is None:
                    continue

                # RR-based trade plan
                if direction == 'BUY':
                    sl = close_i - rr_mult * atr_i
                    tp = close_i + rr_mult * atr_i
                else:
                    sl = close_i + rr_mult * atr_i
                    tp = close_i - rr_mult * atr_i

                signals.append({
                    'symbol': symbol,
                    'direction': direction,
                    'price': round(close_i, 8),
                    'ema200': round(ema200_i, 8),
                    'rsi': round(rsi_i, 2),
                    'atr': round(atr_i, 8),
                    'atr_pct': round(atr_pct, 4),
                    'supertrend_value': round(st_i, 8),
                    'sl': round(sl, 8),
                    'tp': round(tp, 8),
                    'rr': rr_mult,
                    'interval': interval,
                    'detected_at': datetime.now(timezone.utc).isoformat(),
                    'source': self._get_symbol_source(symbol, volume_list, volatility_list),
                })

                time.sleep(0.1)  # Rate limit protection

            except Exception as e:
                logger.debug(f"Supertrend check error for {symbol}: {e}")
                continue

        return signals

    def fetch_candles(self, symbol: str, interval: str, limit: int = 100) -> pd.DataFrame:
        """
        Fetches OHLCV candles from Binance for a symbol/interval.
        Returns DataFrame with columns: open, high, low, close, volume
        """
        try:
            url = f"{self.base_url}/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            raw = response.json()

            if not raw or len(raw) < 2:
                return None

            df = pd.DataFrame(raw, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_base',
                'taker_buy_quote', 'ignore'
            ])

            # Check if last candle is actually closed before discarding
            last_close_time = pd.to_datetime(df['close_time'].iloc[-1], unit='ms', utc=True)
            now = pd.Timestamp.now(tz='UTC')
            if last_close_time > now + pd.Timedelta(seconds=5):
                df = df.iloc[:-1]
                logger.debug(f"{symbol} {interval}: Excluded incomplete last candle")

            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)

            df.set_index('timestamp', inplace=True)
            return df[['open', 'high', 'low', 'close', 'volume']]

        except Exception as e:
            logger.debug(f"Candle fetch failed for {symbol} {interval}: {e}")
            return None
