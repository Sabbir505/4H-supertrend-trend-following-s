# TradeEdge Full-Project Security & Architecture Audit

**Date:** 2026-06-25  
**Scope:** All backend (15 Python files, ~7,635 LOC) + all frontend (8 TSX/TS files, ~4,800 LOC)  
**Method:** Manual line-by-line code review from actual source  
**Rule:** No code changes made. Audit-only.

---

## Plain-Language Overview

TradeEdge is a well-structured crypto trading platform with clean module separation (scanner → signals → tracker → API → frontend). The core trading logic — RR calculations, TP/SL math, 4-TP incremental closing — is consistent across all 5 implementations (api_server.py, utils.ts, reporter.py, backtest.py, signals.py). The Binance integration bugs (TP skip, breakeven SL) were fixed in the prior session.

**What's solid:**
- RR calculation consistency across backend/frontend (all 5 implementations match)
- Config validation with fallback defaults and positive-value guards
- HMAC-SHA256 API signing is correct
- Clean FastAPI + Next.js architecture with proper CORS
- Backtest engine faithfully mirrors live strategy logic
- Signal quality scoring (v5) with multi-factor model
- `.env` gitignored, no secrets in source

**What needs attention:**
- **API server has zero authentication** — anyone who discovers the URL can read all signal data, trade history, and live positions. This is the single highest-impact finding.
- **Railway deployment duplicates all bot logic** from main.py into railway_server.py (454 lines) — a maintenance risk where fixes to main.py don't propagate.
- **Frontend PNL label says "10x Leveraged"** but the actual calculation shows R-multiples (risk-adjusted), not leveraged dollar amounts. Misleading to users.
- **Live-trades page uses `eslint-disable` with `as any` cast** to access `sl_original`, indicating a type gap in the Signal interface.
- **No rate limiting on API endpoints** — all routes are public, unlimited.
- **Macro event calendar is hardcoded** for 2025-2026 — will go stale without updates.

---

## 9-Dimension Evidence Table

### 1. ARCHITECTURE

| # | Finding | Status | Severity | Evidence |
|---|---------|--------|----------|----------|
| A1 | Module separation is clean | PROVED | — | `scanner.py` (data fetch) → `signals.py` (strategy) → `tracker.py` (position mgmt) → `api_server.py` (REST API) → `frontend/` (dashboard). Each module has single responsibility. |
| A2 | Data flow via dict mutation | PROVED | — | Signal dicts created in `signals.py:241-266`, enriched in `main.py:532-578` (Binance metadata), stored via `tracker.log_signal()`, served via `api_server.py`. Consistent schema throughout. |
| A3 | Railway server duplicates main.py | WEAK | Medium | `railway_server.py` (454 lines) copy-pastes `run_1h_scan()`, `run_4h_scan()`, `detect_market_regime_from_btc()` from `main.py` (703 lines). If a bug is fixed in main.py, railway_server.py still has the old code. Lines 175-284 in railway_server.py are near-identical to main.py:430-540. |
| A4 | Frontend has proper component hierarchy | PROVED | — | `DashboardLayout` wraps all pages. Shared utilities in `lib/utils.ts` and `lib/api.ts`. Pages are self-contained with local state. |
| A5 | Backtest modules share pattern but don't share code | WEAK | Low | `backtest.py`, `backtest_directional.py`, `backtest_macro_events.py`, `backtest_trading_hours.py` each implement their own `Backtester` class with identical `compute_indicators()`, `detect_signal()`, `simulate_trade()`, `_calculate_incremental_rr()`. ~300 lines duplicated per file. A base class would eliminate this. |

### 2. PLATFORM COMPATIBILITY

| # | Finding | Status | Severity | Evidence |
|---|---------|--------|----------|----------|
| P1 | Python version | PROVED | — | Dockerfile uses `python:3.11-slim`. Code uses `dict | None` union syntax (requires 3.10+). No 3.12+ features used. Compatible. |
| P2 | Node/React versions | PROVED | — | `package.json`: Next.js 16.2.7, React 19.2.4, TypeScript ^5. All current as of 2026-06. |
| P3 | Python dependencies are version-floored | WEAK | Low | `requirements.txt` uses `>=` ranges (e.g. `pandas>=2.0.0`, `fastapi>=0.100.0`). No upper bounds. A future major version of pandas or FastAPI could break the app. Pin major versions or use `~=` for safety. |
| P4 | Frontend dependencies use `^` ranges | PROVED | — | `package.json` uses caret ranges (`"next": "16.2.7"` pinned, `"recharts": "^3.8.1"` — minor-compatible). Reasonable. |
| P5 | No OS-specific code in backend | PROVED | — | All imports are cross-platform. `pathlib.Path` used for file paths. No `os.system()` or shell calls. |
| P6 | scikit-learn not in requirements.txt | WEAK | Low | `win_predictor.py` imports `sklearn.ensemble.RandomForestClassifier`, but `scikit-learn` is not in `requirements.txt`. Works only because it's wrapped in try/except in main.py/railway_server.py. Should be listed as optional dependency. |

