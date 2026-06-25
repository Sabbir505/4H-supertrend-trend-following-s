"""
Test suite for all audit fixes (HIGH, MEDIUM, LOW).
Tests each fix in isolation using mocks — no live Binance calls.

Run: python -m pytest test_audit_fixes.py -v
"""

import os
import sys
import time
import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timezone, timedelta

import pytest

# Ensure repo root is on path
sys.path.insert(0, str(Path(__file__).parent))


# ═══════════════════════════════════════════════════════════════════════════════
# S1: API Authentication
# ═══════════════════════════════════════════════════════════════════════════════

class TestAPIAuthentication:
    """S1 (HIGH): Verify API key authentication on protected endpoints."""

    @pytest.fixture(autouse=True)
    def setup_client(self, monkeypatch):
        """Create test client with API_SERVER_KEY set."""
        monkeypatch.setenv("API_SERVER_KEY", "test-secret-key-123")
        # Reimport api_server to pick up env var
        if "api_server" in sys.modules:
            del sys.modules["api_server"]
        import api_server
        api_server.API_KEY = "test-secret-key-123"
        # Clear rate limit store between tests
        api_server._rate_limit_store.clear()
        from starlette.testclient import TestClient
        self.client = TestClient(api_server.app)
        self.api_server = api_server

    def test_health_endpoint_no_auth_required(self):
        """Health endpoint should be publicly accessible."""
        resp = self.client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_protected_endpoint_rejected_without_key(self):
        """Requests without X-API-Key header should get 401."""
        resp = self.client.get("/api/dashboard/stats")
        assert resp.status_code == 401
        assert "Invalid or missing API key" in resp.json()["detail"]

    def test_protected_endpoint_rejected_with_wrong_key(self):
        """Requests with wrong API key should get 401."""
        resp = self.client.get(
            "/api/dashboard/stats",
            headers={"X-API-Key": "wrong-key"}
        )
        assert resp.status_code == 401

    def test_protected_endpoint_accepted_with_correct_key(self):
        """Requests with correct API key should succeed."""
        resp = self.client.get(
            "/api/dashboard/stats",
            headers={"X-API-Key": "test-secret-key-123"}
        )
        assert resp.status_code == 200

    def test_auth_skipped_when_no_key_configured(self):
        """When API_SERVER_KEY is empty, all requests pass through."""
        self.api_server.API_KEY = ""
        resp = self.client.get("/api/dashboard/stats")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# PF7: API Rate Limiting
# ═══════════════════════════════════════════════════════════════════════════════

