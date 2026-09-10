"""
Regression tests for bugs found in the live code review.

Each test corresponds to a specific concern. Keep these tests *small and
focused* — they exist to lock in the "X must always be true" invariants.
Run with:  pytest tests/ -v
"""

import os
import sys
import json
import time
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Make the project root importable when running pytest from anywhere.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Force a non-empty .env (validate() refuses to start without one).
if not os.environ.get("TELEGRAM_BOT_TOKEN"):
    os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
if not os.environ.get("TELEGRAM_CHAT_ID"):
    os.environ["TELEGRAM_CHAT_ID"] = "test-chat-id"

# Tests must not touch the user's real signals.json / data/ — sandbox.
# The trackers read SIGNALS_FILE / POSITIONS_FILE / TRADES_FILE from the
# environment (set below, before import). The chdir is defense-in-depth so
# any future hard-coded relative path also lands in the sandbox instead of
# silently clobbering the live bot's state files.
SANDBOX = Path(tempfile.mkdtemp(prefix="tradeedge_tests_"))
os.environ["SIGNALS_FILE"] = str(SANDBOX / "signals.json")
os.environ["POSITIONS_FILE"] = str(SANDBOX / "data" / "positions.json")
os.environ["TRADES_FILE"] = str(SANDBOX / "data" / "trade_history.json")
os.environ["SIGNALS_DATA_DIR"] = str(SANDBOX / "data" / "signals")
(SANDBOX / "data").mkdir(parents=True, exist_ok=True)
os.chdir(SANDBOX)

from config import Config  # noqa: E402
from scanner import CryptoScanner  # noqa: E402
from position_tracker import PositionTracker, COST_RT  # noqa: E402
from signal_tracker import SignalTracker  # noqa: E402
from telegram_bot import TelegramBot  # noqa: E402
from api_server import load_signals, _cached_json, _json_cache  # noqa: E402


# ─── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def config():
    """A fresh Config() per test — avoids cross-test env-var leakage."""
    # Stash the sandbox files so Config-driven side effects (none today,
    # but future-proof) land in a temp dir.
    return Config()


@pytest.fixture
def synthetic_signal():
    """A single BUY signal as scanner.check_entries() would emit it."""
    flip_open = datetime.now(timezone.utc) - timedelta(hours=4)
    return {
        "symbol": "BTCUSDT",
        "direction": "BUY",
        "price": 65000.0,
        "ema200": 60000.0,
        "atr": 1500.0,
        "atr_pct": 2.3,
        "supertrend_value": 63500.0,
        "interval": "4h",
        "strategy": "st_trail_v2",
        "candle_time": (flip_open + timedelta(hours=4)).isoformat(),
        # ↓ the key that broke the first live signal — must always be present
        "flip_candle_open": flip_open.isoformat(),
        "breadth": 0.55,
        "risk_level": "full",
        "risk_pct": 1.0,
        "btc_dir": 1,
        "initial_stop": 65000.0 - 5.0 * 1500.0,
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "source": "both",
    }


# ─── 1. check_entries must emit flip_candle_open ────────────────────────


def test_check_entries_emits_flip_candle_open(monkeypatch, config):
    """Bug #1: open_position crashed with KeyError because check_entries
    never put flip_candle_open on the signal dict. Lock that in."""
    scanner = CryptoScanner(config)

    # Two synthetic symbols: one bullish flip, one bearish.
    # (Flip candles open Monday 2026-08-31 — Sunday-open candles are
    # skipped by the round-5b filter, see test_check_entries_sunday_skip.)
    md = {
        "btc_dir": -1,  # allow shorts
        "breadth": 0.55,
        "interval": "4h",
        "symbols": {
            "AAAUSDT": {
                "close": 100.0, "ema200": 90.0, "atr": 2.0,
                "supertrend_value": 95.0, "dir": 1, "flip": 1,
                "flip_candle_open": pd.Timestamp("2026-08-31 16:00"),
                "candle_time": "2026-08-31T20:00:00+00:00",
            },
            "BBBUSDT": {
                "close": 100.0, "ema200": 110.0, "atr": 2.0,
                "supertrend_value": 105.0, "dir": -1, "flip": -1,
                "flip_candle_open": pd.Timestamp("2026-08-31 16:00"),
                "candle_time": "2026-08-31T20:00:00+00:00",
            },
        },
    }

    signals = scanner.check_entries(md, ["AAAUSDT"], ["BBBUSDT"])
    assert len(signals) == 2
    for sig in signals:
        assert "flip_candle_open" in sig, "missing flip_candle_open"
        # Must be parseable as a Timestamp (the open_position() call path
        # does pd.Timestamp(sig["flip_candle_open"]))
        pd.Timestamp(sig["flip_candle_open"])