### 3. SECURITY

| # | Finding | Status | Severity | Evidence |
|---|---------|--------|----------|----------|
| S1 | API server has zero authentication | WEAK | HIGH | `api_server.py` — no auth middleware, no API keys, no bearer tokens. All 15+ endpoints (signals, dashboard stats, backtest results, market intel) are publicly accessible to anyone who knows the URL. At minimum, read access to all trading signals, positions, and performance data is exposed. |
| S2 | .env properly gitignored | PROVED | — | `.gitignore` line 1: `.env`. Verified `.env` contains BINANCE_API_KEY, BINANCE_API_SECRET, TELEGRAM_BOT_TOKEN. None appear in source code. |
| S3 | HMAC-SHA256 signing correct | PROVED | — | `binance_trader.py:48-58`: `hmac.new(secret, query_string, hashlib.sha256).hexdigest()` with timestamp. Matches Binance SIGNED endpoint spec. |
| S4 | No withdrawal endpoints | PROVED | — | `binance_trader.py` only uses: `POST /fapi/v1/order` (create), `DELETE /fapi/v1/order` (cancel), `DELETE /fapi/v1/allOpenOrders`, `GET /fapi/v2/positionRisk`, `GET /fapi/v1/exchangeInfo`. No transfer/withdraw capabilities. |
| S5 | CORS allows wildcard subdomain | WEAK | Low | `api_server.py:40-41`: `"https://*.netlify.app"` and `"https://*.railway.app"`. Any app on these platforms can make authenticated requests to the API. Should be pinned to exact deployment URLs. |
| S6 | Telegram credentials in .env | PROVED | — | Bot token and chat ID loaded from env vars, never logged or exposed in API responses. |
| S7 | No recvWindow in Binance signing | WEAK | Low | `binance_trader.py:_sign()` — no `recvWindow` parameter. Binance defaults to 5000ms. Should be explicitly set for tighter replay protection. (Previously noted in Binance-specific audit.) |
| S8 | models/ directory not gitignored | WEAK | Low | `win_predictor.py` saves trained model to `models/win_predictor.pkl`. This directory is not in `.gitignore` — ML model binary could be committed. Not a security risk but a repo hygiene issue. |

### 4. PRIVILEGED AREAS

| # | Finding | Status | Severity | Evidence |
|---|---------|--------|----------|----------|
| PR1 | Risk checks gate all order execution | PROVED | — | `main.py:560-570`: Every trade goes through `risk_mgr.can_open_trade()` (position count ≤ MAX_OPEN_POSITIONS) and `risk_mgr.validate_signal()` (field validation, direction/SL logic) before `trader.open_position()`. |
| PR2 | reduceOnly prevents accidental position opens | PROVED | — | `binance_trader.py:close_partial()` uses `reduceOnly=true`. Cannot accidentally open a new position via close. |
| PR3 | cancel_all_orders scope too broad | WEAK | Medium | `binance_trader.py:332`: `move_sl_to_breakeven()` calls `cancel_all_orders(symbol)` which cancels ALL open orders for that symbol on exchange, not just bot-created ones. Manual user orders get cancelled. (Previously noted.) |
| PR4 | Signal expiration doesn't close exchange position | WEAK | Medium | `tracker.py:586-593`: When a signal expires after 7 days, it marks status as EXPIRED but does NOT call `_execute_full_close()`. The position + SL order remain on Binance with no monitoring. SL provides downside protection but TP management stops. (Previously noted.) |
| PR5 | No startup reconciliation | WEAK | Medium | No `sync_with_exchange()` on bot startup. If bot crashes mid-trade, positions exist on Binance but aren't tracked locally. Tracker has no mechanism to discover orphaned positions. (Previously noted.) |

### 5. PERFORMANCE

