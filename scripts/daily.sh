#!/usr/bin/env bash

# NIKKO-QUIET: suppress pandas PerformanceWarning noise
export PYTHONWARNINGS=ignore
# daily.sh -- the whole morning, in order, with the refreshes actually wired in.
#
# WHY THIS EXISTS. Every refresh built tonight was handed over as "wire it into morning.sh" and
# never wired. That is exactly how savant_data reached 438 hours against a 72-hour limit while
# every power flag on the board quietly ran on 18-day-old numbers. A refresh that depends on
# somebody remembering is not a refresh.
#
# ORDER MATTERS -- AND YOUR SLIPS ARE FIRST.
#   0. YOUR SLIPS          -- last night's W/L and what each hitter did. SECONDS.
#   1. preflight           -- say out loud what is missing before anything runs on it
#   2. grade boards        -- board outcomes + the rebuilt feature history + backfills
#   3. refresh inputs      -- the slow part (~8-10 min: statcast pulls)
#   4. audit               -- catches a silently failed fetch THIS morning, not in three weeks
#   5. revalidate (Mon)    -- do the ladder cuts still hold? drift is silent otherwise
#   6. launch              -- build tonight's board from fresh inputs
#
# WHY THE SLIPS ARE FIRST, ABOVE EVERYTHING. They read pending_slips.csv and last night's
# results and NOTHING else -- not the boards, not zone_overlap, not the backfills. Anywhere
# below the top they sit behind build_zone_overlap (6+ min) and four backfills, so the one
# number you actually open the terminal for is the last thing to arrive. `bash daily.sh --slips`
# prints them in seconds and stops.
#
# --- 2026-08-10 rewrite -----------------------------------------------------------------------
#   * STEPS REPORT THEIR EXIT CODE. run() piped straight into tee, so $? was tee's status and
#     nothing looked at it anyway: a step could fail every morning for a month and the sequence
#     would print exactly the same thing. Now every step is OK / SKIP / FAIL with a duration and
#     a summary table at the end.
#   * A MISSING FILE IS LOUD. `[ -f x ] && run python3 x` is silent when x is absent, which is
#     indistinguishable from x running and doing nothing. Now it prints SKIP and names the path.
#   * THE SLIPS ARE GRADED. The loop below only ever found grade_boards.py -- which grades
#     BOARDS. grade_slips.py, which turns last night's slips into W/L, was never in here, and
#     neither was the morning slip report.
#   * THE ARSENAL CHAIN IS IN. fetch_arsenal / build_arsenal_v2 / build_pen_mix were never in
#     this file. The arsenal inputs read June 8 for the whole of July -- 25,804 FF PA stale
#     against 39,516 fresh -- and that is what killed mix_iso_blend.
#   * THE LOG IS WRITTEN ONCE. exec>tee at the top AND run()|tee meant every command's output
#     landed in the log twice.
#   * THE VERIFY CHECKLIST PRINTS ITSELF before launch, so the morning is one file.
#
# Run:  bash daily.sh              (full sequence)
#       bash daily.sh --slips      (JUST last night's slips -- seconds. Nothing else runs.)
#       bash daily.sh --grade-only (slips + board grading + backfills, no refreshes, no launch)
#       bash daily.sh --no-inputs  (NOTHING hits the network -- use if you already ran today)
#       bash daily.sh --zone       (force the 13-month zone rebuild even in a fast mode)
#       bash daily.sh --no-ui      (everything except launching the app -- for cron)
#       bash daily.sh --revalidate (force the weekly re-validation on any day)

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1   # repo root; this script lives in scripts/
source env/bin/activate 2>/dev/null || { echo "!! could not activate env/"; exit 1; }
NOUI=0; FORCEVAL=0; GRADEONLY=0; NOINPUTS=0; SLIPSONLY=0; FORCEZONE=0
for a in "$@"; do
  [ "$a" = "--no-ui" ]      && NOUI=1
  [ "$a" = "--revalidate" ] && FORCEVAL=1
  [ "$a" = "--grade-only" ] && GRADEONLY=1
  [ "$a" = "--no-inputs" ]  && NOINPUTS=1
  [ "$a" = "--slips" ]      && SLIPSONLY=1
  [ "$a" = "--zone" ]       && FORCEZONE=1
