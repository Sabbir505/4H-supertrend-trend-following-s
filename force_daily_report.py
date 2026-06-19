"""
Force-send today's daily report immediately.
Run this standalone script to bypass the scheduler.
"""

import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from config import Config
from telegram_bot import TelegramBot
from reporter import PerformanceReporter

def main():
    config = Config()
    if not config.validate():
        print("Config validation failed. Check your .env file.")
        sys.exit(1)

    telegram = TelegramBot(config)
    reporter = PerformanceReporter(telegram)

    # Bypass the duplicate-prevention guard
    reporter._last_daily_report_date = None

    print("Sending daily report...")
    reporter.send_daily_report()
    print("Done.")

if __name__ == "__main__":
    main()
