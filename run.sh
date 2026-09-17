#!/usr/bin/env bash
# E2E penny tracker pipeline.
#
# Steps:
#   1. Clean up TSV (remove old/duplicate entries)
#   2. Phase 1: collect deals from RebelSavings
#   3. Optionally collect Facebook group posts
#   4. Update HTML report + git push + wait for GitHub Pages
#   5. Phase 2: check all eligible HD candidates
#   6. Update HTML report + git push
#
# Keeps Mac awake via caffeinate for the entire run.
#
# Usage:
#   ./run.sh            # parallel collectors + all eligible HD checks over ~8 hours
#   ./run.sh --skip1    # skip phase 1, start from phase 2
#   ./run.sh --sequential   # collect both sources one at a time
#   ./run.sh --no-facebook  # collect RebelSavings only
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
SCRAPE_FACEBOOK=true
PARALLEL_COLLECTORS=true
RETRY_BLOCKED=false
MAX_HD_CHECKS=""
HD_HOURS=8

usage() {
    echo "Usage: ./run.sh [--skip1] [--sequential | --no-facebook] [--retry-blocked]"
    echo "                [--max-hd-checks N] [--hours N]"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip1) SKIP_PHASE1=true; shift ;;
        --facebook) SCRAPE_FACEBOOK=true; shift ;;
        --parallel) PARALLEL_COLLECTORS=true; SCRAPE_FACEBOOK=true; shift ;;
        --sequential) PARALLEL_COLLECTORS=false; shift ;;
        --no-facebook) SCRAPE_FACEBOOK=false; PARALLEL_COLLECTORS=false; shift ;;
        --retry-blocked) RETRY_BLOCKED=true; shift ;;
        --max-hd-checks)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            MAX_HD_CHECKS="$2"; shift 2 ;;
        --hours)
            [[ $# -ge 2 ]] || { usage; exit 2; }
            HD_HOURS="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
    esac
done

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

    # ── Steps 2-3: collect RebelSavings and optional Facebook data ──
    if [[ "$PARALLEL_COLLECTORS" == true && "$SKIP_PHASE1" == false ]]; then
        echo ""
        echo ">>> Collecting RebelSavings and Facebook in parallel"
        PENNY_TRACKER_ISOLATED_BROWSER=1 \
            python rebelsavings.py --phase 1 --no-chrome-profile &
        rebel_pid=$!
        PENNY_TRACKER_ISOLATED_BROWSER=1 \
            python fb_scraper.py --max-posts 30 --max-days 7 \
                --no-chrome-profile --no-manual-login &
        facebook_pid=$!

        rebel_exit=0
        facebook_exit=0
        wait "$rebel_pid" || rebel_exit=$?
        wait "$facebook_pid" || facebook_exit=$?
        if [[ "$rebel_exit" -ne 0 ]]; then
            echo "RebelSavings collection failed with exit $rebel_exit (non-fatal)"
        fi
        if [[ "$facebook_exit" -ne 0 ]]; then
            echo "Facebook collection failed with exit $facebook_exit (non-fatal)"
            echo ">>> Retrying Facebook with the existing Chrome profile"
            python fb_scraper.py --max-posts 30 --max-days 7 \
                --no-manual-login \
                || echo "Facebook profile retry failed (non-fatal)"
        fi
    else
        if [[ "$SKIP_PHASE1" == false ]]; then
            echo ""
            echo ">>> Phase 1: Collecting from RebelSavings"
            python rebelsavings.py --phase 1 || echo "Phase 1 failed (non-fatal)"
        else
            echo ""
            echo ">>> Skipping Phase 1"
        fi

        if [[ "$SCRAPE_FACEBOOK" == true ]]; then
            echo ""
            echo ">>> Collecting recent Facebook group posts"
            python fb_scraper.py --max-posts 30 --max-days 7 \
                || echo "Facebook collection failed (non-fatal)"
        fi
    fi

    if [[ "$SKIP_PHASE1" == false || "$SCRAPE_FACEBOOK" == true ]]; then
        push
        echo ""
        echo ">>> Waiting 30s for GitHub Pages to refresh..."
        sleep 30
    fi

    # ── Step 4: Phase 2 — check eligible HD items ──
    echo ""
    PHASE2_ARGS=(--phase 2 --hours "$HD_HOURS")
    if [[ -n "$MAX_HD_CHECKS" ]]; then
        echo ">>> Phase 2: Checking up to $MAX_HD_CHECKS recent HD items over $HD_HOURS hours"
        PHASE2_ARGS+=(--max-hd-checks "$MAX_HD_CHECKS")
    else
        echo ">>> Phase 2: Checking all eligible HD items over $HD_HOURS hours"
    fi
    if [[ "$RETRY_BLOCKED" == true ]]; then
        PHASE2_ARGS+=(--recheck)
    fi
    python rebelsavings.py "${PHASE2_ARGS[@]}" \
        || echo "Phase 2 failed (non-fatal)"
    push

    echo ""
    echo "============================================================"
    echo "  Done — $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================"
}

# Keep Mac awake for the entire run (prevent sleep).
# caffeinate -s prevents system sleep; -i prevents idle sleep.
# The process exits when run_pipeline finishes.
# First, clean up any stale caffeinate from previous interrupted runs.
pkill -f "caffeinate -si -w" 2>/dev/null || true
if command -v caffeinate &>/dev/null; then
    echo "☕ Keeping Mac awake via caffeinate..."
    caffeinate -si -w $$ &
    CAFF_PID=$!
fi

# Also keep the Mac awake with the LID CLOSED (caffeinate alone does not do
# this). `pmset -a disablesleep 1` disables sleep on all power sources even
# when the lid is shut. This needs sudo. We restore the setting on exit.
DISABLESLEEP_SET=false
# Optional password file for unattended sudo. SECURITY WARNING: storing your
# password in cleartext is risky. Lock it down: chmod 600 ~/.sudo_pass
SUDO_PASS_FILE="$HOME/.sudo_pass"

# Try pmset without opening a password prompt. This is required during cleanup
# because cleanup may be running in response to Ctrl+C.
_sudo_pmset_noninteractive() {
    sudo -n pmset "$@" 2>/dev/null \
        || { [[ -f "$SUDO_PASS_FILE" ]] \
             && sudo -S pmset "$@" < "$SUDO_PASS_FILE" 2>/dev/null; } \
        || return 1
}

if command -v pmset &>/dev/null; then
    echo "🔒 Disabling lid-close sleep..."
    if _sudo_pmset_noninteractive -a disablesleep 1; then
        DISABLESLEEP_SET=true
        echo "   > Lid-close sleep disabled. Mac stays awake with lid shut."
    else
        echo "ERROR: could not disable lid-close sleep non-interactively." >&2
        echo "Run 'sudo -v' before starting, or configure the protected credential file." >&2
        [[ -n "${CAFF_PID:-}" ]] && kill "$CAFF_PID" 2>/dev/null
        exit 1
    fi
else
    echo "ERROR: pmset is unavailable; cannot guarantee lid-close operation." >&2
    [[ -n "${CAFF_PID:-}" ]] && kill "$CAFF_PID" 2>/dev/null
    exit 1
fi

CLEANUP_DONE=false
cleanup() {
    exit_code=$?
    [[ "$CLEANUP_DONE" == true ]] && return
    CLEANUP_DONE=true
    trap - EXIT INT TERM

    # Stop caffeinate (this instance and any strays we started)
    [[ -n "${CAFF_PID:-}" ]] && kill "$CAFF_PID" 2>/dev/null
    pkill -f "caffeinate -si -w $$" 2>/dev/null || true

    # Restore lid-close sleep behavior
    if [[ "$DISABLESLEEP_SET" == true ]]; then
        echo ""
        echo "🔓 Restoring lid-close sleep setting..."
        if _sudo_pmset_noninteractive -a disablesleep 0; then
            echo "   > Lid-close sleep re-enabled."
        else
            echo "   > WARNING: cleanup cannot prompt for a password."
            echo "     Run manually: sudo pmset -a disablesleep 0"
        fi
    fi

    exit "$exit_code"
}

trap cleanup EXIT
trap 'echo ""; echo "Stopping..."; exit 130' INT
trap 'exit 143' TERM

run_pipeline