# ─── 2. open_position accepts what check_entries emits ──────────────────


def test_open_position_accepts_signal(tmp_path, config, synthetic_signal):
    """End-to-end: synthetic signal → open_position must not raise."""
    pt = PositionTracker.__new__(PositionTracker)
    pt.config = config
    pt.positions = {}
    pt.history = []
    pt._save = staticmethod(lambda *a, **k: None)  # don't write files

    pos = pt.open_position(synthetic_signal)
    assert pos is not None
    assert pos["symbol"] == "BTCUSDT"
    assert pos["entry"] == 65000.0
    assert "params" in pos, "position should snapshot strategy params"
    assert pos["params"]["trail_atr_mult"] == 3.5


# ─── 3. process_exits checks the entry bar against the stop ─────────────


def test_process_exits_checks_entry_bar(config):
    """Parity #3: live tracker used to skip the entry bar, the backtest
    doesn't. This test feeds a series where the entry bar already sweeps
    the stop and asserts the live tracker catches it."""
    pt = PositionTracker.__new__(PositionTracker)
    pt.config = config
    pt.positions = {}
    pt.history = []

    # 1 entry bar (a flush that punches the stop) followed by 19 calm bars.
    n = 20
    base = pd.date_range("2026-08-01", periods=n, freq="4h")
    df = pd.DataFrame({
        "open":  np.full(n, 100.0),
        "high":  np.full(n, 101.0),
        "low":   np.full(n, 99.0),   # entry bar will be carved below
        "close": np.full(n, 100.5),
        "volume": np.full(n, 1_000.0),
        "close_time": base,
    }, index=base)
    # Carve the entry bar's low BELOW the 5xATR stop so the trail/stop
    # check (the first branch in the inner loop) fires immediately.
    df.iloc[0, df.columns.get_loc("low")] = 50.0
    df["supertrend_dir"] = np.array([1] * n)

    # init_dist = max(5.0 * 5.0, 0.02 * 100.0) = 25 -> stop at 100 - 25 = 75
    pt.positions["XUSDT"] = {
        "symbol": "XUSDT",
        "direction": "BUY",
        "entry": 100.0,
        "atr_entry": 5.0,
        "entry_bar_open": base[0].isoformat(),
        "entry_time": "2026-08-01T00:00:00+00:00",
        "interval": "4h",
        "initial_stop": 75.0,
        "trail_stop": 75.0,
        "params": {},
    }

    exits, orphans = pt.process_exits({
        "interval": "4h", "btc_dir": 1, "breadth": 0.5,
        "symbols": {"XUSDT": {"df": df}},
    })
    assert len(orphans) == 0
    assert len(exits) == 1, "entry bar's low = 50 < stop 75 should have exited"
    assert exits[0]["exit_reason"] == "stop"
    assert "XUSDT" not in pt.positions


# ─── 4. process_exits still works when no exit is hit ───────────────────


def test_process_exits_no_exit_persists_ratchet(config):
    pt = PositionTracker.__new__(PositionTracker)
    pt.config = config
    pt.positions = {}
    pt.history = []

    n = 10
    base = pd.date_range("2026-08-01", periods=n, freq="4h")
    closes = np.linspace(100, 130, n)
    df = pd.DataFrame({
        "open": closes, "high": closes + 0.5, "low": closes - 0.5,
        "close": closes, "volume": np.full(n, 1.0), "close_time": base,
    }, index=base)
    df["supertrend_dir"] = 1

    pt.positions["YUSDT"] = {
        "symbol": "YUSDT", "direction": "BUY",
        "entry": 100.0, "atr_entry": 2.0,
        "entry_bar_open": base[0].isoformat(),
        "entry_time": "2026-08-01T00:00:00+00:00",
        "interval": "4h",
        "initial_stop": 90.0, "trail_stop": 90.0, "params": {},
    }
    exits, orphans = pt.process_exits({
        "interval": "4h", "btc_dir": 1, "breadth": 0.5,
        "symbols": {"YUSDT": {"df": df}},
    })
    assert exits == [] and orphans == []
    # Stop should have ratcheted up
    assert pt.positions["YUSDT"]["trail_stop"] > 90.0