done
# NET is the single switch for "may this run hit the network". --no-inputs, --slips and
# --grade-only ALL mean "I already did the slow part today, do not do it again" -- and
# build_zone_overlap.py pulls THIRTEEN MONTHS of statcast, so leaving it outside this
# switch is how --no-inputs still cost 45 minutes.
NET=1
[ "$NOINPUTS" -eq 1 ] || [ "$SLIPSONLY" -eq 1 ] || [ "$GRADEONLY" -eq 1 ] && NET=0
[ "$FORCEZONE" -eq 1 ] && NET=1
STAMP=$(date +%Y-%m-%d_%H%M)
LOG="logs/daily_${STAMP}.log"
mkdir -p logs

exec > >(tee -a "$LOG") 2>&1

C_OK=$'\e[32m'; C_SK=$'\e[33m'; C_NO=$'\e[31m'; C_H=$'\e[1;36m'; C_0=$'\e[0m'
[ -t 1 ] || { C_OK=; C_SK=; C_NO=; C_H=; C_0=; }
SUMMARY=""; FAILED=0

say() { echo ""; printf '%s== %s ==%s\n' "$C_H" "$*" "$C_0"; }

# run <cmd...>  -- reports the exit code, which the old one could not: it piped into tee, so $?
# was tee's, and nothing read it. Output is NOT re-teed here; exec above already logs everything.
run() {
  local t0 rc dur label="$*"
  t0=$(date +%s)
  echo "\$ $*"
  "$@"
  rc=$?
  dur=$(( $(date +%s) - t0 ))
  if [ $rc -eq 0 ]; then
    printf '  %sOK%s    %ss\n' "$C_OK" "$C_0" "$dur"
    SUMMARY="${SUMMARY}OK|${label}|${dur}s\n"
  else
    printf '  %sFAIL%s  exit %s after %ss\n' "$C_NO" "$C_0" "$rc" "$dur"
    SUMMARY="${SUMMARY}FAIL|${label}|exit ${rc}\n"
    FAILED=$((FAILED+1))
  fi
  return 0
}

# runif <file> <cmd...>  -- the old `[ -f x ] && run ...` said NOTHING when x was missing, which
# looks exactly like x running and doing nothing. Say it.
runif() {
  local f="$1"; shift
  if [ -f "$f" ]; then run "$@"; else
    printf '  %sSKIP%s  %s not found\n' "$C_SK" "$C_0" "$f"
    SUMMARY="${SUMMARY}SKIP|$*|missing ${f}\n"
  fi
}

summary() {
  say "RUN SUMMARY"
  printf '%b' "$SUMMARY" | while IFS='|' read -r st lbl note; do
    [ -z "$st" ] && continue
    case "$st" in
      OK)   printf '  %sOK%s    %-52s %s\n' "$C_OK" "$C_0" "$lbl" "$note" ;;
      SKIP) printf '  %sSKIP%s  %-52s %s\n' "$C_SK" "$C_0" "$lbl" "$note" ;;
      *)    printf '  %sFAIL%s  %-52s %s\n' "$C_NO" "$C_0" "$lbl" "$note" ;;
    esac
  done
  [ "$FAILED" -gt 0 ] && printf '\n  %s%s step(s) FAILED -- read the log before you trust tonight'"'"'s board.%s\n' "$C_NO" "$FAILED" "$C_0"
  echo ""
  echo "log: $LOG"
}

echo "PRO-SYNC DAILY  $(date)"

