#!/usr/bin/env bash
# autodaily.sh -- run daily.sh at most once per day, safely, from a scheduler.
#
#   bash scripts/autodaily.sh          run it if today has not been done
#   bash scripts/autodaily.sh --force  run it regardless
#   bash scripts/autodaily.sh --status say what it would do, change nothing
#
# WHY
#
#   There is no cron entry, no systemd timer and no shell hook on this machine.
#   The log filenames say the same thing: 0714, 0733, 0735, 0753, 0900, 0906,
#   0914, 1017, 1252 -- and no 23rd and no 26th.  A scheduler fires at the same
#   minute every day and does not skip days.  daily.sh has been run by hand.
#
#   Cron inside WSL cannot fix that on its own: WSL is not always running, and
#   when it is shut down nothing inside it fires.  The scheduler has to live on
#   the Windows side and start WSL itself.  That means this script may be
#   called at odd times, twice, or on a machine that was asleep through the
#   scheduled hour -- so it has to be safe to call repeatedly.
#
#   It is.  A marker file records the last date that COMPLETED.  A second call
#   the same day does nothing and says so; a call after a missed day runs.
set -u
cd "$(dirname "$0")/.." || exit 1

MARK=".autodaily_last"
TODAY="$(date +%Y-%m-%d)"
FORCE=0
STATUS=0
# Schedule this HOURLY, not daily.  A daily task fires once, and if the machine
# is asleep or off at that minute the day is simply missed -- which is the
# failure being fixed.  Hourly plus the marker means "the first time this
# machine is awake today, do the day's work, then stop asking".  The hour guard
# keeps it from firing at 00:05 against a slate that has no data yet.
NOTBEFORE=7
while [ $# -gt 0 ]; do
  case "$1" in
    --force)      FORCE=1; shift ;;
    --status)     STATUS=1; shift ;;
    --not-before) NOTBEFORE="$2"; shift 2 ;;
    *) echo "unknown argument: $1"; exit 2 ;;
  esac
done
HOUR=$(date +%-H)

LAST="$(cat "$MARK" 2>/dev/null || echo none)"
if [ "$STATUS" = "1" ]; then
  echo "today        $TODAY"
  echo "last done    $LAST"
  echo "hour now     $HOUR (not before $NOTBEFORE)"
  if [ "$LAST" = "$TODAY" ]; then echo "would do     nothing, today is done"
  elif [ "$HOUR" -lt "$NOTBEFORE" ]; then echo "would do     nothing, too early"
  else echo "would do     run daily.sh"; fi
  exit 0
fi

if [ "$LAST" = "$TODAY" ] && [ "$FORCE" = "0" ]; then
  echo "$TODAY already done -- nothing to do.  Use --force to run anyway."
  exit 0
fi

if [ "$HOUR" -lt "$NOTBEFORE" ] && [ "$FORCE" = "0" ]; then
  echo "it is ${HOUR}:00 and the guard is ${NOTBEFORE}:00 -- too early, skipping."
  exit 0
fi

[ -f daily.sh ] || { echo "no daily.sh in $(pwd)"; exit 1; }
mkdir -p logs
LOG="logs/auto_${TODAY}_$(date +%H%M).log"
echo "running daily.sh -> $LOG"
if bash daily.sh >>"$LOG" 2>&1; then
  # only mark on success, so a failed morning is retried rather than skipped
  echo "$TODAY" > "$MARK"
  echo "daily.sh finished OK.  $TODAY marked done."
else
  rc=$?
  echo "daily.sh FAILED (exit $rc).  $TODAY NOT marked -- it will retry."
  echo "last 20 lines of $LOG:"
  tail -20 "$LOG"
  exit "$rc"
fi

# what the board actually got, so a silent partial is visible from the log
echo
echo "freshest inputs after the run:"
ls -lt savant_data.csv pitch_usage.csv pitch-arsenal-stats.csv \
       statcast_data.csv zonefit_barrels.csv 2>/dev/null \
  | awk '{print "   " $6, $7, $8, $9}'
echo "today's board:"
ls -lt boards/boards_"$TODAY".csv nk/boards/board_"$TODAY".csv 2>/dev/null \
  | awk '{print "   " $6, $7, $8, $9}' || echo "   NONE WRITTEN FOR $TODAY"
