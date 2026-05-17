#!/usr/bin/env bash
# E2E penny tracker pipeline.
#
# Steps:
#   1. Clean up TSV (remove old/duplicate entries)
#   2. Phase 1: collect deals from RebelSavings
#   3. Update HTML report + git push
#   4. Phase 2: check HD prices (random batch size 1-10)
#   5. Update HTML report + git push
#
# Usage:
#   ./run.sh            # full pipeline
#   ./run.sh --skip1    # skip phase 1, start from phase 2

set -euo pipefail
cd "$(dirname "$0")"

SKIP_PHASE1=false
if [[ "${1:-}" == "--skip1" ]]; then
    SKIP_PHASE1=true
fi

GIT_SSH="ssh -i ~/.ssh/id_rsa_public_github -o IdentitiesOnly=yes"

push() {
    echo ""
    echo "=== Updating HTML report and pushing ==="
    python rebelsavings.py -m report
    git add -A
    git commit -m "update data $(date '+%Y-%m-%d %H:%M')" || true
    GIT_SSH_COMMAND="$GIT_SSH" git push || echo "Git push failed (non-fatal)"
}

echo "============================================================"
echo "  Penny Tracker — $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"

# ── Step 1: Clean up TSV ──
echo ""
echo ">>> Cleaning up TSV (removing old/duplicate entries)"
python rebelsavings.py -m clean

# ── Step 2: Phase 1 — collect from RebelSavings ──
if [[ "$SKIP_PHASE1" == false ]]; then
    echo ""
    echo ">>> Phase 1: Collecting from RebelSavings"
    python rebelsavings.py --phase 1
    push
else
    echo ""
    echo ">>> Skipping Phase 1"
fi

# ── Step 3: Phase 2 — check HD prices ──
echo ""
echo ">>> Phase 2: Checking HD prices"
python rebelsavings.py --phase 2 --recheck
push

echo ""
echo "============================================================"
echo "  Done — $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================================"