# ── 0. YOUR SLIPS ───────────────────────────────────────────────────────────
# ABOVE EVERYTHING. grade_slips.py reads pending_slips.csv and last night's results;
# slipreport.py prints them W/L in colour with what each hitter actually did. Neither
# touches a board, a backfill or zone_overlap, so there is no reason for either to wait
# behind six minutes of build_zone_overlap. This is the number you open the terminal for.
say "0/6  YOUR SLIPS -- last night"
runif grade_slips.py python3 grade_slips.py
runif slipreport.py python3 slipreport.py

if [ "$SLIPSONLY" -eq 1 ]; then
  say "--slips: stopping here. Nothing else ran."
  summary
  exit $(( FAILED > 0 ))
fi

# ── 1. PREFLIGHT ────────────────────────────────────────────────────────────
# Everything below degrades QUIETLY when an input is missing -- a dead column just produces a
# flag that never fires, and a flag that never fires looks identical to a flag with no signal.
# Say it out loud here instead.
say "1/6  preflight"
if [ ! -f .env ]; then
  echo "!! .env missing -- ODDS_API_KEY is not set."
  echo "   implied_runs will be empty, which means ladder rung L3 CANNOT FIRE:"
  echo "   no TB -110 play, and the HR ladder caps at L2."
else
  KEYLEN=$(awk -F= '/ODDS_API_KEY/{print length($2)}' .env | tr -d '[:space:]')
  if [ -z "${KEYLEN:-}" ] || [ "${KEYLEN:-0}" -lt 30 ]; then
    echo "!! ODDS_API_KEY in .env looks wrong (length=${KEYLEN:-0}, expected 32)."
    echo "   Odds calls will 401 and implied_runs will stay empty."
  else
    echo "ok  .env present, key length ${KEYLEN}"
  fi
fi
# Each entry is a LABEL and the paths it might live at -- the first that exists wins. Reporting
# "absent" for a file that is simply somewhere else is worse than not checking at all.
_chk() {
  local lab="$1"; shift
  local f
  for f in "$@"; do
    if [ -f "$f" ]; then
      AGE=$(( ( $(date +%s) - $(stat -c %Y "$f") ) / 3600 ))
      if [ "$AGE" -gt 96 ]; then echo "!! $lab is ${AGE}h old  ($f)"
      else echo "ok  $lab (${AGE}h)"; fi
      return
    fi
  done
  echo "-- $lab NOT FOUND at: $*"
}
_chk savant_data  savant_data.csv boards/savant_data.csv
_chk zone_batter  zone_batter_v1.csv boards/zone_batter_v1.csv
_chk zone_pitcher zone_pitcher_v1.csv boards/zone_pitcher_v1.csv
_chk batterstats  boards/batterstats.csv batterstats.csv
_chk arsenal      arsenal_v2.csv boards/arsenal_v2.csv arsenal.csv
_chk pen_mix      pen_mix.csv boards/pen_mix.csv
_chk surge        surge_v1.csv boards/surge_v1.csv

# ── 2. GRADE THE BOARDS + REBUILD HISTORY ───────────────────────────────────
# Still ahead of the refreshes -- these read last night's saved board and last night's results
# and depend on none of them. But they are slower than the slips and they are not what you
# came for, so they sit behind phase 0.
say "2/6  grade last night's boards"

# BOARDS: which bats the board called, against what happened.
_GB=""
for g in grade_boards.py boards/grade_boards.py grade.py; do
  [ -f "$g" ] && { _GB="$g"; break; }
done
if [ -n "$_GB" ]; then run python3 "$_GB"; else
  printf '  %sSKIP%s  no grade_boards.py / boards/grade_boards.py / grade.py\n' "$C_SK" "$C_0"
  SUMMARY="${SUMMARY}SKIP|grade boards|no grader found\n"
fi

