"""
Backtest data fetcher.
Pulls 6 months of spot klines (+ indicator warmup) from Binance for the same
universe the live scanner trades, and caches them as parquet under data_cache/.

Usage:
    python data_fetcher.py            # universe + 4h + 30m
    python data_fetcher.py 4h         # just 4h
    python data_fetcher.py 30m        # just 30m
"""

import sys
import json
import time
import logging
from pathlib import Path

import requests
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger("data_fetcher")

BACKTEST_DIR = Path(__file__).parent
CACHE_DIR = BACKTEST_DIR / "data_cache"
UNIVERSE_FILE = CACHE_DIR / "universe.json"

sys.path.insert(0, str(BACKTEST_DIR.parent))  # for production config module

# Backtest window: last 6 months (Mar 1 2026 -> Aug 31 2026).
BT_START = pd.Timestamp("2026-03-01", tz="UTC")
BT_END = pd.Timestamp("2026-09-01", tz="UTC")

# Warmup: 4h needs >=600 closed bars before BT_START (EMA200 x3).
# 30m/1h need ~600 bars before BT_START (30m EMA200 x3, 1h EMA200 x3).
# The 4h EMA50 used by lower-TF strategies is computed on the 4h series,
# which reaches much further back.
FETCH_START = {
    "4h": pd.Timestamp("2025-11-20", tz="UTC"),
    "1h": pd.Timestamp("2026-01-20", tz="UTC"),
    "30m": pd.Timestamp("2026-02-08", tz="UTC"),
}

BINANCE = "https://api.binance.com"
REQUEST_PAUSE = 0.12  # seconds between API calls (weight budget friendly)


def _futures_bases() -> set[str]:
    """USDT futures base symbols on Binance (incl. 1000x-prefixed mappings
    back to their spot base), mirroring the live scanner's futures filter."""
    bases = set()
    data = requests.get("https://fapi.binance.com/fapi/v1/exchangeInfo",
                        timeout=20).json()
    for s in data.get('symbols', []):
        if s.get('status') == 'TRADING' and s['symbol'].endswith('USDT'):
            fb = s['symbol'][:-4]
            bases.add(fb)
            if fb.startswith('1000'):
                bases.add(fb.replace('1000', '', 1))
    return bases


def get_universe() -> list[str]:
    """Mirror the live scanner's universe: top-100 spot USDT pairs by quote
    volume with a futures equivalent, plus top-100 by CoinGecko market cap."""
    if UNIVERSE_FILE.exists():
        return json.loads(UNIVERSE_FILE.read_text())

    import config as proj_config  # reuse exclusion lists from production
    cfg = proj_config.Config()

    # Forex/gold pairs live in cfg.excluded_pairs itself (Config has no
    # separate forex_pairs list). Skip the futures filter on API failure so
    # a flaky fapi endpoint can't wipe the whole universe.
    try:
        futures = _futures_bases()
    except Exception as e:
        log.warning("Futures exchangeInfo failed (%s) — skipping futures filter", e)
        futures = set()

    tickers = requests.get(f"{BINANCE}/api/v3/ticker/24hr", timeout=20).json()
    pairs = []
    for t in tickers:
        sym = t['symbol']
        if not sym.endswith('USDT'):
            continue
        base = sym[:-4]
        if sym in cfg.excluded_pairs or base in cfg.stable_coins:
            continue
        if futures and base not in futures:
            continue
        try:
            pairs.append((sym, float(t['quoteVolume'])))
        except (ValueError, KeyError):
            continue
    pairs.sort(key=lambda x: x[1], reverse=True)
    volume_top = [s for s, _ in pairs[:100]]

    valid = {s for s, _ in pairs}
    mcap_top = []
    for page in range(1, 5):
        resp = requests.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={'vs_currency': 'usd', 'order': 'market_cap_desc',
                    'per_page': 100, 'page': page},
            timeout=20)
        coins = resp.json()
        if not coins:
            break
        for coin in coins:
            sym = coin.get('symbol', '').upper() + 'USDT'
            if sym in valid and sym not in mcap_top:
                mcap_top.append(sym)
        if len(mcap_top) >= 100:
            break

    universe = list(dict.fromkeys(volume_top + mcap_top))
    UNIVERSE_FILE.parent.mkdir(exist_ok=True)
    UNIVERSE_FILE.write_text(json.dumps(universe))
    log.info("Universe: %d symbols (%d volume + %d mcap)", len(universe),
             len(volume_top), len(mcap_top))
    return universe


def fetch_klines(symbol: str, interval: str, start: pd.Timestamp) -> pd.DataFrame | None:
    """Fetch all klines from `start` until now (paginated)."""
    url = f"{BINANCE}/api/v3/klines"
    start_ms = int(start.timestamp() * 1000)
    rows = []
    while True:
        params = {'symbol': symbol, 'interval': interval,
                  'startTime': start_ms, 'limit': 1000}
        for attempt in range(3):
            try:
                resp = requests.get(url, params=params, timeout=20)
                if resp.status_code == 429 or resp.status_code == 418:
                    time.sleep(30)
                    continue
                resp.raise_for_status()
                break
            except requests.RequestException:
                time.sleep(2 * (attempt + 1))
        else:
            return None
        batch = resp.json()
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 1000:
            break
        start_ms = batch[-1][6] + 1
        time.sleep(REQUEST_PAUSE)

    if not rows:
        return None
    df = pd.DataFrame(rows, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'])
    df = df.drop_duplicates('open_time')
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms', utc=True)
    df['close_time'] = pd.to_datetime(df['close_time'], unit='ms', utc=True)
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    # Drop the live candle so every row is a closed candle
    df = df[df['close_time'] <= pd.Timestamp.now(tz='UTC')]
    df = df.set_index('open_time')[['open', 'high', 'low', 'close', 'volume', 'close_time']]
    return df


def ensure_data(interval: str, universe: list[str]) -> list[str]:
    """Download missing symbols for `interval`; returns list of usable symbols."""
    out_dir = CACHE_DIR / interval
    out_dir.mkdir(parents=True, exist_ok=True)
    start = FETCH_START[interval]
    usable = []
    n = len(universe)
    for i, sym in enumerate(universe, 1):
        f = out_dir / f"{sym}.parquet"
        if f.exists():
            usable.append(sym)
            continue
        try:
            df = fetch_klines(sym, interval, start)
        except Exception as e:
            log.warning("[%d/%d] %s failed: %s", i, n, sym, e)
            continue
        if df is None or len(df) == 0:
            log.info("[%d/%d] %s: no data", i, n, sym)
            continue
        df.to_parquet(f)
        usable.append(sym)
        if i % 20 == 0:
            log.info("[%d/%d] fetched %s (%d bars)", i, n, sym, len(df))
        time.sleep(REQUEST_PAUSE)
    log.info("%s: %d/%d symbols cached", interval, len(usable), n)
    return usable


if __name__ == "__main__":
    intervals = sys.argv[1:] or ["4h", "30m"]
    universe = get_universe()
    log.info("Universe size: %d", len(universe))
    for iv in intervals:
        ensure_data(iv, universe)
    log.info("DONE")
