#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO"
python3 analysis/generate_market_history_summary.py

echo
echo "Prepared market context artifacts:"
echo "- analysis/market-history-summary.json"
echo "- tracking-table.md"
echo "- recent raw/*/quotes.json"