# graded_full_* = live features + outcomes. Without this, every measurement runs on the stripped
# export and half the engine's own signals are invisible to it.
run python3 boards/rebuild_graded.py
# ===================== NIKKO-DAILYWIRE =====================
# The record builds itself.  The backtest carries the amplifier scoreboard --
# the number that decides whether the amplifiers stay -- and the audit says how
# deep last night's homers actually sat.
if [ -f nikko.py ]; then
  run python3 nikko.py --backtest || true
  for _hrfile in hr.txt boards/hr_$(date -d yesterday +%Y-%m-%d).txt; do
    [ -f "$_hrfile" ] && { run python3 nikko.py --audit "$_hrfile" || true; break; }
  done
fi
# =================== end NIKKO-DAILYWIRE ===================
run python3 boards/fix_pitcher_join.py --apply
# NIKKO-DAILY-BACKFILL: rebuild_graded.py above rewrites every graded board from
# that night's live board, which DROPS any column added afterwards by a
# backfill. zone_overlap was on 3 of 30 boards this morning because of it.
# These re-apply the backfills so the graded history survives the rebuild.
# NIKKO-ZONEORDER the backfills below read zone_batter_v1.csv and
# NIKKO-ZONEORDER zone_pitcher_v1.csv. This build writes them. It used
# NIKKO-ZONEORDER to run in step 2, so every backfill read the copy from
# NIKKO-ZONEORDER the day before -- 1265 pitchers in, 1263 out.
# build_zone_overlap.py pulls statcast from LAST July to today -- 282 date chunks. It is not a
# daily job and it must never run behind a flag that says "skip the slow stuff". It runs when
# the zone files are missing or older than 3 days, and only when the network is allowed.
# pybaseball caches the pull, but ONLY if it is allowed to finish -- killing it loses the cache,
# so let it run once, alone, all the way through:  nohup python3 build_zone_overlap.py &
_ZAGE=999
for _zf in zone_batter_v1.csv boards/zone_batter_v1.csv; do
  [ -f "$_zf" ] && { _ZAGE=$(( ( $(date +%s) - $(stat -c %Y "$_zf") ) / 3600 )); break; }
done
if [ "$NET" -eq 0 ]; then
  printf '  %sSKIP%s  build_zone_overlap.py -- network off (--no-inputs/--slips/--grade-only). --zone forces it.\n' "$C_SK" "$C_0"
  SUMMARY="${SUMMARY}SKIP|build_zone_overlap.py|network off\n"
elif [ "$_ZAGE" -lt 72 ]; then
  printf '  %sSKIP%s  build_zone_overlap.py -- zone_batter_v1.csv is %sh old, under the 72h bar\n' "$C_SK" "$C_0" "$_ZAGE"
  SUMMARY="${SUMMARY}SKIP|build_zone_overlap.py|fresh (${_ZAGE}h)\n"
else
  echo "   build_zone_overlap: zone files are ${_ZAGE}h old. This is a 13-MONTH statcast pull."
  echo "   Ctrl-C loses the cache and you start over. Skip with --no-inputs if now is bad."
  runif build_zone_overlap.py python3 build_zone_overlap.py   # NIKKO-ZONEORDER
fi
run python3 boards/backfill_zone.py --apply
run python3 boards/backfill_pitcher.py --apply
run python3 boards/backfill_all.py --apply
run python3 boards/backfill_spot.py --apply
# rebuild_graded above wipes the arm-side fills the same way it wipes the
# others -- covfix belongs in this block, not in your head.
runif covfix.py python3 covfix.py --apply

if [ "$GRADEONLY" -eq 1 ]; then
  say "--grade-only: stopping here. Refreshes and launch skipped."
  summary
  exit $(( FAILED > 0 ))
fi

# ── 3. INPUT REFRESH ────────────────────────────────────────────────────────
# THE SLOW PART -- 8-10 minutes, mostly statcast pulls. Everything above is already on screen.
if [ "$NET" -eq 0 ]; then
  say "3/6  input refresh -- SKIPPED (network off)"
