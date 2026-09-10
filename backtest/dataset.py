"""Dataset loading for backtests."""

from pathlib import Path

import pandas as pd

BACKTEST_DIR = Path(__file__).parent
CACHE_DIR = BACKTEST_DIR / "data_cache"

BT_START = pd.Timestamp("2026-03-01", tz="UTC")
BT_END = pd.Timestamp("2026-09-01", tz="UTC")

# Train/validation split for tuning (guard against overfitting)
TRAIN_END = pd.Timestamp("2026-07-16", tz="UTC")


class Dataset:
    """Iterate (symbol, df) over cached klines. For 30m and 1h, attaches the
    4H EMA values of the most recently CLOSED 4h candle to every bar."""

    HTF_INTERVALS = {'30m': '4h', '1h': '4h'}

    def __init__(self, interval: str, symbols: list[str] | None = None,
                 with_htf: bool | None = None):
        self.interval = interval
        cache = CACHE_DIR / interval
        self.symbols = symbols or sorted(p.stem for p in cache.glob('*.parquet'))
        if with_htf is None:
            with_htf = interval in self.HTF_INTERVALS
        self.htf = None
        if with_htf:
            htf_dir = CACHE_DIR / self.HTF_INTERVALS[interval]
            self.htf = {}
            for sym in self.symbols:
                f = htf_dir / f'{sym}.parquet'
                if f.exists():
                    self.htf[sym] = pd.read_parquet(f)
        self._cache_dir = cache

    def __iter__(self):
        btc_iv = self._load_btc_interval()
        btc_1d = self._load_btc_daily()
        for sym in self.symbols:
            f = self._cache_dir / f'{sym}.parquet'
            if not f.exists():
                continue
            df = pd.read_parquet(f)
            if self.htf is not None:
                df = self._attach_htf(sym, df)
            if btc_iv is not None:
                df = self._merge_asof_col(df, btc_iv, ['btc_ema200', 'btc_st_dir'])
            if btc_1d is not None:
                df = self._merge_asof_col(df, btc_1d, ['btc_d_ema50'])
            df.attrs['symbol'] = sym  # merges drop attrs — restore last
            yield sym, df

    def _load_btc_interval(self):
        f = CACHE_DIR / self.interval / 'BTCUSDT.parquet'
        if not f.exists():
            return None
        import indicators as ind
        b = pd.read_parquet(f)
        out = pd.DataFrame({'close_time': b['close_time']})
        out['btc_ema200'] = ind.ema(b['close'], 200).to_numpy()
        _, d = ind.supertrend(b, 10, 3.5)
        out['btc_st_dir'] = d.to_numpy()
        return out.sort_values('close_time')

    def _load_btc_daily(self):
        f = CACHE_DIR / '1d' / 'BTCUSDT.parquet'
        if not f.exists():
            return None
        import indicators as ind
        b = pd.read_parquet(f)
        out = pd.DataFrame({'close_time': b['close_time']})
        out['btc_d_ema50'] = ind.ema(b['close'], 50).to_numpy()
        return out.sort_values('close_time')

    def _merge_asof_col(self, df: pd.DataFrame, right: pd.DataFrame,
                        cols: list[str]) -> pd.DataFrame:
        d = df.reset_index().sort_values('close_time')
        merged = pd.merge_asof(d, right[['close_time'] + cols],
                               left_on='close_time', right_on='close_time',
                               direction='backward')
        merged = merged.set_index('open_time')
        merged.index.name = 'open_time'
        for c in cols:
            if c not in merged.columns:
                merged[c] = float('nan')
        return merged

    def _attach_htf(self, sym: str, df: pd.DataFrame) -> pd.DataFrame:
        htf = self.htf.get(sym)
        if htf is None:
            for p in (50, 100, 200):
                df[f'htf_ema{p}'] = float('nan')
            df['htf_st_dir'] = float('nan')
            return df
        import indicators as ind
        h = pd.DataFrame({'close_time': htf['close_time']})
        for p in (50, 100, 200):
            h[f'htf_ema{p}'] = ind.ema(htf['close'], p)
        _, hdir = ind.supertrend(htf, 10, 3.5)
        h['htf_st_dir'] = hdir.to_numpy()
        h = h.sort_values('close_time')
        d = df.reset_index().sort_values('close_time')
        merged = pd.merge_asof(
            d, h, left_on='close_time', right_on='close_time',
            direction='backward')
        merged = merged.set_index('open_time')
        merged.index.name = 'open_time'
        keep = ['open', 'high', 'low', 'close', 'volume', 'close_time',
                'htf_ema50', 'htf_ema100', 'htf_ema200', 'htf_st_dir']
        return merged[keep]
