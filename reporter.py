"""
Performance Reporter
- Reads signals.json and computes stats
- Sends daily report to Telegram at 00:00 UTC
"""

import json
import os
import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

SIGNALS_FILE = "signals.json"


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


class PerformanceReporter:
    def __init__(self, telegram):
        self.telegram = telegram

    def _load(self) -> list:
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
        signals = self._load()
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=24)

        # Filter to last 24H closed signals (exclude OPEN and EXPIRED from main stats)
        recent = [
            s for s in signals
            if s.get('closed_at') and
            datetime.fromisoformat(s['closed_at']) >= cutoff and
            s.get('status') not in ('OPEN',)
        ]

        all_open = [s for s in signals if s.get('status') == 'OPEN']

        if not recent:
            msg = (
                f"📊  <b>DAILY REPORT</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"\n"
                f"No closed signals in the last 24H.\n"
                f"🔍  Open signals watching:  {len(all_open)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            self.telegram.send_message(msg)
            return

        # ─── Stats Calculation ────────────────────────────────────────────
        total = len(recent)
        wins = [s for s in recent if self._is_win(s)]
        losses = [s for s in recent if self._is_loss(s)]
        neutrals = [s for s in recent if self._is_neutral(s)]
        partials = [s for s in recent if s.get('status') in ('TP1', 'TP2', 'TP3')]
        breakevens = [s for s in recent if s.get('status') == 'BREAKEVEN']

        win_count = len(wins)
        loss_count = len(losses)
        partial_count = len(partials)
        breakeven_count = len(breakevens)
        neutral_count = len(neutrals)

        # Win rate: wins / (wins + losses) * 100, excludes neutral
        win_rate = round((win_count / (win_count + loss_count)) * 100, 1) if (win_count + loss_count) > 0 else 0

        # Average RR on all positive outcomes (wins only, not breakeven)
        rr_values = [calc_signal_rr(s) for s in wins if calc_signal_rr(s) > 0]
        avg_rr = round(sum(rr_values) / len(rr_values), 2) if rr_values else 0

        # Total RR for the period
        total_rr = round(sum(calc_signal_rr(s) for s in recent), 2)

        # Best performing pair
        pair_wins = defaultdict(int)
        pair_total = defaultdict(int)
        for s in recent:
            pair_total[s['symbol']] += 1
            if self._is_win(s):
                pair_wins[s['symbol']] += 1

        best_pair = max(pair_wins, key=pair_wins.get) if pair_wins else 'N/A'
        best_pair_wins = pair_wins.get(best_pair, 0)

        # Strong vs Standard win rates
        strong = [s for s in recent if s.get('strength') == 'STRONG']
        standard = [s for s in recent if s.get('strength') == 'STANDARD']

        def wr(lst):
            if not lst:
                return 'N/A'
            w = sum(1 for s in lst if self._is_win(s))
            l = sum(1 for s in lst if self._is_loss(s))
            return f"{round((w / (w + l)) * 100, 1)}%  ({w}/{w + l})" if (w + l) > 0 else 'N/A'

        # TP level breakdown (count how many hit each TP)
        tp1_count = sum(1 for s in recent if s.get('tp1_hit'))
        tp2_count = sum(1 for s in recent if s.get('tp2_hit'))
        tp3_count = sum(1 for s in recent if s.get('tp3_hit'))
        tp4_count = sum(1 for s in recent if s.get('tp4_hit'))
        breakeven_closed_count = sum(1 for s in recent if s.get('status') == 'BREAKEVEN')

        # Avg time in trade
        times = [s.get('minutes_to_close') for s in recent if s.get('minutes_to_close')]
        avg_mins = round(sum(times) / len(times)) if times else 0
        if avg_mins < 60:
            avg_time_str = f"{avg_mins}m"
        else:
            avg_time_str = f"{avg_mins // 60}h {avg_mins % 60}m"

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

        msg = (
            f"📊  <b>DAILY PERFORMANCE REPORT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🗓   {now.strftime('%d %b %Y')}  •  Last 24H\n"
            f"\n"
            f"{perf_emoji}  <b>{perf_label}</b>\n"
            f"\n"
            f"┌─────────────────────────\n"
            f"│  Total Signals:    {total}\n"
            f"│  ✅  Winners:        {win_count}\n"
            f"│  ☑️   Partial (TP1-3): {partial_count}\n"
            f"│  🟡  Breakeven:     {breakeven_count}\n"
            f"│  ❌  Losers:         {loss_count}\n"
            f"│\n"
            f"│  Win Rate:         {win_rate}%\n"
            f"│  Avg RR (wins):    1:{avg_rr}\n"
            f"│  Total RR:         {total_rr}R\n"
            f"│  Avg Trade Time:  {avg_time_str}\n"
            f"└─────────────────────────\n"
            f"\n"
            f"🎯  <b>TP Breakdown</b>\n"
            f"   TP1 hit:  {tp1_count} / {total}\n"
            f"   TP2 hit:  {tp2_count} / {total}\n"
            f"   TP3 hit:  {tp3_count} / {total}\n"
            f"   TP4 hit:  {tp4_count} / {total}\n"
            f"   Breakeven exits: {breakeven_closed_count}\n"
            f"\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📶  <b>Signal Tier Performance</b>\n"
            f"   🔥 Strong:    {wr(strong)}\n"
            f"   ⚡ Standard:  {wr(standard)}\n"
            f"\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏆  Best Pair:  <b>{best_pair}</b>  ({best_pair_wins} wins)\n"
            f"🔍  Still open:  {len(all_open)} signals\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        self.telegram.send_message(msg)
        logger.info("Daily report sent.")

    def send_weekly_report(self):
        """Sends 7-day performance summary"""
        signals = self._load()
        now = datetime.utcnow()
        cutoff = now - timedelta(days=7)

        closed = [
            s for s in signals
            if s.get('closed_at') and
            datetime.fromisoformat(s['closed_at']) >= cutoff and
            s.get('status') not in ('OPEN',)
        ]

        if not closed:
            self.telegram.send_message("📊 <b>Weekly Report</b>\n\nNo closed signals in the last 7 days.")
            return

        total = len(closed)
        wins = [s for s in closed if self._is_win(s)]
        losses = [s for s in closed if self._is_loss(s)]
        neutrals = [s for s in closed if self._is_neutral(s)]
        partials = [s for s in closed if s.get('status') in ('TP1', 'TP2', 'TP3')]
        breakevens = [s for s in closed if s.get('status') == 'BREAKEVEN']

        win_count = len(wins)
        loss_count = len(losses)
        partial_count = len(partials)
        breakeven_count = len(breakevens)
        neutral_count = len(neutrals)

        # Win rate: wins / (wins + losses) * 100, excludes neutral
        win_rate = round((win_count / (win_count + loss_count)) * 100, 1) if (win_count + loss_count) > 0 else 0

        # Average RR on wins
        rr_values = [calc_signal_rr(s) for s in wins if calc_signal_rr(s) > 0]
        avg_rr = round(sum(rr_values) / len(rr_values), 2) if rr_values else 0

        # Total RR for the period
        total_rr = round(sum(calc_signal_rr(s) for s in closed), 2)

        # TP breakdown
        tp1_count = sum(1 for s in closed if s.get('tp1_hit'))
        tp2_count = sum(1 for s in closed if s.get('tp2_hit'))
        tp3_count = sum(1 for s in closed if s.get('tp3_hit'))
        tp4_count = sum(1 for s in closed if s.get('tp4_hit'))

        # Best pair overall
        pair_wins = defaultdict(int)
        for s in closed:
            if self._is_win(s):
                pair_wins[s['symbol']] += 1
        best_pair = max(pair_wins, key=pair_wins.get) if pair_wins else 'N/A'

        msg = (
            f"📈  <b>WEEKLY PERFORMANCE REPORT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🗓   Last 7 Days\n"
            f"\n"
            f"Total Signals:   {total}\n"
            f"✅  Winners:       {win_count}\n"
            f"☑️   Partial:       {partial_count}\n"
            f"🟡  Breakeven:     {breakeven_count}\n"
            f"❌  Losers:        {loss_count}\n"
            f"\n"
            f"Win Rate:        <b>{win_rate}%</b>\n"
            f"Avg RR (wins):  <b>1:{avg_rr}</b>\n"
            f"Total RR:        <b>{total_rr}R</b>\n"
            f"\n"
            f"🎯  <b>TP Breakdown</b>\n"
            f"   TP1 hit:  {tp1_count} / {total}\n"
            f"   TP2 hit:  {tp2_count} / {total}\n"
            f"   TP3 hit:  {tp3_count} / {total}\n"
            f"   TP4 hit:  {tp4_count} / {total}\n"
            f"\n"
            f"🏆  Best Pair:  <b>{best_pair}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )

        self.telegram.send_message(msg)
        logger.info("Weekly report sent.")