else
say "3/6  input refresh (the slow one -- statcast pulls)"
# Savant leaderboards are season-to-date; twice a week is plenty. Refresh only if the marker is
# older than 3 days, so running this every morning costs nothing.
# savant_data.csv is batter x pitch-type splits rebuilt from raw Statcast -- no leaderboard has
# it. min 15 pitches reproduces Savant's own qualifying bar (4,243 rows vs its 4,286). This feeds
# mix_iso_blend and the arsenal match, and was the stalest input on the system at 438h.
MARK=".last_savant_refresh"
# NIKKO-SAVANTDAILY: was -mtime +3 (four days); the board ran 3-5% of a season behind the raw cache
if [ ! -f "$MARK" ] || [ -n "$(find "$MARK" -mmin +720 2>/dev/null)" ]; then
  run python3 refresh_savant.py && touch "$MARK"
  run python3 build_savant_data.py --apply --min 15
else
  printf '  %sSKIP%s  savant refreshed within 12 h (delete %s to force)\n' "$C_SK" "$C_0" "$MARK"
  SUMMARY="${SUMMARY}SKIP|savant refresh|within 3 days\n"
fi

# ---- THE ARSENAL CHAIN. Never in this file until 2026-08-10. -------------------------------
# fetch_arsenal -> build_arsenal_v2 -> build_pen_mix. These were run by hand or not at all, so
# the arsenal inputs read June 8 for the whole of July: 25,804 FF PA against 39,516 fresh. That
# is what killed mix_iso_blend, which is a caller lane AND 2 of the 14 alignment pairs. It is a
# daily input by definition -- an arsenal that is not rebuilt daily is last month's arsenal.
runif fetch_arsenal.py python3 fetch_arsenal.py
runif build_arsenal_v2.py python3 build_arsenal_v2.py
runif build_pen_mix.py python3 build_pen_mix.py

# these are daily and cheap
runif refresh_all.sh bash refresh_all.sh
# build_surge.py writes surge_v1.csv (rolling ISO / HR-stripped SLG windows). It is a DAILY input
# by definition: a 7-day window that is not rebuilt daily is not a 7-day window. As of the
# NIKKO-SPINEFIX patch it also carries is_rusty, which the rust gate needs.
runif build_surge.py python3 build_surge.py

# these three were listed by daily_audit as "rebuild the automated ones" and were never wired in,
# which is why fb_pct_v1 and pitcher_contact_v1 keep showing up STALE every single morning.
runif boards/fetch_battedball.py python3 boards/fetch_battedball.py
runif build_missing_columns.py python3 build_missing_columns.py
runif build_recent_ev.py python3 build_recent_ev.py
fi

# ── 4. AUDIT ────────────────────────────────────────────────────────────────
# Runs BEFORE the board is built, so a stale input or a dropped column is visible while there is
# still time to do something about it.
say "4/6  health audit"
run python3 boards/daily_audit.py

# ── 5. WEEKLY RE-VALIDATION ─────────────────────────────────────────────────
# Mondays only. The ladder cuts (Zone p70, RecSLG p85, Vuln p85, Total p70) were measured on 14
# nights. As nights accumulate those cuts drift, and drift is SILENT -- the board keeps rendering
# the same tiers whether or not they still hold. This re-runs both ladders and files the numbers.
if [ "$FORCEVAL" -eq 1 ] || [ "$(date +%u)" = "1" ]; then
  say "5/6  weekly re-validation (ladder cuts)"
  VLOG="logs/validate_$(date +%Y-%m-%d).log"
  runif boards/flag_ladder.py python3 boards/flag_ladder.py
  runif boards/tb_ladder.py python3 boards/tb_ladder.py
  echo ""
  echo ">> READ THE HOLDOUT COLUMN. If L1/L2 lift has fallen toward 1.0 on the half the combo"
  echo ">> was NOT chosen from, the cuts have drifted and the ladder needs re-fitting."
else
  say "5/6  re-validation runs Mondays (force with: bash daily.sh --revalidate)"
fi

summary

# ── 6. LAUNCH ───────────────────────────────────────────────────────────────
if [ "$NOUI" -eq 1 ]; then
  say "6/6  --no-ui: skipping launch"