# ─── 5. Orphan detection fires after orphan_alert_days ──────────────────


def test_orphan_alert_fires_after_threshold(config):
    pt = PositionTracker.__new__(PositionTracker)
    pt.config = config
    pt.config.orphan_alert_days = 3
    pt.positions = {}
    pt.history = []

    # Position opened 5 days ago, never seen in universe
    opened = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    pt.positions["ZUSDT"] = {
        "symbol": "ZUSDT", "direction": "BUY",
        "entry": 100.0, "atr_entry": 2.0,
        "entry_bar_open": opened, "entry_time": opened,
        "interval": "4h", "initial_stop": 90.0, "trail_stop": 90.0,
        "params": {},
    }
    exits, orphans = pt.process_exits({
        "interval": "4h", "btc_dir": 1, "breadth": 0.5, "symbols": {},
    })
    assert len(orphans) == 1
    assert orphans[0]["symbol"] == "ZUSDT"
    # Idempotent on second call
    exits2, orphans2 = pt.process_exits({
        "interval": "4h", "btc_dir": 1, "breadth": 0.5, "symbols": {},
    })
    assert orphans2 == []


# ─── 6. Telegram weekly digest math ──────────────────────────────────────


def test_weekly_digest_aggregates_correctly(config, monkeypatch):
    """Spot-check the 7-day vs all-time math in send_weekly_digest()."""
    bot = TelegramBot(config)
    sent = []
    monkeypatch.setattr(bot, "send_message", lambda text, **kw: sent.append(text) or True)

    now = datetime.now(timezone.utc)
    def make_trade(age_days, net_r):
        t = (now - timedelta(days=age_days)).isoformat()
        return {"exit_time": t, "net_r": net_r, "exit_reason": "stop", "symbol": "X", "direction": "BUY"}

    trades = [
        make_trade(0, 1.0), make_trade(1, -0.5), make_trade(2, 2.0),    # 3 this week
        make_trade(10, 1.0), make_trade(20, -1.0),                      # 2 older
    ]
    assert bot.send_weekly_digest(trades) is True
    assert len(sent) == 1
    msg = sent[0]
    # All-time: 3 wins / 5 trades = 60%
    assert "60%" in msg
    # Last-7-day win rate: 2 wins / 3 trades = 67%
    assert "67%" in msg
    # All-time net R sum = 2.5
    assert "+2.50R" in msg


# ─── 7. mtime cache invalidation ─────────────────────────────────────────


def test_cached_json_invalidates_on_mtime(tmp_path):
    """_cached_json must re-read when the file's mtime changes, otherwise
    dashboard polls get stuck on stale data."""
    p = tmp_path / "x.json"
    p.write_text("1")
    _json_cache.clear()

    assert _cached_json(p, 0) == 1
    # Force a measurable mtime change (filesystem mtime resolution is ~1s)
    time.sleep(1.05)
    p.write_text("2")
    assert _cached_json(p, 0) == 2, "cache did not invalidate on mtime change"


# ─── 8. API model accepts both legacy and trend-ride signal shapes ──────


def test_signal_model_accepts_both_shapes():
    from api_server import Signal

    legacy = {
        "id": "X_4h_1", "symbol": "XUSDT", "direction": "BUY",
        "price": 1.0, "atr": 0.1, "atr_pct": 2.0,
        "sl": 0.9, "tp": 1.1, "rr": 1.5, "rsi": 60.0,
        "interval": "4h", "detected_at": "2026-08-30T00:00:00+00:00",
        "source": "volume",
    }
    modern = {
        "id": "Y_4h_1", "symbol": "YUSDT", "direction": "SELL",
        "price": 1.0, "atr": 0.1, "atr_pct": 2.0,
        "interval": "4h", "detected_at": "2026-08-30T00:00:00+00:00",
        "source": "volume",
        "initial_stop": 1.1, "risk_pct": 0.5, "breadth": 0.3,
        "risk_level": "half", "ema200": 0.95, "supertrend_value": 1.05,
        "candle_time": "2026-08-29T20:00:00+00:00", "strategy": "st_trail_v2",
    }
    assert Signal.model_validate(legacy).sl == 0.9
    assert Signal.model_validate(modern).initial_stop == 1.1


