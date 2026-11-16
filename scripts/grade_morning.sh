#!/usr/bin/env bash
# grade_morning.sh — the next-morning routine, all graders in one run.
# Run IN THE MORNING from anywhere:  bash scripts/grade_morning.sh
#
# Morning (not night) on purpose: West Coast games settle late, so grading at
# night turns final-but-unfetched legs into VOID-losses. Grades YESTERDAY.
# Each step soft-fails so one missing script doesn't abort the rest.

set -u
cd "$(dirname "$0")/.." || { echo "❌ repo root not found"; exit 1; }
source env/bin/activate || { echo "❌ could not activate venv 'env'"; exit 1; }

run () {  # run() <label> <script> [args...]
    local label="$1"; shift
    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo "▶ $label"
    echo "════════════════════════════════════════════════════════════"
    if [ -f "$1" ]; then
        python3 "$@" || echo "   ⚠️  $1 errored — continuing."
    else
        echo "   ⚠️  $1 not found — skipped."
    fi
}

run "1/6  grade generator slips -> slip_ledger.csv"      grade_slips.py
run "2/6  mark who homered into the snapshot"            grade_hr_snapshot.py
run "3/6  label full board hits/misses"                  grade_boards.py
run "4/6  HR pull head-to-head (+ append pull_ledger)"   grade_hr_pulls.py
run "5/6  HR postmortem: who/why + commonality"          hr_postmortem.py
run "6/6  CUMULATIVE pull verdict (pooled all nights)"   grade_hr_pulls.py --summary

echo ""
echo "✅ morning grade complete. paste the blocks back to review against the open"
echo "   threads. n is small until ~10-14 nights — read direction, not magnitude."

# --- generator scoreboard (auto-added) ---
echo ""; echo "================ GENERATOR SCOREBOARD ================"
python3 "boards/tracker.py"

# --- pairing monitor (auto-added): leg% vs slip WR vs independent baseline -> LIFT ---
echo ""; echo "================ PAIRING MONITOR ================"
python3 "boards/monitor_pairing.py"

# --- toggle grade (auto-added): every setting WITH vs WITHOUT + full toggle combinations ---
echo ""; echo "================ TOGGLE GRADE (conviction on/off + combos) ================"
python3 "boards/toggle_grade.py"

# --- engine accuracy (auto-added): GUY/GO/T2 vs actual homers + raw/confluence profile ---
echo ""; echo "================ ENGINE ACCURACY (GUY/GO/T2 vs who actually homered) ================"
python3 "boards/engine_accuracy.py"

# --- HR calibration refit (auto-added): re-fit hr_calibration.json on fresh graded outcomes ---
# so the Calibration tab + the applied hr_prob curve stay current instead of drifting stale.
echo ""; echo "================ HR CALIBRATION REFIT ================"
python3 "model/hr_calibration_fit.py"
