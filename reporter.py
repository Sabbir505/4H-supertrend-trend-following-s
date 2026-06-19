"""
Performance Reporter
- Reads signals.json and computes stats
- Sends daily report to Telegram at 00:00 UTC
"""

import json
import os
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

SIGNALS_FILE = "signals.json"
DATA_DIR = Path("data/signals")


def _parse_closed_at(s: dict):
    """Parse closed_at string to timezone-aware datetime."""
    raw = s.get('closed_at')
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError):
        return None


def calc_signal_rr(s: dict) -> float:
    """Calculate realized RR for a signal (matches api_server.py and utils.ts)."""
    status = s.get('status', '')
    rr1 = s.get('rr1', 1.5)
    rr2 = s.get('rr2', 2.0)
    rr3 = s.get('rr3', 2.5)
    rr_max = s.get('rr_max', 3.0)

    if status == 'SL':
        return -1.0
    if status == 'EXPIRED':
        return 0.0
    if status == 'BREAKEVEN':
        total = 0.0
        if s.get('tp1_hit', False):
            total += rr1 * 0.40
        if s.get('tp2_hit', False):
            total += rr2 * 0.30
        if s.get('tp3_hit', False):
            total += rr3 * 0.20
        if s.get('tp4_hit', False):
            total += rr_max * 0.10
        return round(total, 2)
    if status == 'TP1':
        return round(rr1 * 0.40, 2)
    if status == 'TP2':
        return round(rr1 * 0.40 + rr2 * 0.30, 2)
    if status == 'TP3':
        return round(rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20, 2)
    if status in ('TP4', 'WIN'):
        return round(rr1 * 0.40 + rr2 * 0.30 + rr3 * 0.20 + rr_max * 0.10, 2)
    return 0.0


def _load_signals_from_data_dir() -> list:
    """Load all signals from the data/signals/ directory structure"""
    signals = []
    if not DATA_DIR.exists():
        return signals

    for year_dir in DATA_DIR.iterdir():
        if not year_dir.is_dir():
            continue
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir():
                continue
            for json_file in month_dir.glob("*.json"):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            signals.extend(data)
                except (json.JSONDecodeError, Exception):
                    continue

    return signals