# ─── 9. Engine / tracker parity contract ──────────────────────────────────


def test_engine_tracker_parity_contract(config):
    """The live tracker MUST mirror the backtest engine's exit logic.
    This test drives a concrete series and verifies the tracker fires
    an exit with the expected reason.  The engine itself lives in
    backtest/engine.py — if it disagrees with this test, update the engine
    to match, not this test."""
    pt = PositionTracker.__new__(PositionTracker)
    pt.config = config
    pt.positions = {}
    pt.history = []

    n = 25
    base = pd.date_range("2026-08-01", periods=n, freq="4h")
    # Flat close so ATR is stable; open on entry bar = 100.
    base_vals = np.full(n, 100.0)
    df = pd.DataFrame({
        "open": base_vals, "high": base_vals + 0.5,
        "low": base_vals - 0.5, "close": base_vals + 0.1,
        "volume": np.full(n, 1.0), "close_time": base,
    }, index=base)
    # Bars 0-9: flat; bar 10: bearish flip; bars 10-19: downtrend.
    df["supertrend_dir"] = np.array([1] * 10 + [-1] * 15)

    # init_dist = max(5 * 0.5, 0.02 * 100) = max(2.5, 2) = 2.5
    # stop = 100 - 2.5 = 97.5
    # Trailing should NOT activate (no bar closes beyond 100 + 2*0.5 = 101)
    # The flip exit fires at bar 10 because ST flips bearish AND bars 10+
    # have high <= stop (bearish close doesn't need to pierce the stop —
    # direction == -1 and close <= stop triggers "flip" exit in tracker).
    pt.positions["TUSDT"] = {
        "symbol": "TUSDT", "direction": "BUY",
        "entry": 100.0, "atr_entry": 0.5,
        "entry_bar_open": base[0].isoformat(),
        "entry_time": base[0].isoformat(),
        "interval": "4h",
        "initial_stop": 97.5, "trail_stop": 97.5,
        "params": {},
    }
    exits, _ = pt.process_exits({
        "interval": "4h", "btc_dir": 1, "breadth": 0.5,
        "symbols": {"TUSDT": {"df": df}},
    })
    assert len(exits) == 1, "flip should have exited this position"
    assert exits[0]["exit_reason"] in ("stop", "flip", "time")


# ─── 10. Test sandbox must actually isolate the state files ──────────────


def test_tracker_paths_are_sandboxed():
    """The trackers honor the env-var sandbox. If someone reintroduces a
    hard-coded relative path, this fails instead of silently clobbering
    the live bot's positions/trades/signals when pytest runs from the
    project root (the TUSDT trade that polluted data/trade_history.json
    came from exactly that)."""
    from position_tracker import POSITIONS_FILE, TRADES_FILE
    from signal_tracker import SIGNALS_FILE

    for path in (POSITIONS_FILE, TRADES_FILE, SIGNALS_FILE):
        assert str(SANDBOX) in str(path), \
            f"{path} is not inside the test sandbox"


# ─── 11. Tracker anchors the virtual fill to the entry bar's open ────────


def test_process_exits_anchors_entry_to_entry_bar_open(config):
    """The signal carries the flip candle's close, but the engine (and real
    fills) enter at the NEXT bar's open. The first exit check that sees the
    entry bar must re-price the position and reseed the stop from the open."""
    pt = PositionTracker.__new__(PositionTracker)
    pt.config = config
    pt.positions = {}
    pt.history = []

    n = 5
    base = pd.date_range("2026-08-01", periods=n, freq="4h")
    df = pd.DataFrame({
        "open":  np.full(n, 101.0),   # real fill: 101, signal said 100
        "high":  [103.0, 104.0, 104.0, 104.0, 104.0],
        "low":   [100.9, 102.0, 102.0, 102.0, 102.0],
        "close": [102.5, 103.0, 103.0, 103.0, 103.0],
        "volume": np.full(n, 1.0),
        "close_time": base,
    }, index=base)
    df["supertrend_dir"] = 1

    pt.positions["AUSDT"] = {
        "symbol": "AUSDT", "direction": "BUY",
        "entry": 100.0, "atr_entry": 1.0,
        "entry_bar_open": base[0].isoformat(),
        "entry_time": "2026-08-01T00:00:00+00:00",
        "interval": "4h",
        "initial_stop": 95.0, "trail_stop": 95.0,
        "params": {},
    }
    exits, _ = pt.process_exits({
        "interval": "4h", "btc_dir": 1, "breadth": 0.5,
        "symbols": {"AUSDT": {"df": df}},
    })
    assert exits == []
    pos = pt.positions["AUSDT"]
    assert pos["entry"] == 101.0, "entry must be re-anchored to bar open"
    assert pos["entry_anchored"] is True
    # Ratchet must build on the reseeded stop (101 - max(5*1, 2%*101) ≈ 95.95),
    # not the pre-anchor 95.0: bar 0 closes at 102.5 -> 102.5 - 3.5*1 = 99.0
    assert pos["trail_stop"] >= 99.0