| # | Finding | Status | Severity | Evidence |
|---|---------|--------|----------|----------|
| PF1 | API budget well within rate limits | PROVED | — | Per scan: ~100 symbols × 1 request/symbol = ~100 requests + 4 requests/trade × 20 max trades = ~180 requests. Binance limit: 1200 req/min. Scanner adds 80ms sleep between symbols (`scanner.py` line 98, `railway_server.py:252`). |
| PF2 | Exchange info cached 1 hour | PROVED | — | `binance_trader.py:122`: `_exchange_info_ttl = 3600`. `scanner.py:21`: `_cache_ttl = 3600`. Avoids redundant exchangeInfo calls. |
| PF3 | Market intel caching with TTLs | PROVED | — | `market_intel.py`: news=600s, calendar=3600s, token_events=1800s. Prevents excessive external API calls. |
| PF4 | WebSocket lock blocks HTTP calls | WEAK | Medium | `tracker.py:242-251`: `_evaluate_open_signals_locked()` holds `_ws_lock` while making HTTP requests to Binance (close_partial, move_sl_to_breakeven, each with 10s timeout). WebSocket message processing is blocked during these calls. Could cause message backup under high load. (Previously noted.) |
| PF5 | Frontend polling intervals reasonable | PROVED | — | Dashboard: 30s. Live trades: 30s with countdown. Trade history: 30s. Analytics: 30s. Market intel: 300s (5 min). All use `setInterval` with proper cleanup. |
| PF6 | Live-trades fetches Binance prices client-side | WEAK | Low | `live-trades/page.tsx:267-278`: `fetchBinancePrice()` makes individual REST calls to `api.binance.com/api/v3/ticker/price` per symbol from the browser. With 13 open positions, that's 13 requests every 30 seconds from the client. Should use the multi-symbol endpoint (`/api/v3/ticker/price` without params returns all) or backend WebSocket feed. |
| PF7 | No API rate limiting on server | WEAK | Medium | `api_server.py`: No rate limiting middleware. Combined with S1 (no auth), anyone can hammer the API endpoints unlimited. |

### 6. DEPLOYMENT

| # | Finding | Status | Severity | Evidence |
|---|---------|--------|----------|----------|
| D1 | Dockerfile correct | PROVED | — | `python:3.11-slim`, installs requirements, copies app, exposes 8001, runs `railway_server.py`. Proper layer caching with `COPY requirements.txt` before `COPY .`. |
| D2 | Procfile correct | PROVED | — | `web: python railway_server.py` — matches Dockerfile CMD. |
| D3 | .env validation with fallback defaults | PROVED | — | `config.py`: All numeric configs wrapped in try/except with positive-value checks and sane defaults (e.g. `TRADE_AMOUNT_USDT` defaults to 1.0, `MAX_OPEN_POSITIONS` defaults to 5). |
| D4 | AUTO_TRADING_ENABLED defaults to false | PROVED | — | `config.py:29-30`: `auto_trading_enabled = os.getenv('AUTO_TRADING_ENABLED', 'false').lower() == 'true'`. Safe default — trading won't activate without explicit opt-in. |
| D5 | CORS origins list includes dev + prod | PROVED | — | `api_server.py:37-43`: localhost:3000, localhost:3001, *.netlify.app, *.railway.app, and two specific Netlify domains. Covers development and production. |
| D6 | No health check endpoint | WEAK | Low | `api_server.py`: No `/health` or `/ready` endpoint. Railway/Docker healthchecks typically need one. The `/api/dashboard/stats` endpoint works as a proxy but is heavier than needed. |
| D7 | Frontend Next.js config not audited for export | N/A | — | Frontend deploys to Netlify as static export. `next.config.ts` not included in repo files read. API proxy rewrite only works in Next.js server mode, not static export — frontend likely uses direct API URL in production. |

### 7. JOBS / SCHEDULING

