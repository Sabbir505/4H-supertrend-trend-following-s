"""
CryptoScanner — Fetches top 100 symbols by volume from Binance
and pulls OHLCV candle data for signal analysis
"""

import requests
import pandas as pd
import logging
import time
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
        # Refresh cache if older than 1 hour
        if self._futures_symbols is not None and hasattr(self, '_futures_cache_time'):
            if time.time() - self._futures_cache_time < 3600:
                return self._futures_symbols
        try:
            url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
            # Map: spot_base -> futures_full_symbol
            self._futures_symbols = {}
            for s in data.get('symbols', []):
                if s.get('status') == 'TRADING' and s['symbol'].endswith('USDT'):
                    futures_sym = s['symbol']
                    futures_base = futures_sym.replace('USDT', '')
                    # Store the futures full symbol keyed by its base name
                    self._futures_symbols[futures_base] = futures_sym
                    # Also store without 1000 prefix for spot symbol lookup
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
            # Set cache time even on failure to prevent rapid retry loops
            self._futures_cache_time = time.time()
            return self._futures_symbols

    def _is_futures_available(self, spot_symbol: str) -> bool:
        """Check if a spot symbol has a futures equivalent."""
        futures_map = self._get_futures_symbols()
        if not futures_map:
            return True  # If we couldn't fetch futures data, don't filter
        base = spot_symbol.replace('USDT', '')
        return base in futures_map

    def get_futures_symbol(self, spot_symbol: str) -> str:
        """Get the correct futures symbol name for a spot symbol.
        e.g. PEPEUSDT -> 1000PEPEUSDT, BTCUSDT -> BTCUSDT
        """
        futures_map = self._get_futures_symbols()
        base = spot_symbol.replace('USDT', '')
        if base in futures_map:
            return futures_map[base]
        return spot_symbol  # Fallback to spot name

    def get_top_100_symbols(self) -> list:
        """
        Returns top 100 USDT pairs by 24h quote volume,
        excluding stablecoins.
        """
        now = time.time()
        if self._symbol_cache and (now - self._cache_time) < self._cache_ttl:
            return self._symbol_cache

        try:
            url = f"{self.base_url}/api/v3/ticker/24hr"
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            tickers = response.json()

            # Filter: USDT pairs only, active, exclude stables and forex
            # Also filter to only symbols available on Binance Futures
            usdt_pairs = []
            for t in tickers:
                symbol = t['symbol']
                if not symbol.endswith('USDT'):
                    continue
                # Only include symbols available on Binance Futures
                if not self._is_futures_available(symbol):
                    continue
                # Bug fix: Exclude forex/stablecoin pairs explicitly
                if symbol in self.config.forex_pairs:
                    continue
                base = symbol.replace('USDT', '')
                if base in self.config.stable_coins:
                    continue
                try:
                    volume = float(t['quoteVolume'])
                    usdt_pairs.append((symbol, volume))
                except (ValueError, KeyError):
                    continue

            # Sort by volume descending, take top N
            usdt_pairs.sort(key=lambda x: x[1], reverse=True)
            top_symbols = [s[0] for s in usdt_pairs[:self.config.top_n_coins]]

            self._symbol_cache = top_symbols
            self._cache_time = now

            logger.info(f"Symbol list refreshed: {len(top_symbols)} symbols")
            return top_symbols

        except Exception as e:
            logger.error(f"Failed to fetch symbols: {e}")
            return self._symbol_cache  # Return cached on failure

    def get_top_100_by_market_cap(self) -> list:
        """
        Returns top 100 USDT pairs by market cap from CoinGecko,
        mapped to Binance spot symbols. Excludes stablecoins.
        """
        try:
            # CoinGecko API: top 100 coins by market cap
            url = "https://api.coingecko.com/api/v3/coins/markets"
            params = {
                'vs_currency': 'usd',
                'order': 'market_cap_desc',
                'per_page': 100,
                'page': 1,
                'sparkline': 'false'
            }
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            coins = response.json()

            symbols = []
            for coin in coins:
                symbol_upper = coin.get('symbol', '').upper()
                if not symbol_upper:
                    continue
                # Skip stablecoins
                if symbol_upper in self.config.stable_coins:
                    continue
                # Map to Binance USDT pair
                binance_symbol = f"{symbol_upper}USDT"
                symbols.append(binance_symbol)

            logger.info(f"Market cap top 100: {len(symbols)} symbols fetched")
            return symbols

        except Exception as e:
            logger.error(f"Failed to fetch market cap data: {e}")
            return []

    def check_ema_crossovers(self, symbols: list, interval: str = '4h', ema_fast: int = 21, ema_slow: int = 55) -> list:
        """
        Check for EMA crossovers for a list of symbols.
        Returns list of dicts with symbol, crossover_type, price, ema_fast, ema_slow.
        crossover_type: 'GOLDEN_CROSS' (price/EMA fast crossing above EMA slow)
                        or 'DEATH_CROSS' (price/EMA fast crossing below EMA slow)
        Only reports when a crossover is detected (previous candle on opposite side).
        """
        crossovers = []

        for symbol in symbols:
            try:
                df = self.fetch_candles(symbol, interval, limit=100)
                if df is None or len(df) < ema_slow + 5:
                    continue

                close = df['close']

                # Calculate EMAs
                ema_f = close.ewm(span=ema_fast, adjust=False).mean()
                ema_s = close.ewm(span=ema_slow, adjust=False).mean()

                # Need at least 2 candles to detect a crossover
                if len(ema_f) < 2 or len(ema_s) < 2:
                    continue

                prev_fast = ema_f.iloc[-2]
                prev_slow = ema_s.iloc[-2]
                curr_fast = ema_f.iloc[-1]
                curr_slow = ema_s.iloc[-1]
                curr_price = close.iloc[-1]

                prev_position = prev_fast - prev_slow
                curr_position = curr_fast - curr_slow

                # Detect crossover: signs differ (one above, one below)
                if prev_position <= 0 and curr_position > 0:
                    crossovers.append({
                        'symbol': symbol,
                        'crossover_type': 'GOLDEN_CROSS',
                        'price': round(curr_price, 6),
                        'ema_fast': round(curr_fast, 6),
                        'ema_slow': round(curr_slow, 6),
                        'interval': interval
                    })
                elif prev_position >= 0 and curr_position < 0:
                    crossovers.append({
                        'symbol': symbol,
                        'crossover_type': 'DEATH_CROSS',
                        'price': round(curr_price, 6),
                        'ema_fast': round(curr_fast, 6),
                        'ema_slow': round(curr_slow, 6),
                        'interval': interval
                    })

                time.sleep(0.1)  # Rate limit protection

            except Exception as e:
                logger.debug(f"EMA check error for {symbol}: {e}")
                continue

        return crossovers

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

            # Bug #16 fix: Check if last candle is actually closed before discarding
            # Use close_time from the last candle to determine if it's complete
            last_close_time = pd.to_datetime(df['close_time'].iloc[-1], unit='ms', utc=True)
            now = pd.Timestamp.now(tz='UTC')
            # If last close time is in the future, the candle is still open
            if last_close_time > now + pd.Timedelta(seconds=5):
                # Last candle is still open, exclude it
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