# ─── 12. Engine gap-through-stop fills at the bar's open ─────────────────


def test_engine_trail_mode_crash_bar_fills_at_open():
    """A bar that GAPS through the trail stop must fill at that bar's open
    (a real stop-market order fills on the gap), not at the better stop
    price — the old behavior recorded fantasy fills ~15% above the market
    on crash bars."""
    sys.path.insert(0, str(ROOT / "backtest"))
    import engine as bt_engine

    n = 6
    base = pd.date_range("2026-08-01", periods=n, freq="4h")
    df = pd.DataFrame({
        "open":  [100, 101, 103, 105, 107, 90],
        "high":  [101, 103, 105, 107, 108, 91],
        "low":   [99.5, 100.5, 102.5, 104.5, 106.5, 60],
        "close": [101, 103, 105, 107, 107.5, 65],
        "volume": np.full(n, 1.0),
        "close_time": base,
    }, index=base)
    plan = bt_engine.TradePlan(
        idx=0, direction=1, sl_frac=0.05, tp_frac=None,
        exit_mode='trail', trail_mult=1.0, atr_entry=1.0)
    trades = bt_engine.simulate_symbol(df, [plan])

    assert len(trades) == 1
    t = trades[0]
    # Trail ratchets to 107.5 - 1.0*1.0 = 106.5 before the crash bar; the
    # crash bar opens at 90, far below the stop -> fill at the open.
    assert abs(t["exit"] - 90.0) < 1e-6, \
        f"crash bar must fill at the open (90), got {t['exit']}"
    assert t["exit_reason"] == "trail"

    # Intrabar pierce (open above the stop) still fills AT the stop.
    df2 = df.copy()
    df2.iloc[5, df2.columns.get_loc("open")] = 107.0   # no gap
    trades2 = bt_engine.simulate_symbol(df2, [plan])
    assert abs(trades2[0]["exit"] - 106.5) < 1e-6


def test_tracker_gap_through_stop_fills_at_open(config):
    """Live tracker parity: a crash bar opening below the trailed stop must
    record the exit at the bar's open, mirroring the fixed engine."""
    pt = PositionTracker.__new__(PositionTracker)
    pt.config = config
    pt.positions = {}
    pt.history = []

    n = 4
    base = pd.date_range("2026-08-01", periods=n, freq="4h")
    df = pd.DataFrame({
        "open":  [100.0, 102.0, 104.0, 80.0],
        "high":  [101.0, 103.0, 105.0, 81.0],
        "low":   [99.0, 101.0, 103.5, 50.0],
        "close": [100.5, 102.5, 104.5, 55.0],
        "volume": np.full(n, 1.0),
        "close_time": base,
    }, index=base)
    df["supertrend_dir"] = 1

    # trail_stop persisted from a previous scan: 104.5 - 3.5*0.5 = 102.75
    pt.positions["GUSDT"] = {
        "symbol": "GUSDT", "direction": "BUY",
        "entry": 100.0, "atr_entry": 0.5,
        "entry_bar_open": base[0].isoformat(),
        "entry_time": base[0].isoformat(),
        "interval": "4h",
        "initial_stop": 97.5, "trail_stop": 102.75,
        "trail_stop_asof": base[2].isoformat(),
        "entry_anchored": True,
        "params": {},
    }
    exits, _ = pt.process_exits({
        "interval": "4h", "btc_dir": 1, "breadth": 0.5,
        "symbols": {"GUSDT": {"df": df}},
    })
    assert len(exits) == 1
    # Crash bar opens at 80, below the 102.75 stop -> fill at the open.
    assert exits[0]["exit_reason"] == "stop"
    assert abs(exits[0]["exit"] - 80.0) < 1e-9