| # | Finding | Status | Severity | Evidence |
|---|---------|--------|----------|----------|
| J1 | Scheduler structure correct | PROVED | — | `main.py:619-635` / `railway_server.py:328-360`: 4H scan at :00/:04/:08/:12/:16/:20, 1H scan at :01 every hour, position monitor every 15 min, daily report at 23:55 UTC. All registered via `schedule` library. |
| J2 | Signal pipeline order correct | PROVED | — | `main.py:532-534`: Signal generated → `telegram.send_signal()` → `_auto_trade_signal()` (Binance) → `tracker.log_signal()`. Failure in auto-trade doesn't block signal logging (try/except at line 589). |
| J3 | WebSocket + REST fallback | PROVED | — | `tracker.py`: WebSocket connection to `wss://stream.binance.com:9443/stream` for real-time prices. REST fallback via `check_open_signals()` every 5 minutes. WebSocket reconnects on disconnect with exponential backoff. |
| J4 | Railway server missing auto-trade integration | WEAK | HIGH | `railway_server.py:268-282`: The `run_1h_scan()` function calls `telegram.send_signal(sig)` and `tracker.log_signal(sig)` but does NOT call `_auto_trade_signal()`. The Binance auto-trading integration added to `main.py` was NOT replicated in `railway_server.py`. **When deployed on Railway, auto-trading will silently not work.** |
| J5 | Macro event calendar is hardcoded | WEAK | Medium | `backtest_macro_events.py:54-210`: `MACRO_EVENTS_2025_2026` is a static dict of dates. The code comments say "estimated / projected" and "should fetch from a live calendar API in production". This will go stale after 2026. |
| J6 | Cooldown and circuit breaker implemented | PROVED | — | Backtest: 12-bar cooldown after each trade, circuit breaker suspends trading for 50 bars when drawdown exceeds 4R. Live: `tracker.has_recent_signal(symbol, minutes=30)` prevents re-entry. `tracker.is_on_cooldown(symbol)` checked before each signal. |

### 8. BUSINESS LOGIC

| # | Finding | Status | Severity | Evidence |
|---|---------|--------|----------|----------|
| B1 | RR calculation consistent across all 5 implementations | PROVED | — | Verified identical formulas in: `api_server.py:403-433`, `frontend/lib/utils.ts:23-64`, `reporter.py:34-65`, `backtest.py:359-387`, `signals.py:263-266`. All use: SL=-1, TP1=rr1*0.40, TP2=+rr2*0.30, TP3=+rr3*0.20, TP4=+rr_max*0.10, BREAKEVEN=sum of hit TPs. |
| B2 | BREAKEVEN calculation correctly checks tp_hit booleans | PROVED | — | All implementations check `tp1_hit`, `tp2_hit`, `tp3_hit`, `tp4_hit` for BREAKEVEN status. A TP2-then-breakeven trade correctly returns 1.20R (rr1*0.40 + rr2*0.30), not 0.60R. |
| B3 | TP skip bug in tracker.py | PROVED (FIXED) | — | Previously CRITICAL. Fixed in prior session: `tracker.py:634-678` now cumulatively closes skipped TPs and moves SL to breakeven on TP2/TP3 direct hits. |
| B4 | Signal quality score formula (v5) | PROVED | — | `signals.py:268-303`: Multi-factor scoring with RSI proximity to extremes, MACD histogram strength, volume ratio (log-scaled), ADX bands (0-25: low, 25-40: mid, 40+: strong). Properly normalized to 0-100 range. |
| B5 | Market regime filter correctly applied | PROVED | — | `main.py:520-528` / `railway_server.py:216-221`: BULL=LONGs only, BEAR=SHORTs only, NEUTRAL=skip all. BTC 4H regime detected via EMA21/55 cross + RSI vs threshold. |
| B6 | $1 minimum notional constraint | WEAK | Low | `TRADE_AMOUNT_USDT=1` × 10x leverage = $10 notional. Many Binance Futures pairs have MIN_NOTIONAL > $10 (e.g. BTCUSDT requires ~$100 at current prices). `binance_trader.py` handles this gracefully (returns 0.0 quantity, raises error), but many pairs will silently skip. Not a bug — just a constraint of $1 sizing. |
| B7 | PNL label misleading on live-trades | WEAK | Low | `live-trades/page.tsx:636`: Label says "PNL (10x Leveraged)" but the calculation at lines 196-198 computes `priceDiff / slDistance` which is R-multiples, not leveraged dollar PNL. The `pnlPercent` is also R-based (×100), not percentage of capital. Label should say "PNL (R-multiple)" or the calculation should account for leverage. |
| B8 | Backtest TP skip handling correct | PROVED | — | `backtest.py:284-300`: When price jumps past TP1 to TP2, `tps_hit` list is set to `['tp1', 'tp2']` (not just `['tp2']`). SL moves to breakeven. Consistent across all 4 backtest files. |
| B9 | Win rate excludes BREAKEVEN and EXPIRED | PROVED | — | All implementations: `win_rate = wins / (wins + losses) * 100`. BREAKEVEN and EXPIRED are neutral — not counted in denominator. Consistent across backend, frontend, and backtest. |

### 9. CODE QUALITY