else
  say "6/6  launch"
  cat <<'VERIFY'

  READ THE TERMINAL after the first board builds. These lines are the difference
  between a patch being IN THE FILE and a patch having RUN.

    [export] all N wanted columns present
        the board now exports al14, the caller stack, pullfly_x_power and ev96.
        If al_* or hr_al14_n come back MISSING, display_df was not usable.

    [rust]  is_rusty on the board: yes -- N bat(s) flagged
        this gate had never fired before 08-10. If N is large, say so.

    [tb15]  batterstats joined on last_name, first_name -- xBA on ~95% of bats
    [chain] tb_df_gen 63 -> 63           the TB contact pool survives
    [probe] caller inputs live: 12 of 12  no dark columns
    [pairs] nk_align = bat x arm pairs    the diamonds count pairs
    [widen] TB refill: N bat(s) had NO sort value
    [tbgen] blend written back: N read(s)
    [LEG]   ... -> NONE (leg dropped)     a SHORT slip is the LOCK floor working
    [swallow] ...                         a bug report. Chase it the same day.

  NOT expected: [engine] BLOCK FAILED · MISSING: eng_xba · a chip reading
  "not in the current flag set".

VERIFY
# ===================== NIKKO-DAILYWIRE =====================
# Everything the new engine needs, before the UI comes up.  Writes all three
# market boards, exercises the slip rotation, and prints GO / NO-GO on whether
# the site can see them.  It never blocks the launch -- read the log.
if [ -f nightly.py ]; then
  run python3 nightly.py || true
fi
# =================== end NIKKO-DAILYWIRE ===================
  # NIKKO-DAILYWIRE-SITE: the board CSV is written by the render and every tool
  # downstream reads it, so repair it AFTER the fetches and BEFORE the
  # site comes up.  Safe to re-run: it only fills holes.
  python3 nk/asof.py --apply
  # ===================== NIKKO-LIVEASOF =====================
  # --apply ALONE stamps only the graded directory.  asof.py --help:
  #   "Without this the features only ever reach graded boards, and a
  #    read locked on them cannot fire on tonight's card."
  # That is what was happening.  Same board, same gates:
  #   without --board   0 of 403 bat(s) carried a read
  #   with    --board  48 of 403 bat(s) carried a read
  # This must stay ABOVE the readspanel stamp -- readspanel reads the
  # columns this writes.
  _NKL="boards/boards_$(date +%F).csv"
  if [ -f "$_NKL" ]; then
    python3 nk/asof.py --board "$_NKL" --apply || true
  else
    echo "[liveasof] no $_NKL -- the nine have no columns to gate on"
  fi
  # =================== end NIKKO-LIVEASOF ===================
  python3 nk/boardfix.py --apply
  # NIKKO-READSPANEL
  _NKB="boards/boards_$(date +%Y-%m-%d).csv"
  [ -f "$_NKB" ] || _NKB="$(ls -t boards/boards_*.csv 2>/dev/null | head -1)"
  if [ -n "$_NKB" ] && [ -f "$_NKB" ]; then
    python3 nk/readspanel.py --board "$_NKB" --stamp || true
  fi
  # NIKKO-READSPANEL-END
  # the site is newsite.py on 8502 (nk/golive.sh).  launch.sh serves
  # app.py on 8501 and kills every streamlit to do it, which takes 8502
  # down with it.  This line used to read: bash launch.sh
# ===================== NIKKO-DAYFIX =====================
# The site loader asks for nk/boards/board_<today>.csv and silently
# falls back to the NEWEST board on disk when it is missing -- which is
# why the page kept opening on yesterday's slate.  Build today's first.
python3 nk/board.py --date "$(date +%F)" \
  || echo "[dayfix] nk/board.py failed for $(date +%F) -- the site will fall back to the newest board on disk"
# =================== end NIKKO-DAYFIX ===================
  bash nk/golive.sh
fi
python3 nk/boardfix.py --apply