# ─── 13. Entry alerts fire even when no virtual position is opened ───────


def test_entry_alert_notes_unopened_virtual_position(config, monkeypatch,
                                                     synthetic_signal):
    """Position-cap full must never suppress the Telegram alert — the alert
    carries a note instead (the TUSDT-era behavior silently dropped it)."""
    bot = TelegramBot(config)
    sent = []
    monkeypatch.setattr(bot, "send_message",
                        lambda text, **kw: sent.append(text) or True)

    # Opened as usual -> no virtual-position line (unchanged message shape)
    assert bot.send_entry_alert(synthetic_signal) is True
    assert "Virtual position" not in sent[-1]

    # At capacity -> alert still sent, with the reason attached
    assert bot.send_entry_alert(
        synthetic_signal, vp_note="not opened — max 10 positions reached"
    ) is True
    assert "Virtual position" in sent[-1]
    assert "max 10 positions reached" in sent[-1]


# ─── 14. Exit replay must be causal (no future-informed stop) ────────────


def test_process_exits_replay_is_causal(config):
    """Bug: the persisted trail_stop (ratcheted through the latest candle)
    was seeded into the re-simulation from the entry bar, so old bars were
    judged against a stop level that only existed later — retroactively
    "stopping out" positions at their entry bar with fake negative-R exits.
    The replay must rebuild the causal stop path instead: an early dip that
    stayed above the *then-current* stop must never exit, no matter how far
    the trail has ratcheted up since."""
    pt = PositionTracker.__new__(PositionTracker)
    pt.config = config
    pt.positions = {}
    pt.history = []

    n = 6
    base = pd.date_range("2026-08-01", periods=n, freq="4h")
    # Entry bar dips to 98.5 — below entry, but ABOVE the initial stop 97.5.
    # Closes then run up, ratcheting the trail to ~108.25 by bar 3.
    closes = [100.5, 105.0, 108.0, 110.0, 109.5, 109.8]
    lows =   [98.5, 104.0, 107.0, 109.0, 108.5, 108.8]
    highs =  [101.0, 106.0, 109.0, 111.0, 110.0, 110.3]
    df = pd.DataFrame({
        "open":  [c - 0.3 for c in closes],
        "high":  highs,
        "low":   lows,
        "close": closes,
        "volume": np.full(n, 1.0),
        "close_time": base,
    }, index=base)
    df["supertrend_dir"] = 1

    pos = {
        "symbol": "CUSDT", "direction": "BUY",
        "entry": 100.0, "atr_entry": 0.5,
        "entry_bar_open": base[0].isoformat(),
        "entry_time": base[0].isoformat(),
        "interval": "4h",
        "initial_stop": 97.5, "trail_stop": 97.5,
        "params": {},
    }
    pt.positions["CUSDT"] = dict(pos)

    symbols = {"CUSDT": {"df": df}}
    # Scan 1: only bars 0-3 are closed — trail ratchets to 110 - 1.75 = 108.25
    partial = {"interval": "4h", "btc_dir": 1, "breadth": 0.5,
               "symbols": {"CUSDT": {"df": df.iloc[:4]}}}
    exits, _ = pt.process_exits(partial)
    assert exits == []
    assert abs(pt.positions["CUSDT"]["trail_stop"] - 108.25) < 1e-9
    assert pt.positions["CUSDT"]["trail_stop_asof"] == base[3].isoformat()

    # Scan 2: all 6 bars. The buggy code seeded the replay from the entry bar
    # with the 108.25 stop -> bar 0's low (98.5) "hit" it -> fake exit at the
    # entry bar. Causally the position was never stopped.
    full = {"interval": "4h", "btc_dir": 1, "breadth": 0.5, "symbols": symbols}
    exits, _ = pt.process_exits(full)
    assert exits == [], (
        "entry-bar dip above the initial stop must not exit against a "
        "future-ratcheted trail"
    )
    assert "CUSDT" in pt.positions
    assert pt.positions["CUSDT"]["trail_stop_asof"] == base[5].isoformat()