| # | Finding | Status | Severity | Evidence |
|---|---------|--------|----------|----------|
| C1 | Error handling comprehensive in backend | PROVED | — | All Binance API calls wrapped in try/except with logging. Signal validation checks for NaN/inf values (`signals.py:304-313`). Config parsing has try/except with fallback defaults. Scanner handles missing candle data. Market intel handles aiohttp failures. |
| C2 | Frontend error states handled | PROVED | — | All 6 pages implement loading skeleton → error display → data render pattern. Uses isMounted guard to prevent state updates on unmounted components. Proper cleanup of intervals in useEffect return. |
| C3 | Type safety gap in live-trades | WEAK | Low | `live-trades/page.tsx:331-332`: `(trade as any).sl_original` — `eslint-disable` used to access `sl_original` which isn't in the `TradeDisplay` interface (line 19 has `sl_original?: number` but the cast happens on a different code path where it's accessing the Signal object). Should use proper type narrowing. |
| C4 | Empty catch blocks in analytics | WEAK | Low | `analytics/page.tsx:235`: `} catch {}` — empty catch block silently swallows date parsing errors. Should at minimum log or skip the entry explicitly. |
| C5 | Duplicate code in backtest files | WEAK | Low | 4 backtest files each implement identical `compute_indicators()` (~40 lines), `detect_signal()` (~30 lines), `simulate_trade()` (~120 lines), `_calculate_incremental_rr()` (~20 lines). ~840 total duplicated lines. Should extract a shared `BacktesterBase` class. |
| C6 | `risk_manager.can_open_trade()` returns untyped tuple | WEAK | Low | Returns `tuple` without generic type hint — should be `tuple[bool, str]`. Minor readability issue. (Previously noted.) |
| C7 | Private method access across modules | WEAK | Low | `tracker.py:779`: Calls `trader._round_quantity()` — accessing private method of `binance_trader.py`. Should be made public or wrapped. (Previously noted.) |
| C8 | CoinGecko icon mapping hardcoded | WEAK | Low | `live-trades/page.tsx:38-170`: 130+ coin IDs hardcoded. New coins won't have icons. Should use CoinGecko API's search endpoint or a dynamic icon service. |
| C9 | Consistent coding style | PROVED | — | Backend follows PEP 8 conventions. Frontend uses consistent React patterns (hooks, memoization). TypeScript interfaces match backend Pydantic models. |

---

## Summary by Severity

| Severity | Count | Issues |
|----------|-------|--------|
| **HIGH** | 2 | S1: API has zero authentication; J4: Railway server missing auto-trade integration |
| **MEDIUM** | 6 | A3: Railway duplicates main.py; PR3: cancel_all_orders scope; PR4: Expiry doesn't close position; PR5: No startup reconciliation; PF4: WebSocket lock blocks HTTP; PF7: No API rate limiting |
| **LOW** | 13 | P3: Unbounded dependency versions; P6: scikit-learn not in requirements; S5: CORS wildcard subdomains; S7: No recvWindow; S8: models/ not gitignored; PF6: Client-side Binance calls; D6: No health endpoint; J5: Hardcoded macro calendar; B6: $1 notional constraint; B7: PNL label misleading; C3: eslint-disable any cast; C4: Empty catch; C6: Untyped tuple |
| **LOW (structural)** | 3 | A5: Backtest code duplication; C5: Same duplication detail; C7: Private method access; C8: Hardcoded icon mapping |
| **PROVED (no issue)** | 24 | Architecture core, platform compat, security core (signing, secrets, no withdrawals), risk checks, API budget, caching, scheduler, signal pipeline, RR consistency, TP/SL math, error handling, frontend patterns |
| **N/A** | 1 | D7: Frontend export config |
| **BLOCKED** | 1 | Binance MIN_NOTIONAL verification — geo-restricted from this VM |

---

## Top 5 Priority Actions

1. **Add API authentication** (S1, HIGH) — Even read-only access exposes trade data. Add API key header check or JWT.
2. **Sync railway_server.py with main.py** (J4, HIGH) — Auto-trading doesn't work in Railway deployment. Either import from main.py or merge files.
3. **Add startup reconciliation** (PR5, MEDIUM) — On restart, sync tracker state with Binance positions.
4. **Fix signal expiry to close positions** (PR4, MEDIUM) — Expired signals should close the Binance position.
5. **Add API rate limiting** (PF7, MEDIUM) — Prevent abuse of unauthenticated endpoints.
