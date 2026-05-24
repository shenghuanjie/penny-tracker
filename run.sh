#!/usr/bin/env bash
# E2E penny tracker pipeline.
#
# Steps:
#   1. Clean up TSV (remove old/duplicate entries)
#   2. Phase 1: collect deals from RebelSavings
#   3. Update HTML report + git push + wait for GitHub Pages
#   4. Phase 2: check HD prices (spread over 8 hours)
#   5. Update HTML report + git push
#
# Keeps Mac awake via caffeinate for the entire run.
#
# Usage:
#   ./run.sh            # full pipeline (~8 hours)
#   ./run.sh --skip1    # skip phase 1, start from phase 2
#
# For best anti-bot results, launch Chrome with remote debugging before running:
#   /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
#       --remote-debugging-port=9222 \
#       --user-data-dir="$HOME/Library/Application Support/Google/Chrome-Debug" \
#       --no-first-run --no-default-browser-check
# The script auto-detects Chrome on port 9222 and attaches to it.

set -uo pipefail
cd "$(dirname "$0")"

SKIP_PHASE1=false
if [[ "${1:-}" == "--skip1" ]]; then
    SKIP_PHASE1=true
fi

GIT_SSH="ssh -i ~/.ssh/id_rsa_public_github -o IdentitiesOnly=yes"

push() {
    echo ""
    echo "=== Updating HTML report and pushing ==="
    python rebelsavings.py -m report || echo "Report generation failed (non-fatal)"
    git add -A
    git commit -m "update data $(date '+%Y-%m-%d %H:%M')" || true
    GIT_SSH_COMMAND="$GIT_SSH" git push || echo "Git push failed (non-fatal)"
}

run_pipeline() {
    echo "============================================================"
    echo "  Penny Tracker — $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"

    # ── Step 1: Clean up TSV ──
    echo ""
    echo ">>> Cleaning up TSV (removing old/duplicate entries)"
    python rebelsavings.py -m clean || echo "Clean failed (non-fatal)"

    # ── Step 2: Phase 1 — collect from RebelSavings ──
    if [[ "$SKIP_PHASE1" == false ]]; then
        echo ""
        echo ">>> Phase 1: Collecting from RebelSavings"
        python rebelsavings.py --phase 1 || echo "Phase 1 failed (non-fatal)"
        push
        echo ""
        echo ">>> Waiting 30s for GitHub Pages to refresh..."
        sleep 30
    else
        echo ""
        echo ">>> Skipping Phase 1"
    fi

    # ── Step 3: Phase 2 — check HD prices (spread over 8 hours) ──
    echo ""
    echo ">>> Phase 2: Checking HD prices (spread over 8 hours)"
    python rebelsavings.py --phase 2 --recheck --hours 8 || echo "Phase 2 failed (non-fatal)"
    push

    echo ""
    echo "============================================================"
    echo "  Done — $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"
}

# Keep Mac awake for the entire run (prevent sleep).
# caffeinate -s prevents system sleep; -i prevents idle sleep.
# The process exits when run_pipeline finishes.
if command -v caffeinate &>/dev/null; then
    echo "☕ Keeping Mac awake via caffeinate..."
    caffeinate -si -w $$ &
    CAFF_PID=$!
    trap "kill $CAFF_PID 2>/dev/null" EXIT
fi

run_pipeline
