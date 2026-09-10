"""
CryptoScanner — Fetches top 100 symbols by 24h volume (Binance) and top 100
by market cap (CoinGecko) and detects 4H Supertrend trend-ride entries
(backtest round-4 final config) with EMA200 long gate, BTC-regime short gate
and market-breadth measurement for position sizing.
"""

import requests
import pandas as pd
import numpy as np
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from config import Config

logger = logging.getLogger(__name__)


class CryptoScanner:
    def __init__(self, config: Config):
        self.config = config
        self.base_url = config.binance_base_url
        self._session = requests.Session()
        self._symbol_cache = []
        self._cache_time = 0
        self._cache_ttl = 3600  # Refresh symbol list every 1H
        self._marketcap_cache = []
        self._marketcap_cache_time = 0
        self._futures_symbols = None
        self._futures_cache_time = 0

    def _get_futures_symbols(self) -> dict:
        """Fetch available symbols from Binance Futures API.
        Returns a dict mapping spot base names to their futures symbol name.
        e.g. {'PEPE': '1000PEPEUSDT', 'BTC': 'BTCUSDT'}
        """
        if self._futures_symbols is not None and time.time() - self._futures_cache_time < 3600:
            return self._futures_symbols
        try:
            url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
            response = self._session.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            new_map: dict = {}
            for s in data.get('symbols', []):
                if s.get('status') == 'TRADING' and s['symbol'].endswith('USDT'):
                    futures_sym = s['symbol']
                    futures_base = futures_sym.replace('USDT', '')
                    new_map[futures_base] = futures_sym
                    if futures_base.startswith('1000'):
                        spot_base = futures_base.replace('1000', '', 1)
                        if spot_base not in new_map:
                            new_map[spot_base] = futures_sym
            self._futures_symbols = new_map
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
        if symbol in self.config.excluded_pairs:
            return False
        base = symbol.replace('USDT', '')
        if base in self.config.stable_coins:
            return False
        return True

    def get_top_100_symbols(self) -> list:
        """Returns top 100 USDT pairs by 24h quote volume, excluding stablecoins."""
        now = time.time()
        if self._symbol_cache and (now - self._cache_time) < self._cache_ttl:
            return self._symbol_cache

        try:
            url = f"{self.base_url}/api/v3/ticker/24hr"
            response = self._session.get(url, timeout=15)
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

    def get_top_100_by_market_cap(self) -> list:
        """
        Returns up to top_n_coins USDT pairs by CoinGecko market cap,
        filtered to pairs that trade on Binance with a futures equivalent.
        Results are cached for 1 hour to respect CoinGecko rate limits.
        """
        now = time.time()
        if self._marketcap_cache and (now - self._marketcap_cache_time) < self._cache_ttl:
            return self._marketcap_cache

        try:
            # Build set of valid Binance USDT pairs (with futures)
            url = f"{self.base_url}/api/v3/ticker/24hr"
            response = self._session.get(url, timeout=15)
            response.raise_for_status()
            tickers = response.json()

            valid_symbols = set()
            for t in tickers:
                symbol = t['symbol']
                if self._is_valid_pair(symbol):
                    valid_symbols.add(symbol)

            # Fetch pages from CoinGecko until we have enough valid symbols
            top_symbols = []
            page = 1
            max_pages = 4  # Safety cap (400 coins should cover >100 Binance futures pairs)

            while len(top_symbols) < self.config.top_n_coins and page <= max_pages:
                cg_url = "https://api.coingecko.com/api/v3/coins/markets"
                params = {
                    'vs_currency': 'usd',
                    'order': 'market_cap_desc',
                    'per_page': self.config.top_n_coins,
                    'page': page,
                }
                if getattr(self.config, 'coingecko_api_key', None):
                    params['x_cg_demo_api_key'] = self.config.coingecko_api_key

                response = self._session.get(cg_url, params=params, timeout=15)
                response.raise_for_status()
                coins = response.json()
                if not coins:
                    break

                for coin in coins:
                    base = coin.get('symbol', '').upper()
                    if not base:
                        continue
                    symbol = f"{base}USDT"
                    if symbol in valid_symbols and symbol not in top_symbols:
                        top_symbols.append(symbol)
                        if len(top_symbols) >= self.config.top_n_coins:
                            break

                page += 1

            self._marketcap_cache = top_symbols[:self.config.top_n_coins]
            self._marketcap_cache_time = now

            logger.info(
                f"Market-cap list refreshed: {len(self._marketcap_cache)} symbols "
                f"(scanned {min(page - 1, max_pages)} CoinGecko page(s))"
            )
            return self._marketcap_cache

        except Exception as e:
            logger.error(f"Failed to fetch market cap symbols: {e}")
            return self._marketcap_cache

    def get_combined_symbols(self) -> list[str]:
        """Get deduplicated list of volume top-100 and market-cap top-100."""
        volume_symbols = self.get_top_100_symbols()
        marketcap_symbols = self.get_top_100_by_market_cap()

        seen = set()
        combined = []
        for sym in volume_symbols:
            if sym not in seen:
                seen.add(sym)
                combined.append(sym)
        for sym in marketcap_symbols:
            if sym not in seen:
                seen.add(sym)
                combined.append(sym)

        return combined

    def _get_symbol_source(self, symbol: str, volume_list: list, marketcap_list: list) -> str:
        """Determine which scanner list(s) a symbol belongs to."""
        in_volume = symbol in volume_list
        in_marketcap = symbol in marketcap_list
        if in_volume and in_marketcap:
            return "both"
        if in_volume:
            return "volume"
        if in_marketcap:
            return "marketcap"
        return "unknown"

    # ─── Indicator helpers ──────────────────────────────────────────────────

    @staticmethod
    def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
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
    def compute_supertrend(
        df: pd.DataFrame,
        atr_period: int = 10,
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
            if basic_upper.iloc[i] <= final_lower.iloc[i - 1] or prev_close.iloc[i - 1] > final_upper.iloc[i - 1]:
                final_upper.iloc[i] = basic_upper.iloc[i]
            else:
                final_upper.iloc[i] = basic_upper.iloc[i] if basic_upper.iloc[i] < final_upper.iloc[i - 1] else final_upper.iloc[i - 1]

            if basic_lower.iloc[i] >= final_upper.iloc[i - 1] or prev_close.iloc[i - 1] < final_lower.iloc[i - 1]:
                final_lower.iloc[i] = basic_lower.iloc[i]
            else:
                final_lower.iloc[i] = basic_lower.iloc[i] if basic_lower.iloc[i] > final_lower.iloc[i - 1] else final_lower.iloc[i - 1]

        # Supertrend and direction
        supertrend = pd.Series(index=df.index, dtype=float)
        direction = pd.Series(index=df.index, dtype=float)

        # Seed with first valid value (only if ATR is warmed up)
        first_atr_valid = (
            n > 0
            and not pd.isna(final_upper.iloc[0])
            and not pd.isna(final_lower.iloc[0])
        )
        if first_atr_valid:
            direction.iloc[0] = 1 if df['close'].iloc[0] >= final_upper.iloc[0] else -1
            supertrend.iloc[0] = final_upper.iloc[0] if direction.iloc[0] == 1 else final_lower.iloc[0]

        for i in range(1, n):
            prev_dir_i = direction.iloc[i - 1]
            prev_st_i = supertrend.iloc[i - 1]
            close_i = df['close'].iloc[i]

            if pd.isna(prev_dir_i) or pd.isna(prev_st_i):
                # Still in warmup — leave supertrend NaN so signal logic ignores it
                if not pd.isna(final_upper.iloc[i]):
                    direction.iloc[i] = 1 if close_i >= final_upper.iloc[i] else -1
                    supertrend.iloc[i] = final_upper.iloc[i] if direction.iloc[i] == 1 else final_lower.iloc[i]
                continue

            # Switch to upper (resistance → bearish) when close crosses below prev supertrend
            if prev_dir_i == 1 and close_i < prev_st_i:
                direction.iloc[i] = -1
                supertrend.iloc[i] = final_upper.iloc[i]
            # Switch to lower (support → bullish) when close crosses above prev supertrend
            elif prev_dir_i == -1 and close_i > prev_st_i:
                direction.iloc[i] = 1
                supertrend.iloc[i] = final_lower.iloc[i]
            else:
                direction.iloc[i] = prev_dir_i
                # Trailing: supertrend = upper if bearish, lower if bullish (clamped band)
                supertrend.iloc[i] = final_upper.iloc[i] if prev_dir_i == -1 else final_lower.iloc[i]

        direction = direction.astype('Int64')

        out = df.copy()
        out['atr'] = atr
        out['supertrend'] = supertrend
        out['supertrend_dir'] = direction
        return out

    # ─── 4H trend-ride strategy (backtest round-4 final) ────────────────────

    def _prepare_symbol(self, symbol: str, interval: str, fetch_limit: int,
                        st_period: int, st_mult: float, ema_period: int) -> dict | None:
        """Fetch candles + compute indicators for one symbol. Returns the
        per-symbol payload for market_data['symbols'], or None on failure."""
        df = self.fetch_candles(symbol, interval, limit=fetch_limit)
        if df is None:
            return None
        # Symbols with too little history (recent listings) are excluded
        # from entries AND breadth — config.min_history_bars (default: the
        # full fetch window, ~EMA200 x3 warmup). Deliberate, not an
        # accident of the fetch size.
        if len(df) < self.config.min_history_bars:
            return None
        df = self.compute_supertrend(df, st_period, st_mult)
        i = len(df) - 1
        close_i = df['close'].iloc[i]
        ema_i = float(df['close'].ewm(span=ema_period, adjust=False).mean().iloc[i])
        atr_i = float(df['atr'].iloc[i])
        dir_i = df['supertrend_dir'].iloc[i]
        dir_prev = df['supertrend_dir'].iloc[i - 1]
        if any(pd.isna(x) for x in [close_i, ema_i, atr_i, dir_i, dir_prev]) or atr_i <= 0:
            return None

        flip = 0
        if dir_prev == -1 and dir_i == 1:
            flip = 1
        elif dir_prev == 1 and dir_i == -1:
            flip = -1

        return {
            'df': df,
            'close': float(close_i),
            'ema200': ema_i,
            'atr': atr_i,
            'supertrend_value': float(df['supertrend'].iloc[i]),
            'dir': int(dir_i),
            'flip': flip,
            'flip_candle_open': df.index[i],
            'candle_time': df['close_time'].iloc[i].isoformat(),
        }

    def prepare_market_data(self, symbols: list, interval: str = '4h') -> dict:
        """Phase 1 of the scan: fetch candles + precompute indicators for every
        symbol, BTC's Supertrend direction (short gate) and market breadth
        (fraction of universe above its own EMA200). All on CLOSED candles.
        Fetches run in a small thread pool; failures are counted and logged
        (skipped symbols skew breadth, so the count must be visible)."""
        fetch_limit = self.config.candle_fetch_limit
        ema_period = self.config.ema_filter_period
        st_period = self.config.supertrend_atr_period
        st_mult = self.config.supertrend_multiplier

        # BTC regime (short gate)
        btc_dir = 0
        try:
            btc_df = self.fetch_candles('BTCUSDT', interval, limit=fetch_limit)
            if btc_df is not None and len(btc_df) >= st_period * 3:
                btc_df = self.compute_supertrend(btc_df, st_period, st_mult)
                btc_dir = int(btc_df['supertrend_dir'].iloc[-1])
        except Exception as e:
            logger.warning(f"BTC regime fetch failed: {e}")

        symbols_out = {}
        above = 0
        total = 0
        failed = 0
        with ThreadPoolExecutor(max_workers=max(1, self.config.fetch_workers)) as pool:
            futures = {
                pool.submit(self._prepare_symbol, symbol, interval,
                            fetch_limit, st_period, st_mult, ema_period): symbol
                for symbol in symbols
            }
            for fut in as_completed(futures):
                symbol = futures[fut]
                try:
                    payload = fut.result()
                except Exception as e:
                    logger.warning(f"Prepare failed for {symbol}: {e}")
                    payload = None
                if payload is None:
                    failed += 1
                    continue
                symbols_out[symbol] = payload
                above += 1 if payload['close'] > payload['ema200'] else 0
                total += 1

        if failed:
            logger.warning(
                "Skipped %d/%d symbols (fetch/indicator failure) — "
                "breadth is computed over the successful subset",
                failed, len(symbols),
            )

        breadth = (above / total) if total else 0.0
        logger.info(
            "Market data ready: %d symbols (%d failed), breadth=%.2f, BTC ST dir=%+d",
            total, failed, breadth, btc_dir,
        )
        return {'btc_dir': btc_dir, 'breadth': breadth, 'symbols': symbols_out,
                'interval': interval}

    def check_entries(self, market_data: dict, volume_list: list = None,
                      marketcap_list: list = None) -> list:
        """Phase 2a: entry signals on the just-closed 4H candle.
        Long: bullish ST flip + close > EMA200.
        Short: bearish ST flip + BTC Supertrend bearish.
        Round-5b filters (REPORT §6f, 3-year OOS): no entries at all while
        breadth is below config.breadth_gate, and flip candles that open on
        Sunday are skipped (config.skip_sunday).
        """
        if volume_list is None or marketcap_list is None:
            volume_list = self.get_top_100_symbols()
            marketcap_list = self.get_top_100_by_market_cap()

        breadth = market_data['breadth']
        btc_dir = market_data['btc_dir']
        risk_level = 'full' if breadth >= self.config.breadth_threshold else 'half'
        risk_pct = (self.config.risk_pct_full if risk_level == 'full'
                    else self.config.risk_pct_half)

        if breadth < self.config.breadth_gate:
            logger.info(
                "Breadth %.2f below entry gate %.2f — no entries this scan",
                breadth, self.config.breadth_gate,
            )
            return []

        def quality_tier(direction: str, symbol: str) -> tuple[str, str]:
            """A–D quality label from the 3-year trade study (REPORT §6f):
            LONG pays when breadth confirms (>= threshold); the best SHORTs
            fire when breadth is collapsing (< threshold) or very high;
            mid-breadth shorts and shorts on BTC itself are the weak sets."""
            thr = self.config.breadth_threshold
            if direction == 'BUY':
                if breadth >= thr:
                    return 'A', f"trend-confirmed long (breadth {breadth:.2f})"
                return 'C', f"low-breadth long (breadth {breadth:.2f})"
            if symbol == 'BTCUSDT':
                return 'D', "short on BTC (historically ~breakeven)"
            if breadth < thr:
                return 'B', f"flush short (breadth {breadth:.2f})"
            if breadth >= 0.5:
                return 'B', f"high-breadth short (breadth {breadth:.2f})"
            return 'C', f"mid-breadth short (breadth {breadth:.2f})"

        signals = []
        skipped_quality = 0
        for symbol, d in market_data['symbols'].items():
            atr_pct_i = d['atr'] / d['close'] * 100.0 if d['close'] else 0
            if atr_pct_i < self.config.atr_min_pct or atr_pct_i > self.config.atr_max_pct:
                continue

            # Sunday-open flip candles are skipped (weekend liquidity)
            if self.config.skip_sunday and d['flip_candle_open'].dayofweek == 6:
                continue

            if d['flip'] == 1 and d['close'] > d['ema200']:
                direction = 'BUY'
            elif d['flip'] == -1 and btc_dir == -1:
                direction = 'SELL'
            else:
                continue

            close_i = d['close']
            atr_i = d['atr']
            quality, quality_reason = quality_tier(direction, symbol)
            # Quality filter (REPORT §6f): default trades only A/B — the
            # weak C/D sets historically had negative expectancy.
            if quality not in self.config.quality_tiers:
                skipped_quality += 1
                continue
            signals.append({
                'symbol': symbol,
                'direction': direction,
                'price': round(close_i, 8),
                'ema200': round(d['ema200'], 8),
                'atr': round(atr_i, 8),
                'atr_pct': round(atr_i / close_i * 100.0, 4),
                'supertrend_value': round(d['supertrend_value'], 8),
                'interval': market_data.get('interval', '4h'),
                'strategy': 'st_trail_v2',
                'candle_time': d['candle_time'],
                # open time of the flip candle — PositionTracker derives the
                # entry bar (next bar) from this; must never be dropped
                'flip_candle_open': d['flip_candle_open'].isoformat(),
                'breadth': round(breadth, 4),
                'risk_level': risk_level,
                'risk_pct': risk_pct,
                'btc_dir': btc_dir,
                'quality': quality,
                'quality_reason': quality_reason,
                # Same floor the tracker/engine apply: max(INITIAL_STOP_ATR_MULT xATR, 2% of
                # price). Without it the alerted stop is wider than the one
                # actually enforced whenever ATR% < 0.4.
                'initial_stop': round(close_i - (1 if direction == 'BUY' else -1)
                                      * max(self.config.initial_stop_atr_mult * atr_i,
                                            0.02 * close_i), 8),
                'detected_at': datetime.now(timezone.utc).isoformat(),
                'source': self._get_symbol_source(symbol, volume_list, marketcap_list),
            })
        if skipped_quality:
            logger.info("Quality filter %s skipped %d signal(s) this scan",
                        ",".join(sorted(self.config.quality_tiers)),
                        skipped_quality)
        return signals

    def fetch_candles(self, symbol: str, interval: str, limit: int = 100,
                      retries: int = 3) -> pd.DataFrame:
        """
        Fetches OHLCV candles from Binance for a symbol/interval.
        Returns DataFrame with columns: open, high, low, close, volume
        containing only closed candles (the live candle is dropped).
        Honors 429/418 Retry-After so a rate-limit burst doesn't silently
        drop symbols from the scan.
        """
        url = f"{self.base_url}/api/v3/klines"
        params = {
            'symbol': symbol,
            'interval': interval,
            # +1 so that after the live candle is trimmed below, callers
            # still receive the full `limit` of closed candles.
            'limit': min(limit + 1, 1000)
        }
        try:
            for attempt in range(retries):
                response = self._session.get(url, params=params, timeout=10)
                if response.status_code in (429, 418):
                    wait = float(response.headers.get('Retry-After', 2 ** attempt))
                    logger.warning(
                        f"{symbol} {interval}: rate limited ({response.status_code}), "
                        f"backing off {wait}s (attempt {attempt + 1}/{retries})"
                    )
                    time.sleep(min(wait, 30))
                    continue
                response.raise_for_status()
                raw = response.json()
                break
            else:
                logger.error(f"{symbol} {interval}: gave up after {retries} rate-limit retries")
                return None

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

            df = df.rename(columns={'timestamp': 'open_time'})
            df['close_time'] = pd.to_datetime(df['close_time'], unit='ms', utc=True)
            df.set_index('open_time', inplace=True)
            return df[['open', 'high', 'low', 'close', 'volume', 'close_time']]

        except Exception as e:
            logger.debug(f"Candle fetch failed for {symbol} {interval}: {e}")
            return None