# ─── 15. Weekly digest lists open positions from the tracker ─────────────


def test_weekly_digest_lists_open_positions(config, monkeypatch):
    """Regression: the digest checked `scanner.position_tracker`, an
    attribute CryptoScanner never had, so the open-positions section could
    never render. The tracker must be passed explicitly, and a BUY position
    in profit must show positive R (the old code only matched 'LONG')."""
    class _FakeTracker:
        def get_open_positions(self):
            return [{
                "symbol": "OPUSDT", "direction": "BUY",
                "entry": 100.0, "current_price": 110.0,
                "initial_stop": 90.0,
            }]

    bot = TelegramBot(config, position_tracker=_FakeTracker())
    sent = []
    monkeypatch.setattr(bot, "send_message",
                        lambda text, **kw: sent.append(text) or True)

    now = datetime.now(timezone.utc)
    trades = [{"exit_time": now.isoformat(), "net_r": 1.0,
               "exit_reason": "stop", "symbol": "X", "direction": "BUY"}]
    assert bot.send_weekly_digest(trades) is True
    msg = sent[0]
    assert "Open positions (1)" in msg
    assert "OPUSDT" in msg
    # (110 - 100) / (110 - 90 initial stop) = +1.0R — the sign bug would
    # have shown -1.00R for a BUY.
    assert "+1.00R" in msg


# ─── 16. Unalerted signals are retried, not suppressed ───────────────────


def test_signal_retry_after_failed_alert(config):
    """A signal recorded while Telegram was down (never marked alerted) must
    be re-recordable on the next scan — same row, same id — and only become
    a duplicate once it has actually been alerted."""
    tracker = SignalTracker(config)
    tracker.signals = []

    base = {
        "symbol": "RUSDT", "direction": "BUY", "price": 1.0,
        "atr": 0.01, "atr_pct": 1.0, "interval": "4h",
        "detected_at": "2026-09-01T00:05:00+00:00",
        "source": "volume",
        "candle_time": "2026-09-01T00:00:00+00:00",
        "flip_candle_open": "2026-08-31T20:00:00+00:00",
    }

    assert tracker.record_signal(dict(base)) is True
    first_id = tracker.signals[0]["id"]

    # Telegram send failed -> mark_alerted never called. The next scan must
    # allow the retry and reuse the same row/id.
    assert tracker.record_signal(dict(base)) is True
    assert len(tracker.signals) == 1, "retry must replace, not duplicate"
    assert tracker.signals[0]["id"] == first_id

    # Alert succeeded this time -> the same candle is now a duplicate.
    tracker.mark_alerted(first_id)
    assert tracker.record_signal(dict(base)) is False


# ─── 17. Round-5b entry filters: Sunday skip + breadth gate ──────────────


def _entry_md(symbol: str, flip_open: pd.Timestamp, breadth: float) -> dict:
    """A single bullish-flip symbol with an ATR% inside the default band."""
    return {
        "btc_dir": -1,
        "breadth": breadth,
        "interval": "4h",
        "symbols": {
            symbol: {
                "close": 100.0, "ema200": 90.0, "atr": 2.0,
                "supertrend_value": 95.0, "dir": 1, "flip": 1,
                "flip_candle_open": flip_open,
                "candle_time": (flip_open + pd.Timedelta("4h")).isoformat(),
            },
        },
    }


def test_check_entries_sunday_skip(config):
    """Round-5b: flip candles opening on SUNDAY are skipped (3-year OOS:
    Sunday entries average negative R — REPORT §6f). Other days unaffected;
    disabling the flag restores them."""
    scanner = CryptoScanner(config)
    md = _entry_md("SUNUSDT", pd.Timestamp("2026-09-06 00:00"), 0.55)   # Sunday
    md["symbols"]["MONUSDT"] = {
        "close": 100.0, "ema200": 90.0, "atr": 2.0,
        "supertrend_value": 95.0, "dir": 1, "flip": 1,
        "flip_candle_open": pd.Timestamp("2026-08-31 16:00"),           # Monday
        "candle_time": "2026-08-31T20:00:00+00:00",
    }

    signals = scanner.check_entries(md, [], [])
    syms = {s["symbol"] for s in signals}
    assert "SUNUSDT" not in syms, "Sunday flip candle must be skipped"
    assert "MONUSDT" in syms

    config.skip_sunday = False
    signals = scanner.check_entries(md, [], [])
    assert {"SUNUSDT", "MONUSDT"} <= {s["symbol"] for s in signals}


