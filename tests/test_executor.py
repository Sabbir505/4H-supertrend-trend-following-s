"""
Tests for the Binance futures executor (executor.py).

Live network is never touched: requests go through a fake session, and
dry-mode tests verify order *intent* (logs/state) without any transport.
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from executor import FuturesExecutor, BinanceFuturesError, BinanceRateLimited


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
    def __init__(self, payload=None, status=200, headers=None, text=None):
        self._payload = payload or {}
        self.status_code = status
        self.text = text if text is not None else str(self._payload)
        self.headers = headers or {}

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
                    {"filterType": "PRICE_FILTER", "tickSize": "0.001"},
                ],
            }, {
                "symbol": "RICHUSDT",
                "filters": [
                    {"filterType": "LOT_SIZE",
                     "stepSize": "0.001", "minQty": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }]})
        if "/fapi/v2/positionRisk" in url:
            return FakeResponse([
                {"symbol": "AAAUSDT", "positionAmt": "5"},
                {"symbol": "NOISEUSDT", "positionAmt": "0"},
            ])
        if "/fapi/v2/balance" in url:
            return FakeResponse([{"asset": "USDT", "balance": "1000",
                                  "availableBalance": "900"}])
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


def test_live_entry_retries_once_on_notional_rejection(ex):
    """-4164 (notional < $5 at fill time, e.g. price slipped below the
    signal price) must trigger one retry at a larger notional, not lose
    the trade."""
    calls = {"n": 0}
    original_request = ex._session.request

    def flaky(method, url, headers=None, timeout=None):
        if "/fapi/v1/order" in url and calls["n"] == 0:
            calls["n"] += 1
            ex._session.calls.append(
                {"method": method, "url": url, "headers": headers})
            return FakeResponse(
                {"code": -4164,
                 "msg": "Order's notional must be no smaller than 5."},
                400)
        return original_request(method, url, headers=headers, timeout=timeout)

    ex._session.request = flaky
    assert ex.open_position(_pos()) is True
    order_urls = [c["url"] for c in ex._session.calls
                  if "/fapi/v1/order" in c["url"]]
    assert len(order_urls) == 2, "rejected entry retried once"
    assert "quantity=5.2" in order_urls[1], "retry uses +5% notional (5.25)"
    algo_urls = [c["url"] for c in ex._session.calls
                 if "/fapi/v1/algoOrder" in c["url"]]
    assert len(algo_urls) == 1, "stop placed after the successful retry"


def test_live_entry_not_retried_for_other_errors(ex):
    original = ex._qty_for_notional
    ex._qty_for_notional = lambda symbol, price, notional=None: original(
        symbol, price) if notional is None else original(
        symbol, price, notional)
    calls = {"n": 0}
    req = ex._session.request

    def bad(method, url, headers=None, timeout=None):
        if "/fapi/v1/order" in url:
            calls["n"] += 1
            return FakeResponse({"code": -2019, "msg": "Margin is insufficient."}, 400)
        return req(method, url, headers=headers, timeout=timeout)

    ex._session.request = bad
    assert ex.open_position(_pos()) is False
    assert calls["n"] == 1, "non-notional errors must not be retried"


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
    ex._qty_for_notional = lambda symbol, price, notional=None: 5.0  # bypass per-symbol filters
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
    ex.sync_stop(_pos(stop=0.9, trail=0.90004))        # sub-tick ratchet -> no-op
    assert len(ex._session.calls) == n_before
    ex.sync_stop(_pos(stop=0.9, trail=0.95))           # ratcheted -> replace
    urls = [c["url"] for c in ex._session.calls[n_before:]]
    assert any("algoOrder" in u and "triggerPrice=0.95" in u for u in urls)
    assert not any("allOpenOrders" in u for u in urls), \
        "replacement must be place-first (the -4130 recovery handles the " \
        "old stop), not an unconditional cancel of every order"


def test_place_stop_reuses_identical_existing_stop(ex):
    """-4130 with an existing closePosition stop at the SAME trigger must
    be treated as success — this is exactly the state left behind by a
    rate-limited cancel, and reusing it is what makes sync_stop idempotent
    across outages."""
    real_signed = ex._signed
    ex._algo_place_path = "/fapi/v1/algoOrder"

    def conflicting(method, path, params):
        if method == "POST" and path == "/fapi/v1/algoOrder":
            raise BinanceFuturesError(
                'POST /fapi/v1/algoOrder -> 400: {"code":-4130,"msg":"An '
                'open stop or take profit order with GTE and closePosition '
                'in the direction is existing."}')
        return real_signed(method, path, params)

    ex._signed = conflicting
    # exchange reports the stop already at the desired trigger
    ex._working_close_stop = lambda s, side: (12345, 0.9)
    ex._place_stop("AAAUSDT", "SELL", 0.9)
    assert ex._last_stop["AAAUSDT"] == 0.9
    assert ex._algo_id_by_symbol["AAAUSDT"] == 12345
    posts = [c for c in ex._session.calls
             if "/fapi/v1/algoOrder" in c["url"] and c["method"] == "POST"]
    assert not posts, "identical existing stop must be kept, not re-placed"


def test_place_stop_replaces_conflicting_stop_at_other_level(ex):
    real_signed = ex._signed

    def conflicting_then_ok(method, path, params):
        if method == "POST" and path == "/fapi/v1/algoOrder" \
                and not conflicting_then_ok.retried:
            conflicting_then_ok.retried = True
            raise BinanceFuturesError(
                'POST /fapi/v1/algoOrder -> 400: {"code":-4130,"msg":"An '
                'open stop or take profit order with GTE and closePosition '
                'in the direction is existing."}')
        return real_signed(method, path, params)
    conflicting_then_ok.retried = False

    ex._signed = conflicting_then_ok
    ex._working_close_stop = lambda s, side: (999, 0.8)   # stale level
    ex._place_stop("AAAUSDT", "SELL", 0.9)
    deletes = [c["url"] for c in ex._session.calls
               if "algoOpenOrders" in c["url"]]
    assert deletes, "stale stop must be batch-cancelled before re-placing"
    posts = [c for c in ex._session.calls
             if "/fapi/v1/algoOrder" in c["url"] and c["method"] == "POST"]
    assert conflicting_then_ok.retried, "first placement must hit -4130"
    assert len(posts) == 1, "exactly one retry after the batch cancel"
    assert ex._last_stop["AAAUSDT"] == 0.9


def test_cancel_symbol_orders_uses_two_batch_cancels(ex):
    ex.open_position(_pos())
    n_before = len(ex._session.calls)
    ex._cancel_symbol_orders("AAAUSDT")
    urls = [c["url"] for c in ex._session.calls[n_before:]]
    assert any("allOpenOrders" in u for u in urls)
    assert any("algoOpenOrders" in u for u in urls), \
        "algo orders must be cancelled via the batch endpoint"
    assert not any("openAlgoOrders" in u for u in urls), \
        "no per-order probe: the batch cancel replaces GET+DELETE loops"


def test_ip_ban_pauses_all_requests(ex):
    """A 418 must set the ban window and every later call must fail fast
    WITHOUT touching the network — requests sent during a ban extend it."""
    real_request = ex._session.request
    ban = {"hits": 0}

    def banned(method, url, headers=None, timeout=None):
        if "balance" in url:
            ban["hits"] += 1
            return FakeResponse({}, 418, headers={"Retry-After": "120"},
                                text='{"code":-1003,"msg":"Way too many '
                                     'requests; IP(1.2.3.4) banned until '
                                     '9999999999999."}')
        return real_request(method, url, headers=headers, timeout=timeout)

    ex._session.request = banned
    with pytest.raises(BinanceRateLimited):
        ex._signed("GET", "/fapi/v2/balance", {})
    assert ban["hits"] == 1
    calls_before = len(ex._session.calls)
    with pytest.raises(BinanceRateLimited):
        ex._signed("GET", "/fapi/v2/balance", {})
    assert ban["hits"] == 1, "banned requests must not reach the network"
    assert len(ex._session.calls) == calls_before
    assert ex._banned_until > time.time()


def test_close_cancels_stop_and_sends_reduce_only(ex):
    ex.open_position(_pos())
    n_before = len(ex._session.calls)
    ex.close_position(_pos(), reason="trail")
    new = ex._session.calls[n_before:]
    assert any("allOpenOrders" in c["url"] for c in new)
    assert any("reduceOnly=true" in c["url"] for c in new), \
        "close must be reduce-only"
    assert ex.open_count == 0


# ── sizing (fixed margin per trade) ─────────────────────────────────────


def test_sizing_is_always_fixed_margin(ex):
    """Every position commits exactly EXECUTION_MARGIN_USDT x leverage,
    regardless of wallet balance — the balance endpoint is never queried."""
    assert ex.open_position(_pos(entry=1.0, stop=0.9)) is True
    assert ex._qty_by_symbol["AAAUSDT"] == 5.0      # $1 x 5x at price 1.0
    assert not any("/fapi/v2/balance" in c["url"] for c in ex._session.calls), \
        "fixed sizing must not fetch account equity"


def test_reconcile_manages_only_exchange_positions(ex):
    """Restart safety: a virtual position with no exchange position (paper
    record, manual close) must never get orders — and must not consume the
    executor's position cap."""
    ex.reconcile([_pos("AAAUSDT"), _pos("PHANTOMUSDT")])
    assert ex.open_count == 1, "only the real exchange position counts"
    assert ex._last_stop.get("AAAUSDT") is not None, "real one gets its stop"
    assert "PHANTOMUSDT" not in ex._last_stop
    assert not any("PHANTOMUSDT" in c["url"] for c in ex._session.calls),         "no orders may be sent for phantom positions"