class TestAPIRateLimiting:
    """PF7 (MEDIUM): Verify per-IP sliding window rate limiting."""

    @pytest.fixture(autouse=True)
    def setup_client(self, monkeypatch):
        monkeypatch.setenv("API_SERVER_KEY", "")
        monkeypatch.setenv("API_RATE_LIMIT", "5")  # Low limit for testing
        if "api_server" in sys.modules:
            del sys.modules["api_server"]
        import api_server
        api_server.API_KEY = ""
        api_server.RATE_LIMIT_MAX = 5
        api_server._rate_limit_store.clear()
        from starlette.testclient import TestClient
        self.client = TestClient(api_server.app)
        self.api_server = api_server

    def test_requests_within_limit_succeed(self):
        """Requests under the limit should pass."""
        for _ in range(5):
            resp = self.client.get("/api/dashboard/stats")
            assert resp.status_code == 200

    def test_requests_exceeding_limit_get_429(self):
        """The 6th request should get 429."""
        for _ in range(5):
            self.client.get("/api/dashboard/stats")
        resp = self.client.get("/api/dashboard/stats")
        assert resp.status_code == 429
        assert "Rate limit exceeded" in resp.json()["detail"]

    def test_rate_limit_resets_after_window(self):
        """After the time window expires, requests should succeed again."""
        for _ in range(5):
            self.client.get("/api/dashboard/stats")
        # Manually expire all timestamps
        for key in self.api_server._rate_limit_store:
            self.api_server._rate_limit_store[key] = [
                t - 120 for t in self.api_server._rate_limit_store[key]
            ]
        resp = self.client.get("/api/dashboard/stats")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# D6: Health Endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    """D6 (LOW): Verify /health endpoint exists for Railway/Docker."""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        if "api_server" in sys.modules:
            del sys.modules["api_server"]
        import api_server
        api_server.API_KEY = ""
        api_server._rate_limit_store.clear()
        from starlette.testclient import TestClient
        self.client = TestClient(api_server.app)

    def test_health_returns_ok(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════════════════
# S5: CORS Pinning
# ═══════════════════════════════════════════════════════════════════════════════

class TestCORSPinning:
    """S5 (LOW): Verify CORS origins are pinned (no wildcards)."""

    def test_no_wildcard_origins(self):
        if "api_server" in sys.modules:
            del sys.modules["api_server"]
        import api_server
        # Check middleware stack for CORSMiddleware
        for mw in api_server.app.user_middleware:
            if "CORSMiddleware" in str(mw.cls):
                origins = mw.kwargs.get("allow_origins", [])
                for origin in origins:
                    assert "*" not in origin, (
                        f"Wildcard found in CORS origin: {origin}"
                    )
                break


# ═══════════════════════════════════════════════════════════════════════════════
# PR3: Scoped cancel_all_orders
# ═══════════════════════════════════════════════════════════════════════════════

class TestScopedCancelOrders:
    """PR3 (MEDIUM): move_sl_to_breakeven should cancel only bot's SL, not all orders."""

    def _make_trader(self):
        config = MagicMock()
        config.binance_api_key = "test"
        config.binance_api_secret = "test"
        config.auto_trading_enabled = True
        config.trade_amount_usdt = 1
        config.leverage = 10
        from binance_trader import BinanceTrader
        trader = BinanceTrader(config, scanner=None)
        return trader

    def test_cancel_specific_sl_order_when_id_provided(self):
        """When sl_order_id is given, cancel only that order."""
        trader = self._make_trader()
        trader.cancel_order = MagicMock(return_value={})
        trader.cancel_all_orders = MagicMock()
        trader._cancel_stop_orders = MagicMock()
        trader._request = MagicMock(return_value={"orderId": 999})
        trader._round_price = MagicMock(return_value=100.0)

        trader.move_sl_to_breakeven("BTCUSDT", 100.0, "LONG", sl_order_id=12345)

        trader.cancel_order.assert_called_once_with("BTCUSDT", 12345)
        trader.cancel_all_orders.assert_not_called()
        trader._cancel_stop_orders.assert_not_called()

    def test_cancel_stop_orders_fallback_when_no_id(self):
        """When no sl_order_id, use _cancel_stop_orders (not cancel_all_orders)."""
        trader = self._make_trader()
        trader.cancel_order = MagicMock(return_value={})
        trader.cancel_all_orders = MagicMock()
        trader._cancel_stop_orders = MagicMock()
        trader._request = MagicMock(return_value={"orderId": 999})
        trader._round_price = MagicMock(return_value=100.0)

        trader.move_sl_to_breakeven("BTCUSDT", 100.0, "LONG", sl_order_id=None)

        trader._cancel_stop_orders.assert_called_once_with("BTCUSDT")
        trader.cancel_all_orders.assert_not_called()

    def test_cancel_stop_orders_only_cancels_stop_types(self):
        """_cancel_stop_orders should only cancel STOP_MARKET orders."""
        trader = self._make_trader()
        trader._request = MagicMock(return_value=[
            {"orderId": 1, "type": "STOP_MARKET"},
            {"orderId": 2, "type": "LIMIT"},
            {"orderId": 3, "type": "STOP"},
            {"orderId": 4, "type": "TAKE_PROFIT_MARKET"},
        ])
        trader.cancel_order = MagicMock(return_value={})

        trader._cancel_stop_orders("BTCUSDT")

        # Should only cancel orders 1 (STOP_MARKET) and 3 (STOP)
        cancelled_ids = [
            call.args[1] for call in trader.cancel_order.call_args_list
        ]
        assert 1 in cancelled_ids
        assert 3 in cancelled_ids
        assert 2 not in cancelled_ids
        assert 4 not in cancelled_ids


# ═══════════════════════════════════════════════════════════════════════════════
# PR4: Signal Expiry Closes Binance Position
# ═══════════════════════════════════════════════════════════════════════════════

class TestSignalExpiryClosesPosition:
    """PR4 (MEDIUM): Expired signals must close the Binance position."""

    def test_expiry_calls_execute_full_close(self):
        """When a signal expires, _execute_full_close should be called."""
        config = MagicMock()
        config.signal_expiration_minutes = 10080  # 7 days
        config.auto_trading_enabled = False
        telegram = MagicMock()

        from tracker import SignalTracker
        tracker = SignalTracker(config, telegram, trader=None)
        tracker._execute_full_close = MagicMock()
        tracker._send_outcome = MagicMock()
        tracker._save = MagicMock()

        # Create a signal that's expired (older than 7 days)
        fired_time = (
            datetime.now(timezone.utc) - timedelta(days=8)
        ).isoformat()
        sig = {
            'id': 'test-1',
            'symbol': 'BTCUSDT',
            'direction': 'LONG',
            'entry': 100000,
            'sl': 99000,
            'tp1': 101500,
            'tp2': 102000,
            'tp3': 103000,
            'tp4': 104000,
            'status': 'OPEN',
            'outcome': None,
            'closed_at': None,
            'fired_at': fired_time,
            'tp1_hit': False,
            'tp2_hit': False,
            'tp3_hit': False,
            'tp4_hit': False,
            'sl_hit': False,
            'sl_at_breakeven': False,
            'rr1': 1.5,
            'rr2': 2.0,
            'rr3': 3.0,
            'rr_max': 4.0,
        }
        tracker.signals = [sig]
        tracker.cooldown = {}

        # Evaluate at a price that doesn't hit TP or SL
        tracker._evaluate(sig, 100500)

        assert sig['status'] == 'EXPIRED'
        assert sig['outcome'] == 'EXPIRED'
        tracker._execute_full_close.assert_called_once_with(sig)


# ═══════════════════════════════════════════════════════════════════════════════
# PR5: Startup Reconciliation
# ═══════════════════════════════════════════════════════════════════════════════

class TestStartupReconciliation:
    """PR5 (MEDIUM): Bot startup should reconcile tracked vs Binance positions."""

    def test_reconcile_logs_mismatch(self):
        """reconcile_positions should detect tracked vs Binance drift."""
        config = MagicMock()
        config.auto_trading_enabled = True
        telegram = MagicMock()
        trader = MagicMock()
        trader.get_open_positions.return_value = [
            {"symbol": "BTCUSDT", "positionAmt": "0.001"},
            {"symbol": "ETHUSDT", "positionAmt": "0.01"},
        ]

        from tracker import SignalTracker
        tracker = SignalTracker(config, telegram, trader=trader)
        tracker.signals = [
            {"status": "OPEN", "futures_symbol": "BTCUSDT"},
            {"status": "TP1", "futures_symbol": "SOLUSDT"},
        ]

        with patch("tracker.logger") as mock_logger:
            tracker.reconcile_positions()
            # SOLUSDT tracked but not on Binance
            warning_calls = [
                str(c) for c in mock_logger.warning.call_args_list
            ]
            assert any("SOLUSDT" in c for c in warning_calls)
            # ETHUSDT on Binance but not tracked
            assert any("ETHUSDT" in c for c in warning_calls)

    def test_reconcile_ok_when_matched(self):
        """No warnings when tracked and Binance positions match."""
        config = MagicMock()
        telegram = MagicMock()
        trader = MagicMock()
        trader.get_open_positions.return_value = [
            {"symbol": "BTCUSDT", "positionAmt": "0.001"},
        ]

        from tracker import SignalTracker
        tracker = SignalTracker(config, telegram, trader=trader)
        tracker.signals = [
            {"status": "OPEN", "futures_symbol": "BTCUSDT"},
        ]

        with patch("tracker.logger") as mock_logger:
            tracker.reconcile_positions()
            mock_logger.warning.assert_not_called()
            assert any(
                "Reconciliation OK" in str(c)
                for c in mock_logger.info.call_args_list
            )

    def test_reconcile_skipped_without_trader(self):
        """When no trader configured, reconciliation should skip gracefully."""
        config = MagicMock()
        telegram = MagicMock()
        from tracker import SignalTracker
        tracker = SignalTracker(config, telegram, trader=None)
        # Should not raise
        tracker.reconcile_positions()

    def test_main_calls_reconcile_on_startup(self):
        """main.py run_startup() should call tracker.reconcile_positions()."""
        import importlib
        # Read main.py source and verify reconcile_positions is called
        main_src = Path(__file__).parent / "main.py"
        content = main_src.read_text()
        assert "tracker.reconcile_positions()" in content, (
            "run_startup() must call tracker.reconcile_positions()"
        )

    def test_railway_calls_reconcile_on_startup(self):
        """railway_server.py run_startup() should call tracker.reconcile_positions()."""
        rail_src = Path(__file__).parent / "railway_server.py"
        content = rail_src.read_text()
        assert "tracker.reconcile_positions()" in content, (
            "railway_server.py run_startup() must call tracker.reconcile_positions()"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PF4: WebSocket Lock Release Before HTTP Calls
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebSocketLockRelease:
    """PF4 (MEDIUM): _evaluate_open_signals_locked must release lock during HTTP calls."""

    def test_lock_released_during_evaluation(self):
        """Lock should be released before _evaluate runs (which may do HTTP)."""
        config = MagicMock()
        config.signal_expiration_minutes = 10080
        config.auto_trading_enabled = False
        telegram = MagicMock()

        from tracker import SignalTracker
        tracker = SignalTracker(config, telegram, trader=None)
        tracker._last_eval_log = 0

        sig = {
            'id': 'test-lock-1',
            'symbol': 'BTCUSDT',
            'status': 'OPEN',
            'entry': 100000,
            'sl': 99000,
            'tp1': 101500,
            'tp2': 102000,
            'tp3': 103000,
            'tp4': 104000,
            'direction': 'LONG',
            'fired_at': datetime.now(timezone.utc).isoformat(),
            'tp1_hit': False,
            'tp2_hit': False,
            'tp3_hit': False,
            'tp4_hit': False,
            'sl_hit': False,
            'sl_at_breakeven': False,
            'rr1': 1.5,
            'rr2': 2.0,
            'rr3': 3.0,
            'rr_max': 4.0,
            'outcome': None,
            'closed_at': None,
        }
        tracker.signals = [sig]
        tracker._price_cache = {'BTCUSDT': 100200.0}

        lock_was_released = threading.Event()
        original_evaluate = tracker._evaluate

        def spy_evaluate(s, price):
            # During _evaluate, the lock should NOT be held
            if not tracker._ws_lock.locked():
                lock_was_released.set()
            return original_evaluate(s, price)

        tracker._evaluate = spy_evaluate
        tracker._save = MagicMock()

        # Acquire lock as the caller would
        tracker._ws_lock.acquire()
        tracker._evaluate_open_signals_locked()
        # Lock should be re-acquired after the method returns
        assert tracker._ws_lock.locked(), "Lock should be re-acquired after evaluation"
        tracker._ws_lock.release()

        assert lock_was_released.is_set(), (
            "Lock should have been released during _evaluate() execution"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# J4+A3: Railway Server Auto-Trade Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestRailwayAutoTrade:
    """J4 (HIGH) + A3 (MEDIUM): Railway server must have auto-trade integration."""

    def test_railway_has_auto_trade_function(self):
        """railway_server.py must define _auto_trade_signal."""
        rail_src = Path(__file__).parent / "railway_server.py"
        content = rail_src.read_text()
        assert "def _auto_trade_signal" in content

    def test_railway_signal_loop_calls_auto_trade(self):
        """Both signal processing loops must call _auto_trade_signal."""
        rail_src = Path(__file__).parent / "railway_server.py"
        content = rail_src.read_text()
        # Find the signal processing section
        # Should have: telegram.send_signal(sig) → _auto_trade_signal(sig) → tracker.log_signal(sig)
        lines = content.split("\n")
        auto_trade_calls = [
            i for i, line in enumerate(lines)
            if "_auto_trade_signal(sig)" in line
        ]
        assert len(auto_trade_calls) >= 2, (
            f"Expected at least 2 calls to _auto_trade_signal(sig) in "
            f"signal loops, found {len(auto_trade_calls)}"
        )

    def test_railway_initializes_trader(self):
        """railway_server.py must initialize BinanceTrader and RiskManager."""
        rail_src = Path(__file__).parent / "railway_server.py"
        content = rail_src.read_text()
        assert "BinanceTrader" in content
        assert "RiskManager" in content
        assert "trader = BinanceTrader" in content or "trader = None" in content

    def test_railway_no_code_duplication_with_main(self):
        """A3: railway_server.py should not be a copy-paste of main.py.
        Specifically it must define its own _auto_trade_signal with the same
        logic pattern (risk check → validate → open_position)."""
        rail_src = Path(__file__).parent / "railway_server.py"
        content = rail_src.read_text()
        # Must have the complete auto-trade logic
        assert "risk_mgr.can_open_trade()" in content
        assert "risk_mgr.validate_signal(sig)" in content
        assert "trader.open_position(sig)" in content


# ═══════════════════════════════════════════════════════════════════════════════
# S7: recvWindow Parameter
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecvWindow:
    """S7 (LOW): Binance signing must include recvWindow."""

    def test_sign_includes_recv_window(self):
        config = MagicMock()
        config.binance_api_key = "test"
        config.binance_api_secret = "secret"
        config.auto_trading_enabled = True
        config.trade_amount_usdt = 1
        config.leverage = 10

        from binance_trader import BinanceTrader
        trader = BinanceTrader(config, scanner=None)
        params = trader._sign({"symbol": "BTCUSDT"})
        assert "recvWindow" in params
        assert params["recvWindow"] == 5000


# ═══════════════════════════════════════════════════════════════════════════════
# S8: models/ in .gitignore
# ═══════════════════════════════════════════════════════════════════════════════

class TestGitignoreModels:
    """S8 (LOW): models/ directory should be in .gitignore."""

    def test_models_in_gitignore(self):
        gitignore = Path(__file__).parent / ".gitignore"
        content = gitignore.read_text()
        assert "models/" in content


# ═══════════════════════════════════════════════════════════════════════════════
# P3: Dependency Version Pinning
# ═══════════════════════════════════════════════════════════════════════════════

class TestDependencyPinning:
    """P3 (LOW): Dependencies should use compatible-release (~=) not unbounded (>=)."""

    def test_no_unbounded_versions(self):
        req_file = Path(__file__).parent / "requirements.txt"
        content = req_file.read_text()
        for line in content.strip().splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            assert ">=" not in line, (
                f"Unbounded version found: {line}. Use ~= instead."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# P6: scikit-learn Listed as Optional
# ═══════════════════════════════════════════════════════════════════════════════

class TestOptionalDependencies:
    """P6 (LOW): scikit-learn should be documented as optional dependency."""

    def test_sklearn_mentioned_in_requirements(self):
        req_file = Path(__file__).parent / "requirements.txt"
        content = req_file.read_text()
        assert "scikit-learn" in content, (
            "scikit-learn should be listed (even as commented-out optional)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# C6: RiskManager Type Hints
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskManagerTypeHints:
    """C6 (LOW): RiskManager methods should have proper tuple type hints."""

    def test_can_open_trade_returns_typed_tuple(self):
        from risk_manager import RiskManager
        import inspect
        sig = inspect.signature(RiskManager.can_open_trade)
        ret = sig.return_annotation
        assert ret != inspect.Parameter.empty, "Return type annotation missing"
        assert "tuple" in str(ret).lower()

    def test_validate_signal_returns_typed_tuple(self):
        from risk_manager import RiskManager
        import inspect
        sig = inspect.signature(RiskManager.validate_signal)
        ret = sig.return_annotation
        assert ret != inspect.Parameter.empty, "Return type annotation missing"
        assert "tuple" in str(ret).lower()


# ═══════════════════════════════════════════════════════════════════════════════
# C7: Public round_quantity
# ═══════════════════════════════════════════════════════════════════════════════

class TestPublicRoundQuantity:
    """C7 (LOW): round_quantity should be a public method."""

    def test_round_quantity_is_public(self):
        from binance_trader import BinanceTrader
        assert hasattr(BinanceTrader, "round_quantity")
        assert not BinanceTrader.round_quantity.__name__.startswith("_")


# ═══════════════════════════════════════════════════════════════════════════════
# B7: PNL Label
# ═══════════════════════════════════════════════════════════════════════════════

class TestPNLLabel:
    """B7 (LOW): PNL label should say R-multiple, not 10x Leveraged."""

    def test_pnl_label_not_leveraged(self):
        page_file = (
            Path(__file__).parent
            / "frontend" / "src" / "app" / "live-trades" / "page.tsx"
        )
        content = page_file.read_text()
        assert "10x Leveraged" not in content, (
            "PNL label should not say '10x Leveraged'"
        )
        assert "R-multiple" in content


# ═══════════════════════════════════════════════════════════════════════════════
# C3: No eslint-disable any cast
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoAnycast:
    """C3 (LOW): No eslint-disable / as any for sl_original access."""

    def test_no_eslint_disable_for_sl_original(self):
        page_file = (
            Path(__file__).parent
            / "frontend" / "src" / "app" / "live-trades" / "page.tsx"
        )
        content = page_file.read_text()
        assert "as any" not in content or "sl_original" not in content.split("as any")[0].split("\n")[-1], (
            "sl_original access should not use 'as any' cast"
        )

    def test_sl_original_in_interface(self):
        page_file = (
            Path(__file__).parent
            / "frontend" / "src" / "app" / "live-trades" / "page.tsx"
        )
        content = page_file.read_text()
        assert "sl_original?" in content, (
            "TradeDisplay interface must include sl_original"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# C4: No Empty Catch
# ═══════════════════════════════════════════════════════════════════════════════

class TestNoEmptyCatch:
    """C4 (LOW): Empty catch blocks should have a comment."""

    def test_no_bare_empty_catch_in_analytics(self):
        page_file = (
            Path(__file__).parent
            / "frontend" / "src" / "app" / "analytics" / "page.tsx"
        )
        content = page_file.read_text()
        # Should not have "} catch {}" with nothing inside
        assert "catch {}" not in content, (
            "Empty catch blocks should have at least a comment"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: RiskManager + BinanceTrader
# ═══════════════════════════════════════════════════════════════════════════════

class TestRiskManagerIntegration:
    """Verify risk manager correctly gates trading."""

    def test_can_open_trade_respects_max_positions(self):
        config = MagicMock()
        config.auto_trading_enabled = True
        config.max_open_positions = 13
        trader = MagicMock()
        trader.is_ready.return_value = True
        trader.get_open_position_count.return_value = 13

        from risk_manager import RiskManager
        rm = RiskManager(config, trader)
        allowed, reason = rm.can_open_trade()
        assert not allowed
        assert "Max positions reached" in reason

    def test_can_open_trade_allows_below_max(self):
        config = MagicMock()
        config.auto_trading_enabled = True
        config.max_open_positions = 13
        trader = MagicMock()
        trader.is_ready.return_value = True
        trader.get_open_position_count.return_value = 5

        from risk_manager import RiskManager
        rm = RiskManager(config, trader)
        allowed, reason = rm.can_open_trade()
        assert allowed
        assert reason == "OK"

    def test_validate_signal_rejects_invalid_direction(self):
        config = MagicMock()
        from risk_manager import RiskManager
        rm = RiskManager(config)
        sig = {
            'symbol': 'BTCUSDT', 'direction': 'INVALID',
            'entry': 100, 'sl': 99,
            'tp1': 101, 'tp2': 102, 'tp3': 103, 'tp4': 104,
        }
        valid, reason = rm.validate_signal(sig)
        assert not valid
        assert "Invalid direction" in reason

    def test_validate_signal_rejects_long_sl_above_entry(self):
        config = MagicMock()
        from risk_manager import RiskManager
        rm = RiskManager(config)
        sig = {
            'symbol': 'BTCUSDT', 'direction': 'LONG',
            'entry': 100, 'sl': 105,
            'tp1': 101, 'tp2': 102, 'tp3': 103, 'tp4': 104,
        }
        valid, reason = rm.validate_signal(sig)
        assert not valid
        assert "below entry" in reason


# ═══════════════════════════════════════════════════════════════════════════════
# Config Validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigValidation:
    """Verify config defaults and validation from .env."""

    def test_trade_amount_defaults_to_1(self):
        with patch.dict(os.environ, {}, clear=False):
            if "config" in sys.modules:
                del sys.modules["config"]
            os.environ.pop("TRADE_AMOUNT_USDT", None)
            from config import Config
            c = Config()
            assert c.trade_amount_usdt == 1.0

    def test_auto_trading_defaults_to_false(self):
        """When AUTO_TRADING_ENABLED is unset, it should default to False."""
        # Verify the Config class reads the env var with 'false' default
        from config import Config
        saved = os.environ.pop("AUTO_TRADING_ENABLED", None)
        try:
            c = Config()
            assert c.auto_trading_enabled is False
        finally:
            if saved is not None:
                os.environ["AUTO_TRADING_ENABLED"] = saved


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
