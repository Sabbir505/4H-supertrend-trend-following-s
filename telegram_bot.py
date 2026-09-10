"""
Telegram Bot - Sends 4H Supertrend trend-ride entry/exit alerts, bot-health
error alerts, orphaned-position warnings and weekly performance digests.
"""

import requests
import time
import logging
from config import Config

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, config: Config, scanner=None, position_tracker=None):
        self.config = config
        self.token = config.telegram_token
        self.chat_id = config.telegram_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.scanner = scanner
        # Needed by the weekly digest to list open positions. The scanner
        # does NOT own the tracker (main.py wires them separately), so it
        # must be passed explicitly.
        self.position_tracker = position_tracker

    def send_message(self, text: str, parse_mode: str = 'HTML') -> bool:
        for attempt in range(3):
            try:
                url = f"{self.base_url}/sendMessage"
                payload = {
                    'chat_id': self.chat_id,
                    'text': text,
                }
                if parse_mode:
                    payload['parse_mode'] = parse_mode
                response = requests.post(url, json=payload, timeout=10)
                response.raise_for_status()
                return True
            except requests.exceptions.RequestException as e:
                wait_time = 0.5 * (2 ** attempt)
                logger.warning(f"Telegram send attempt {attempt+1} failed: {e}, retrying in {wait_time}s...")
                time.sleep(wait_time)
            except Exception as e:
                logger.error(f"Telegram send error (non-retryable): {e}")
                return False

        logger.error("All Telegram send attempts failed")
        return False

    def send_entry_alert(self, alert: dict, vp_note: str | None = None) -> bool:
        """4H Supertrend trend-ride entry alert with breadth-scaled risk.

        vp_note: appended when no virtual position was opened for this
        signal (capacity cap or position already open), so the alert isn't
        mistaken for a tracked position."""
        symbol = alert['symbol']
        direction = alert['direction']
        entry = alert['price']
        stop = alert.get('initial_stop')
        breadth = alert.get('breadth')
        risk = alert.get('risk_level', 'full')

        if direction == 'BUY':
            emoji = '\U0001f7e2'  # green circle
            label = 'LONG ENTRY'
            gate = f"flip bullish · close > EMA{self.config.ema_filter_period}"
        else:
            emoji = '\U0001f534'  # red circle
            label = 'SHORT ENTRY'
            gate = "flip bearish · BTC Supertrend bearish"

        from datetime import datetime
        try:
            dt = datetime.fromisoformat(alert.get('detected_at', ''))
            display_time = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            display_time = alert.get('detected_at', '')
        breadth_txt = (f"{breadth:.2f}" if isinstance(breadth, (int, float))
                       else "n/a")
        vp_line = (f"Virtual position: <code>{vp_note}</code>\n"
                   if vp_note else "")
        quality = alert.get('quality')
        quality_line = (f"Quality: <b>{quality}</b> — "
                        f"{alert.get('quality_reason', '')}\n" if quality else "")

        msg = (
            f"<b>{emoji} {label}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"<b>{symbol}</b> | {label}\n"
            f"Supertrend({self.config.supertrend_atr_period}, "
            f"{self.config.supertrend_multiplier}) {gate}\n"
            f"{quality_line}"
            f"\n"
            f"<b>Trade Plan</b>\n"
            f"Entry: <code>{entry}</code>\n"
            f"Initial Stop: <code>{stop}</code> "
            f"({self.config.initial_stop_atr_mult}×ATR · min 2%)\n"
            f"Exit: {self.config.trail_atr_mult}×ATR trail · opposite flip · "
            f"{self.config.time_stop_bars}-bar time stop\n"
            f"\n"
            f"<b>Position Risk</b>\n"
            f"Market breadth: <code>{breadth_txt}</code>\n"
            f"Risk level: <code>{risk.upper()}</code>"
            + (" (breadth below "
               f"{self.config.breadth_threshold})" if risk != 'full' else "") + "\n"
            + vp_line
            + "\n"
            f"Detected: {display_time}\n"
            f"\n"
            f"<i>Informational only — not financial advice.</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(msg, parse_mode='HTML')

    def send_exit_alert(self, trade: dict) -> bool:
        """Virtual position exit alert (stop/trail, flip, or time stop)."""
        symbol = trade['symbol']
        direction = trade['direction']
        reason = trade['exit_reason']
        net_r = trade.get('net_r', 0)
        gross_r = trade.get('gross_r', 0)

        emoji = '\U0001f7e2' if net_r > 0 else '\U0001f534'
        reason_label = {
            'stop': 'Stop / trail hit',
            'flip': 'Opposite Supertrend flip',
            'time': f"Time stop ({self.config.time_stop_bars} bars)",
        }.get(reason, reason)

        try:
            from datetime import datetime
            dt = datetime.fromisoformat(trade.get('exit_time', ''))
            display_time = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            display_time = trade.get('exit_time', '')

        bars = trade.get('bars_held')
        held_txt = (f"{bars} bars (~{round(bars * 4)}h)"
                    if isinstance(bars, (int, float)) else str(bars))
        msg = (
            f"<b>{emoji} EXIT — {direction}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"<b>{symbol}</b> closed\n"
            f"Entry: <code>{trade['entry']}</code>\n"
            f"Exit: <code>{trade['exit']}</code>\n"
            f"Reason: {reason_label}\n"
            f"Held: <code>{held_txt}</code>\n"
            f"\n"
            f"Result: <b>{net_r:+.2f}R net</b> ({gross_r:+.2f}R gross)\n"
            f"\n"
            f"Closed: {display_time}\n"
            f"\n"
            f"<i>Virtual position tracking — informational only.</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(msg, parse_mode='HTML')

    def send_startup_message(self):
        msg = f"""\U0001f680 <b>TradeEdge Scanner Started</b>

Connected to Binance
Scanning top 100 by volume + top 100 by market cap

Strategy (backtested round-4 final):
- 4H Supertrend({self.config.supertrend_atr_period}/{self.config.supertrend_multiplier}) trend-ride
- Longs: flip + close &gt; EMA{self.config.ema_filter_period}
- Shorts: flip + BTC Supertrend bearish
- {self.config.trail_atr_mult}×ATR trail · {self.config.initial_stop_atr_mult}×ATR initial stop · {self.config.time_stop_bars}-bar time stop
- Risk scaled by market breadth (full ≥ {self.config.breadth_threshold})

Schedule:
- 4H scan: every 4 hours at :05
- Weekly digest: Mondays 09:00 UTC

Alerts are informational only — not trade signals."""
        self.send_message(msg)

    def send_error_alert(self, context: str, error: Exception | str) -> bool:
        """Bot-health alert: a scheduled job failed. The process keeps
        running, but scans may be affected."""
        msg = (
            f"\u26a0\ufe0f <b>TradeEdge — Job Error</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"Context: <code>{context}</code>\n"
            f"Error: <code>{type(error).__name__}: {error}</code>\n"
            f"\n"
            f"Check bot.log for the full traceback.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(msg)

    def send_watchdog_alert(self, hours_stale: float) -> bool:
        """Alert that scans have stalled (heartbeat older than expected)."""
        msg = (
            f"\U0001f6a8 <b>TradeEdge — Scans Stalled</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"No successful 4H scan in <b>{hours_stale:.1f} hours</b>.\n"
            f"Expected cadence: every 4 hours.\n"
            f"\n"
            f"The process may be hung, rate-limited, or partially dead.\n"
            f"Check bot.log and restart if needed.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(msg)

    def send_orphan_alert(self, orphan: dict) -> bool:
        """Alert that an open position's symbol left the scan universe and
        is no longer being exit-checked."""
        msg = (
            f"\U0001f47b <b>Orphaned Position</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"<b>{orphan['symbol']}</b> {orphan['direction']}\n"
            f"Entry: <code>{orphan.get('entry')}</code>\n"
            f"Entered: {str(orphan.get('entry_time', ''))[:16]}\n"
            f"\n"
            f"Symbol hasn't appeared in the scan universe for "
            f"&gt;={self.config.orphan_alert_days} days, so trail/flip/time "
            f"exits can't be evaluated. It will resume if the symbol returns.\n"
            f"\n"
            f"<i>Consider closing it manually if you use these signals.</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(msg)

    def send_weekly_digest(self, trades: list) -> bool:
        """Weekly performance digest over closed virtual trades: last-7-day
        stats plus all-time totals (win rate, avg R, cumulative R)."""
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        def _dt(s):
            try:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            except (ValueError, TypeError, AttributeError):
                return None

        cutoff = now - timedelta(days=7)

        def stats(rows):
            if not rows:
                return None
            rs = [r.get("net_r", 0) or r.get("gross_r", 0) or 0 for r in rows]
            wins = [r for r in rs if r > 0]
            return {
                "n": len(rows),
                "win_rate": 100 * len(wins) / len(rows),
                "avg_r": sum(rs) / len(rs),
                "total_r": sum(rs),
                "best": max(rs),
                "worst": min(rs),
            }

        recent = [t for t in trades if (_dt(t.get("exit_time", "")) or now) >= cutoff]
        s7 = stats(recent)
        sall = stats(trades)
        if sall is None:
            logger.info("Weekly digest skipped: no closed trades yet")
            return False

        def line(s):
            return (
                f"Trades: <b>{s['n']}</b> · Win rate: <b>{s['win_rate']:.0f}%</b>\n"
                f"Avg: <b>{s['avg_r']:+.2f}R</b> · Total: <b>{s['total_r']:+.2f}R</b>\n"
                f"Best: <code>{s['best']:+.2f}R</code> · "
                f"Worst: <code>{s['worst']:+.2f}R</code>"
            )

        # ── Open positions with unrealized P&L ────────────────────────────────
        open_section = ""
        try:
            if self.position_tracker is not None:
                open_pos = self.position_tracker.get_open_positions()
            else:
                open_pos = []

            if open_pos:
                lines = []
                for o in open_pos:
                    sym = o.get("symbol", "?")
                    direction = str(o.get("direction", "?")).upper()
                    entry = o.get("entry")
                    current = o.get("current_price")
                    stop = o.get("current_stop") or o.get("initial_stop")
                    r_multiple = o.get("unrealized_r") or o.get("unrealized_pnl_r")

                    if r_multiple is None and entry and current and stop:
                        try:
                            risk = abs(float(entry) - float(stop))
                            if risk > 0:
                                # PositionTracker records BUY/SELL
                                direction_mult = 1 if direction in ("BUY", "LONG") else -1
                                r_multiple = (
                                    (float(current) - float(entry)) * direction_mult
                                ) / risk
                        except (ValueError, TypeError):
                            r_multiple = None

                    if (r_multiple or 0) > 0:
                        emoji = "🟢"
                    else:
                        emoji = "🔴"
                    pnl_txt = f"{r_multiple:+.2f}R" if r_multiple is not None else "n/a"
                    current_txt = f"<code>{current}</code>" if current else "n/a"
                    entry_txt = f"<code>{entry}</code>" if entry else "n/a"
                    lines.append(
                        f"{emoji} <b>{sym}</b> {direction} · {pnl_txt}\n"
                        f"   entry {entry_txt} · now {current_txt}"
                    )
                open_section = (
                    f"\n<b>Open positions ({len(open_pos)})</b>\n"
                    + "\n".join(lines) + "\n"
                )
        except Exception as e:
            logger.warning(f"Failed to render open positions: {e}")
            open_section = ""

        msg = (
            f"📊 <b>TradeEdge — Weekly Digest</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"\n"
            f"<b>Last 7 days</b>\n"
            f"{line(s7) if s7 else 'No trades closed this week.'}\n"
            f"\n"
            f"<b>All time</b>\n"
            f"{line(sall)}\n"
            f"{open_section}\n"
            f"Virtual positions — informational only.\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        return self.send_message(msg)