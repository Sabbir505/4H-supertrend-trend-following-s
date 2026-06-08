"""
Data Splitter - Split signals.json into year/month/week files
Run this once to migrate existing data
"""

import json
import os
from datetime import datetime
from collections import defaultdict

SIGNALS_FILE = "signals.json"
DATA_DIR = "data/signals"


def split_signals_by_date():
    """Split signals.json into separate files by year/month/week"""

    if not os.path.exists(SIGNALS_FILE):
        print("No signals.json found")
        return

    with open(SIGNALS_FILE, 'r', encoding='utf-8') as f:
        signals = json.load(f)

    print(f"Loaded {len(signals)} signals")

    # Group signals by year/month/week
    grouped = defaultdict(list)

    for sig in signals:
        fired_at = sig.get('fired_at')
        if not fired_at:
            # Put in "unknown" file
            grouped['unknown'] += [sig]
            continue

        try:
            dt = datetime.fromisoformat(fired_at)
            year = dt.year
            month = dt.month
            week = dt.isocalendar()[1]  # ISO week number

            key = f"{year}/{month}/week_{week}"
            grouped[key] += [sig]
        except Exception:
            grouped['unknown'] += [sig]

    # Save each group to separate file
    for key, sigs in grouped.items():
        # Create directory structure
        parts = key.split('/')
        dir_path = os.path.join(DATA_DIR, *parts[:-1])
        os.makedirs(dir_path, exist_ok=True)

        # Save file
        file_path = os.path.join(DATA_DIR, key + '.json')
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(sigs, f, indent=2)

        print(f"  Saved {len(sigs)} signals to {file_path}")

    # Create metadata file with summary
    metadata = {
        'split_at': datetime.utcnow().isoformat(),
        'total_signals': len(signals),
        'files': list(grouped.keys()),
        'years': sorted(set(k.split('/')[0] for k in grouped.keys() if k != 'unknown')),
    }

    with open(os.path.join(DATA_DIR, 'metadata.json'), 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"\nDone! Created {len(grouped)} files")
    print(f"Metadata saved to {DATA_DIR}/metadata.json")


def get_current_week_key():
    """Get the key for current week's data"""
    dt = datetime.utcnow()
    year = dt.year
    month = dt.month
    week = dt.isocalendar()[1]
    return f"{year}/{month}/week_{week}"


def load_recent_signals(weeks_back: int = 4) -> list:
    """Load signals from recent weeks only"""
    signals = []

    dt = datetime.utcnow()
    for i in range(weeks_back):
        # Calculate week going back
        week_dt = dt - timedelta(weeks=i)
        year = week_dt.year
        month = week_dt.month
        week = week_dt.isocalendar()[1]

        key = f"{year}/{month}/week_{week}"
        file_path = os.path.join(DATA_DIR, key + '.json')

        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                signals.extend(json.load(f))

    return signals


if __name__ == "__main__":
    from datetime import timedelta

    # Run split
    split_signals_by_date()

    # Test loading recent
    recent = load_recent_signals(4)
    print(f"\nTest: Loaded {len(recent)} signals from last 4 weeks")