#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
TRACKING_PATH = ROOT / 'tracking-table.md'
RAW_DIR = ROOT / 'raw'
ANALYSIS_DIR = ROOT / 'analysis'
OUTPUT_PATH = ANALYSIS_DIR / 'market-history-summary.json'
CUTOFF_DATE = os.environ.get('MARKET_HISTORY_CUTOFF_DATE')

CATEGORY_MAP = {
    'DDR5-6400': ['DDR5-6400 32GB', 'DDR5-6400 64GB', 'DDR5-6400 128GB'],
    'DDR5-5600': ['DDR5-5600 32GB', 'DDR5-5600 64GB', 'DDR5-5600 128GB'],
    'PCIe4 TLC': ['PCIe4 TLC 3.84TB', 'PCIe4 TLC 7.68TB', 'PCIe4 TLC 15.36TB', 'PCIe4 TLC 30.72TB'],
    'PCIe5 TLC': ['PCIe5 TLC 3.84TB', 'PCIe5 TLC 7.68TB', 'PCIe5 TLC 15.36TB', 'PCIe5 TLC 30.72TB'],
    'PCIe4 QLC': ['PCIe4 QLC 15.36TB', 'PCIe4 QLC 30.72TB', 'PCIe4 QLC 61.44TB', 'PCIe4 QLC 122.88TB'],
}


def parse_date(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def within_cutoff(value: str | None) -> bool:
    if not CUTOFF_DATE:
        return True
    parsed = parse_date(value)
    if not parsed:
        return False
    return parsed <= CUTOFF_DATE


def parse_tracking_table() -> list[dict[str, str]]:
    if not TRACKING_PATH.exists():
        return []

    lines = TRACKING_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()
    table_lines = [line for line in lines if line.startswith('|')]
    if len(table_lines) < 3:
        return []

    headers = [cell.strip() for cell in table_lines[0].strip('|').split('|')]
    rows: list[dict[str, str]] = []
    for line in table_lines[2:]:
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        if len(cells) != len(headers):
            continue
        row = dict(zip(headers, cells))
        if not within_cutoff(row.get('Date')):
            continue
        rows.append(row)
    return rows


def to_num(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped or stripped == 'NA':
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def category_summary(rows: list[dict[str, str]], category: str, cols: list[str]) -> dict:
    recent_rows = rows[-14:]
    latest = recent_rows[-1] if recent_rows else None
    previous = recent_rows[-2] if len(recent_rows) >= 2 else None

    series: dict[str, list[int]] = defaultdict(list)
    for row in recent_rows:
        for col in cols:
            value = to_num(row.get(col))
            if value is not None:
                series[col].append(value)

    latest_values = {col: to_num(latest.get(col) if latest else None) for col in cols}
    previous_values = {col: to_num(previous.get(col) if previous else None) for col in cols}

    filled_latest = sum(1 for col in cols if latest_values[col] is not None)
    filled_recent = [sum(1 for col in cols if to_num(row.get(col)) is not None) for row in recent_rows]
    avg_coverage = (sum(filled_recent) / len(filled_recent)) if filled_recent else 0.0

    change_signals: list[str] = []
    for col in cols:
        current_value = latest_values[col]
        previous_value = previous_values[col]
        if current_value is None or previous_value is None:
            continue
        if current_value > previous_value:
            change_signals.append('up')
        elif current_value < previous_value:
            change_signals.append('down')
        else:
            change_signals.append('flat')

    if not change_signals:
        trend = 'unknown'
    elif change_signals.count('up') > max(change_signals.count('down'), change_signals.count('flat')):
        trend = 'up'
    elif change_signals.count('down') > max(change_signals.count('up'), change_signals.count('flat')):
        trend = 'down'
    else:
        trend = 'flat_or_mixed'

    rolling_medians = {col: (int(median(values)) if values else None) for col, values in series.items()}

    latest_date = parse_date(latest.get('Date') if latest else None)
    per_column: dict[str, dict[str, object]] = {}
    missing_columns: list[str] = []
    for col in cols:
        last_seen_date = None
        consecutive_missing_days = 0
        for row in reversed(recent_rows):
            row_date = parse_date(row.get('Date'))
            row_value = to_num(row.get(col))
            if row_value is None:
                consecutive_missing_days += 1
                continue
            last_seen_date = row_date
            break
        if latest_values[col] is None:
            missing_columns.append(col)
        per_column[col] = {
            'latestValue': latest_values[col],
            'previousValue': previous_values[col],
            'rollingMedian14d': rolling_medians.get(col),
            'lastSeenDate': last_seen_date,
            'consecutiveMissingDays': consecutive_missing_days if latest_values[col] is None else 0,
        }

    return {
        'category': category,
        'latestDate': latest_date,
        'latestCoverage': {
            'filled': filled_latest,
            'total': len(cols),
        },
        'averageCoverage14d': round(avg_coverage, 2),
        'trend': trend,
        'latestValues': latest_values,
        'previousValues': previous_values,
        'rollingMedians14d': rolling_medians,
        'missingColumns': missing_columns,
        'columns': per_column,
    }


def latest_raw_run_notes() -> dict[str, list[str]]:
    notes: dict[str, list[str]] = {}
    if not RAW_DIR.exists():
        return notes

    candidate_dirs = sorted(path for path in RAW_DIR.iterdir() if path.is_dir())
    if CUTOFF_DATE:
        candidate_dirs = [path for path in candidate_dirs if within_cutoff(path.name)]
    latest_dirs = candidate_dirs[-7:]
    for day_dir in latest_dirs:
        quotes_path = day_dir / 'quotes.json'
        if not quotes_path.exists():
            continue
        try:
            payload = json.loads(quotes_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            continue
        notes[day_dir.name] = payload.get('run_notes', [])
    return notes


def main() -> int:
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    rows = parse_tracking_table()
    summary = {
        'generatedAt': datetime.now().isoformat(),
        'cutoffDate': CUTOFF_DATE,
        'trackingRows': len(rows),
        'categories': {
            category: category_summary(rows, category, cols)
            for category, cols in CATEGORY_MAP.items()
        },
        'recentRunNotes': latest_raw_run_notes(),
    }
    OUTPUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(OUTPUT_PATH)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
