#!/usr/bin/env bash
# E2E penny tracker run.
#
# Flow (--phase both, the default):
#   1. Launch HD browser, warm up session (login if --hd-login)
#   2. Phase 1: collect deals from RebelSavings → update HTML → git push
#   3. Phase 2: check HD prices in batches → update HTML → git push
#
# Usage:
#   ./run.sh                              # full E2E, random batch size 1-10
#   ./run.sh --batch-size 3               # full E2E, fixed batch size
#   ./run.sh --phase 1                    # collection only, no HD
#   ./run.sh --phase 2 --recheck          # HD re-check blocked/error items
#   ./run.sh --hd-login                   # pause for manual HD login first
#   ./run.sh --remote-debug localhost:9222 # attach to running Chrome
#
# All arguments are forwarded to rebelsavings.py.

set -euo pipefail
cd "$(dirname "$0")"

echo "============================================================"
echo "  Penny Tracker — $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

python rebelsavings.py "$@"