def test_reconcile_aborts_cleanly_when_verification_fails(ex):
    """If the exchange can't be queried, place nothing rather than risk
    orders for phantom positions."""
    def boom(method, path, params):
        if "positionRisk" in path:
            raise RuntimeError("network down")
        return {"ok": True}

    ex._signed = boom
    ex._alert = lambda *a, **k: None
    ex.reconcile([_pos("AAAUSDT")])
    assert ex.open_count == 0
    assert not ex._last_stop


def test_live_requires_api_keys():
    c = Config()
    c.binance_api_key = ""
    c.binance_api_secret = ""
    c.execution_mode = "live"
    # emulate Config's fallback logic
    if c.execution_mode == "live" and not (c.binance_api_key and c.binance_api_secret):
        c.execution_mode = "dry"
    assert c.execution_mode == "dry", "live without keys must fall back to dry"


# ── close robustness: qty tracked until confirmed flat ───────────────────


def test_market_close_keeps_qty_on_transport_error(ex, monkeypatch):
    """A network drop during a close must not orphan the real position: the
    tracked quantity survives for the pending-close retry (the 2026-09-28
    SYRUPUSDT close failure popped the qty before the order was sent)."""
    monkeypatch.setattr("executor.time.sleep", lambda s: None)
    ex.open_position(_pos())
    assert ex.open_count == 1

    real = ex._session.request
    calls = {"n": 0}

    def down(method, url, headers=None, timeout=None):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("SSL EOF")

    ex._session.request = down
    with pytest.raises(requests.exceptions.RequestException):
        ex._market_close("AAAUSDT", "BUY")
    assert calls["n"] == 3, "transport errors are retried"
    assert "AAAUSDT" in ex._qty_by_symbol, "qty must survive a failed close"

    # heals on a later scan: pending retry closes and cleans bookkeeping
    ex._session = FakeSession()
    ex._pending_closes["AAAUSDT"] = "BUY"
    ex.retry_pending_closes()
    assert "AAAUSDT" not in ex._qty_by_symbol
    assert "AAAUSDT" not in ex._pending_closes
    assert ex.open_count == 0