class PerformanceReporter:
    def __init__(self, telegram):
        self.telegram = telegram
        self._last_daily_report_date = None
        self._last_weekly_report_date = None

    def _load(self) -> list:
        """Load signals from data directory or fallback to signals.json"""
        # Try data directory first (matches api_server.py)
        signals = _load_signals_from_data_dir()
        if signals:
            return signals
        # Fallback to legacy signals.json
        if not os.path.exists(SIGNALS_FILE):
            return []
        try:
            with open(SIGNALS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return []

    def _is_win(self, s: dict) -> bool:
        """A win is any signal that hit at least one TP (TP1-TP4 or WIN)."""
        return s.get('status') in ('TP1', 'TP2', 'TP3', 'TP4', 'WIN')

    def _is_loss(self, s: dict) -> bool:
        """A loss is only SL."""
        return s.get('status') == 'SL'

    def _is_neutral(self, s: dict) -> bool:
        """Neutral: BREAKEVEN or EXPIRED."""
        return s.get('status') in ('BREAKEVEN', 'EXPIRED')

    def send_daily_report(self):
        """Sends 24H performance summary to Telegram"""
        now = datetime.now(timezone.utc)
        today = now.strftime('%Y-%m-%d')

        # Prevent duplicate daily reports
        if self._last_daily_report_date == today:
            logger.info("Daily report already sent today, skipping duplicate.")
            return

        signals = self._load()
        cutoff = now - timedelta(hours=24)

        # Filter to last 24H fully closed signals (exclude OPEN, TP1, TP2, TP3 - partial closes)
        closed_statuses = ('TP4', 'SL', 'BREAKEVEN', 'EXPIRED', 'WIN')
        recent = [
            s for s in signals
            if (closed_dt := _parse_closed_at(s)) is not None and
            closed_dt >= cutoff and
            s.get('status') in closed_statuses
        ]

        if not recent:
            msg = (
                f"📊  <b>DAILY REPORT</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"\n"
                f"No closed signals in the last 24H.\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            self.telegram.send_message(msg)
            return

        # ─── Stats Calculation ────────────────────────────────────────────
        total = len(recent)
        wins = [s for s in recent if self._is_win(s)]
        losses = [s for s in recent if self._is_loss(s)]
        breakevens = [s for s in recent if s.get('status') == 'BREAKEVEN']

        win_count = len(wins)
        loss_count = len(losses)
        breakeven_count = len(breakevens)

        # Win rate: wins / (wins + losses) * 100, excludes neutral
        win_rate = round((win_count / (win_count + loss_count)) * 100, 1) if (win_count + loss_count) > 0 else 0

        # Total RR for the period
        total_rr = round(sum(calc_signal_rr(s) for s in recent), 2)

        # Overall emoji
        if win_rate >= 60:
            perf_emoji = '🟢'
            perf_label = 'Good day'
        elif win_rate >= 45:
            perf_emoji = '🟡'
            perf_label = 'Average day'
        else:
            perf_emoji = '🔴'
            perf_label = 'Tough day'

        # TP level breakdown (count how many hit each TP)
        tp1_count = sum(1 for s in recent if s.get('tp1_hit'))
        tp2_count = sum(1 for s in recent if s.get('tp2_hit'))
        tp3_count = sum(1 for s in recent if s.get('tp3_hit'))
        tp4_count = sum(1 for s in recent if s.get('tp4_hit'))

        msg = (
            f"📊  <b>DAILY PERFORMANCE REPORT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🗓   {now.strftime('%d %b %Y')}\n"
            f"\n"
            f"{perf_emoji}  <b>{perf_label}</b>\n"
            f"\n"
            f"┌─────────────────────────\n"
            f"│  Total Signals:    {total}\n"
            f"│  ✅  Winners:        {win_count}\n"
            f"│  🟡  Breakeven:     {breakeven_count}\n"
            f"│  ❌  Losers:         {loss_count}\n"
            f"│\n"
            f"│  Win Rate:         {win_rate}%\n"
            f"│  Total RR:         {total_rr}R\n"
            f"└─────────────────────────\n"
            f"\n"
            f"🎯  <b>TP Breakdown</b>\n"
            f"   TP1 hit:  {tp1_count}\n"
            f"   TP2 hit:  {tp2_count}\n"
            f"   TP3 hit:  {tp3_count}\n"
            f"   TP4 hit:  {tp4_count}\n"
            f"\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        self.telegram.send_message(msg)
        self._last_daily_report_date = today
        logger.info("Daily report sent.")

    def send_weekly_report(self):
        """Sends 7-day performance summary"""
        now = datetime.now(timezone.utc)
        week_key = now.strftime('%Y-W%U')

        # Prevent duplicate weekly report
        if self._last_weekly_report_date == week_key:
            logger.info("Weekly report already sent this week, skipping duplicate.")
            return

        signals = self._load()
        cutoff = now - timedelta(days=7)

        closed = [
            s for s in signals
            if (closed_dt := _parse_closed_at(s)) is not None and
            closed_dt >= cutoff and
            s.get('status') not in ('OPEN',)
        ]

        if not closed:
            self.telegram.send_message("📊 <b>Weekly Report</b>\n\nNo closed signals in the last 7 days.")
            return

        total = len(closed)
        wins = [s for s in closed if self._is_win(s)]
        losses = [s for s in closed if self._is_loss(s)]
        breakevens = [s for s in closed if s.get('status') == 'BREAKEVEN']

        win_count = len(wins)
        loss_count = len(losses)
        breakeven_count = len(breakevens)

        # Win rate: wins / (wins + losses) * 100, excludes neutral
        win_rate = round((win_count / (win_count + loss_count)) * 100, 1) if (win_count + loss_count) > 0 else 0

        # Total RR for the period
        total_rr = round(sum(calc_signal_rr(s) for s in closed), 2)

        # Overall emoji
        if win_rate >= 60:
            perf_emoji = '🟢'
            perf_label = 'Good week'
        elif win_rate >= 45:
            perf_emoji = '🟡'
            perf_label = 'Average week'
        else:
            perf_emoji = '🔴'
            perf_label = 'Tough week'

        # TP breakdown
        tp1_count = sum(1 for s in closed if s.get('tp1_hit'))
        tp2_count = sum(1 for s in closed if s.get('tp2_hit'))
        tp3_count = sum(1 for s in closed if s.get('tp3_hit'))
        tp4_count = sum(1 for s in closed if s.get('tp4_hit'))

        msg = (
            f"📈  <b>WEEKLY PERFORMANCE REPORT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🗓   Last 7 Days\n"
            f"\n"
            f"{perf_emoji}  <b>{perf_label}</b>\n"
            f"\n"
            f"┌─────────────────────────\n"
            f"│  Total Signals:    {total}\n"
            f"│  ✅  Winners:        {win_count}\n"
            f"│  🟡  Breakeven:     {breakeven_count}\n"
            f"│  ❌  Losers:         {loss_count}\n"
            f"│\n"
            f"│  Win Rate:         {win_rate}%\n"
            f"│  Total RR:         {total_rr}R\n"
            f"└─────────────────────────\n"
            f"\n"
            f"🎯  <b>TP Breakdown</b>\n"
            f"   TP1 hit:  {tp1_count}\n"
            f"   TP2 hit:  {tp2_count}\n"
            f"   TP3 hit:  {tp3_count}\n"
            f"   TP4 hit:  {tp4_count}\n"
            f"\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        self.telegram.send_message(msg)
        self._last_weekly_report_date = week_key
        logger.info("Weekly report sent.")
