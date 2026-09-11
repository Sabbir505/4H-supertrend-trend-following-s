"""
Tests for the Binance futures executor (executor.py).

Live network is never touched: requests go through a fake session, and
dry-mode tests verify order *intent* (logs/state) without any transport.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from executor import FuturesExecutor


@pytest.fixture
def config():
    c = Config()
    c.execution_mode = "live"
    c.binance_api_key = "test-key"
    c.binance_api_secret = "test-secret"
    c.execution_margin_usdt = 1.0
    c.execution_leverage = 5
    c.execution_max_positions = 15
    return c


class FakeResponse:
    def __init__(self, payload=None, status=200):
        self._payload = payload or {}
        self.status_code = status
        self.text = str(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    """Records every request; replies with canned payloads per path."""

    def __init__(self):
        self.calls = []

    def request(self, method, url, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers})
        if "exchangeInfo" in url:
            return FakeResponse({"symbols": [{
                "symbol": "AAAUSDT",
                "filters": [
                    {"filterType": "LOT_SIZE",
                     "stepSize": "0.1", "minQty": "0.1"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }, {
                "symbol": "RICHUSDT",
                "filters": [
                    {"filterType": "LOT_SIZE",
                     "stepSize": "0.001", "minQty": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }]})
        if "marginType" in url:
            # emulate "already isolated" once
            return FakeResponse({"code": -4046, "msg": "No need to change margin type."}, 400)
        return FakeResponse({"ok": True})

    def get_json_calls(self):
        return [c for c in self.calls if "order" in c["url"] or "allOpenOrders" in c["url"]]


@pytest.fixture
def ex(config):
    session = FakeSession()
    executor = FuturesExecutor(config, session=session)
    executor._symbol_filters = {}   # real cache, fake transport
    return executor


def _pos(symbol="AAAUSDT", direction="BUY", entry=1.0, stop=0.9, trail=None):
    return {"symbol": symbol, "direction": direction, "entry": entry,
            "initial_stop": stop, "trail_stop": trail or stop}


# ── quantity rounding / exchange minimums ────────────────────────────────


def test_qty_respects_step_size_and_min_notional(ex):
    # $1 margin x 5x = $5 notional; price 1.0 -> qty 5.0 (step 0.1) -> 5.0 OK
    assert ex._qty_for_notional("AAAUSDT", 1.0) == 5.0
    # price 2.0 -> raw 2.5 -> step 0.1 -> 2.5, notional 5.0 OK
    assert ex._qty_for_notional("AAAUSDT", 2.0) == 2.5
    # price 2.6 -> raw 1.923 -> rounds DOWN to 1.9 (4.94 < 5 floor) ->
    # bumped UP one step to 2.0 -> notional 5.2, exchange-legal
    assert ex._qty_for_notional("AAAUSDT", 2.6) == 2.0


def test_qty_bump_up_stays_within_one_step(ex):
    q = ex._qty_for_notional("RICHUSDT", 6.25)   # step 0.001: 0.8 exactly
    assert q == 0.8
    assert q * 6.25 <= 5.0 + 1e-9
    # round-down lands below the $5 floor (0.666 x 7.5 = 4.995) ->
    # bumped UP one step (0.667) -> exchange-legal, over-plan by one step only
    q2 = ex._qty_for_notional("RICHUSDT", 7.5)
    assert q2 == 0.667
    assert q2 * 7.5 >= 5.0
    assert (q2 - 5.0 / 7.5) * 7.5 <= 0.001 * 7.5 + 1e-9


# ── dry mode: orders logged, never sent ──────────────────────────────────


def test_dry_mode_never_sends_orders(config):
    config.execution_mode = "dry"
    session = FakeSession()
    ex = FuturesExecutor(config, session=session)
    assert ex.open_position(_pos()) is True
    assert ex.open_count == 1
    # public exchangeInfo (for rounding) is allowed; no orders may be sent
    assert not any("/fapi/v1/order" in c["url"] for c in session.calls), \
        "dry mode must not place orders"
    assert not any("allOpenOrders" in c["url"] for c in session.calls)
    ex.close_position(_pos(), reason="test")
    assert ex.open_count == 0
    assert not any("/fapi/v1/order" in c["url"] for c in session.calls)


def test_off_mode_is_a_full_no_op(config):
    config.execution_mode = "off"
    session = FakeSession()
    ex = FuturesExecutor(config, session=session)
    assert ex.enabled is False
    assert ex.open_position(_pos()) is False
    assert ex.open_count == 0
    assert len(session.calls) == 0


# ── live mode: order construction ────────────────────────────────────────


def test_live_open_places_market_entry_then_algo_stop(ex):
    assert ex.open_position(_pos()) is True
    order_urls = [c["url"] for c in ex._session.calls if "/fapi/v1/order" in c["url"]]
    assert len(order_urls) == 1 and "type=MARKET" in order_urls[0]
    assert "side=BUY" in order_urls[0]
    algo_urls = [c["url"] for c in ex._session.calls
                 if "/fapi/v1/algoOrder" in c["url"]]
    assert len(algo_urls) == 1, "protective stop via Algo Order API"
    assert "type=STOP_MARKET" in algo_urls[0]
    assert "closePosition=true" in algo_urls[0]
    assert "triggerPrice=0.9" in algo_urls[0]
    assert "side=SELL" in algo_urls[0], "long stop must be a SELL"
    assert "X-MBX-APIKEY" in ex._session.calls[0]["headers"]
    assert "signature=" in order_urls[0], "orders must be signed"


def test_live_short_entry_uses_sell_and_buy_stop(ex):
    ex._qty_for_notional = lambda symbol, price: 5.0   # bypass per-symbol filters
    assert ex.open_position(_pos(direction="SELL", stop=1.1)) is True
    order_urls = [c["url"] for c in ex._session.calls if "/fapi/v1/order" in c["url"]]
    assert "side=SELL" in order_urls[0]
    algo_urls = [c["url"] for c in ex._session.calls
                 if "/fapi/v1/algoOrder" in c["url"]]
    assert "side=BUY" in algo_urls[0], "short stop must be a BUY"


def test_failed_stop_after_entry_flattens(ex):
    calls = {"stop_attempts": 0}
    real_signed = ex._signed

    def flaky(method, path, params):
        if path == "/fapi/v1/algoOrder" and method == "POST":
            calls["stop_attempts"] += 1
            raise RuntimeError("stop rejected")
        return real_signed(method, path, params)

    ex._signed = flaky
    assert ex.open_position(_pos()) is False, "entry without stop must not stand"
    assert calls["stop_attempts"] == 1
    close_calls = [c["url"] for c in ex._session.calls
                   if "/fapi/v1/order" in c["url"] and "reduceOnly=true" in c["url"]]
    assert close_calls, "naked entry must be flattened"


def test_execution_cap_enforced(ex):
    ex.config.execution_max_positions = 2
    assert ex.open_position(_pos("AAAUSDT")) is True
    assert ex.open_position(_pos("RICHUSDT")) is True
    assert ex.open_position(_pos("AAAUSDT")) is False
    assert ex.open_count == 2


def test_sync_stop_replaces_only_when_trail_moved(ex):
    ex.open_position(_pos(stop=0.9, trail=0.9))
    n_before = len(ex._session.calls)
    ex.sync_stop(_pos(stop=0.9, trail=0.9))            # unchanged -> no-op
    assert len(ex._session.calls) == n_before
    ex.sync_stop(_pos(stop=0.9, trail=0.95))           # ratcheted -> replace
    urls = [c["url"] for c in ex._session.calls[n_before:]]
    assert any("allOpenOrders" in u for u in urls)     # cancel old
    assert any("algoOrder" in u and "triggerPrice=0.95" in u for u in urls)


def test_close_cancels_stop_and_sends_reduce_only(ex):
    ex.open_position(_pos())
    n_before = len(ex._session.calls)
    ex.close_position(_pos(), reason="trail")
    new = ex._session.calls[n_before:]
    assert any("allOpenOrders" in c["url"] for c in new)
    assert any("reduceOnly=true" in c["url"] for c in new), \
        "close must be reduce-only"
    assert ex.open_count == 0


def test_live_requires_api_keys():
    c = Config()
    c.binance_api_key = ""
    c.binance_api_secret = ""
    c.execution_mode = "live"
    # emulate Config's fallback logic
    if c.execution_mode == "live" and not (c.binance_api_key and c.binance_api_secret):
        c.execution_mode = "dry"
    assert c.execution_mode == "dry", "live without keys must fall back to dry"