def test_check_entries_breadth_gate(config):
    """Round-5b: NO entries at all while breadth is below BREADTH_GATE,
    regardless of any symbol's signal."""
    scanner = CryptoScanner(config)
    config.breadth_gate = 0.15
    config.quality_tiers = {"A", "B", "C", "D"}   # isolate the gate test

    md = _entry_md("GATEUSDT", pd.Timestamp("2026-08-31 16:00"), 0.10)
    assert scanner.check_entries(md, [], []) == []

    md["breadth"] = 0.20   # above the gate, below the sizing threshold
    signals = scanner.check_entries(md, [], [])
    assert len(signals) == 1
    assert signals[0]["risk_level"] == "half"


def test_config_round5b_defaults(config):
    """The round-5b knobs exist and default to the deployed values."""
    assert config.skip_sunday is True
    assert config.breadth_gate == pytest.approx(0.15)


# ─── 18. Signal quality tiers ─────────────────────────────────────────────


def _md(symbol: str, direction: str, breadth: float) -> dict:
    flip = {"LONG": 1, "BUY": 1, "SHORT": -1, "SELL": -1}[direction]
    return {
        "btc_dir": -1 if direction in ("SHORT", "SELL") else 1,
        "breadth": breadth,
        "interval": "4h",
        "symbols": {
            symbol: {
                "close": 100.0,
                "ema200": 90.0 if direction in ("LONG", "BUY") else 110.0,
                "atr": 2.0,
                "supertrend_value": 95.0 if flip == 1 else 105.0,
                "dir": flip, "flip": flip,
                "flip_candle_open": pd.Timestamp("2026-08-31 16:00"),
                "candle_time": "2026-08-31T20:00:00+00:00",
            },
        },
    }


def test_signal_quality_tiers(config):
    """Round-5b: every signal carries a quality tier derived from the 3-year
    study — A: confirmed longs; B: flush/high-breadth shorts; C: the weak
    sets (low-breadth longs, mid-breadth shorts); D: shorts on BTC itself.
    Labeling is tested with the filter disabled; filtering has its own test."""
    scanner = CryptoScanner(config)
    config.quality_tiers = {"A", "B", "C", "D"}

    long_a = scanner.check_entries(_md("AAAUSDT", "BUY", 0.55), [], [])
    long_c = scanner.check_entries(_md("CCCUSDT", "BUY", 0.20), [], [])
    short_b = scanner.check_entries(_md("BBBUSDT", "SELL", 0.20), [], [])
    short_c = scanner.check_entries(_md("CCCUSDT2", "SELL", 0.40), [], [])
    short_d = scanner.check_entries(_md("BTCUSDT", "SELL", 0.55), [], [])

    assert long_a[0]["quality"] == "A"
    assert long_c[0]["quality"] == "C"
    assert short_b[0]["quality"] == "B"
    assert short_c[0]["quality"] == "C"
    assert short_d[0]["quality"] == "D"
    # reasons are human-readable and non-empty
    for sig in (long_a[0], short_b[0]):
        assert sig["quality_reason"]


def test_quality_filter_default_trades_ab_only(config):
    """Deployed default QUALITY_FILTER=A,B: the weak C sets (low-breadth
    longs, mid-breadth shorts) and BTC shorts are suppressed, while A and B
    pass. 'all' restores everything."""
    scanner = CryptoScanner(config)
    assert config.quality_tiers == {"A", "B"}

    assert len(scanner.check_entries(_md("AAAUSDT", "BUY", 0.55), [], [])) == 1    # A: kept
    assert len(scanner.check_entries(_md("BBBUSDT", "SELL", 0.20), [], [])) == 1   # B: kept

    assert scanner.check_entries(_md("CCCUSDT", "BUY", 0.20), [], []) == []     # C dropped
    assert scanner.check_entries(_md("CCCUSDT2", "SELL", 0.40), [], []) == []   # C dropped
    assert scanner.check_entries(_md("BTCUSDT", "SELL", 0.55), [], []) == []    # D dropped

    config.quality_tiers = {"A", "B", "C", "D"}
    assert len(scanner.check_entries(_md("BTCUSDT", "SELL", 0.55), [], [])) == 1
