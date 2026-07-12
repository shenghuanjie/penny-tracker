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

# Ensure the penny-tracker conda env is active (it has the deps:
# undetected_chromedriver, selenium, ...). Activate it if not already.
if [[ "${CONDA_DEFAULT_ENV:-}" != "penny-tracker" ]]; then
    echo "Activating conda env: penny-tracker"
    # Load conda's shell functions, then activate.
    if command -v conda &>/dev/null; then
        source "$(conda info --base)/etc/profile.d/conda.sh"
        conda activate penny-tracker || {
            echo "ERROR: could not activate conda env 'penny-tracker'" >&2
            exit 1
        }
    else
        echo "ERROR: conda not found in PATH" >&2
        exit 1
    fi
fi

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
fi

# Also keep the Mac awake with the LID CLOSED (caffeinate alone does not do
# this). `pmset -b disablesleep 1` disables sleep on battery even when the
# lid is shut. This needs sudo. We restore the original setting on exit.
DISABLESLEEP_SET=false
# Optional password file for unattended sudo. SECURITY WARNING: storing your
# password in cleartext is risky. Lock it down: chmod 600 ~/.sudo_pass
SUDO_PASS_FILE="$HOME/.sudo_pass"
if command -v pmset &>/dev/null; then
    echo "🔒 Disabling lid-close sleep (needs sudo)..."
    if sudo -n pmset -b disablesleep 1 2>/dev/null \
        || { [[ -f "$SUDO_PASS_FILE" ]] \
             && sudo -S pmset -b disablesleep 1 < "$SUDO_PASS_FILE" 2>/dev/null; } \
        || sudo pmset -b disablesleep 1; then
        DISABLESLEEP_SET=true
        echo "   > Lid-close sleep disabled. Mac stays awake with lid shut."
    else
        echo "   > Could not disable lid-close sleep (continuing anyway)."
    fi
fi

cleanup() {
    # Restore lid-close sleep behavior
    if [[ "$DISABLESLEEP_SET" == true ]]; then
        echo ""
        echo "🔓 Restoring lid-close sleep setting..."
        { sudo -n pmset -b disablesleep 0 2>/dev/null \
            || { [[ -f "$SUDO_PASS_FILE" ]] \
                 && sudo -S pmset -b disablesleep 0 < "$SUDO_PASS_FILE" 2>/dev/null; } \
            || sudo pmset -b disablesleep 0 2>/dev/null; } \
            && echo "   > Lid-close sleep re-enabled."
    fi
    # Stop caffeinate
    [[ -n "${CAFF_PID:-}" ]] && kill "$CAFF_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

run_pipeline