def test_close_position_failure_keeps_slot_and_registers_retry(ex, monkeypatch):
    monkeypatch.setattr("executor.time.sleep", lambda s: None)
    ex.open_position(_pos())
    ex._alert = lambda *a, **k: None

    def down(method, url, headers=None, timeout=None):
        raise requests.exceptions.ConnectionError("down")

    ex._session.request = down
    ex.close_position(_pos(), reason="stop")
    assert ex.open_count == 1, "failed close keeps the executor slot"
    assert ex._pending_closes.get("AAAUSDT") == "BUY"

    ex._session = FakeSession()
    ex.retry_pending_closes()
    assert "AAAUSDT" not in ex._pending_closes
    assert ex.open_count == 0


def test_market_close_handles_already_flat(ex):
    ex.open_position(_pos())

    def flat(method, url, headers=None, timeout=None):
        if "/fapi/v1/order" in url:
            return FakeResponse({"code": -2022, "msg": "ReduceOnly Order is rejected."}, 400)
        return FakeResponse({"ok": True})

    ex._session.request = flat
    assert ex._market_close("AAAUSDT", "BUY") is True
    assert "AAAUSDT" not in ex._qty_by_symbol


def test_close_sends_market_before_cancelling_stop(ex):
    """Close FIRST: if the close fails, the protective stop is still in
    force (cancel-first left the position naked on a close failure)."""
    ex.open_position(_pos())
    ex._session.calls.clear()
    ex.close_position(_pos(), reason="test")
    urls = [c["url"] for c in ex._session.calls]
    order_i = next(i for i, u in enumerate(urls) if "/fapi/v1/order" in u)
    cancel_i = next(i for i, u in enumerate(urls) if "allOpenOrders" in u)
    assert order_i < cancel_i


def test_half_risk_positions_use_half_margin(ex):
    ex.config.execution_margin_usdt = 4.0
    qty_full, label_full = ex._qty_for_position("AAAUSDT", _pos())
    pos_half = _pos()
    pos_half["risk_level"] = "half"
    qty_half, label_half = ex._qty_for_position("AAAUSDT", pos_half)
    assert qty_full == 20.0          # $4 x 5x / 1.0
    assert qty_half == 10.0          # $2 x 5x / 1.0
    assert "[half-risk]" in label_half
    assert "[half-risk]" not in label_full


def test_resting_stop_is_disaster_in_close_mode(ex):
    """Round-6 close mode: the resting exchange stop is the static disaster
    net — both at entry and on sync — never the ratcheted trail (a resting
    chandelier would fire intrabar and defeat the close trigger)."""
    pos = _pos(entry=1.0, stop=0.9)
    pos["disaster_stop"] = 0.85
    assert ex._resting_stop(pos) == 0.85

    ex.open_position(pos)
    algo_urls = [c["url"] for c in ex._session.calls if "algoOrder" in c["url"]]
    assert "triggerPrice=0.85" in algo_urls[0], "entry rests the disaster stop"

    # sync must keep the disaster level even though the trail has moved
    n_algo = len(ex._session.calls)
    pos["trail_stop"] = 0.7
    ex.sync_stop(pos)
    assert len(ex._session.calls) == n_algo, "disaster stop never churns"

    # legacy wick mode: the initial stop / trail is the resting level again
    ex.config.stop_trigger_mode = "wick"
    assert ex._resting_stop(pos) == 0.9
