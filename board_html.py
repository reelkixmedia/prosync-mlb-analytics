"""
board_html.py -- the board, rendered as a real component.

    from board_html import board_html
    components.html(board_html(df, list(df.columns), max_rows=150, title="BOARD"),
                    height=720, scrolling=False)

DROP-IN REPLACEMENT. Same signature, same call sites, same contents -- app.py is untouched.
Only the renderer changes.

WHY THIS EXISTS
  st.dataframe paints to a <canvas>. No CSS ever reaches it, so the largest element on the
  page could be themed and never styled. This is real DOM.

WHAT IT DOES THAT THE OLD ONE DID NOT
  * click a row -> a drawer with every read as RAW VALUE + SLATE PERCENTILE side by side,
    grouped POWER / MATCHUP / THE ARM / CONTACT, with a bar showing where the bat sits in
    tonight's field. That is the part that lets a threshold be eyeballed instead of guessed.
  * gate rows carry a green rail and a bloom; ELITE bands glow gold
  * confirmations render as pips, not a number
  * filter, sort, and a stat strip that recomputes off the visible rows

COLUMN DETECTION
  app.py renames columns before calling this (show_tab's rename map runs first), so every
  lookup below accepts BOTH the display name and the raw one, and anything it cannot find
  is simply skipped. A board missing a column renders a smaller board, never an error.
"""
import html as _html
import json as _json

import numpy as np
import os
import pandas as pd

# ---------------------------------------------------------------- NIKKO-GAMEKEY
# The game tile was named with " @ ".join(sorted([_a, _b])) -- alphabetical, so a home
# game read as an away game whenever the away team sorted second.  This orders the pair
# AWAY @ HOME from MLB's schedule for the date (boards/game_side_v1.csv, written by
# nk/gamekey.py --stamp).  A pair it does not know comes back in the order it arrived,
# so the worst case is the alphabetical name this replaced -- never an invented one.
_GK_SIDE = {}
try:
    import os as _gk_os, csv as _gk_csv
    for _gk_try in ("boards/game_side_v1.csv",
                    _gk_os.path.join(_gk_os.path.dirname(_gk_os.path.abspath(__file__)),
                                     "boards", "game_side_v1.csv")):
        try:
            with open(_gk_try, encoding="utf-8") as _gk_f:
                for _gk_r in _gk_csv.DictReader(_gk_f):
                    _gk_a = str(_gk_r.get("away", "")).strip().upper()
                    _gk_h = str(_gk_r.get("home", "")).strip().upper()
                    if _gk_a and _gk_h:
                        _GK_SIDE[frozenset((_gk_a, _gk_h))] = _gk_a
            if _GK_SIDE:
                break
        except Exception:
            continue
except Exception:
    _GK_SIDE = {}


def _gk_order(_gk_x, _gk_y):
    """(away, home).  Unknown pair -> unchanged."""
    try:
        _gk_p, _gk_q = str(_gk_x).strip().upper(), str(_gk_y).strip().upper()
        _gk_w = _GK_SIDE.get(frozenset((_gk_p, _gk_q)))
        if _gk_w:
            return (_gk_x, _gk_y) if _gk_w == _gk_p else (_gk_y, _gk_x)
    except Exception:
        pass
    return (_gk_x, _gk_y)
# ---------------------------------------------------------------- end NIKKO-GAMEKEY

PAL = {"bg": "#07080b", "pn": "#0d0f14", "el": "#12151c", "ln": "#1c2029", "ln2": "#252b36",
       "tx": "#eef1f6", "dm": "#8d95a5", "mu": "#5a616f", "ac": "#4c8dff", "ac2": "#8b5cf6",
       "ok": "#22d17c", "hot": "#ffb020"}

# ===================== NIKKO-ALIGNDRAWER =====================
# Measured on 29 graded boards, 7,451 graded rows, base 11.2% HR. Per-night top
# decile of each column, graded, with odd/even nights as the overfit check.
#   'lift'  -> printed beside the number in green when >= 1.30
#   INVERT  -> the TOP decile finishes BELOW base, i.e. the bar has been pointing
#              the wrong way. Redrawn from the other end with a warning tag.
#   absent  -> under 8 nights of export coverage, or never exported at all. No bar
#              is drawn and the row reads 'unverified'. Not deleted -- labelled.
VERDICT = {}   # NIKKO-NOCHIPS: the per-read 29-night grade tags.
# Emptied, not deleted -- every reader is .get()-style so they
# simply stop rendering. The old table is in the backup.
INVERT = set()   # NIKKO-NOCHIPS: a 0.87x grade was flipping the bar
# while the printed percentile stayed raw, so sweet spot at p4 drew
# a near-full bar. Bar and number now say the same thing.
GRADED_NIGHTS = 29

# (display label, [candidate column names])
GROUPS = [
    # THE ALIGNMENT LEADS. This is the validated ladder core in the order it is
    # built -- zone p70 + recent xSLG p85 is L1 (19.3%, 1.73x), plus pitch vuln p85
    # is L2 (19.7%, 1.76x) -- followed by the rest of the reads the flag count
    # counts. Every entry here graded 1.22x or better on 29 nights. This group did
    # not exist before: the alignment was computed nightly and shown nowhere.
    # NIKKO-LAYOUT2: was "ALIGNMENT". Every read in it is a BAT read -- one half of a
    # pairing, under a heading that promises the pairing. The alignment is the band at the
    # top of the drawer, and it is now the only thing on the panel called that.
    ("THE BAT", [("Zone overlap", ["zone_overlap", "Zone", "Overlap"]),
                   ("Recent xSLG", ["r_xslg", "RecSLG"]),
                   ("Pitch vuln", ["pitch_vuln_score", "Vuln", "PVuln"]),
                   ("Barrel %", ["brl_percent", "BRL%", "brl%", "barrel_pct"]),
                   ("Loft match", ["hr_loft_match", "Loft"]),
                   ("Matchup z", ["hr_matchup_z", "Matchup", "Matchup-z"]),
                   ("Mix ISO", ["mix_iso_blend", "Mix"]),
                   ("Form delta", ["recent_iso_delta"])]),
    # the four reads above are NOT repeated below -- one number, one place.
    ("POWER", [("xISO", ["xiso", "xISO"]),
               # NIKKO-LANESIG: the HR anchor and its family, so a row click shows
               # the number the engine actually selected on.
               ("HH balls in play", ["nk_hh_bip"]),
               ("HH per game", ["nk_hh_g"]),
               ("HH count", ["nk_hh_n"]),
               ("Recent xISO", ["r_xiso", "rISO"]),
               ("xwOBA", ["xwoba", "xwOBA"]),
               ("Hard hit %", ["hard_hit_percent", "hard_hit_pct"]),
               ("EV50", ["ev50", "EV50"]),
               ("Bat speed", ["avg_bat_speed", "bat_speed"]),
               ("Pull-air", ["pull_air_rate", "pull_pct"]),
               ("Sweet spot %", ["sweet_spot_pct"]),
               ("Launch angle", ["avg_launch_ang", "LA"]),
               ("HR distance", ["avg_hr_distance"])]),
    # NIKKO-BOARDCOLS: SLG-FIT and ISO vs hand were on the eyeball export and not
    # here, which is the whole difference between the two boards. slgfit_arm is
    # the strongest sort measured on 52 nights for BOTH props; iso_hand_mult is
    # the partner in every depth pair that held. mix_iso_blend is the depth read.
    ("MATCHUP", [("SLG-FIT", ["slgfit_arm", "SLG-FIT"]),
                 # NIKKO-LANESIG: the bat half of SLG-FIT, gated on the bat having
                 # real data over half the arm's mix. The stronger of the two.
                 ("SLG-FIT bat", ["slgfit_bat"]),
                 ("Mix coverage", ["slg_fit_own"]),
                 # --- NIKKO-ISOSHOW: display only.  HR selects on this. ---
                 ("ISO-FIT", ["isofit_arm", "ISO-FIT"]),
                 ("SLG-fit raw", ["slg_fit"]),
                 ("ISO vs hand", ["iso_hand_mult", "ISO vs hand"]),
                 ("Mix ISO", ["mix_iso_blend", "mix_iso_sp"]),
                 ("Implied runs", ["implied_runs"]),
                 ("Arsenal match", ["hr_arsenal_match", "Arsenal"]),
                 ("Loc fit", ["loc_fit"]),
                 ("Platoon", ["platoon_mult"]),
                 ("Weather", ["weather_hr_mult", "weather"]),
                 ("Park", ["park_factor", "PF"]),
                 ("Zone EV", ["zone_fit", "ZoneEV (unval)"])]),
    ("THE ARM", [("HR per 9", ["p_hr_per_9", "P HR/9"]),
                 ("Weak arm", ["hr_weak_arm"]),
                 ("Worst pitch xSLG", ["worst_pitch_xslg"]),
                 ("Barrels allowed", ["p_brl_allowed", "P brl-allow"]),
                 ("K per 9", ["p_k_per_9", "P K/9"]),
                 ("xSLG allowed", ["p_xslg_allowed", "P xSLG-allow"]),
                 ("WHIP", ["p_whip", "P WHIP"]),
                 ("GB allowed", ["p_gb_allowed"]),
                 ("Pitcher form", ["p_form_m", "Form mult"]),
                 ("Pitcher lean", ["p_net_lean", "Net lean"]),
                 ("Bullpen HR/PA", ["pen_hr_per_pa", "Pen HR/PA"]),
                 ("Bullpen threat", ["pen_threat"])]),
    # NIKKO-BOARDCOLS: TB prob removed -- probabilities are out of selection and it
    # was still the first read on the column. tb_score is the xBA-led number the
    # TB engine uses. The rest were on the export and missing here.
    # NIKKO-HRRSHOW: the six terms hrr_score is built from, so the tier on the row
    # can be argued with. HRR is an OPPORTUNITY market -- how often a bat comes up,
    # how often it reaches, and whether there is an offense around it -- which is why
    # lineup slot is a first-class read here and never was for HR.
    # NIKKO-LANECOL: what the LANE column is built from, so the rank can be argued with.
    # ===================== NIKKO-GROUPFIX =====================
    # The recency lane. Every one of these is on the board CSV, three of them are
    # LEGS of live consensus gates, and not one of them had a bar anywhere on this
    # panel -- which is the whole difference between this drawer and the mobile
    # export. nk_prior_games is here because it is the denominator behind Own HR
    # rate: a bat with 4 prior games has no own rate and should not be read as if
    # it had one.
    ("RECENCY", [("HR last 3", ["nk_hr_l3"]),
                 ("HR last 5", ["nk_hr_l5"]),
                 ("HR last 7", ["nk_hr_l7"]),
                 ("TB last 3", ["nk_tb_l3"]),
                 ("TB last 5", ["nk_tb_l5"]),
                 ("2+TB no HR L3", ["nk_tb_noHR_l3"]),
                 ("Games since HR", ["nk_since_hr"]),
                 ("Hit streak", ["nk_streak"]),
                 ("Prior games", ["nk_prior_games"])]),
    # =================== end NIKKO-GROUPFIX ===================
    ("THE LANES", [("Lane score", ["nk_isolane"]),
                   ("ISO vs hand", ["iso_hand_mult"]),
                   ("ISO vs mix", ["mix_iso_blend", "mix_iso_sp"]),
                   ("Own HR rate", ["nk_own_hr"]),
                   ("Cold-power seat", ["nk_lowhr_n"]),
                   ("Longshot seat", ["nk_shot_n"])]),
    ("OPPORTUNITY / HRR", [("HRR score", ["hrr_score"]),
                           ("Exp PA", ["exp_pa"]),
                           ("Contact score", ["contact_score"]),
                           ("Implied runs", ["implied_runs"]),
                           ("Slot", ["batting_order"]),
                           ("xISO", ["xiso"]),
                           ("K %", ["k_percent"])]),
    ("CONTACT / TB", [("TB score", ["tb_score"]),
                      # NIKKO-LANESIG: the depth lane's inputs -- game context,
                      # which is what reaches board rank 101-250.
                      ("Park factor", ["park_factor"]),
                      ("Board rank", ["nk_board_rank"]),
                      ("Zone overlap", ["zone_overlap"]),
                      ("Pitch vuln", ["pitch_vuln_score"]),
                      ("LD rate", ["ld_rate", "ld_percent"]),
                      ("Recent xBA", ["r_xba"]),
                      ("Sleeper", ["sleeper_score", "Sleeper score"]),
                      ("Contact score", ["contact_score", "Contact"]),
                      ("Exp PA", ["exp_pa"]),
                      ("K %", ["k_percent"]),
                      ("xBA", ["xba", "xBA"]),
                      ("BABIP", ["babip"]),
                      ("Season BA", ["batting_avg", "actual BA"]),
                      ("Slot", ["batting_order"])]),
    # NIKKO-COMBOBOOK v1 -- written onto the board by combowire.py.  These are the frozen
    # per-tier combination rules: how many fired on this bat tonight, and
    # the fit rate of the strongest one that did.  Text companions
    # (nk_combo_badge / nk_combo_rules / nk_combo_best) are on the CSV too.
    # NIKKO-COMBOBOOK v2 -- upgraded from v1: adds the LOFT flag and VOL/SHARP/ALT.
    ("COMBO BOOK", [("Rules fired", ["nk_combo_n"]),
                    ("Best rule rate", ["nk_combo_rate"]),
                    ("LOFT flag", ["nk_lwf_n"]),
                    ("LOFT best rate", ["nk_lwf_rate"]),
                    ("VOL", ["nk_hr_vol"]),
                    ("SHARP", ["nk_hr_sharp"]),
                    ("ALT", ["nk_hr_alt"])]),
]
# every column that is NOT in GROUPS and not one of the spine columns still has to go
# somewhere -- it lands in ENGINE / CONTEXT. Nothing disappears just because it left the
# table; it moves into the drawer. That is the whole point of removing the horizontal scroll.
SKIP_DETAIL = {"name", "PLAYER", "Player", "BATTER", "team_abbrev", "TEAM", "Team",
               "opp_pitcher", "ARM", "PITCHER", "opponent", "TIER", "ps_band", "ps_tier",
               "tier", "hr_tier", "hr_edges", "SIGNALS", "hr_flags_new", "tb15_edges",
               "edges", "hr_gate_rank", "GATE", "hr_diamond", "hr_diamond2", "date",
               "player_id", "opp_pitcher_id",
               # the graded 0/1 outcomes -- present on graded_full CSVs, never on a live
               # board. Skipped so a graded file rendered through this never shows the
               # answer. NOTE: hit / single / double / ab are SEASON totals on this board
               # (ab runs 46-430), not tonight's line, so they stay visible.
               "hr_hit", "tb15_hit", "tb25_hit",
               # NIKKO-WHATALIGNS: consumed by the alignment band, not a display field.
               # hr_stack_pairs is a packed string and would render as a wall of text.
               "hr_stack_pairs", "hr_stack_n", "hr_stack_avail"}

NAME_C = ["name", "PLAYER", "Player", "BATTER"]
TEAM_C = ["team_abbrev", "TEAM", "Team"]
OPP_C = ["FACING", "opp_pitcher", "ARM", "PITCHER", "TONIGHT" + chr(39) + "S ARM", "opponent"]
TIER_C = ["TIER", "HR TIER", "ps_tier", "tier", "hr_tier", "ps_band"]
TBT_C = ["TB TIER", "tb_tier", "TB", "tb_band", "GRIND", "grind_tier"]
# NIKKO-HRRSHOW: 1.5 HRR = H + R + RBI > 1.5. Written by hrrboard.py.
HRR_C = ["HRR TIER", "hrr_tier", "HRR"]
# NIKKO-LANECOL: the lanes. nk_isolane_rk is the ISO lane rank (lanewire.py);
# nk_lowhr_n is the cold-power seat (deeplane.py); nk_shot_n is the market-longshot
# seat (shotlane.py). Seat 0 means "not in that pool tonight".
LANE_C = ["nk_isolane_rk", "LANE"]
LOW_C  = ["nk_lowhr_n"]
SHOT_C = ["nk_shot_n"]
BAND_C = ["BAND", "ps_cband", "cband", "CONF BAND"]
PROB_C = ["hr_prob", "HR %", "HR%", "tb_prob", "TB %", "slp_prob"]
FLAG_C = ["hr_edges", "SIGNALS", "hr_flags_new", "tb15_edges", "edges"]
CONF_C = ["hr_cband_n", "hr_align_n", "hr_edge_n", "N"]
GATE_C = ["hr_gate_rank", "GATE"]
DIA_C = ["hr_diamond", "hr_diamond2"]


def _pick(df, cands):
    """First candidate present. Kept for columns where presence is the whole test."""
    for c in cands:
        if c in df.columns:
            return c
    return None


def _pick_rich(df, cands, namelike=None):
    """First candidate that exists and carries data. Order means order.  # NIKKO-PICKORDER

    These lists are written in preference order -- hr_prob is first in PROB_C because
    hr_prob is what that slot wants. Scoring candidates by fill x text length overrode
    that every time and put slp_prob in the HR% column, because 0.168 has more characters
    than 0.25. Length was never a reason to prefer a column.

    The name slot is the exception and keeps its own test: a name has one to three
    spaces, is letters, 6-30 characters, and if none of the named candidates qualify it
    scans the whole frame rather than falling through to a team code.
    """
    import re as _re
    _NAMEISH = {"name", "batter", "player", "player_name", "batter_name",
                "full_name", "playername"}
    _PAT = _re.compile("^[A-Za-z\u00c0-\u024f][A-Za-z\u00c0-\u024f.' -]{4,29}$")
    if namelike is None:
        namelike = any(str(c).strip().lower() in _NAMEISH for c in cands)

    def _fill(c):
        if c not in df.columns:
            return 0.0, None
        v = df[c].astype(str).replace({"nan": "", "None": "", "<NA>": "", "-": ""})
        nz = v[v.str.len() > 0]
        return (float(len(nz)) / float(max(len(v), 1))), nz

    if namelike:
        def _looks(c):
            full, nz = _fill(c)
            if nz is None or not len(nz):
                return None
            ok = float(nz.str.match(_PAT).mean())
            sp = float(nz.str.count(" ").between(1, 3).mean())
            if ok < 0.7 or sp < 0.7:
                return None
            uq = float(nz.nunique()) / float(len(nz))
            return full * 100.0 + ok * 40.0 + uq * 30.0
        # A NAMED candidate wins outright. Scoring the whole frame alongside the list let
        # "Slug HardHit LowK-arm" -- letters, spaces, right length -- outscore the real
        # name column. The frame scan is a fallback for a renamed column, not a contest.
        for c in cands:
            if _looks(c) is not None:
                return c
        best, score = None, -1.0
        for c in df.columns:
            if c in cands:
                continue
            sc = _looks(c)
            if sc is not None and sc > score:
                best, score = c, sc
        if best is not None:
            return best
        # nothing looked like a name -- fall through to plain order below

    for c in cands:
        full, _nz = _fill(c)
        if full >= 0.5:
            return c
    for c in cands:                      # nothing well filled: take anything present
        if c in df.columns:
            return c
    return None


# ===================== NIKKO-SITEPCT =====================
# The full-slate ranking population, and the lookup that uses it.
def _sp_load():
    """The whole exported board -- the same file eyeball.py reads.  None if
    it is not there, in which case the caller keeps the old behaviour."""
    import glob as _g
    import datetime as _dt
    try:
        _t = _dt.date.today().isoformat()
        for _p in ("boards/boards_%s.csv" % _t, "boards/boards_%s_late.csv" % _t):
            if os.path.exists(_p):
                return pd.read_csv(_p, low_memory=False), _p
        _c = sorted(_g.glob("boards/boards_*.csv"), key=os.path.getmtime)
        if _c:
            return pd.read_csv(_c[-1], low_memory=False), _c[-1]
    except Exception:
        pass
    return None, None


def _sp_rank(vals, ref):
    """Percentile of each displayed value inside the full-slate distribution."""
    import numpy as _np
    _r = pd.to_numeric(ref, errors="coerce").dropna().values
    _r = _np.sort(_r)
    _v = pd.to_numeric(vals, errors="coerce").values
    _n = len(_r)
    _out = []
    for _x in _v:
        if _x != _x:
            _out.append(0)
        else:
            _out.append(int(round(100.0 * _np.searchsorted(_r, _x, side="right") / _n)))
    return _out
# =================== end NIKKO-SITEPCT ===================


# ===================== NIKKO-AGREEFLAG =====================
# The consensus set: gates that survived 2+ of the four walk-forward folds with
# positive own-lift.  (short label, long label, [ (column candidates, lo, hi) ]).
# The window is INCLUSIVE on both ends and is a slate percentile, not a raw cut.
AGREE_GATES = [
    ("L3-ARM", "hr L3 x weak arm x TB-no-HR L3",
     [(["nk_hr_l3"], 70, 90),
      (["hr_weak_arm", "p_hr_per_9"], 70, 90),
      (["nk_tb_noHR_l3"], 70, 90)]),
    ("L7-TB5", "hr L7 x TB L5",
     [(["nk_hr_l7"], 70, 90),
      (["nk_tb_l5"], 70, 90)]),
    ("FORM-ARS", "form delta x arsenal match",
     [(["recent_iso_delta"], 70, 90),
      (["hr_arsenal_match"], 40, 70)]),
    ("XBA-XHR", "xBA x arm xHR diff",
     [(["xba", "xBA"], 40, 70),
      (["p_xhr_diff"], 70, 90)]),
]
_AG_SUNP = 80          # slgfit_arm percentile the sun needs behind a single gate
# NIKKO-AGSHARE: the widest share of the slate one leg may name before the gate
# carrying it is treated as degenerate rather than selective. Live legs tonight run
# 14-31%; a constant column runs 100%. Nothing sits near this line.
_AG_MAXSHARE = 60.0
# NIKKO-AGFLOOR: the confirmer percentile a bat must clear before an agreement badge
# means anything. Below it the same gates run 5.00% against a 10.61% base -- they do
# not just stop working, they invert. p50 is the top-half split the main pool was
# always defined by, not a tuned number.
_AG_POOLP = 50

# ===================== NIKKO-SIGWIRE =====================
# The signal set. (chip label, family key, column candidates, lo, hi).  Every entry
# is one LEG of a consensus gate, in the window it was measured in -- so a row of
# chips reads as the union that named the bat, not as a list of retired pairings.
#   r = recency   a = arm   b = bat   m = matchup   x = confirmer
# ===================== NIKKO-PAIRSIG =====================
# The four surviving icon pairs. Each is a BAT read above its cut AND an ARM read
# above its cut, on this bat tonight -- not a single number.
# (label, family, bat col, bat pct, arm col, arm pct, arm is LOW-is-better)
# Re-measured on 56 graded nights against a 10.61% base, all four positive own-lift
# and holding in all four folds. The other eight from the reference panel have
# NEGATIVE own-lift -- they find bats that already homer -- and are deliberately not
# here. Zone is the strongest: 23.83%, 2.25x, own-lift +5.17, p=0.0000.
# NIKKO-SIGBAR: what each chip graded at, for the header band and the drawer rail.
# label -> (rate, lift, what it reads). Rate/lift only where the chip IS the measured
# object -- the four surviving pairs. A single-read leg is a COMPONENT of a gate and
# its own rate is not the gate's rate, so it carries its window and nothing else.
SIGMETA = {
    "Best90": ("", "", "best pitch x his bat, p90+"),
    "Zone":    ("23.8%", "2.25x", "zone overlap p94 x pitch vuln p94"),
    "Mix":     ("20.7%", "1.95x", "mix ISO p87 x arm xSLG allowed p87"),
    "xWOBA":   ("18.3%", "1.72x", "xwOBA p86 x pen xwOBA allowed p86"),
    "Contact": ("15.1%", "1.42x", "contact score p88 x K per 9 LOW p88"),
    "L3":      ("", "", "homers last 3 games, p70-90"),
    "L7":      ("", "", "homers last 7 games, p70-90"),
    "TB5":     ("", "", "total bases last 5, p70-90"),
    "TBnoHR":  ("", "", "2+ TB nights with no homer, last 3, p70-90"),
    "WeakArm": ("", "", "arm HR per 9, p70-90"),
    "xHRdiff": ("", "", "arm expected-HR differential, p70-90"),
    "Form":    ("", "", "recent ISO delta, p70-90"),
    "xBA":     ("", "", "xBA, p40-70"),
    "Arsenal": ("", "", "arsenal match, p40-70"),
    "SLG-FIT": ("", "", "the confirmer, p80+"),
    # NIKKO-READCHIPS
    "T1": ("31.1%", "2.92x", "TOP band \u00b7 3.1 a night \u00b7 3of4[EV7 g85, MIXISO g55, ARMSLG g85, DUE_EV g55]"),
    "T2": ("29.9%", "2.81x", "TOP band \u00b7 3.2 a night \u00b7 3of5[HARDxSLG g85, ATTACK g85, EV7 g85, ARMSLG g85, DUE_EV g55]"),
    "T3": ("26.9%", "2.53x", "TOP band \u00b7 5.0 a night \u00b7 3of5[EV7 g85, HRFB7 g85, MIXISO g55, ARMSLG g85, DUE_EV g55]"),
    "M1": ("25.5%", "2.40x", "MID band \u00b7 2.4 a night \u00b7 LAUNCH g70 x GROUNDED g70 + 1of3[EV g85, MIXISO g85, HRAIR g85]"),
    "M2": ("20.1%", "1.89x", "MID band \u00b7 6.9 a night \u00b7 (LAUNCH g70 x GROUNDED g70) OR (ATTACK g85 x SWEETxHARD g85)"),
    "M3": ("20.0%", "1.88x", "MID band \u00b7 6.9 a night \u00b7 (LAUNCH g70 x GROUNDED g70) OR (PULLxARM g70 x HARDxSLG g85)"),
    "D1": ("17.6%", "1.65x", "DEEP band \u00b7 3.6 a night \u00b7 4of5[MIXISO g85, NOGB g85, XSLG g85, LAUNCH g85, HARDxSLG g70]"),
    "D2": ("16.1%", "1.51x", "DEEP band \u00b7 5.8 a night \u00b7 3of4[MIXISO g85, NOGB g85, HARDxSLG g70, OWNHR g85]"),
    "D3": ("15.8%", "1.49x", "DEEP band \u00b7 6.1 a night \u00b7 3of4[NOGB g85, BARREL g85, HARDxSLG g70, FB g85]"),
}

# ===================== NIKKO-UNIONBAR =====================
# What each chip IS, in words, on the chip itself.  Every entry is
#   label -> (glyph, kind, what it reads, what it pairs with / why it is here)
# kind is the whole point of this table:
#   "u"  UNION -- a bat read AND an arm read, both clearing their cut, on this
#        bat tonight.  These are the four that survived re-measurement with
#        positive own-lift.  A union is the object that was graded, so it is the
#        only kind that carries a rate.
#   "l"  LEG   -- ONE read in ONE window.  It is a COMPONENT of a consensus
#        gate, not a call.  Its own rate is not the gate's rate and it is
#        deliberately not shown one.
#   "f"  FLOOR -- the confirmer.  Not a gate leg at all; it decides whether the
#        gates mean anything on this half of the board.
# The glyphs are the same ones the old flag table used for the same four reads,
# so a chip you recognised on an older board still reads as itself.
SIGX = {
 # ===================== NIKKO-LANESIG =====================
 # The measured engine. Every rate below is holdout / fit on 56 graded nights,
 # 40/15 split, and every object beats BOTH its legs alone on BOTH halves.
 "SHARP":  ("\U0001F3AF", "u",
            "hard-hit balls in play p95 \u00d7 the bat's own SLG vs this arm's mix p90",
            "The tightest HR object measured. 31.0% holdout, 21.4% fit, 3.9 a "
            "night, own-lift +15.5. slgfit_bat is NaN when the bat's own data "
            "covers under half the arm's mix, so a thin night can call none."),
 "VOL":    ("\U0001F525", "u",
            "hard-hit balls in play p80 \u00d7 the bat's own SLG vs this arm's mix p90",
            "The same pair, opened up. 25.1% holdout, 18.1% fit, 11.1 a night, "
            "own-lift +9.3 \u2014 the volume version of SHARP."),
 "ALT":    ("\U0001F500", "u",
            "hard-hit balls in play p80 \u00d7 ps_rank in its BOTTOM 5%",
            "ps_rank is a rank \u2014 1 is best \u2014 so its low end is the signal. "
            "25.6% holdout, 19.9% fit, 8.1 a night, own-lift +7.4. The one HR "
            "object that does not need slgfit_bat, so it survives a thin night."),
 "TBcore": ("\U0001F4CF", "u",
            "hard-hit balls in play p70 \u00d7 the arm's SLG allowed across its mix p80",
            "The TB engine. 51.0% holdout, 41.5% fit, 13.5 a night, own-lift "
            "+16.3. Three or more TB legs land on 100% of holdout nights."),
 "DEEPpk": ("\U0001F3DF", "u",
            "expected PA p85 \u00d7 park factor p70, board rank 101-250 only",
            "Depth is game context, not bat quality. 21.9% holdout, 15.8% fit, "
            "4.3 a night, own-lift +10.4 \u2014 against a 7.4% base for that band. "
            "The main score is bat and matchup reads, which is why it ranks "
            "these bats 150th."),
 "DEEPlf": ("\U0001F680", "u",
            "launch angle p85 \u00d7 implied runs p70, board rank 101-250 only",
            "19.4% on BOTH halves \u2014 the closest split of any object in this "
            "project. 2.4 a night, own-lift +7.1. Uppercut swing in a "
            "high-scoring game, at board rank 150."),
 "TBdeep": ("\U0001F30A", "u",
            "hard-hit per game p85, board rank 101-250 only",
            "39.3% holdout, 38.9% fit, 8 a night, against a 27.2% base for the "
            "band. The strongest depth signal in either market."),
 # =================== end NIKKO-LANESIG ===================
 "Zone":   ("\U0001F5FA", "u",
            "bat's zone overlap with where this arm lives p94 \u00d7 that arm's pitch vulnerability p94",
            "The bat swings where this arm works, and this arm is hittable there. "
            "23.8% over 214 calls, 2.25x the board, own-lift +5.17 \u2014 the strongest "
            "single object measured on 56 nights."),
 "Mix":    ("\U0001F9F2", "u",
            "bat's ISO against this arm's pitch mix p87 \u00d7 arm's xSLG allowed p87",
            "The bat punishes the pitches this arm actually throws, and the arm gives "
            "up slug. 20.7%, 1.95x, own-lift +2.87."),
 "xWOBA":  ("\U0001F4CA", "u",
            "bat xwOBA p86 \u00d7 the pen's xwOBA allowed p86",
            "Quality contact into a staff that surrenders it. 18.3%, 1.72x, own-lift +2.27."),
 "Contact":("\U0001F3AF", "u",
            "contact score p88 \u00d7 arm K per 9 LOW p88",
            "Bat puts it in play, arm cannot miss bats. 15.1%, 1.42x, own-lift +1.56 "
            "\u2014 the weakest of the four, and the one to drop first."),
 "L3":     ("", "l", "homers in the last 3 games, p70-90 of tonight's slate",
            "One leg of L3-ARM. Alone it is not a call \u2014 it needs WeakArm and "
            "TBnoHR beside it. p70-90 is one homer in three, not the hottest bat "
            "on the board."),
 "L7":     ("", "l", "homers in the last 7 games, p70-90",
            "One leg of L7-TB5. Pairs with TB5."),
 "TB5":    ("", "l", "total bases in the last 5 games, p70-90",
            "One leg of L7-TB5. Pairs with L7."),
 "TBnoHR": ("", "l", "2+ total-base nights with NO homer, last 3, p70-90",
            "One leg of L3-ARM. Damage the bat has not cashed \u2014 squaring it up "
            "without clearing the fence."),
 "WeakArm":("", "l", "arm HR allowed per 9, p70-90",
            "One leg of L3-ARM. Pairs with L3 and TBnoHR. Identical to p_hr_per_9 "
            "(rho 1.00) \u2014 the same read under two names."),
 "xHRdiff":("", "l", "arm expected-HR differential, p70-90",
            "One leg of XBA-XHR. Pairs with xBA."),
 "Form":   ("", "l", "recent ISO delta, p70-90",
            "One leg of FORM-ARS. Pairs with Arsenal."),
 "xBA":    ("", "l", "xBA, p40-70 \u2014 the MIDDLE of the slate",
            "One leg of XBA-XHR. The window is deliberate: the top of xBA is chalk "
            "and grades worse than its middle."),
 "Arsenal":("", "l", "arsenal match, p40-70 \u2014 middle of the slate",
            "One leg of FORM-ARS. Pairs with Form."),
 "SLG-FIT":("", "f", "the confirmer \u2014 slgfit_arm, p80+ tonight",
            "Not a gate leg and not a pair. This is the POOL FLOOR. Above the confirmer median, "
            "2+ gates run 20.9% (86 calls, p=0.002). Below it the same gates run "
            "5.0% against a 10.61% base \u2014 they invert, and the badge is withheld."),
 # ===================== NIKKO-READCHIPS =====================
 # kind 'g' -- a locked union.  Graded as ONE object, so it carries a
 # rate the way a pair does, but it is not a bat x arm pair and it is
 # not a component of anything.  Its own group in the band.
 "T1":("\U0001F451", "g",
       "3of4[EV7 g85, MIXISO g55, ARMSLG g85, DUE_EV g55]",
       "Locked 2026-09-01 and graded IN SAMPLE on 61 nights against a 10.64% board base -- the search that found it saw those nights, so this rate is a claim, not a record. python3 nk/bandhunt.py --grade is the forward test. TOP band, 3.1 bats a night. only 0, onlyHR 0.00 -- bandhunt prints this one as FULLY COVERED by the rest of the set. Every bat it calls, another read already called. It is on the board because it is locked, not because it has added anything."),
 "T2":("\U0001F4A5", "g",
       "3of5[HARDxSLG g85, ATTACK g85, EV7 g85, ARMSLG g85, DUE_EV g55]",
       "Locked 2026-09-01 and graded IN SAMPLE on 61 nights against a 10.64% board base -- the search that found it saw those nights, so this rate is a claim, not a record. python3 nk/bandhunt.py --grade is the forward test. TOP band, 3.2 bats a night. only 64 bat-nights, onlyHR 0.20 a night. A strict subset of T1 on 2026-09-01 -- it called three bats and all three were already T1's."),
 "T3":("\u26A1", "g",
       "3of5[EV7 g85, HRFB7 g85, MIXISO g55, ARMSLG g85, DUE_EV g55]",
       "Locked 2026-09-01 and graded IN SAMPLE on 61 nights against a 10.64% board base -- the search that found it saw those nights, so this rate is a claim, not a record. python3 nk/bandhunt.py --grade is the forward test. TOP band, 5.0 bats a night. only 100 bat-nights, onlyHR 0.31 a night. The widest of the three TOP reads and the one that carries the band."),
 "M1":("\U0001F388", "g",
       "LAUNCH g70 x GROUNDED g70 + 1of3[EV g85, MIXISO g85, HRAIR g85]",
       "Locked 2026-09-01 and graded IN SAMPLE on 61 nights against a 10.64% board base -- the search that found it saw those nights, so this rate is a claim, not a record. python3 nk/bandhunt.py --grade is the forward test. MID band, 2.4 bats a night. only 0, onlyHR 0.00 -- FULLY COVERED by the rest of the set. Shares the LAUNCH x GROUNDED core with M2 and M3 and adds nothing they do not."),
 "M2":("\U0001F3F9", "g",
       "(LAUNCH g70 x GROUNDED g70) OR (ATTACK g85 x SWEETxHARD g85)",
       "Locked 2026-09-01 and graded IN SAMPLE on 61 nights against a 10.64% board base -- the search that found it saw those nights, so this rate is a claim, not a record. python3 nk/bandhunt.py --grade is the forward test. MID band, 6.9 bats a night. only 170 bat-nights, onlyHR 0.52 a night -- tied for the most exclusive work in the set. A union: the OR is unreachable by any conjunction."),
 "M3":("\U0001F531", "g",
       "(LAUNCH g70 x GROUNDED g70) OR (PULLxARM g70 x HARDxSLG g85)",
       "Locked 2026-09-01 and graded IN SAMPLE on 61 nights against a 10.64% board base -- the search that found it saw those nights, so this rate is a claim, not a record. python3 nk/bandhunt.py --grade is the forward test. MID band, 6.9 bats a night. only 173 bat-nights, onlyHR 0.52 a night -- the most exclusive read in the set. On 2026-09-01 it called Tatis and Diaz, both homers, both bats no other read named."),
 "D1":("\U0001F48E", "g",
       "4of5[MIXISO g85, NOGB g85, XSLG g85, LAUNCH g85, HARDxSLG g70]",
       "Locked 2026-09-01 and graded IN SAMPLE on 61 nights against a 10.64% board base -- the search that found it saw those nights, so this rate is a claim, not a record. python3 nk/bandhunt.py --grade is the forward test. DEEP band, 3.6 bats a night. only 22 bat-nights, onlyHR 0.08 a night. The narrowest DEEP read; four of five gates is a hard ask and it mostly re-finds D2's bats."),
 "D2":("\U0001F9ED", "g",
       "3of4[MIXISO g85, NOGB g85, HARDxSLG g70, OWNHR g85]",
       "Locked 2026-09-01 and graded IN SAMPLE on 61 nights against a 10.64% board base -- the search that found it saw those nights, so this rate is a claim, not a record. python3 nk/bandhunt.py --grade is the forward test. DEEP band, 5.8 bats a night. only 118 bat-nights, onlyHR 0.30 a night. The widest read in the set -- 26 bats on 2026-09-01, twelve of them called by nothing else."),
 "D3":("\U0001F9E8", "g",
       "3of4[NOGB g85, BARREL g85, HARDxSLG g70, FB g85]",
       "Locked 2026-09-01 and graded IN SAMPLE on 61 nights against a 10.64% board base -- the search that found it saw those nights, so this rate is a claim, not a record. python3 nk/bandhunt.py --grade is the forward test. DEEP band, 6.1 bats a night. only 150 bat-nights, onlyHR 0.36 a night. The barrel route into DEEP; it is the only read carrying BARREL as a gate."),
 # NIKKO-READGLYPH: the nine carried the band marker, three glyphs across nine
 # reads, so two chips on one bat were the same triangle.  Each has
 # its own now.  The band is still the 'g' kind and the group.
 # =================== end NIKKO-READCHIPS ===================
}
# Two different objects were both "the union", which is the whole confusion:
#   a UNION is a consensus GATE -- 2 or 3 legs ANDed (L3-ARM is three).  The badge
#     counts unions, and it is what sets 2+.
#   a PAIR   is one bat read x one arm read on this bat tonight.  Graded as its own
#     object, carries its own rate, does NOT feed the badge.
# The band header says UNIONS because it heads the gate verdict.  The chips say
# PAIRS / LEGS because that is what a chip is.
_UBK = {"u": "PAIR", "l": "LEG", "f": "FLOOR"}
# =================== end NIKKO-UNIONBAR ===================

PAIR_READS = [
    ("Zone",    "p", ["zone_overlap"],   94, ["pitch_vuln_score"],    94, False),
    ("Mix",     "p", ["mix_iso_blend", "mix_iso_sp"], 87, ["p_xslg_allowed"], 87, False),
    ("xWOBA",   "p", ["xwoba"],          86, ["pen_xwoba_allowed"],   86, False),
    ("Contact", "p", ["contact_score"],  88, ["p_k_per_9"],           88, True),
    # NIKKO-LANESIG: the measured objects. Same mechanism, same cuts the engine
    # uses, so a chip here fires on exactly the bats nk_hr_pick promotes.
    ("SHARP",   "p", ["nk_hh_bip"],       95, ["slgfit_bat"],          90, False),
    ("VOL",     "p", ["nk_hh_bip"],       80, ["slgfit_bat"],          90, False),
    ("ALT",     "p", ["nk_hh_bip"],       80, ["ps_rank"],              5, True),
    ("TBcore",  "p", ["nk_hh_bip"],       70, ["arm_slg_mix"],         80, False),
]

# NIKKO-LANESIG: the depth objects. These need board rank 101-250, which this
# panel cannot compute, so they are read off the columns app.py writes rather
# than guessed at. (label, family, column) -- fires when the column is truthy.
FLAG_READS = [
    ("DEEPpk", "p", "nk_hr_deep1"),
    ("DEEPlf", "p", "nk_hr_deep2"),
    ("TBdeep", "p", "nk_tb_deep"),
    # NIKKO-READCHIPS: fires off the column readspanel.py --stamp writes.
    # No column, no chip -- never drawn as if it passed.
    ("T1", "p", "nk_read_T1"),
    ("T2", "p", "nk_read_T2"),
    ("T3", "p", "nk_read_T3"),
    ("M1", "p", "nk_read_M1"),
    ("M2", "p", "nk_read_M2"),
    ("M3", "p", "nk_read_M3"),
    ("D1", "p", "nk_read_D1"),
    ("D2", "p", "nk_read_D2"),
    ("D3", "p", "nk_read_D3"),
]
# =================== end NIKKO-PAIRSIG ===================

SIG_READS = [
    ("L3",      "r", ["nk_hr_l3"],          70, 90),
    ("L7",      "r", ["nk_hr_l7"],          70, 90),
    ("TB5",     "r", ["nk_tb_l5"],          70, 90),
    ("TBnoHR",  "r", ["nk_tb_noHR_l3"],     70, 90),
    ("WeakArm", "a", ["hr_weak_arm", "p_hr_per_9"], 70, 90),
    ("xHRdiff", "a", ["p_xhr_diff"],        70, 90),
    ("Form",    "b", ["recent_iso_delta"],  70, 90),
    ("xBA",     "b", ["xba", "xBA"],        40, 70),
    ("Arsenal", "m", ["hr_arsenal_match"],  40, 70),
    ("SLG-FIT", "x", ["slgfit_arm", "SLG-FIT"], 80, 100),
]
# =================== end NIKKO-SIGWIRE ===================


def _ag_norm(x):
    """NIKKO-AGPOOL: join key of last resort. Accents folded, case and punctuation
    dropped, so 'Andres Chaparro' and 'Andr\u00e9s Chaparro' are one bat."""
    import re as _re, unicodedata as _u
    s = _u.normalize("NFKD", str(x))
    s = "".join(ch for ch in s if not _u.combining(ch))
    return _re.sub(r"[^a-z ]", "", s.lower()).strip()


def _ag_rank(vals, ref):
    """NIKKO-AGSHARE: percentile with ties AVERAGED, not maximised.

    _sp_rank -- correct for the drawer bars, and untouched there -- uses
    searchsorted(side="right"), which puts every tied value at the TOP of its tie
    group. On a continuous read that is a rounding difference. On a count it is the
    whole answer: nk_hr_l3 is 0 for 181 of 226 bats, and side="right" ranks all 181
    of them at p80 -- inside p70-90 -- so a gate measured to name 17% of the slate
    named 81% of it instead.

    The gates were fitted on pandas rank(pct=True), which averages ties. This
    reproduces that: the midpoint of the tie group rather than its top. On nk_hr_l3
    the three groups land at p40 / p89 / p99, and p70-90 selects the 39 bats with
    exactly one homer in three games -- the read that was actually measured."""
    import numpy as _np
    _r = _np.sort(pd.to_numeric(ref, errors="coerce").dropna().values)
    _n = len(_r)
    if not _n:
        return None
    _out = []
    for _x in pd.to_numeric(vals, errors="coerce").values:
        if _x != _x:
            _out.append(0)
        else:
            _lo = _np.searchsorted(_r, _x, side="left")
            _hi = _np.searchsorted(_r, _x, side="right")
            # pandas rank(pct=True) is 1-indexed: avg rank = (lo + hi + 1) / 2.
            # The +1 is not cosmetic -- without it every percentile sits 0.5/n low and
            # a bat exactly on a window edge falls the wrong side of it, so the probe
            # and the board disagree by a name or two.
            _out.append(int(round(100.0 * (_lo + _hi + 1) / 2.0 / _n)))
    return _out


def _ag_pool(d, sp, cands):
    """NIKKO-AGPOOL: the read is not on the frame app.py handed in -- pull it from
    the full-slate CSV instead, per bat.

    This is the path every recency column takes. nk_hr_l3 and friends are built by
    walking GRADED boards in date order, which app.py does not have at render time,
    so they only ever exist on the CSV nkwire writes. _sp_pool IS that CSV -- it is
    already loaded, and it is already the reference every other percentile on this
    page is ranked against."""
    if sp is None:
        return None
    c = next((x for x in cands if x in sp.columns), None)
    if c is None:
        return None
    ref = pd.to_numeric(sp[c], errors="coerce")
    # NIKKO-AGSHARE: was nunique() < 5. Constant only -- the window-share check in
    # _build is what catches a read that is too wide to mean anything.
    if ref.notna().sum() < 8 or ref.dropna().nunique() < 2:
        return None
    vals = None
    for k in ("player_id", "batter_id"):
        if k in d.columns and k in sp.columns:
            m = (pd.Series(ref.values, index=pd.to_numeric(sp[k], errors="coerce"))
                 .groupby(level=0).first())
            vals = pd.to_numeric(d[k], errors="coerce").map(m)
            break
    if vals is None or vals.notna().sum() < 8:
        dn = _pick(d, NAME_C)
        sn = next((x for x in NAME_C if x in sp.columns), None)
        if dn is None or sn is None:
            return None
        m = (pd.Series(ref.values, index=sp[sn].map(_ag_norm))
             .groupby(level=0).first())
        vals = d[dn].map(_ag_norm).map(m)
    if vals.notna().sum() < 8:
        return None
    # a bat that is not in the pool comes back NaN; _ag_rank scores it 0, so no
    # window fires for it. Absent is absent -- it is not imputed to the median.
    return _ag_rank(vals, ref)


def _ag_series(d, df, sp, cands):
    """Slate percentile for one read, or None if the read cannot be trusted.

    None is returned when the column is absent from BOTH the handed-in frame and
    the full-slate pool, when fewer than 8 bats carry a value, or when the
    reference distribution has under 5 distinct values.  That last guard is the
    important one: a column that is constant (weather_hr_mult is 1 for half the
    board, pitch_vuln_score is modal -1) ranks every bat at p50, and a p40-70
    window on that read fires on the whole slate."""
    c = _pick(d, cands)
    if c is None:
        # NIKKO-AGPOOL: not on app.py's frame -- try the wired CSV before giving up.
        return _ag_pool(d, sp, cands)
    ref = None
    if sp is not None and c in sp.columns:
        _r = pd.to_numeric(sp[c], errors="coerce")
        if _r.notna().sum() >= 8:
            ref = _r
    if ref is None:
        _r = pd.to_numeric(df[c], errors="coerce")
        if _r.notna().sum() < 8:
            return None
        ref = _r
    # NIKKO-AGSHARE: was nunique() < 5, which threw away legitimate count columns
    # (nk_hr_l3 has three values because a bat hits 0, 1 or 2 in three games).
    # Constant only; width is judged per WINDOW in _build.
    if ref.dropna().nunique() < 2:
        return None
    return _ag_rank(_num(d, c), ref)
# =================== end NIKKO-AGREEFLAG ===================


def _lncol(col, d, i):
    """NIKKO-LANECOL: a lane rank or seat as an int, or 0 when absent.

    Seat 0 and NaN both mean the bat is not in that pool tonight. Returning 0 for
    both lets the renderer drop the badge entirely instead of printing 'LOW 0',
    which is the same nan-renders-as-text bug the BAND column had."""
    if not col:
        return 0
    try:
        v = pd.to_numeric(d[col], errors="coerce").iloc[i]
    except Exception:
        return 0
    return int(v) if v == v and v > 0 else 0


def _num(df, c):
    return pd.to_numeric(df[c], errors="coerce")


def board_html(df, columns=None, max_rows=150, title="BOARD"):
    try:
        return _build(df, max_rows, title)
    except Exception as e:            # never take the page down over a renderer
        return ("<div style='color:#ff6b6b;font:13px system-ui;padding:12px'>"
                "board component error: %s</div>" % _html.escape(str(e)))


def _build(df, max_rows, title):
    d = df.head(int(max_rows)).copy().reset_index(drop=True)
    n_all = len(df)
    _sp_pool, _sp_note = _sp_load()   # NIKKO-SITEPCT: full-slate ranking population
    if _sp_pool is not None:
        try:
            print("[board_html] percentiles ranked against %s (%d bats), not the "
                  "%d handed in" % (_sp_note, len(_sp_pool), len(df)))
        except Exception:
            pass

    cn, ct, co = _pick_rich(d, NAME_C), _pick_rich(d, TEAM_C), _pick_rich(d, OPP_C)
    # NIKKO-HOMETAG: which park this bat is in tonight, appended to the team string the
    # band, the TEAM column and the search box all read.  Written by nk/homeaway.py.
    _hmc = next((_c for _c in ("home_away", "is_home", "home_or_away") if _c in d.columns
                 and d[_c].notna().any()), None)

    def _hmtag(_i4):
        if not _hmc:
            return ""
        _v4 = d[_hmc].iloc[_i4]
        if _v4 != _v4 or _v4 is None:
            return ""
        if isinstance(_v4, (bool, int, float)):
            return " HOME" if float(_v4) == 1 else (" AWAY" if float(_v4) == 0 else "")
        _s4 = str(_v4).strip().upper()
        if not _s4 or _s4 in ("NAN", "NONE", "NA", "-"):
            return ""
        if _s4.startswith("H") or _s4 in ("1", "TRUE"):
            return " HOME"
        if _s4.startswith("A") or _s4.startswith("R") or _s4 in ("0", "FALSE"):
            return " AWAY"
        return ""
    # NIKKO-ARMHAND: which hand tonight's arm throws with, appended to the string the
    # drawer band, the FACING column and the search box all read.  matchup_hand is not a
    # candidate -- its first letter is the BAT's side.  co falling back to a team code
    # (OPP_C's last candidate) is not an arm, so nothing is appended to that either.
    # NIKKO-ARMERA: the arm's season ERA, printed right after his name.  First column
    # that exists and carries something; nothing is appended when none of them does.
    _erc = next((_c for _c in ("p_era", "era", "arm_era")
                 if _c in d.columns and d[_c].notna().any()), None)

    def _ertag(_i5):
        if not _erc:
            return ""
        try:
            _v5 = float(str(d[_erc].iloc[_i5]).strip())
        except (TypeError, ValueError):
            return ""
        if _v5 != _v5 or _v5 < 0 or _v5 > 99:
            return ""
        return " %.2f era" % _v5

    _ahnd = None
    if co and str(co) != "opponent":
        for _hc in ("arm_hand", "p_throws", "throws", "p_hand", "pitch_hand"):
            if _hc in d.columns:
                _hs = d[_hc].astype(str).str.strip().str.upper()
                if _hs.isin(("L", "R", "LHP", "RHP", "LEFT", "RIGHT")).any():
                    _ahnd = _hc
                    break

    # NIKKO-HANDFIX: the batter's side.  bestpitch stamps bat_hand as RHB / LHB on
    # every board; `stand` is the raw Statcast letter and is read as a fallback.  A bat
    # with neither gets an empty string, exactly as the arm tag does.
    _bhnd = None
    for _bc in ("bat_hand", "stand", "b_hand", "bats"):
        if _bc in d.columns:
            _bs = d[_bc].astype(str).str.strip().str.upper()
            if _bs.isin(("L", "R", "LHB", "RHB", "LEFT", "RIGHT", "S")).any():
                _bhnd = _bc
                break

    def _bhtag(_i6):
        if not _bhnd:
            return ""
        _v6 = str(d[_bhnd].iloc[_i6]).strip().upper()
        if not _v6 or _v6 in ("NAN", "NONE", "NA", "-"):
            return ""
        if _v6.startswith("L"):
            return "  LHB"
        if _v6.startswith("S"):
            return "  SWH"
        if _v6.startswith("R"):
            return "  RHB"
        return "  " + _v6[:4]

    def _ahtag(_i3):
        if not _ahnd:
            return ""
        _v3 = str(d[_ahnd].iloc[_i3]).strip().upper()
        if not _v3 or _v3 in ("NAN", "NONE", "NA", "-"):
            return ""
        if _v3.startswith("L"):
            return "  LHP"
        if _v3.startswith("R"):
            return "  RHP"
        return "  " + _v3[:4]
    ctier, cprob = _pick(d, TIER_C), _pick(d, PROB_C)
    cflag, cconf = _pick(d, FLAG_C), _pick(d, CONF_C)
    cgate, cdia = _pick(d, GATE_C), _pick(d, DIA_C)
    ctbt, cband = _pick_rich(d, TBT_C), _pick_rich(d, BAND_C)
    chrr = _pick_rich(d, HRR_C)   # NIKKO-HRRSHOW
    clane = _pick(d, LANE_C)      # NIKKO-LANECOL
    clow, cshot = _pick(d, LOW_C), _pick(d, SHOT_C)
    # ===================== NIKKO-RANKSAFE =====================
    # d and df are two different frames.  Columns are resolved on d --
    # which is the frame readchips hydrates onto -- and were then read
    # from df, the full board swapped in so percentiles rank against
    # every bat.  A column on d and not on df raised KeyError, and
    # board_html()'s except turned that into one red line where the
    # whole tab used to be:  board component error: 'ld_asof'
    # Rank on df when it has the column, on d when it does not.
    def _rs_src(_c):
        try:
            if _c in df.columns:
                return df
        except Exception:
            pass
        _RS_FELLBACK.append(str(_c))
        return d
    _RS_FELLBACK = []
    # =================== end NIKKO-RANKSAFE ===================
    pct, raw = {}, {}
    for _, items in GROUPS:
        for lab, cands in items:
            c = _pick(d, cands)
            if c is None:
                continue
            # ===================== NIKKO-SITEPCT =====================
            # Was: rank against `df` -- the frame app.py handed in, which for the
            # HR tab has already lost every bat under hr_prob 0.15 (NIKKO-HRCORE).
            # Ranking 48 survivors against each other inflates every percentile on
            # the page.  eyeball.py ranks against the whole exported board; this
            # now reads that same file so the two agree.  Values are looked up in
            # the full-slate distribution, so filtering or reindexing upstream
            # cannot misalign them.
            s_all = pd.to_numeric(_rs_src(c)[c], errors="coerce")
            if s_all.notna().sum() < 8:
                continue
            raw[lab] = _num(d, c).tolist()
            _sp_ref = _sp_pool[c] if (_sp_pool is not None and c in _sp_pool.columns) else None
            if _sp_ref is not None and _sp_ref.notna().sum() >= 8:
                pct[lab] = _sp_rank(_num(d, c), _sp_ref)
            else:
                # --- NIKKO-TAILFIX: rank d against the full frame, not df's head ---
                if s_all.notna().sum() >= 8:
                    pct[lab] = _sp_rank(_num(d, c), s_all)
                else:
                    pct[lab] = (pd.Series(_num(d, c), dtype="float64")
                                .rank(pct=True) * 100).round().tolist()
                # --- end NIKKO-TAILFIX ---
            # =================== end NIKKO-SITEPCT ===================

    gate = None
    if cgate:
        g = _num(d, cgate)
        gate = (g >= 1000).fillna(False).tolist() if g.notna().any() else None
    if gate is None and "GATE" in d.columns:
        gate = d["GATE"].astype(str).str.contains("FIRE", case=False, na=False).tolist()

    dia = None
    if cdia is not None:
        try:
            dia = d[cdia].fillna(False).astype(bool).tolist()
        except Exception:
            dia = None

    # ===================== NIKKO-AGREEFLAG =====================
    # The four consensus gates, evaluated against tonight's slate.  Windows are
    # percentiles with a floor AND a ceiling -- p70-90 means p70 through p90, not
    # p70 and up.  Ranking reuses _sp_rank against the full exported board so a
    # bat's percentile here is the same number the drawer bars show.
    agrows, agnames, agsun = [0] * len(d), [[]] * len(d), [False] * len(d)
    agsigs = [[] for _ in range(len(d))]   # NIKKO-SIGWIRE
    _agout = [False] * len(d)              # NIKKO-AGFLOOR
    try:
        agnames = [[] for _ in range(len(d))]
        _ag_live, _ag_skip = [], []
        _agp_n = 0
        for _gs, _gl, _legs in AGREE_GATES:
            _ok, _hit = True, [True] * len(d)
            for _cands, _lo, _hi in _legs:
                # NIKKO-AGPOOL: count the reads that had to come from the pool, so a
                # board running on wired columns is visible in the console and a
                # silent join failure can never read as a cold night.
                if _pick(d, _cands) is None:
                    _agp_n += 1
                _p = _ag_series(d, df, _sp_pool, _cands)
                if _p is None:
                    _ok = False
                    _ag_skip.append("%s (%s)" % (_gs, _cands[0]))
                    break
                # ===================== NIKKO-AGSHARE =====================
                # Judge the WINDOW, not the column. A constant read ranks every bat
                # at p50, so a p40-70 window on it selects the whole slate -- that is
                # the failure, and it is only visible once lo/hi are known. A leg
                # naming more than 60% of the board is a pass-through, not a read.
                _agw_n = sum(1 for _x in _p if _lo <= _x <= _hi)
                _agw_share = (100.0 * _agw_n / len(d)) if len(d) else 0.0
                if _agw_share > _AG_MAXSHARE:
                    _ok = False
                    _ag_skip.append("%s (%s p%d-%d names %d%% of the slate)"
                                    % (_gs, _cands[0], _lo, _hi, int(round(_agw_share))))
                    break
                # =================== end NIKKO-AGSHARE ===================
                for _i in range(len(d)):
                    if not (_lo <= _p[_i] <= _hi):
                        _hit[_i] = False
            if not _ok:
                continue
            _ag_live.append(_gs)
            for _i in range(len(d)):
                if _hit[_i]:
                    agrows[_i] += 1
                    agnames[_i].append(_gs)
        # the sun: ONE gate named, plus slgfit_arm high on tonight's slate.
        # ===================== NIKKO-AGFLOOR =====================
        # The pool floor. ars_xslg is the fallback because it is what the "37 of 55
        # nights" reach has always actually been -- slgfit_arm is built on it and is
        # only on the boards from 08-19 forward.
        _agp = _ag_series(d, df, _sp_pool, ["slgfit_arm", "SLG-FIT", "ars_xslg"])
        _agout = [False] * len(d)
        if _agp is not None:
            for _i in range(len(d)):
                if agrows[_i] >= 1 and _agp[_i] < _AG_POOLP:
                    # keep the chips, drop the badge: the reads are still true, but in
                    # this half of the board the agreement between them is not.
                    _agout[_i] = True
                    agrows[_i] = 0
                    agnames[_i] = []
        try:
            print("[agfloor] confirmer %s | %d bat(s) named but below p%d -- badge withheld"
                  % ("live" if _agp is not None else "MISSING (no floor applied)",
                     sum(1 for _x in _agout if _x), _AG_POOLP))
        except Exception:
            pass
        # =================== end NIKKO-AGFLOOR ===================
        _sf = _agp
        if _sf is not None:
            for _i in range(len(d)):
                agsun[_i] = (agrows[_i] == 1 and _sf[_i] >= _AG_SUNP)
        # ===================== NIKKO-SIGWIRE =====================
        # The chips, from the same percentiles the gates run on. A read whose column
        # is missing everywhere simply contributes no chip -- it is never guessed at,
        # and a bat with no chips is a bat nothing measured is saying anything about.
        for _sl, _sfam, _scand, _slo, _shi in SIG_READS:
            _sp = _ag_series(d, df, _sp_pool, _scand)
            if _sp is None:
                continue
            for _i in range(len(d)):
                if _slo <= _sp[_i] <= _shi:
                    agsigs[_i].append([_sl, _sfam, int(_sp[_i])])
        # =================== end NIKKO-SIGWIRE ===================
        # ===================== NIKKO-PAIRSIG =====================
        # A pair fires only when BOTH halves clear their cut. A missing arm column
        # means the chip cannot fire at all -- it is never treated as if the arm half
        # passed, which is how "dark" chips got counted as firing on the old panel.
        for _pl, _pf, _pbc, _pbp, _pac, _pap, _plow in PAIR_READS:
            _ps_lo = _ag_series(d, df, _sp_pool, _pbc)
            _ps_hi = _ag_series(d, df, _sp_pool, _pac)
            if _ps_lo is None or _ps_hi is None:
                continue
            for _i in range(len(d)):
                _ps_p = (100 - _ps_hi[_i]) if _plow else _ps_hi[_i]
                if _ps_lo[_i] >= _pbp and _ps_p >= _pap:
                    agsigs[_i].append([_pl, _pf, int(_ps_lo[_i])])
        # =================== end NIKKO-PAIRSIG ===================
        # ===================== NIKKO-LANESIG =====================
        # Depth chips come off the engine's own columns. A missing column means
        # the chip never fires -- it is never treated as if it passed.
        # ===================== NIKKO-READCHIPS =====================
        # nk_read_* is written by readspanel.py --stamp onto
        # nk/boards/board_<date>.csv.  display_df has an export whitelist and
        # drops everything else, so these never arrive on this frame.
        # Read them off that board and join on whatever key the two share.
        #
        # Everything goes to /tmp/readchips.log as well as stdout.  streamlit
        # does not reliably deliver print() to the terminal, which is why this
        # was invisible for an entire day.  The file always exists.
        _RCV = {}
        def _rclog(_m):
            try:
                print("[readchips] " + _m)
            except Exception:
                pass
            try:
                with open("/tmp/readchips.log", "a") as _f:
                    _f.write(_m + chr(10))
            except Exception:
                pass
        try:
            import glob as _rcg, os as _rco, datetime as _rcdt
            # board_html binds pandas as _p in this scope, NOT _pd.  The
            # FLAG_READS loop below says _pd and has never fired -- its three
            # columns are never on the frame, so it continues before it gets
            # there -- so the bug sat unseen.  Bind it ourselves and depend on
            # no alias at all.
            import pandas as _rcpd
            globals()["_RCPD"] = _rcpd
            # the eighteen columns the nine reads gate on.  display_df drops
            # every one, which is why the drawer could not show them.
            # Not a hand-picked list.  Every column any drawer row asks
            # for, plus the read columns.  display_df has an export whitelist
            # and drops the rest, which is why [saymiss] has printed NO SUCH
            # COLUMN for fifty-odd rows every night about columns that are
            # sitting on the board.  Take the whole wish list; hydrate whatever
            # is actually there; name what is not.
            _RCOLS = []
            try:
                for _g in GROUPS:
                    for _lab, _cands in _g[1]:
                        for _c in _cands:
                            if _c not in _RCOLS:
                                _RCOLS.append(_c)
            except Exception:
                pass
            for _c in [x[2] for x in FLAG_READS]:
                if _c not in _RCOLS:
                    _RCOLS.append(_c)
            # ===================== NIKKO-LINEUPTAG =====================
            # nk/board.py writes slot_source ("lineup" | "roster") and
            # lineup_slot on every bat.  display_df's export whitelist drops
            # both on the way to boards/boards_<date>.csv, so the frame never
            # sees them -- measured 2026-09-04: 439 rows on the research
            # board carried slot_source, 226 rows on the app board carried
            # none.  Adding them to the wish list makes the readfill join
            # below hydrate them like any other dropped column.
            for _c in ("slot_source", "lineup_slot"):
                if _c not in _RCOLS:
                    _RCOLS.append(_c)
            # =================== end NIKKO-LINEUPTAG ===================
            _rclog("---- render %s ----"
                   % _rcdt.datetime.now().strftime("%H:%M:%S"))
            _rcdir = _rco.path.dirname(_rco.path.abspath(__file__))
            # ===================== NIKKO-READFILL =====================
            # The stat hydration further down sits INSIDE the branch that only
            # runs when readspanel --stamp has already written nk_read_* onto
            # the board.  On an un-stamped board nothing hydrates at all, and
            # [saymiss] then names 120 drawer rows NO SUCH COLUMN for columns
            # that are sitting on nk/boards/board_<date>.csv.  The two jobs are
            # unrelated, so do this one here, first, unconditionally.
            _rfpick = None
            try:
                _rftoday = _rco.path.join(
                    _rcdir, "nk", "boards",
                    "board_%s.csv" % _rcdt.date.today().isoformat())
                _rfall = sorted(_rcg.glob(_rco.path.join(
                    _rcdir, "nk", "boards", "board_2*.csv")))
                if _rco.path.exists(_rftoday):
                    _rfpick = _rftoday
                elif _rfall:
                    _rfpick = _rfall[-1]
                    _rclog("NO RESEARCH BOARD FOR TODAY -- falling back to %s."
                           "  Every read and every column below is THAT date's,"
                           " joined onto tonight's bats."
                           % _rco.path.basename(_rfpick))
                if _rfpick:
                    _rfb = _rcpd.read_csv(_rfpick, low_memory=False)
                    _rfn = _rco.path.basename(_rfpick)
                    _rfkey = None
                    for _rfk in ("player_id", "id", "batter_id", "mlbam_id",
                                 "name", "player_name", "batter", "player"):
                        if _rfk in d.columns and _rfk in _rfb.columns:
                            _rfkey = _rfk
                            break
                    _rfs = [c for c in _RCOLS
                            if c in _rfb.columns and c not in d.columns]
                    if _rfkey is None:
                        _rclog("readfill: no shared key with %s -- nothing"
                               " hydrated" % _rfn)
                    elif not _rfs:
                        _rclog("readfill: %s carries no drawer column the"
                               " frame is missing" % _rfn)
                    else:
                        if _rfkey in ("name", "player_name", "batter",
                                      "player"):
                            _rfl = d[_rfkey].astype(str).str.strip()
                            _rfb[_rfkey] = (_rfb[_rfkey].astype(str)
                                            .str.strip())
                        else:
                            _rfl = _rcpd.to_numeric(d[_rfkey], errors="coerce")
                            _rfb[_rfkey] = _rcpd.to_numeric(_rfb[_rfkey],
                                                            errors="coerce")
                        _rfy = (_rfb[[_rfkey] + _rfs]
                                .dropna(subset=[_rfkey])
                                .drop_duplicates(_rfkey)
                                .set_index(_rfkey))
                        _rfhit = int(_rfl.isin(_rfy.index).sum())
                        _rfok = 0
                        for _rfc in _rfs:
                            try:
                                d[_rfc] = _rfl.map(_rfy[_rfc]).values
                                _rfok += 1
                            except Exception:
                                pass
                        _rclog("readfill: %s -> %d drawer column(s) hydrated,"
                               " key '%s', %d of %d bat(s) matched"
                               " (stamped or not)"
                               % (_rfn, _rfok, _rfkey, _rfhit, len(d)))
                # ===================== NIKKO-DRAWERKEEP =====================
                # boards/boards_<date>.csv is rewritten by the app itself on
                # every render, from display_df, whose export whitelist drops
                # the *_asof / mix / arm columns.  So the drawer is complete
                # until the first page load and thin forever after.  Keep a
                # copy of the drawer columns somewhere the app never writes,
                # and fill from it once the board has been stripped.
                _dks = _rco.path.join(_rcdir, "nk", "boards",
                                      "drawer_%s.csv"
                                      % _rcdt.date.today().isoformat())
                _dkb = _rco.path.join(_rcdir, "boards",
                                      "boards_%s.csv"
                                      % _rcdt.date.today().isoformat())
                _dkkey = None
                for _dkk in ("player_id", "id", "batter_id", "mlbam_id",
                             "name", "player_name", "batter", "player"):
                    if _dkk in d.columns:
                        _dkkey = _dkk
                        break
                # 1. refresh the snapshot, but only ever with MORE than it has
                try:
                    if _dkkey and _rco.path.exists(_dkb):
                        _dkc = list(_rcpd.read_csv(_dkb, nrows=1).columns)
                        if _dkkey in _dkc:
                            _dkhave = [c for c in _RCOLS if c in _dkc]
                            _dkold = []
                            if _rco.path.exists(_dks):
                                _dkold = [c for c in _rcpd.read_csv(
                                    _dks, nrows=1).columns if c in _RCOLS]
                            if _dkhave and len(_dkhave) >= len(_dkold):
                                (_rcpd.read_csv(_dkb,
                                                usecols=[_dkkey] + _dkhave,
                                                low_memory=False)
                                 .to_csv(_dks, index=False))
                                _rclog("drawerkeep: snapshot %s <- %d drawer"
                                       " column(s) off the app board"
                                       % (_rco.path.basename(_dks),
                                          len(_dkhave)))
                            elif _dkold:
                                _rclog("drawerkeep: app board is down to %d"
                                       " drawer column(s), snapshot holds %d"
                                       " -- snapshot kept"
                                       % (len(_dkhave), len(_dkold)))
                except Exception as _dke1:
                    _rclog("drawerkeep: snapshot skipped: %r" % (_dke1,))
                # 2. fill whatever is still missing from it
                try:
                    _dkneed = [c for c in _RCOLS if c not in d.columns]
                    if _dkkey and _dkneed and _rco.path.exists(_dks):
                        _dkf = _rcpd.read_csv(_dks, low_memory=False)
                        if _dkkey in _dkf.columns:
                            _dkuse = [c for c in _dkneed if c in _dkf.columns]
                            if _dkuse:
                                if _dkkey in ("name", "player_name", "batter",
                                              "player"):
                                    _dkl = d[_dkkey].astype(str).str.strip()
                                    _dkf[_dkkey] = (_dkf[_dkkey].astype(str)
                                                    .str.strip())
                                else:
                                    _dkl = _rcpd.to_numeric(d[_dkkey],
                                                            errors="coerce")
                                    _dkf[_dkkey] = _rcpd.to_numeric(
                                        _dkf[_dkkey], errors="coerce")
                                _dky = (_dkf[[_dkkey] + _dkuse]
                                        .dropna(subset=[_dkkey])
                                        .drop_duplicates(_dkkey)
                                        .set_index(_dkkey))
                                _dkok = 0
                                for _dkc2 in _dkuse:
                                    try:
                                        d[_dkc2] = _dkl.map(
                                            _dky[_dkc2]).values
                                        _dkok += 1
                                    except Exception:
                                        pass
                                # NIKKO-SAYFIX: a column restored is not a
                                # column with numbers in it.  A join on a key
                                # that does not match assigns every one of
                                # them and lands NaN in all of them, and a
                                # NaN column fails notna()>=8 so the row does
                                # not draw.  Say how many actually carry data.
                                _dkhit = int(_dkl.isin(_dky.index).sum())
                                _dklive = 0
                                for _dkc3 in _dkuse:
                                    try:
                                        if _rcpd.to_numeric(
                                                d[_dkc3],
                                                errors="coerce"
                                                ).notna().sum() >= 8:
                                            _dklive += 1
                                    except Exception:
                                        pass
                                _rclog("drawerkeep: %d column(s) restored,"
                                       " key '%s', %d of %d bat(s) matched,"
                                       " %d carry 8+ values (the rest cannot"
                                       " draw a row)"
                                       % (_dkok, _dkkey, _dkhit, len(d),
                                          _dklive))
                    _rclog("drawerkeep: %d of %d drawer column(s) on the frame"
                           % (len([c for c in _RCOLS if c in d.columns]),
                              len(_RCOLS)))
                except Exception as _dke2:
                    _rclog("drawerkeep: fill skipped: %r" % (_dke2,))
                # =================== end NIKKO-DRAWERKEEP ===================
            except Exception as _rfe:
                _rclog("readfill skipped: %r" % (_rfe,))
            # =================== end NIKKO-READFILL ===================
            _rcw = [c[2] for c in FLAG_READS if str(c[2]).startswith("nk_read_")]
            _rcneed = [c for c in _rcw if c not in d.columns]
            _rclog("frame %d row(s) %d col(s); %d nk_read_* wanted, %d missing"
                   % (len(d), len(d.columns), len(_rcw), len(_rcneed)))
            if not _rcw:
                _rclog("FLAG_READS has no nk_read_* entries")
            elif not _rcneed:
                _rclog("already on the frame -- using it directly")
            else:
                _rcf = sorted(_rcg.glob(_rco.path.join(
                    _rcdir, "nk", "boards", "board_2*.csv")))
                if _rfpick:
                    _rcf = [_rfpick]   # NIKKO-READFILL: today's, not last by name
                # ===================== NIKKO-CHIPSRC =====================
                # The nine are stamped onto the APP board.  It is the
                # only board carrying hr_score, so it is the only one
                # readspanel can band on -- on the research board every
                # read "fires on nobody" and the stamp is nine columns
                # of zeros, which readchips then joins and believes.
                # Reads from the board that can band; the as-of and mix
                # columns still come off the research board above.
                try:
                    _cs = _rco.path.join(
                        _rcdir, "boards",
                        "boards_%s.csv" % _rcdt.date.today().isoformat())
                    if _rco.path.exists(_cs):
                        _csc = list(_rcpd.read_csv(_cs, nrows=1).columns)
                        _csn = [c for c in _rcneed if c in _csc]
                        if _csn:
                            _rcf = [_cs]
                            _rclog("reads off the app board %s -- %d of"
                                   " the %d nk_read_* column(s)"
                                   % (_rco.path.basename(_cs), len(_csn),
                                      len(_rcneed)))
                        else:
                            _rclog("app board %s carries no nk_read_* --"
                                   " run: python3 nk/asof.py --board %s"
                                   " --apply  then readspanel --stamp"
                                   % (_rco.path.basename(_cs), _cs))
                except Exception as _cse:
                    _rclog("chipsrc skipped: %r" % (_cse,))
                # =================== end NIKKO-CHIPSRC ===================
                if not _rcf:
                    _rclog("no nk/boards/board_2*.csv under " + _rcdir)
                else:
                    _rcb = _rcpd.read_csv(_rcf[-1], low_memory=False)
                    _rcn = _rco.path.basename(_rcf[-1])
                    _rch = [c for c in _rcneed if c in _rcb.columns]
                    _rclog("%s: %d row(s), %d of the nk_read_* column(s)"
                           % (_rcn, len(_rcb), len(_rch)))
                    if not _rch:
                        _rclog("run: python3 nk/readspanel.py --board "
                               "nk/boards/" + _rcn + " --stamp")
                    else:
                        _rckey = None
                        for _k in ("player_id", "id", "batter_id", "mlbam_id",
                                   "name", "player_name", "batter", "player"):
                            if _k in d.columns and _k in _rcb.columns:
                                _rckey = _k
                                break
                        if _rckey is None:
                            _rclog("NO SHARED KEY.")
                            _rclog("  frame: "
                                   + ", ".join(map(str, list(d.columns))))
                            _rclog("  board: "
                                   + ", ".join(map(str,
                                     list(_rcb.columns)[:40])))
                        else:
                            if _rckey in ("name", "player_name", "batter",
                                          "player"):
                                _rcl = d[_rckey].astype(str).str.strip()
                                _rcb[_rckey] = (_rcb[_rckey].astype(str)
                                                .str.strip())
                            else:
                                _rcl = _rcpd.to_numeric(d[_rckey],
                                                      errors="coerce")
                                _rcb[_rckey] = _rcpd.to_numeric(_rcb[_rckey],
                                                              errors="coerce")
                            _rcx = (_rcb[[_rckey] + _rch]
                                    .dropna(subset=[_rckey])
                                    .drop_duplicates(_rckey)
                                    .set_index(_rckey))
                            _rcmatch = int(_rcl.isin(_rcx.index).sum())
                            for _rcc in _rch:
                                _RCV[_rcc] = _rcl.map(
                                    _rcx[_rcc]).fillna(0).values
                            _rcflag = sum(1 for _i in range(len(d))
                                          if any(_RCV[_c][_i] for _c in _rch))
                            _rclog("key '%s': %d of %d row(s) matched, "
                                   "%d bat(s) carry a read"
                                   % (_rckey, _rcmatch, len(d), _rcflag))
                            # and the stat columns, onto the frame, so the
                            # drawer can draw what the reads actually gate on
                            _rcs = [c for c in _RCOLS
                                    if c in _rcb.columns and c not in d.columns]
                            if _rcs:
                                _rcy = (_rcb[[_rckey] + _rcs]
                                        .dropna(subset=[_rckey])
                                        .drop_duplicates(_rckey)
                                        .set_index(_rckey))
                                _rcok = 0
                                for _rcc in _rcs:
                                    try:
                                        d[_rcc] = _rcl.map(_rcy[_rcc]).values
                                        _rcok += 1
                                    except Exception:
                                        pass
                                _rclog("hydrated %d column(s) onto the frame"
                                       % _rcok)
                                _rcmiss = [c for c in _RCOLS
                                           if c not in _rcb.columns
                                           and c not in d.columns]
                                if _rcmiss:
                                    _rclog("%d drawer column(s) exist nowhere: %s"
                                           % (len(_rcmiss), ", ".join(_rcmiss)))
                            else:
                                _rclog("read columns already on the frame")
                            if _rcmatch and not _rcflag:
                                _rclog("matched, none fire -- no bat on this "
                                       "tab carries a read tonight")
                            if not _rcmatch:
                                _rclog("  frame keys: " + ", ".join(map(str,
                                       list(_rcl.head(4)))))
                                _rclog("  board keys: " + ", ".join(map(str,
                                       list(_rcx.index[:4]))))
        except Exception as _rce:
            try:
                import traceback as _rctb
                _rclog("FAILED: %r" % (_rce,))
                _rclog(_rctb.format_exc())
            except Exception:
                pass
        # =================== end NIKKO-READCHIPS ===================
        for _lsg_l, _lsg_f, _lsg_c in FLAG_READS:
            if _lsg_c in _RCV:
                _lsg_v = _RCV[_lsg_c]
            elif _lsg_c not in d.columns:
                continue
            else:
                _lsg_v = _RCPD.to_numeric(d[_lsg_c], errors="coerce").fillna(0).values
            for _i in range(len(d)):
                if _lsg_v[_i]:
                    agsigs[_i].append([_lsg_l, _lsg_f, 100])
        # =================== end NIKKO-LANESIG ===================
        try:
            print("[agreeflag] live %s | skipped %s | from pool %d | "
                  "2+ %d  3+ %d  1 %d  sun %d"
                  % (",".join(_ag_live) or "NONE",
                     ",".join(_ag_skip) or "none", _agp_n,
                     sum(1 for _x in agrows if _x >= 2),
                     sum(1 for _x in agrows if _x >= 3),
                     sum(1 for _x in agrows if _x == 1),
                     sum(1 for _x in agsun if _x)))
        except Exception:
            pass
    except Exception as _age:
        try:
            print("[agreeflag] DISABLED this render: %s" % _age)
        except Exception:
            pass
        agrows, agnames, agsun = [0] * len(d), [[] for _ in range(len(d))], [False] * len(d)
        agsigs = [[] for _ in range(len(d))]   # NIKKO-SIGWIRE
    # =================== end NIKKO-AGREEFLAG ===================

    # anything not already grouped, so removing a table column never loses the number
    # ===================== NIKKO-LATELOAD =====================
    # pct/raw were built ~150 lines above, BEFORE readchips/readfill/
    # drawerkeep put anything on the frame.  Every row whose column arrived
    # in the hydrate was already discarded by then.  Second pass: same
    # resolve, same floor, same ranking -- only for rows that did not draw.
    try:
        _ll_add, _ll_grp = 0, {}
        for _ll_g, _ll_items in GROUPS:
            for _ll_lab, _ll_c in _ll_items:
                if _ll_lab in pct:
                    continue
                _ll_col = _pick(d, _ll_c)
                if _ll_col is None:
                    continue
                _ll_s = pd.to_numeric(_rs_src(_ll_col)[_ll_col],
                                      errors="coerce")
                if _ll_s.notna().sum() < 8:
                    continue
                raw[_ll_lab] = _num(d, _ll_col).tolist()
                _ll_ref = (_sp_pool[_ll_col]
                           if (_sp_pool is not None
                               and _ll_col in _sp_pool.columns) else None)
                if _ll_ref is not None and _ll_ref.notna().sum() >= 8:
                    pct[_ll_lab] = _sp_rank(_num(d, _ll_col), _ll_ref)
                else:
                    pct[_ll_lab] = _sp_rank(_num(d, _ll_col), _ll_s)
                _ll_add += 1
                _ll_grp[_ll_g] = _ll_grp.get(_ll_g, 0) + 1
        if _ll_add:
            print("[lateload] %d row(s) recovered -- their column arrived in"
                  " the hydrate, after the drawer had already chosen"
                  % _ll_add)
            for _ll_k in sorted(_ll_grp, key=lambda z: -_ll_grp[z]):
                print("[lateload]   %-46s +%d row(s)"
                      % (str(_ll_k)[:46], _ll_grp[_ll_k]))
        else:
            print("[lateload] no rows to recover -- the first pass already"
                  " had every column it could use")
        print("[lateload] %d of %d panel row(s) will draw"
              % (len(pct), sum(len(_x[1]) for _x in GROUPS)))
    except Exception as _ll_e:
        print("[lateload] skipped: %r" % (_ll_e,))
    # =================== end NIKKO-LATELOAD ===================
    grouped = set()
    for _, items in GROUPS:
        for _, cands in items:
            c = _pick(d, cands)
            if c:
                grouped.add(c)
    extra = [c for c in d.columns
             if c not in grouped and c not in SKIP_DETAIL and not str(c).startswith("_")]
    ex_pct, ex_raw, ex_txt = {}, {}, {}
    # ===================== NIKKO-RANKSAFE =====================
    def _rs_say():
        try:
            _u = sorted(set(_RS_FELLBACK))
            if _u:
                print('[ranksafe] %d column(s) ranked on the %d handed in,'
                      ' not on the full board: %s'
                      % (len(_u), len(d), ', '.join(_u[:12])
                         + (' ...' if len(_u) > 12 else '')))
            else:
                print('[ranksafe] every drawer column was on the full board')
        except Exception:
            pass
    # =================== end NIKKO-RANKSAFE ===================
    for c in extra:
        s_all = pd.to_numeric(_rs_src(c)[c], errors="coerce")
        if s_all.notna().sum() >= 8:
            ex_raw[c] = _num(d, c).tolist()
            # ============ NIKKO-DRAWPCT ============
            # SITEPCT fixed the group bars and never reached here.
            # These are the drawer rows, and they were still ranked
            # against the filtered frame app.py hands the renderer.
            _dp_ref = (_sp_pool[c] if (_sp_pool is not None
                       and c in _sp_pool.columns) else None)
            if _dp_ref is not None and _dp_ref.notna().sum() >= 8:
                ex_pct[c] = _sp_rank(_num(d, c), _dp_ref)
            else:
                # --- NIKKO-TAILFIX ---
                if s_all.notna().sum() >= 8:
                    ex_pct[c] = _sp_rank(_num(d, c), s_all)
                else:
                    ex_pct[c] = (pd.Series(_num(d, c), dtype="float64")
                                 .rank(pct=True) * 100).round().tolist()
                # --- end NIKKO-TAILFIX ---
            # ========== end NIKKO-DRAWPCT ==========
        else:
            v = d[c].astype(str).replace({"nan": "", "None": "", "<NA>": ""})
            if v.str.len().max() and v.str.len().max() <= 40:
                ex_txt[c] = v.tolist()

    _rs_say()
    # ===================== NIKKO-ALIGNBAND =====================
    # The alignment as a THING, not as its ingredients.
    #
    # The LADDER is READ, never recomputed. app.py cuts it on the full slate
    # (zone p70 & r_xslg p85 -> L1, + vuln p85 -> L2); this renderer only ever sees the
    # board that was handed to it, so recomputing would print a rung that disagrees with
    # the LADDER column on the same page.
    _clad = _pick(d, ["LADDER", "hr_ladder_disp"])
    _cladn = _pick(d, ["hr_ladder"])
    _LADN = {1: "L1 BASE", 2: "L2 STRONG", 3: "L3 PREMIUM"}

    def _ladtxt(_i2):
        _t = ""
        if _clad:
            _t = str(d[_clad].iloc[_i2]).strip()
            if _t.lower() in ("nan", "none", "<na>", "-"):
                _t = ""
        if not _t and _cladn:
            try:
                _t = _LADN.get(int(float(d[_cladn].iloc[_i2])), "")
            except Exception:
                _t = ""
        return _t

    def _rank(_cands):
        """slate percentile of the first candidate column that carries data.

        Same convention the group bars use: rank over the whole frame, then take the
        rows this board is showing. A column under 8 values is not ranked at all.
        """
        for _c in _cands:
            if _c in df.columns:
                _s = pd.to_numeric(df[_c], errors="coerce")
                if _s.notna().sum() >= 8:
                    # ======== NIKKO-DRAWPCT ========
                    # _sp_rank returns 0-100; this helper returns 0-1,
                    # so divide.  Fallback is the original line.
                    _dp_ref = (_sp_pool[_c] if (_sp_pool is not None
                               and _c in _sp_pool.columns) else None)
                    if _dp_ref is not None and _dp_ref.notna().sum() >= 8:
                        return (pd.Series(_sp_rank(_num(d, _c), _dp_ref),
                                          dtype="float64") / 100.0
                                ).reset_index(drop=True)
                    # ====== end NIKKO-DRAWPCT ======
                    # --- NIKKO-TAILFIX ---
                    if _s.notna().sum() >= 8:
                        return (pd.Series(_sp_rank(_num(d, _c), _s),
                                          dtype="float64") / 100.0
                                ).reset_index(drop=True)
                    # --- end NIKKO-TAILFIX ---
                    return pd.Series(_num(d, _c), dtype="float64").rank(pct=True).reset_index(drop=True)
        return None

    # NIKKO-WHATALIGNS: app.py packs the firing _STK pairs as
    #     bat:pct|arm:pct;bat:pct|arm:pct
    # Built there on purpose -- see the comment at NIKKO-WHATALIGNS in app.py.
    _cstk = _pick(d, ["hr_stack_pairs"])
    _cstkn = _pick(d, ["hr_stack_avail"])

    # ===================== NIKKO-LINEUPTAG =====================
    # CONFIRMED vs PROJECTED.  Resolved once, outside the row loop, off
    # whichever frame actually carries the column -- d after readfill in the
    # normal case.  Returns [] when the bat is not on tonight's research
    # board, and [] renders as nothing rather than as a false PROJ.
    _lu_src = "slot_source" if "slot_source" in getattr(d, "columns", ()) else None
    _lu_slot = "lineup_slot" if "lineup_slot" in getattr(d, "columns", ()) else None

    def _lutag(_i2):
        if not _lu_src:
            return []
        try:
            _v = d[_lu_src].iloc[_i2]
        except Exception:
            return []
        if _v != _v:
            return []
        _v = str(_v).strip().lower()
        _s = ""
        if _lu_slot:
            try:
                _n = d[_lu_slot].iloc[_i2]
                if _n == _n and str(_n).strip() != "":
                    _s = str(int(float(_n)))
            except Exception:
                _s = ""
        if _v.startswith("lineup"):
            return ["lineup", _s]
        if _v.startswith("roster"):
            return ["roster", ""]
        return []
    # =================== end NIKKO-LINEUPTAG ===================

    def _stk(_i2):
        if not _cstk:
            return []
        _v = d[_cstk].iloc[_i2]
        if _v != _v or not str(_v).strip():
            return []
        _out = []
        for _seg in str(_v).split(";"):
            if "|" not in _seg:
                continue
            _l, _r2 = _seg.split("|", 1)
            _ln, _, _lp = _l.rpartition(":")
            _rn, _, _rp = _r2.rpartition(":")
            if not _ln or not _rn:
                continue
            _out.append({"a": _ln, "pa": _lp, "b": _rn, "pb": _rp})
        return _out

    _stk_of = 0
    if _cstkn:
        try:
            _sv = _num(d, _cstkn).dropna()
            _stk_of = int(_sv.max()) if len(_sv) else 0
        except Exception:
            _stk_of = 0

    _RK = {"zone": _rank(["zone_overlap", "Zone", "Overlap"]),
           "mix":  _rank(["mix_iso_blend", "Mix"]),
           "loc":  _rank(["loc_fit"]),
           "wpx":  _rank(["worst_pitch_xslg"]),
           "prob": _rank(["hr_prob", "HR %", "HR%"])}
    _CN = _num(d, cconf).fillna(0) if cconf else None
    # (label, measured lift, [(key, slate-percentile cut)], minimum clean-flag count)
    READS = [
        ("zone + mix agree", "1.44x", [("zone", 0.70), ("mix", 0.70)], 0),
        ("loc x arm",        "1.89x", [("loc", 0.80), ("wpx", 0.70)], 0),
        ("prob + 3 clean",   "1.98x", [("prob", 0.90)], 3),
        ("zone top 5%",      "2.02x", [("zone", 0.95)], 0),
    ]
    _rd_ok = [all(_RK.get(_k) is not None for _k, _c in _t)
              and (_need == 0 or _CN is not None)
              for _l, _x, _t, _need in READS]
    _n_read = sum(1 for _b in _rd_ok if _b)
    _read_hits = []
    for _i2 in range(len(d)):
        _fires = []
        for _j, (_lab, _lift, _terms, _need) in enumerate(READS):
            if not _rd_ok[_j]:
                continue
            _ok = True
            for _k, _cut in _terms:
                _v = _RK[_k].iloc[_i2]
                if not (_v == _v and _v >= _cut):
                    _ok = False
                    break
            if _ok and _need and float(_CN.iloc[_i2]) < _need:
                _ok = False
            if _ok:
                _fires.append({"l": _lab, "x": _lift})
        _read_hits.append(_fires)
    # ===================== end NIKKO-ALIGNBAND =====================

    rows = []
    for i in range(len(d)):
        det = []
        for gname, items in GROUPS:
            sub = []
            for lab, cands in items:
                if lab not in pct:
                    continue
                v, p = raw[lab][i], pct[lab][i]
                if v != v or p != p:
                    continue
                av = abs(v)
                fmt = "%.3f" if av < 3 else ("%.1f" if av < 200 else "%.0f")
                # NIKKO-ALIGNDRAWER: k = 0 unverified (no bar) | 1 graded | 2 inverted
                _lf = VERDICT.get(lab)
                _iv = lab in INVERT
                sub.append({"l": lab, "v": fmt % v, "p": int(p),
                            "k": 0 if _lf is None else (2 if _iv else 1),
                            "lf": ("%.2fx" % _lf) if _lf is not None else ""})
            if sub:
                det.append({"g": gname, "r": sub})
        sub = []
        for c in ex_raw:
            v, p = ex_raw[c][i], ex_pct[c][i]
            if v != v or p != p:
                continue
            av = abs(v)
            fmt = "%.3f" if av < 3 else ("%.1f" if av < 200 else "%.0f")
            sub.append({"l": str(c)[:18], "v": fmt % v, "p": int(p),
                        "k": 0, "lf": ""})   # NIKKO-ALIGNDRAWER: never graded
        if sub:
            det.append({"g": "ENGINE / CONTEXT (ungraded)", "r": sub})
        txt = [{"l": str(c)[:18], "v": ex_txt[c][i]} for c in ex_txt if ex_txt[c][i]]
        pv = ""
        if cprob:
            x = _num(d, cprob).iloc[i]
            if x == x:
                pv = ("%.1f%%" % (100 * x)) if x <= 1.5 else ("%.1f" % x)
        rows.append({
            "n": (str(d[cn].iloc[i]) + _bhtag(i)) if cn else "",   # NIKKO-HANDFIX
            "t": (str(d[ct].iloc[i]) + _hmtag(i)) if ct else "",   # NIKKO-HOMETAG
            "o": (str(d[co].iloc[i]) + _ahtag(i) + _ertag(i)) if co else "",   # NIKKO-HANDFIX: hand, then era   # NIKKO-ARMHAND / NIKKO-ARMERA
            "tier": (str(d[ctier].iloc[i]) if ctier else "").upper().strip()[:9],
            "tbt": (str(d[ctbt].iloc[i]) if ctbt else "").upper().strip()[:9],
            # NIKKO-HRRSHOW: a bat below p50 has an empty hrr_tier, pandas reads that
            # back as NaN, and str(nan).upper() is the literal "NAN" -- the same bug
            # the BAND column had. Guarded here rather than fixed later.
            "hrrt": ("" if (not chrr or d[chrr].iloc[i] != d[chrr].iloc[i])
                     else str(d[chrr].iloc[i]).upper().strip()[:9]),
            # NIKKO-LANECOL: seat 0 and NaN both mean "not in that pool tonight" and
            # render as nothing, rather than as a seat called 0.
            "lnrk": _lncol(clane, d, i),
            "lnlow": _lncol(clow, d, i),
            "lnshot": _lncol(cshot, d, i),
            # NIKKO-SIGWIRE: str(nan).upper() is "NAN", which is what the BAND
            # column has been printing on every bat with no ps_cband value.
            "band": ("" if (not cband or d[cband].iloc[i] != d[cband].iloc[i])
                     else str(d[cband].iloc[i]).upper().strip()[:9]),
            "hp": pv,
            "g": bool(gate[i]) if gate else False,
            "dm": bool(dia[i]) if dia else False,
            # NIKKO-AGREEFLAG: how many of the four consensus gates name this bat,
            # which ones, and the single-gate + high-slgfit_arm sun.  r.g and r.dm
            # stay on the row untouched -- nothing on the page reads them now, but
            # the exports and app.py still do.
            "ag": int(agrows[i]),
            "sg": list(agsigs[i]),   # NIKKO-SIGWIRE: [label, family, percentile]
            # NIKKO-AGFLOOR: gates named this bat, but it sits below the confirmer
            # median where the same gates measure 5.00% against a 10.61% base.
            "agx": bool(_agout[i]),
            "agw": list(agnames[i]),
            "sun": bool(agsun[i]),
            # NIKKO-LINEUPTAG: ["lineup", "<slot>"] | ["roster", ""] | []
            "lu": _lutag(i),
            "c": int(_num(d, cconf).fillna(0).iloc[i]) if cconf else 0,
            "f": str(d[cflag].iloc[i]) if cflag and d[cflag].iloc[i] == d[cflag].iloc[i] else "",
            # NIKKO-ALIGNBAND: ladder rung + the measured reads firing for THIS bat
            "lad": _ladtxt(i),
            "pr": _read_hits[i],
            "np": _n_read,
            "stk": _stk(i),          # NIKKO-WHATALIGNS
            "sof": _stk_of,
            "d": det, "x": txt,
        })

    # --- NIKKO-GAMESPLIT: a stable per-GAME key.  Sorted so the home half and
    # the away half of the same game land on the SAME tile.  rows[] was appended
    # in d's row order, so index i lines up.  Absent columns -> arm name -> ALL.
    _gt = next((_c for _c in ("team", "bat_team", "Team", "TEAM", "tm")
                if _c in d.columns), None)
    _go = next((_c for _c in ("opponent", "opp_team", "opp", "OPP", "OPPONENT",
                              "opp_name", "vs_team") if _c in d.columns), None)
    _ga = next((_c for _c in ("away_team", "away", "AWAY") if _c in d.columns), None)
    _gh = next((_c for _c in ("home_team", "home", "HOME") if _c in d.columns), None)

    def _cell(_c, _i):
        try:
            _v = str(d[_c].iloc[_i]).strip().upper()
        except Exception:
            return ""
        return "" if _v in ("", "NAN", "NONE", "NAT") else _v

    for _i, _r in enumerate(rows):
        _key = ""
        # best: the board names both sides outright -> AWAY @ HOME, MLB order.
        if _ga and _gh:
            _x, _y = _cell(_ga, _i), _cell(_gh, _i)
            if _x and _y and _x != _y:
                _key = "%s @ %s" % (_x, _y)
        if not _key:
            # the row dict already carries the team the card prints as r.t --
            # use that before going back to the frame, since the frame column is
            # not always present on every render path.
            _a = str(_r.get("t") or "").strip().upper()
            if _a in ("", "NAN", "NONE"):
                _a = _cell(_gt, _i) if _gt else ""
            _b = _cell(_go, _i) if _go else ""
            if _a and _b and _a != _b:
                _key = "%s @ %s" % _gk_order(_a, _b)   # NIKKO-GAMEKEY
            elif _a:
                # one team on this frame (a single-game board) -- still a tile,
                # named for the team rather than for each arm.
                _key = _a
        if not _key:
            _key = str(_r.get("o", "")).strip() or "ALL"
        _r["gm"] = _key
    # --- end NIKKO-GAMESPLIT ---
    # ===================== NIKKO-SGBEST90 =====================
    # _sb_draw reads r.sg -- a per-row list of [chipkey, glyphclass] -- and NOT
    # the flag columns. So a chip is registered HERE, after every row exists and
    # right before the template is filled. rows[] was appended in d's row order,
    # so index i lines up, exactly as NIKKO-GAMESPLIT relies on.
    #
    # No pandas: this file does not import it. Plain lists and a sorted cut.
    # bat_best_slg is ranked WITHIN this frame, so p90 is this board's top tenth
    # and a bat with no cell (arm not in the pitch cache) can never qualify.
    try:
        _b9c = "bat_best_slg" if "bat_best_slg" in list(d.columns) else None
        if _b9c and len(rows) == len(d):
            _b9v = []
            for _b9x in list(d[_b9c]):
                try:
                    _b9v.append(float(_b9x))
                except Exception:
                    _b9v.append(None)
            _b9s = sorted([_v for _v in _b9v if _v is not None and _v == _v])
            if len(_b9s) >= 10:
                _b9cut = _b9s[int(round(0.90 * (len(_b9s) - 1)))]
                # inherit a glyph class from a row that already carries a chip,
                # so the new chip is styled like every other one
                _b9g = ""
                for _b9r in rows:
                    _b9sg = _b9r.get("sg") or []
                    if _b9sg:
                        try:
                            _b9g = _b9sg[0][1]
                        except Exception:
                            _b9g = ""
                        break
                _b9hit = 0
                for _b9i in range(len(rows)):
                    _b9x = _b9v[_b9i]
                    if _b9x is None or _b9x != _b9x or _b9x < _b9cut:
                        continue
                    _b9r = rows[_b9i]
                    _b9sg = _b9r.get("sg")
                    if not isinstance(_b9sg, list):
                        _b9sg = []
                        _b9r["sg"] = _b9sg
                    if not any((isinstance(_e, (list, tuple)) and _e
                                and _e[0] == "Best90") for _e in _b9sg):
                        # NIKKO-SGPCT: sg is [label, family, percentile] -- the card prints x[2].
                        # Two elements rendered "Best90undefined" on every card. _b9s is already
                        # sorted, so the percentile is a bisect, not another pass over the board.
                        _b9lo = 0
                        _b9hi = len(_b9s)
                        while _b9lo < _b9hi:
                            _b9md = (_b9lo + _b9hi) // 2
                            if _b9s[_b9md] <= _b9x:
                                _b9lo = _b9md + 1
                            else:
                                _b9hi = _b9md
                        _b9sg.append(["Best90", _b9g,
                                      int(round(100.0 * _b9lo / len(_b9s)))])
                        _b9hit += 1
                print("[best90] %d bat(s) at p90+ on best pitch x his bat "
                      "(cut %.4f of %d valued)" % (_b9hit, _b9cut, len(_b9s)))
            else:
                print("[best90] only %d bat(s) carry bat_best_slg -- no chip"
                      % len(_b9s))
        else:
            print("[best90] bat_best_slg not on the frame (%d col(s)) -- no chip"
                  % len(list(d.columns)))
    except Exception as _b9e:
        try:
            print("[swallow] NIKKO-SGBEST90 %s" % _b9e)
        except Exception:
            pass
    # ===================== end NIKKO-SGBEST90 =====================
    return _TPL.replace("__ROWS__", _json.dumps(rows)) \
               .replace("__TITLE__", _html.escape(str(title))) \
               .replace("__NALL__", str(n_all)) \
               .replace("__NSHOW__", str(len(d))) \
               .replace("__HASCONF__", "1" if cconf else "0") \
               .replace("__HASTBT__", "1" if ctbt else "0") \
               .replace("__HASHRR__", "1" if chrr else "0") \
               .replace("__SIGMETA__", _json.dumps(SIGMETA)) \
               .replace("__SIGX__", _json.dumps(SIGX)) \
               .replace("__HASLANE__", "1" if clane else "0") \
               .replace("__HASBAND__", "1" if cband else "0")


_TPL = r"""<!doctype html><meta charset="utf-8">
<link rel=preconnect href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600;700&display=swap" rel=stylesheet>
<style>
:root{--bg:#07080b;--pn:#0d0f14;--el:#12151c;--ln:#1c2029;--ln2:#252b36;
--tx:#eef1f6;--dm:#8d95a5;--mu:#5a616f;--ac:#4c8dff;--ac2:#8b5cf6;--ok:#22d17c;--hot:#ffb020;
--sans:'Inter',ui-sans-serif,system-ui,-apple-system,sans-serif;
--mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:radial-gradient(900px 480px at 10% -10%,#17203a 0%,transparent 60%),
 radial-gradient(700px 420px at 92% -6%,#2a1840 0%,transparent 56%),var(--bg);
 color:var(--tx);font-family:var(--sans);font-size:13.5px;-webkit-font-smoothing:antialiased}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.hd{padding:12px 16px 10px;border-bottom:1px solid var(--ln);display:flex;
 align-items:center;gap:14px;flex-wrap:wrap;
 background:linear-gradient(180deg,rgba(7,8,11,.95),rgba(7,8,11,.7));backdrop-filter:blur(12px)}
.mk{width:20px;height:20px;border-radius:6px;flex:none;
 background:linear-gradient(135deg,var(--ac),var(--ac2));
 box-shadow:0 0 18px rgba(76,141,255,.55),inset 0 1px 0 rgba(255,255,255,.3)}
h1{margin:0;font-size:12px;letter-spacing:.18em;font-weight:800;
 background:linear-gradient(92deg,#fff,#9db8ff 60%,#c4a5ff);
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.tiles{display:flex;gap:8px;margin-left:auto;flex-wrap:wrap}
.tl{background:linear-gradient(160deg,var(--el),rgba(13,15,20,.5));border:1px solid var(--ln);
 border-radius:8px;padding:5px 10px;min-width:64px;position:relative;overflow:hidden}
.tl:after{content:'';position:absolute;inset:0 0 auto;height:1px;
 background:linear-gradient(90deg,transparent,rgba(120,160,255,.4),transparent)}
.tk{font-size:8px;letter-spacing:.13em;color:var(--mu);font-weight:700}
.tv{font-size:15px;font-weight:800;margin-top:1px}
#q{background:var(--el);border:1px solid var(--ln2);border-radius:8px;color:var(--tx);
 padding:6px 11px;font:12px var(--sans);outline:none;width:190px}
#q:focus{border-color:var(--ac);box-shadow:0 0 0 3px rgba(76,141,255,.14)}
.gs{display:flex;flex-wrap:wrap;gap:6px;padding:8px 0 10px}
.gs .gt{background:#11161d;border:1px solid #2b3440;border-radius:7px;color:#adbac7;
 font:600 11px/1.25 inherit;letter-spacing:.04em;padding:6px 10px;cursor:pointer;
 display:flex;flex-direction:column;align-items:flex-start;gap:2px;min-width:96px}
.gs .gt:hover{border-color:#3d4b5c;color:#e6edf3}
.gs .gt.on{border-color:#1f6feb;color:#79c0ff;background:#0e1a2b}
.gs .gt b{font-weight:700;font-size:13px;color:#e6edf3}
.gs .gt.on b{color:#79c0ff}
.gs .gt i{font-style:normal;font-size:9px;color:#6e7681;letter-spacing:.02em}
.wrap{height:calc(100% - 46px);overflow:auto}
table{width:100%;border-collapse:separate;border-spacing:0 5px;padding:0 10px 30px}
th{text-align:left;font-size:8.5px;letter-spacing:.13em;color:var(--mu);font-weight:700;
 padding:9px 9px 6px;position:sticky;top:0;background:var(--bg);z-index:5;cursor:pointer;
 white-space:nowrap;user-select:none}
th:hover{color:var(--dm)}
th.s:after{content:' \25BE';color:var(--ac)}
th.sa:after{content:' \25B4';color:var(--ac)}
tr.r td{background:linear-gradient(160deg,var(--pn),rgba(13,15,20,.45));
 border-top:1px solid var(--ln);border-bottom:1px solid var(--ln);padding:13px 11px;
 transition:background .15s}
tr.r td:first-child{border-left:1px solid var(--ln);border-radius:9px 0 0 9px;
 position:sticky;left:0;z-index:2}
tr.r td:last-child{border-right:1px solid var(--ln);border-radius:0 9px 9px 0}
tr.r{cursor:pointer}
tr.r:hover td{background:linear-gradient(160deg,#151922,rgba(21,25,34,.55))}
tr.r.fire td{background:linear-gradient(160deg,rgba(18,32,26,.9),rgba(13,15,20,.5))}
tr.r.fire td:first-child{box-shadow:inset 3px 0 0 var(--ok),-5px 0 20px -6px rgba(34,209,124,.75)}
tr.r.open td{background:linear-gradient(160deg,#161a24,rgba(22,26,36,.6))}
.nm{font-weight:700;font-size:14px;letter-spacing:.01em}
.tm{color:var(--mu);font-size:10px;margin-left:7px;font-weight:700;letter-spacing:.1em}
.op{color:var(--dm);font-size:10.5px}
.chip{display:inline-block;padding:2px 8px;border-radius:20px;font-size:8.5px;
 letter-spacing:.09em;font-weight:700;border:1px solid var(--ln2);color:var(--dm);white-space:nowrap}
.CHALK,.PREMIUM{color:#9db8ff;border-color:#2c3f6b;background:rgba(76,141,255,.09)}
.MID,.MIDDLE,.BALANCED{color:#7ee2c0;border-color:#1f5546;background:rgba(34,209,124,.08)}
.VALUE{color:#ffd18a;border-color:#5d4620;background:rgba(255,176,32,.08)}
.LONG,.LONGSHOT{color:#d0a5ff;border-color:#472f6b;background:rgba(139,92,246,.1)}
.fires{color:#22d17c;border-color:#1f6b45;background:rgba(34,209,124,.13);
 box-shadow:0 0 13px -3px rgba(34,209,124,.55)}
.tbt{color:#9db8ff;border-color:#2c3f6b;background:rgba(76,141,255,.07);
 font-family:var(--mono);font-size:8px}
.ELITE{color:#ffce5c;border-color:#6b5420;background:rgba(255,176,32,.11);
 box-shadow:0 0 12px -4px rgba(255,176,32,.7)}
.GREAT{color:#7ee2c0;border-color:#1f5546;background:rgba(34,209,124,.09)}
.GOOD{color:#9db8ff;border-color:#2c3f6b;background:rgba(76,141,255,.08)}
.dia{color:#ffce5c;border-color:#6b5420;background:rgba(255,176,32,.13);
 box-shadow:0 0 13px -3px rgba(255,176,32,.6)}
.hp{font-weight:800;font-size:14px}
/* NIKKO-ALIGNDRAWER */
.alg{display:inline-flex;align-items:center;gap:6px;padding:3px 9px 3px 7px;border-radius:8px;
 border:1px solid var(--ln2);background:rgba(255,255,255,.03);line-height:1}
.alg b{font-size:15px;font-weight:800}
.alg i{font-style:normal;font-size:7.5px;letter-spacing:.14em;font-weight:800;color:var(--mu)}
.alg.a0{opacity:.32}
.alg.a0 b{color:var(--mu)}
.alg.a1{border-color:#2c3f6b;background:rgba(76,141,255,.08)}
.alg.a1 b{color:#9db8ff}
.alg.a3{border-color:#5d4620;background:rgba(255,176,32,.11);box-shadow:0 0 13px -4px rgba(255,176,32,.6)}
.alg.a3 b,.alg.a3 i{color:#ffd18a}
.alg.a5{border-color:#6b5420;background:linear-gradient(135deg,rgba(255,176,32,.2),rgba(255,206,92,.07));
 box-shadow:0 0 18px -4px rgba(255,176,32,.85)}
.alg.a5 b,.alg.a5 i{color:#ffce5c}
.nof{color:var(--mu);font-size:11px}
.grd{font-size:8.5px;font-weight:800;letter-spacing:.04em;margin-left:6px;color:var(--ok)}
.inv{font-size:8px;font-weight:800;letter-spacing:.1em;margin-left:6px;color:var(--hot)}
.unv{font-size:8px;font-weight:700;letter-spacing:.1em;margin-left:6px;color:var(--mu)}
.rw.u0 .rl,.rw.u0 .rv{color:var(--mu);opacity:.62}
.fl.bad{background:linear-gradient(90deg,#8a4a1a,var(--hot));box-shadow:0 0 8px rgba(255,176,32,.45)}
.lgd{grid-column:1/-1;border-top:1px solid var(--ln);margin-top:4px;padding-top:9px;
 font-size:9.5px;color:var(--mu);line-height:1.6}
/* NIKKO-ALIGNBAND -- the band that leads every drawer. Rounded to match .pan's top
   corners, because .pan is not overflow:hidden. */
.algband{padding:12px 16px 12px;border-bottom:1px solid var(--ln);border-radius:10px 10px 0 0;
 background:linear-gradient(180deg,rgba(76,141,255,.06),transparent)}
.abhead{display:flex;align-items:center;gap:11px;flex-wrap:wrap}
.abt{font-size:8.5px;letter-spacing:.16em;color:var(--mu);font-weight:800}
.abl{color:#ffd18a;border:1px solid #5d4620;background:rgba(255,176,32,.1);font-size:8.5px}
.abl b{font-family:var(--mono);color:var(--ok);margin-left:6px;font-weight:700}
.abn{font-size:9.5px;color:var(--mu);margin-left:auto;white-space:nowrap}
.abchips{display:flex;gap:5px;flex-wrap:wrap;margin-top:9px}
.abpairs{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px}
.abp{font-size:9.5px;padding:2.5px 8px;border-radius:6px;color:#7ee2c0;
 border:1px solid #1f5546;background:rgba(34,209,124,.08);white-space:nowrap}
.abp b{color:var(--ok);font-weight:800;margin-left:6px;font-family:var(--mono)}
.abnone{font-size:10px;color:var(--mu);margin-top:8px;opacity:.75}
/* NIKKO-WHATALIGNS */
.abwa{margin-top:11px;border-top:1px solid var(--ln);padding-top:9px}
.abwt{font-size:8.5px;letter-spacing:.15em;color:var(--mu);margin:0 0 7px;font-weight:800;
 display:flex;align-items:center;gap:10px}
.abwn{font-family:var(--mono);color:var(--dm);letter-spacing:0;font-size:9.5px;font-weight:600}
.abrow{display:grid;grid-template-columns:1fr 14px 1fr;align-items:center;gap:8px;
 max-width:560px;padding:2.5px 0}
.abside{display:flex;align-items:center;justify-content:space-between;gap:8px;
 font-size:10.5px;color:var(--dm);background:rgba(255,255,255,.03);
 border:1px solid var(--ln);border-radius:6px;padding:3px 9px}
.abside b{color:var(--tx);font-weight:700;font-size:10px}
.abx{font-size:9px;color:var(--mu);text-align:center;font-weight:700}
/* NIKKO-PAIRLABEL */
.abu{font-size:9px;color:var(--mu);margin-left:-4px}
.abwt2{font-size:8.5px;letter-spacing:.15em;color:var(--mu);margin:12px 0 6px;font-weight:800;
 display:flex;align-items:center;gap:10px;border-top:1px solid var(--ln);padding-top:9px}
.pip{width:4.5px;height:4.5px;border-radius:50%;background:var(--ln2);display:inline-block;margin-right:2px}
.pip.on{background:linear-gradient(135deg,var(--ok),#7ee2c0);box-shadow:0 0 6px rgba(34,209,124,.85)}
/* NIKKO-WHATALIGNS: was nowrap + overflow:hidden + max-width:330px, which is what
   forced the +2. Wraps to a second line now and clips nothing. */
.sig{display:flex;gap:4px;flex-wrap:wrap;max-width:none;align-items:center}
.sg{font-size:9.5px;padding:1.5px 6px;border-radius:5px;background:rgba(255,255,255,.045);
 border:1px solid var(--ln2);color:var(--dm);white-space:nowrap;flex:none;line-height:1.35}
.more{font-size:9px;color:var(--dm);flex:none;font-weight:700;padding:1.5px 5px;border-radius:5px;
 background:rgba(76,141,255,.12);border:1px solid #2c3f6b;line-height:1.35}
.txr{display:flex;justify-content:space-between;gap:10px;padding:3px 0;font-size:11px}
.txr b{color:var(--mu);font-weight:600}
.dr td{padding:0;background:transparent!important;border:0!important;box-shadow:none!important}
.pan{margin:-1px 0 6px;border:1px solid var(--ln2);border-radius:11px;
 background:linear-gradient(165deg,#0f131b,rgba(10,12,17,.92));
 box-shadow:0 16px 40px -18px rgba(0,0,0,.9)}
.pg{padding:14px 16px;display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px 22px}
/* NIKKO-DRAWERREF: the panel is two columns now -- reads left, reference right. The rail
   is flex:none so it never steals width from the reads, and it drops underneath them
   below 1150px instead of squeezing them. */
/* NIKKO-LAYOUT2: the band is the two-column row; the body is one full-width grid. */
.algwrap{display:flex;align-items:stretch;border-bottom:1px solid var(--ln);
 border-radius:10px 10px 0 0;background:linear-gradient(180deg,rgba(76,141,255,.06),transparent)}
.algleft{flex:1 1 58%;min-width:0}
.algright{flex:0 1 42%;min-width:270px;max-width:520px;border-left:1px solid var(--ln)}
.algwrap .algband{border-bottom:0;background:none;border-radius:0}
.algwrap .pref{width:auto;border-left:0;background:none;padding:12px 16px 14px}
@media(max-width:1250px){.algwrap{flex-wrap:wrap}
 .algright{flex-basis:100%;max-width:none;border-left:0;border-top:1px solid var(--ln)}}
.pbody{display:block}
.pbody>.pg{flex:1;min-width:0}
.pref{flex:none;width:250px;border-left:1px solid var(--ln);padding:13px 14px 15px;
 background:rgba(255,255,255,.012)}
.prt{font-size:8.5px;letter-spacing:.15em;color:var(--mu);font-weight:800;margin:0 0 2px;
 display:flex;flex-direction:column;gap:3px}
.prt span{letter-spacing:0;font-weight:500;font-size:9px;opacity:.8;font-family:var(--mono)}
.prh{font-size:8px;letter-spacing:.14em;color:var(--ac);font-weight:800;
 margin:13px 0 5px;opacity:.85}
.prf{display:grid;grid-template-columns:auto 1fr;gap:0 7px;padding:3px 0;font-size:10px;
 border-bottom:1px solid rgba(255,255,255,.04)}
.prf b{color:var(--tx);font-weight:700;font-size:10.5px}
/* NIKKO-SIGICON: fixed width so the names stay in a column and the row still
   scans as a list rather than as ragged text. */
.prfi{display:inline-block;width:14px;margin-right:5px;font-size:11px;
 line-height:1;text-align:center;vertical-align:-1px}
.prf u{justify-self:end;text-decoration:none;color:var(--ok);font-family:var(--mono);
 font-size:9.5px;font-weight:700}
.prf i{grid-column:1/-1;font-style:normal;color:var(--dm);line-height:1.4}
.prf.off b{color:var(--mu)}
.prg{display:flex;align-items:baseline;justify-content:space-between;gap:8px;
 font-size:10px;color:var(--dm);padding:2.5px 0;flex-wrap:wrap}
.prg b{font-weight:600;color:var(--tx)}
.prg u{text-decoration:none;color:var(--ok);font-family:var(--mono);font-size:9.5px;
 font-weight:700}
.prg i{flex-basis:100%;font-style:normal;font-size:9px;color:var(--mu)}
.prp{font-size:9.5px;color:var(--dm);line-height:1.55}
.prp span{display:block;margin-top:4px}
.prp b{color:var(--tx);font-weight:700}
.prn{font-size:9.5px;color:var(--mu)}
/* NIKKO-LAYOUT2 */
.prmore{margin-top:12px;border-top:1px solid var(--ln);padding-top:8px}
.prmore>summary{cursor:pointer;list-style:none;font-size:9px;letter-spacing:.12em;
 color:var(--mu);font-weight:800;text-transform:uppercase}
.prmore>summary::-webkit-details-marker{display:none}
.prmore>summary:before{content:'\25B8  ';color:var(--ac)}
.prmore[open]>summary:before{content:'\25BE  '}
.prmore>summary:hover{color:var(--tx)}
@media(max-width:1150px){.pbody{flex-wrap:wrap}
 .pref{width:100%;border-left:0;border-top:1px solid var(--ln)}}
.wide{grid-column:1/-1;border-top:1px solid var(--ln);padding-top:8px;margin-top:2px}
.wide .cols{column-count:5;column-gap:22px;padding-top:4px}
.wide .rw{break-inside:avoid;-webkit-column-break-inside:avoid}
@media(max-width:1150px){.wide .cols{column-count:3}}
@media(max-width:760px){.wide .cols{column-count:2}}
/* the engine internals and the raw board fields open on demand -- the four scouting
   groups above them are what a threshold gets eyeballed on, and they fit on one screen. */
summary{list-style:none;cursor:pointer;font-size:8.5px;letter-spacing:.15em;color:var(--mu);
 font-weight:800;display:flex;align-items:center;gap:7px;padding:2px 0}
summary::-webkit-details-marker{display:none}
summary:hover{color:var(--dm)}
summary:before{content:'\25B8';font-size:9px;color:var(--ac);transition:transform .15s}
details[open]>summary:before{transform:rotate(90deg)}
summary:after{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--ln2),transparent)}
summary .cnt{letter-spacing:.06em;color:var(--mu);font-weight:700}
.gg{font-size:8.5px;letter-spacing:.15em;color:var(--mu);margin:0 0 6px;font-weight:800;
 display:flex;align-items:center;gap:7px}
.gg:after{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--ln2),transparent)}
.rw{padding:3px 0}
.rt{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.rl{color:var(--dm);font-size:11px}
.rv{font-size:11.5px;font-weight:700;white-space:nowrap}
.pv{color:var(--mu);font-size:9.5px;margin-left:6px;font-weight:600}
.bar{height:2.5px;border-radius:2px;background:var(--ln);margin-top:4px;overflow:hidden}
.fl{height:100%;border-radius:2px;background:linear-gradient(90deg,#2f5fa8,var(--ac));
 transition:width .45s cubic-bezier(.2,.8,.2,1)}
.fl.hi{background:linear-gradient(90deg,#1f8f58,var(--ok));box-shadow:0 0 8px rgba(34,209,124,.55)}
.fl.top{background:linear-gradient(90deg,#a8791f,var(--hot));box-shadow:0 0 8px rgba(255,176,32,.6)}
/* ===================== NIKKO-READLIT =====================
   A row a firing read gates on.  The label brightens, the bar takes the
   read colour, and the tag names which read wants it.  Read-lit is a
   different thing from the p90 bar colour, so it does not reuse it. */
.rw.rdlit .rl{color:var(--tx);font-weight:700}
.rw.rdlit .bar{background:rgba(139,92,246,.20)}
.rw.rdlit .fl{background:linear-gradient(90deg,#6d3fd4,var(--ac2));
 box-shadow:0 0 9px rgba(139,92,246,.65)}
.rdt{display:inline-block;margin-left:6px;padding:0 4px;border-radius:3px;
 background:rgba(139,92,246,.22);color:#c9b6ff;font-size:8.5px;
 font-weight:800;letter-spacing:.04em;vertical-align:1px}
/* =================== end NIKKO-READLIT =================== */
/* ===================== NIKKO-RAILREADS =====================
   THE READS in the rail.  Narrow column, same row furniture as the
   grid, tighter leading so eighteen rows sit under the chips without
   pushing the note off the card. */
.rrp{margin:2px 0 10px}
.rrp .rw{padding:2px 0}
.rrp .rl{font-size:10.5px}
.rrp .rv{font-size:11px}
.rrp .bar{margin-top:3px}
/* =================== end NIKKO-RAILREADS =================== */
.fz{grid-column:1/-1;border-top:1px solid var(--ln);padding-top:10px;font-size:11px;color:var(--dm)}
.empty{padding:26px;text-align:center;color:var(--mu)}
/* ===================== NIKKO-LAYOUT2 =====================
   THIS BLOCK IS LAST ON PURPOSE. Every selector below is also defined earlier in this
   stylesheet, and CSS takes the last rule of equal specificity -- so putting these up
   beside body{} (the obvious place) would have changed nothing at all. Verified in a
   real browser: with the block up top, .gg still computed 8.5px and .abrow still 560px.
   Each rule only raises a size or a spacing. No selector gains or loses a property. */
.gg{font-size:9.5px}
.rl{font-size:12px}
.rv{font-size:12.5px}
.pv{font-size:10.5px}
.grd,.inv,.unv{font-size:9.5px}
.abt{font-size:9.5px}
.abn{font-size:10.5px}
.abwt,.abwt2{font-size:9.5px}
.abwn{font-size:10.5px}
.abside{font-size:11.5px;padding:4px 10px}
.abside b{font-size:11px}
.abp{font-size:10.5px;padding:3px 9px}
.abchips .sg,.sig .sg{font-size:10.5px;padding:2.5px 7px}
.abrow{max-width:none;padding:3px 0;grid-template-columns:1fr 16px 1fr}
.prt{font-size:9.5px}
.prt span{font-size:10px}
.prh{font-size:9px;margin:14px 0 6px}
.prf{font-size:11px;padding:4px 0}
.prf b{font-size:11.5px}
.prf u{font-size:10.5px}
.prg{font-size:11px;padding:3px 0}
.prg u{font-size:10.5px}
.prg i{font-size:10px}
.prp{font-size:10.5px;line-height:1.6}
.prn{font-size:10.5px}
.lgd{font-size:10.5px}
.fz{font-size:12px}
.nof{font-size:12px}
.pg{gap:12px 26px;grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
/* ===================== end NIKKO-LAYOUT2 ===================== */
/* ===================== NIKKO-LAYOUT3 =====================
   Also last on purpose -- see the note above. Everything here is geometry. */
/* flags and measured reads on one row */
.abtop{display:flex;align-items:flex-start;gap:18px;flex-wrap:wrap;margin-top:9px}
.abtop>.abchips{margin-top:0;flex:1 1 auto;min-width:0}
.abreads{flex:0 1 auto;max-width:60%;min-width:220px;margin-left:auto}
.abreads .abwt2{margin:0 0 5px;border-top:0;padding-top:0}
.abreads .abpairs{margin-top:0}
.abreads .abnone{margin-top:0}
/* pairs in columns, each sized to what it holds -- not one 1226px line per pair */
.abgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(400px,1fr));
 gap:4px 20px;margin-top:2px}
.abrow{max-width:none;padding:0;grid-template-columns:1fr 14px 1fr}
/* the reference reads left to right instead of running past the fold */
.pref{column-count:2;column-gap:22px;column-fill:balance}
.pref>*{break-inside:avoid-column;-webkit-column-break-inside:avoid}
.pref .prt{column-span:all;margin-bottom:8px}
.prmore{column-span:all}
@media(max-width:1500px){.pref{column-count:1}}
/* and a little more room for it, now that it is two columns */
.algleft{flex:1 1 54%}
.algright{flex:1 1 46%;max-width:820px}
/* ===================== NIKKO-DRAWBOLD =====================
   Third override block, same reason as LAYOUT2 and LAYOUT3 above: CSS takes the
   last rule of equal specificity, so this has to sit at the bottom of the sheet
   to beat the earlier .rl / .rv / .pv / .gg / .nm declarations. Sizes, weights
   and colour only -- no selector changes layout flow. */
.gg{font-size:11px;color:#8b96a3;letter-spacing:.13em}
.rl{font-size:13px;color:#9aa6b2;font-weight:600}
.rv{font-size:14.5px;font-weight:800;letter-spacing:.005em}
.pv{font-size:11.5px;font-weight:700;color:#79838f}
.rw{padding:4px 0}
.bar{height:4px;border-radius:3px;margin-top:5px}
.fl{border-radius:3px}
.fl.hi{box-shadow:0 0 11px rgba(34,209,124,.7)}
.fl.top{box-shadow:0 0 11px rgba(255,176,32,.75)}
.rw.u0 .rl,.rw.u0 .rv{opacity:.55}
/* the names get some flash -- a sheen across the text, nothing structural */
.nm{font-size:16.5px;font-weight:800;letter-spacing:.005em;
 background:linear-gradient(92deg,#ffffff 0%,#dfe8f2 46%,#a8bdd4 100%);
 -webkit-background-clip:text;background-clip:text;
 -webkit-text-fill-color:transparent;color:#e9eff5;
 text-shadow:0 0 18px rgba(150,190,235,.16)}
.tm{font-size:11px}
.hp{font-size:15.5px;font-weight:800}
.prf b{font-size:12.5px}
.prg b{font-size:12px}
/* ===================== end NIKKO-DRAWBOLD ===================== */
/* ===================== end NIKKO-LAYOUT3 ===================== */
/* ===================== NIKKO-AGREEFLAG =====================
   Appended last on purpose, same reason as LAYOUT2 / LAYOUT3 / DRAWBOLD above:
   equal specificity, last rule wins, so these override the row and chip rules
   defined earlier in the sheet without having to edit them in place. */
.agb{display:inline-flex;align-items:center;margin-left:7px;padding:1px 6px;
 border-radius:6px;font-family:var(--mono);font-size:10px;font-weight:800;
 letter-spacing:.05em;vertical-align:2px;line-height:1.5}
.agb.a3{color:#241703;background:linear-gradient(93deg,#ffb020,#ffd97a);
 box-shadow:0 0 15px rgba(255,176,32,.62)}
.agb.a2{color:#041a0f;background:linear-gradient(93deg,#22d17c,#69f0b0);
 box-shadow:0 0 13px rgba(34,209,124,.5)}
.agb.a1{color:#9db6d2;background:rgba(76,141,255,.13);border:1px solid #2e4870;
 box-shadow:none}
/* NIKKO-LINEUPTAG: LU n = card posted, batting n.  PROJ = active roster. */
.nklu{margin-left:6px;font-size:10px;font-weight:800;letter-spacing:.06em;
 padding:1px 5px;border-radius:3px;vertical-align:2px;font-family:ui-monospace,
 SFMono-Regular,Menlo,monospace}
.nklu.lin{color:#7ef0b4;background:rgba(46,220,140,.12);border:1px solid #2c6b4c}
.nklu.prj{color:#8f9dae;background:rgba(140,158,178,.10);border:1px solid #3a4652}
.sunm{margin-left:6px;font-size:13px;line-height:1;vertical-align:1px;color:#ffc44d;
 text-shadow:0 0 8px rgba(255,196,64,.85)}
/* the rail. 2+ keeps the green it always had; 3+ takes amber so the two read apart
   at a glance from the far side of the table. */
tr.r.trip td{background:linear-gradient(160deg,rgba(40,29,9,.92),rgba(13,15,20,.5))}
tr.r.trip td:first-child{border-left:1px solid #6b5420;
 box-shadow:inset 3px 0 0 var(--hot),-5px 0 24px -6px rgba(255,176,32,.85)}
tr.r.trip:hover td{background:linear-gradient(160deg,#241a09,rgba(30,24,12,.6))}
/* the name flare. .nm is a clipped gradient since DRAWBOLD, so the colour has to be
   set as a background here -- a plain `color` would be painted over by the clip. */
tr.r.fire .nm{background:linear-gradient(92deg,#ffffff 0%,#b9f2d5 44%,#4ee29a 100%);
 -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
 text-shadow:0 0 20px rgba(34,209,124,.34)}
tr.r.trip .nm{background:linear-gradient(92deg,#fffaf0 0%,#ffdf9c 40%,#ffb020 100%);
 -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;
 text-shadow:0 0 22px rgba(255,176,32,.45)}
/* the header tiles for the two flag counts */
.tv.ag2{color:#5ceaa4}
.tv.ag3{color:#ffc44d}
/* which gates fired, at the head of the drawer band */
.agwho{display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap;margin-left:10px;
 padding:2px 8px;border-radius:7px;font-size:9.5px;letter-spacing:.04em}
.agwho b{font-family:var(--mono);font-size:9px;letter-spacing:.13em;font-weight:800}
.agwho i{font-style:normal;font-family:var(--mono);font-size:10px;font-weight:700;
 padding:0 5px;border-radius:4px;background:rgba(0,0,0,.26)}
.agwho.a3{color:#ffd88a;background:rgba(255,176,32,.13);border:1px solid #6b5420}
.agwho.a2{color:#8df0bd;background:rgba(34,209,124,.12);border:1px solid #1f6b45}
.agwho.a1{color:#9db6d2;background:rgba(76,141,255,.1);border:1px solid #2e4870}
.agwho.a0{color:var(--mu);background:rgba(255,255,255,.03);border:1px solid var(--ln2)}
.agwho.a0 i{background:none;padding:0;font-family:inherit;font-weight:500}
/* the SIGNALS chips. var(--dm) #8d95a5 on a 4.5%-white pill was unreadable at 9.5px
   against the row gradient -- your "damn near invisible". Lifted to near-text and
   given a real border, not the same grey the text was. */
.sg{font-size:10.5px;padding:2px 7px;color:#d6dee9;font-weight:600;
 background:rgba(255,255,255,.075);border:1px solid #39414f;letter-spacing:.01em}
.abchips .sg,.sig .sg{font-size:11px;padding:3px 8px;font-weight:600}
tr.r.fire .sg{color:#e7efe9;border-color:#2f5c45;background:rgba(34,209,124,.09)}
tr.r.trip .sg{color:#f3ead9;border-color:#6b5420;background:rgba(255,176,32,.1)}
.nof{color:#6f7887}
/* ===================== end NIKKO-AGREEFLAG ===================== */
/* ===================== NIKKO-DRAWTRIM =====================
   Last block in the sheet, same last-rule-wins reason as LAYOUT2 / LAYOUT3 /
   DRAWBOLD / AGREEFLAG above. */

/* --- the rail travels the whole panel --------------------------------------
   .algwrap wrapped the band ONLY, so .algright had nothing to be sticky inside
   -- roughly 180px of travel while the scouting groups ran full-width below it.
   display:contents dissolves the wrapper and promotes .algleft and .algright to
   grid items of .pan, so the rail can span both rows and run the panel's full
   height. Nothing moves in the DOM. */
.pan{display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,372px);
 align-items:start}
.algwrap{display:contents}
.algleft{grid-column:1;grid-row:1;min-width:0;border-bottom:1px solid var(--ln)}
.algright{grid-column:2;grid-row:1/span 2;min-width:0;max-width:none;
 border-left:1px solid var(--ln);border-top:0;height:100%}
.pbody{grid-column:1;grid-row:2;min-width:0}
/* LAYOUT3 set .pref{column-count:2} back when the rail was a wide 46% half of the
   band. In a 340px column that splits it into two ~150px sub-columns and every
   label wraps mid-word. One column. */
/* NIKKO-DRAWERSTICK: the drawer's top band -- the bat's name, team and tonight's arm, the
   UNIONS / PAIRS chips -- stays pinned under the column header while that drawer is in view.
   .algleft is a grid item of .pan (the whole drawer), so it travels the drawer's full height,
   exactly as the WHAT MATTERS rail (.pref) already does at the same 34px offset. */
.algleft{position:sticky;top:34px;z-index:150;background:var(--pn)}
@media(max-width:1250px){.algleft{position:static}}
.algwrap .pref{position:sticky;top:34px;width:auto;border-left:0;background:none;
 padding:11px 14px 13px;max-height:calc(100vh - 130px);overflow-y:auto;
 overscroll-behavior:contain;column-count:1;column-gap:normal}
.algwrap .pref .prt,.algwrap .pref .wmt{column-span:none}
.algwrap .pref::-webkit-scrollbar{width:6px}
.algwrap .pref::-webkit-scrollbar-thumb{background:#2b3440;border-radius:3px}
@media(max-width:1250px){
 .pan{display:block}
 .algwrap{display:flex;flex-wrap:wrap}
 .algright{flex-basis:100%;border-left:0;border-top:1px solid var(--ln)}
 .algwrap .pref{position:static;max-height:none;overflow:visible}}

/* --- who you clicked -------------------------------------------------------- */
.abnm{margin:0 0 9px;font-size:15px;font-weight:800;letter-spacing:.005em;color:#eef4fa;
 display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
.abnmt{font-size:10.5px;font-weight:600;color:var(--dm);letter-spacing:.04em}
tr.r.fire .abnm{color:#b9f2d5}
tr.r.trip .abnm{color:#ffdf9c}

/* --- WHAT MATTERS ----------------------------------------------------------- */
.wmt{font-size:8.5px;letter-spacing:.15em;color:var(--mu);font-weight:800;margin:0 0 3px;
 display:flex;justify-content:space-between;align-items:baseline;gap:8px;
 white-space:nowrap}
.wmt span{letter-spacing:0;font-weight:500;font-size:9px;opacity:.75;font-family:var(--mono)}
.wmh{font-size:8px;letter-spacing:.14em;color:var(--ac);font-weight:800;margin:12px 0 5px;
 opacity:.9}
.wmh:first-of-type{margin-top:9px}
.wmv{display:grid;grid-template-columns:1fr auto;gap:1px 8px;padding:7px 10px;
 white-space:nowrap;
 border-radius:8px;border:1px solid var(--ln2);background:rgba(255,255,255,.02)}
.wmv b{font-family:var(--mono);font-size:11px;font-weight:800;letter-spacing:.07em}
.wmv u{text-decoration:none;font-family:var(--mono);font-size:13px;font-weight:800;
 justify-self:end}
.wmv i{grid-column:1/-1;font-style:normal;font-size:9.5px;color:var(--dm);line-height:1.4;
 margin-top:2px;white-space:normal}
.wmv.a3{border-color:#6b5420;background:rgba(255,176,32,.1)}
.wmv.a3 b,.wmv.a3 u{color:#ffc44d}
.wmv.a2{border-color:#1f6b45;background:rgba(34,209,124,.09)}
.wmv.a2 b,.wmv.a2 u{color:#5ceaa4}
.wmv.a1{border-color:#2e4870;background:rgba(76,141,255,.07)}
.wmv.a1 b,.wmv.a1 u{color:#9dc0ee}
.wmv.a0 b,.wmv.a0 u{color:var(--mu)}

/* the four gates. dim by default, lit when the gate fires on this bat -- what it
   MISSED is as much of the read as what it hit. */
.wmg{display:grid;grid-template-columns:1fr auto auto;gap:0 7px;padding:4px 7px 4px 7px;
 border-left:2px solid var(--ln2);margin-bottom:3px;opacity:.42;white-space:nowrap}
.wmg b{font-family:var(--mono);font-size:10.5px;font-weight:800;color:var(--tx);
 letter-spacing:.05em}
.wmg u{text-decoration:none;font-family:var(--mono);font-size:10px;font-weight:700;
 color:var(--tx)}
.wmg s{text-decoration:none;font-family:var(--mono);font-size:9.5px;font-weight:700;
 color:var(--ok);min-width:34px;text-align:right}
.wmg i{grid-column:1/-1;font-style:normal;font-size:9px;color:var(--mu);line-height:1.45;
 margin-top:1px;white-space:normal}
.wmg.wmlit{opacity:1;border-left-color:var(--ok);background:rgba(34,209,124,.055)}
.wmg.wmlit b{color:#8df0bd}

/* the tier table and the chip list share one row shape */
.wmr{display:grid;grid-template-columns:1fr auto auto;gap:0 8px;align-items:baseline;
 font-size:10px;color:var(--dm);padding:2.5px 0;
 border-bottom:1px solid rgba(255,255,255,.035)}
.wmr b{font-weight:700;color:var(--tx);font-size:10.5px}
.wmr u{text-decoration:none;color:var(--ok);font-family:var(--mono);font-size:10px;
 font-weight:700}
.wmr i{font-style:normal;font-size:9px;color:var(--mu);font-family:var(--mono);
 text-align:right;white-space:nowrap}
.wmr b,.wmr u{white-space:nowrap}
.wmr.wmn b{color:var(--dm);font-weight:600}
.wmr.wmn u{color:var(--dm)}
.wmnote{margin:11px 0 0;padding-top:8px;border-top:1px solid var(--ln);
 font-size:9px;line-height:1.5;color:var(--mu)}

/* the WHAT IS ALIGNING rules are dead with the block that used them */
.abwa,.abgrid,.abrow,.abside,.abx,.abwt{display:none}
/* ===================== end NIKKO-DRAWTRIM ===================== */
/* ===================== NIKKO-SIGWIRE =====================
   Last block; same last-rule-wins reason as every override above it. */
.sg{display:inline-flex;align-items:baseline;gap:5px}
.sg b{font-family:var(--mono);font-size:9px;font-weight:700;opacity:.72;
 letter-spacing:0}
/* one colour per family, so a union is visible before a word is read */
.sgr{color:#8df0bd;border-color:#1f6b45;background:rgba(34,209,124,.1)}
.sga{color:#ffc9a0;border-color:#7a4a2a;background:rgba(255,143,92,.1)}
.sgb{color:#9dc0ee;border-color:#2e4870;background:rgba(76,141,255,.11)}
.sgm{color:#d5b3ff;border-color:#54397a;background:rgba(139,92,246,.13)}
.sgx{color:#ffd88a;border-color:#6b5420;background:rgba(255,176,32,.1)}
.sig{gap:5px}
/* ===================== end NIKKO-SIGWIRE ===================== */
/* ===================== NIKKO-HRRSHOW ===================== */
.chip.hrr{font-weight:800;letter-spacing:.07em}
.chip.hrr.prime{color:#ffc44d;border-color:#6b5420;background:rgba(255,176,32,.14)}
.chip.hrr.strong{color:#5ceaa4;border-color:#1f6b45;background:rgba(34,209,124,.12)}
.chip.hrr.mid{color:#9dc0ee;border-color:#2e4870;background:rgba(76,141,255,.11)}
/* ===================== end NIKKO-HRRSHOW ===================== */
/* ===================== NIKKO-LANECOL ===================== */
.lnr{font-family:var(--mono);font-size:12.5px;font-weight:800;color:#d5b3ff}
.lns{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:5px;
 font-family:var(--mono);font-size:9px;font-weight:800;letter-spacing:.05em;
 vertical-align:1px}
/* two different bats, two different rules -- they never share a colour */
.lns.low{color:#8df0bd;background:rgba(34,209,124,.13);border:1px solid var(--okd)}
.lns.shot{color:#ffc9a0;background:rgba(255,143,92,.13);border:1px solid #7a4a2a}
/* ===================== end NIKKO-LANECOL ===================== */
/* ===================== NIKKO-AGFLOOR ===================== */
.wmv.ax{border-color:#5c3722;background:rgba(255,143,92,.09)}
.wmv.ax b,.wmv.ax u{color:#ff9d6e}
/* ===================== end NIKKO-AGFLOOR ===================== */
/* ===================== NIKKO-PAIRSIG =====================
   The pair chips get their own colour. A pair is a bat read AND an arm read both
   clearing their cut -- a different kind of object from the single-read legs, and it
   should never be mistaken for one at a glance. */
.sgp{color:#ffe08a;border-color:#7a6320;background:rgba(255,204,64,.14);
 font-weight:700}
.sgp b{opacity:.8}
/* ===================== end NIKKO-PAIRSIG ===================== */
/* ===================== NIKKO-SIGBAR ===================== */
.sigbar{display:flex;gap:5px;flex-wrap:wrap;align-items:center;flex:1 1 auto;
 margin:0 14px;min-width:0}
.sbc{font-size:10px;padding:3px 8px;border-radius:6px;cursor:pointer;
 background:rgba(255,255,255,.05);border:1px solid #39414f;color:#d6dee9;
 font-weight:600;letter-spacing:.01em;display:inline-flex;align-items:baseline;gap:5px;
 font-family:inherit;line-height:1.5}
.sbc b{font-family:var(--mono);font-size:11px;font-weight:800}
.sbc i{font-style:normal;font-family:var(--mono);font-size:9px;opacity:.62}
.sbc:hover{border-color:#5a6472;color:#fff}
.sbc.on{outline:1px solid currentColor;outline-offset:1px;filter:brightness(1.25)}
.sbc.sgp{color:#ffe08a;border-color:#7a6320;background:rgba(255,204,64,.14)}
.sbc.sgr{color:#8df0bd;border-color:var(--okd);background:rgba(34,209,124,.1)}
.sbc.sga{color:#ffc9a0;border-color:#7a4a2a;background:rgba(255,143,92,.1)}
.sbc.sgb{color:#9dc0ee;border-color:var(--acd);background:rgba(76,141,255,.11)}
.sbc.sgm{color:#d5b3ff;border-color:#54397a;background:rgba(139,92,246,.13)}
.sbc.sgx{color:#ffd88a;border-color:var(--hotd);background:rgba(255,176,32,.1)}
/* the rail rows, one per firing chip */
.wmr.sbp u{color:#ffe08a}
.wmr.sbr u{color:#8df0bd}
.wmr.sba u{color:#ffc9a0}
.wmr.sbb u{color:#9dc0ee}
.wmr.sbm u{color:#d5b3ff}
.wmr.sbx u{color:#ffd88a}
.sbw{font-size:9px;color:var(--mu);line-height:1.4;margin:-1px 0 5px;padding-left:1px}
/* ===================== end NIKKO-SIGBAR ===================== */
/* ===================== NIKKO-UNIONBAR =====================
   Last block in the sheet -- same last-rule-wins reason as every override above. */

/* --- the band: two named groups, not one undifferentiated row --------------- */
.ubsep{font-size:7.5px;letter-spacing:.16em;font-weight:800;color:var(--mu);
 padding:0 3px 0 7px;align-self:center;white-space:nowrap;opacity:.8}
.ubsep:first-child{padding-left:0}
.abchips{display:flex;flex-wrap:wrap;gap:5px;align-items:center}
.abchips .ubsep{padding:0 2px 0 6px}
/* the sticky <th> band is position:sticky z-index:5 in the ROOT stacking context.
   .hd has backdrop-filter, which makes it a stacking context, but it is
   position:static -- so it paints in the block layer, UNDER every positioned
   element on the page, and the hover card was being sliced off at the header row.
   Positioning .hd puts its whole subtree above the sticky header. It is not
   sticky itself, so it still scrolls away and covers nothing. */
.hd{position:relative;z-index:200}
.sbc{position:relative;overflow:visible}
.sbc.ubu{padding-left:5px}
.ubg{font-size:11px;line-height:1;margin-right:1px;filter:saturate(1.15)}
.sg .ubg{font-size:10px;margin-right:2px}
.sg.ubu{font-weight:700}

/* --- the hover card. This is what replaces the reference panel: what the chip
       reads, what it pairs with, what it graded at, and why it is on the page.
       It is on a delay-free CSS hover so it appears the moment you are over the
       chip, not after the browser's own ~1s title timeout. -------------------- */
.ubp{position:absolute;top:calc(100% + 7px);left:0;z-index:120;width:330px;
 display:none;padding:11px 13px 12px;border-radius:10px;
 background:#0d1017;border:1px solid #39414f;
 box-shadow:0 18px 44px rgba(0,0,0,.72),0 0 0 1px rgba(255,255,255,.03) inset;
 text-align:left;white-space:normal;cursor:default;font-family:var(--sans)}
.sbc:hover .ubp{display:block}
.sigbar>.sbc:nth-last-child(-n+3) .ubp{left:auto;right:0}
.ubp em{display:block;font-style:normal;font-size:13px;font-weight:800;color:#eef4fa;
 letter-spacing:.01em;margin-bottom:1px}
.ubp .ubk{display:inline-block;text-decoration:none;font-size:7.5px;font-weight:800;
 letter-spacing:.15em;padding:2px 6px;border-radius:4px;margin-bottom:7px;
 border:1px solid var(--ln2);color:var(--mu)}
.ubp .ubku{color:#ffe08a;border-color:#7a6320;background:rgba(255,204,64,.13)}
.ubp .ubkl{color:#9dc0ee;border-color:var(--acd);background:rgba(76,141,255,.1)}
.ubp .ubkf{color:#ffd88a;border-color:var(--hotd);background:rgba(255,176,32,.1)}
.ubp q{display:block;quotes:none;font-family:var(--mono);font-size:10px;line-height:1.5;
 color:#cdd7e4;margin:0 0 7px;padding-bottom:7px;border-bottom:1px solid var(--ln)}
.ubp u{display:block;text-decoration:none;font-family:var(--mono);font-size:12px;
 font-weight:800;color:var(--ok);margin-bottom:5px}
.ubp .ubw{display:block;font-style:normal;font-size:10.5px;line-height:1.55;
 color:var(--dm)}
.ubp .ubh{display:block;margin-top:8px;padding-top:7px;border-top:1px solid var(--ln);
 font-size:9px;font-weight:600;color:var(--mu);font-family:var(--mono)}

/* --- the rail. It was a 300px column carrying 8px type; the numbers that matter
       most on the page were the smallest thing on it. ------------------------ */
.pan{grid-template-columns:minmax(0,1fr) minmax(364px,436px)}
.algwrap .pref{padding:13px 16px 15px}
.wmt{font-size:10px;letter-spacing:.13em;margin:0 0 6px}
.wmt span{font-size:9.5px}
.wmh{font-size:9.5px;letter-spacing:.12em;margin:15px 0 7px}
.wmv{padding:9px 12px;gap:2px 10px}
.wmv b{font-size:12.5px}
.wmv u{font-size:17px}
.wmv i{font-size:11px;line-height:1.45;margin-top:4px}
.wmg{padding:6px 9px;margin-bottom:5px;gap:0 9px}
.wmg b{font-size:12px}
.wmg u{font-size:11.5px}
.wmg s{font-size:11px;min-width:40px}
.wmg i{font-size:10.5px;line-height:1.5;margin-top:3px}
.wmnote{font-size:10px;line-height:1.6;margin-top:14px;padding-top:10px}
@media(max-width:1250px){.pan{grid-template-columns:none}}
/* ===================== end NIKKO-UNIONBAR ===================== */
/* ===================== NIKKO-SIDEPANEL =====================
   Last block in the sheet -- same last-rule-wins reason as every override above. */
:root{--lrw:248px}
body{padding-left:var(--lrw)}

/* --- the column ------------------------------------------------------------
   position:fixed, full height, its own scroll. It does not move when the board
   scrolls -- that is the whole point of it. */
#sigbar{position:fixed;left:0;top:0;bottom:0;width:var(--lrw);margin:0;
 display:block;flex:none;overflow-y:auto;overscroll-behavior:contain;
 padding:14px 12px 18px;border-right:1px solid var(--ln);
 background:linear-gradient(180deg,#0a0c11,#07080b);z-index:300}
#sigbar::-webkit-scrollbar{width:7px}
#sigbar::-webkit-scrollbar-thumb{background:#2b3440;border-radius:4px}

/* --- the two group headings ------------------------------------------------ */
#sigbar .ubsep{display:block;padding:0 0 6px 2px;margin:18px 0 8px;
 font-size:10.5px;letter-spacing:.17em;font-weight:800;color:#8fa3bb;opacity:1;
 border-bottom:1px solid var(--ln2)}
#sigbar .ubsep:first-of-type{margin-top:4px}

/* --- the rows. Bigger and bolder: 14px name, 17px count, 11px subline. ------ */
#sigbar .sbc{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 6px;
 width:100%;margin-bottom:5px;padding:8px 11px;border-radius:8px;
 font-size:14px;font-weight:700;letter-spacing:.005em;line-height:1.3;
 text-align:left}
#sigbar .sbc b{margin-left:auto;font-size:17px;font-weight:800;letter-spacing:0}
#sigbar .sbc i{flex-basis:100%;font-size:11px;font-weight:600;opacity:.85;
 margin-top:3px;letter-spacing:.01em}
#sigbar .ubg{font-size:15px;margin-right:2px}
#sigbar .sbc.on{filter:brightness(1.3)}

/* --- the hover card. position:FIXED -- see the note at the top of this patch.
       Type raised to match the column. ------------------------------------- */
#sigbar .ubp{position:fixed;left:calc(var(--lrw) + 10px);right:auto;top:0;
 width:352px;padding:14px 16px 15px}
#sigbar .ubp em{font-size:16px;margin-bottom:3px}
#sigbar .ubp .ubk{font-size:9px;letter-spacing:.16em;padding:3px 8px;margin-bottom:9px}
#sigbar .ubp q{font-size:12px;line-height:1.55;color:#dbe4ef;margin-bottom:9px;
 padding-bottom:9px}
#sigbar .ubp u{font-size:16px;margin-bottom:7px}
#sigbar .ubp .ubw{font-size:12.5px;line-height:1.6;color:#a9b7c6}
#sigbar .ubp .ubh{font-size:10.5px;margin-top:10px;padding-top:9px}

/* --- the column's own heading and legend ----------------------------------- */
.lrt{font-size:11px;letter-spacing:.16em;font-weight:800;color:#c3d0de;
 display:flex;align-items:center;gap:8px;margin:0 0 4px;padding-left:2px}
.lrt em{font-style:normal;font-size:10.5px;letter-spacing:.02em;font-weight:600;
 color:var(--mu);font-family:var(--mono)}
.lrd{width:6px;height:6px;border-radius:50%;background:var(--ac);flex:none;
 box-shadow:0 0 9px var(--ac)}
.lrn{margin:16px 0 0;padding-top:12px;border-top:1px solid var(--ln);
 font-size:11px;line-height:1.65;color:#8b98a8}
.lrn b{color:#ffe08a;font-weight:800;letter-spacing:.04em}
.lrn u{text-decoration:none;color:#9dc0ee;font-weight:800;letter-spacing:.04em}

/* --- narrow: the column would eat the page, so it folds back into a band above
       the header. NOT sticky -- a stuck header is exactly what it must not be. */
@media(max-width:1180px){
 body{padding-left:0}
 #sigbar{position:static;width:auto;height:auto;display:flex;flex-wrap:wrap;
  align-items:center;gap:5px;border-right:0;padding:9px 12px;margin:0;
  background:none;border-bottom:1px solid var(--ln)}
 #sigbar .ubsep{display:inline-block;border:0;margin:0;padding:0 3px 0 8px;
  font-size:9px}
 #sigbar .sbc{display:inline-flex;flex-wrap:nowrap;width:auto;margin-bottom:0;
  padding:5px 9px;font-size:12px}
 #sigbar .sbc b{margin-left:0;font-size:13px}
 #sigbar .sbc i{flex-basis:auto;margin-top:0;font-size:10px}
 #sigbar .ubp{left:12px;width:min(340px,calc(100vw - 24px))}
 .lrt{width:100%;margin:0 0 6px}
 .lrn{width:100%;margin-top:8px;padding-top:8px;font-size:10px}}
/* ===================== end NIKKO-SIDEPANEL ===================== */
/* ===================== NIKKO-GROUPFIX ===================== */
/* --- narrower columns. 230px minimum meant five columns of mostly empty bar on a
       wide screen; 182 fits seven and the reads stop being spread thin. --------- */
.pg{grid-template-columns:repeat(auto-fit,minmax(182px,1fr));gap:9px 18px;
 padding:12px 14px}
.rw{padding:1.5px 0}
.bar{margin-top:3px;height:2px}
.rl{font-size:10.5px}
.rv{font-size:11px}
.pv{margin-left:5px;font-size:9px}
.wide .cols{column-count:6;column-gap:18px}
@media(max-width:1400px){.wide .cols{column-count:4}}
@media(max-width:1000px){.wide .cols{column-count:2}}

/* --- what the group is, under its heading ---------------------------------- */
.gg{margin-bottom:2px}
.ggw{font-size:9px;line-height:1.4;color:var(--mu);margin:0 0 7px;
 padding-bottom:5px;border-bottom:1px solid rgba(255,255,255,.045);
 font-weight:500;letter-spacing:.01em}
/* a read that carries an explanation gets a quiet marker, so it is discoverable
   rather than a tooltip nobody knows is there */
.rw[title]{cursor:help}
.rw[title] .rl::after{content:"\00b7";margin-left:5px;color:var(--ac);
 font-weight:800;opacity:.75}
/* ===================== end NIKKO-GROUPFIX ===================== */

/* ===================== NIKKO-READABLE ===================== */
/* Appended last on purpose: every rule here has the same specificity as the one
   it supersedes, so cascade order is what makes it win. Nothing above is edited. */

/* --- 1. the badge row and the chip row share one line ---------------------- */
.algband{display:flex;flex-wrap:wrap;align-items:flex-start;gap:8px 16px}
.algband>*{flex:0 0 100%;min-width:0}
.algband>.abhead{flex:0 0 auto;margin-top:0}
.algband>.abtop{flex:1 1 340px;margin-top:0;min-width:0}
.abhead{align-items:center}
.abtop{align-items:center}

/* --- 2. wording you can read at arm's length ------------------------------- */
.rl{font-size:12.5px;line-height:1.35}
.rv{font-size:13px}
.pv{font-size:10.5px;margin-left:6px}
.ggw{font-size:11px;line-height:1.5;margin-bottom:8px}
.gg{font-size:11.5px;letter-spacing:.13em}   /* the group heading is a <p class=gg> */
.rw{padding:2.5px 0}
.sbc{font-size:13px}
.ubsep{font-size:10.5px}
.sg{font-size:11.5px}

/* --- 3. shorter bars ------------------------------------------------------- */
.bar{max-width:108px;height:3px;margin-top:4px;border-radius:3px}
.fl{border-radius:3px}
/* a little more column so the bigger type does not wrap mid-label */
.pg{grid-template-columns:repeat(auto-fit,minmax(198px,1fr));gap:10px 20px}
@media(max-width:1500px){.pg{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}}
/* ===================== end NIKKO-READABLE ===================== */
</style>
<div class=hd><div class=mk></div><h1>__TITLE__</h1>
 <input id=q placeholder="filter bats, teams, arms...">
 <div id=sigbar class=sigbar></div>
 <div class=tiles>
  <div class=tl><div class=tk>ON SLATE</div><div class="tv mono">__NALL__</div></div>
  <!-- NIKKO-AGREEFLAG: GATE FIRES / ALIGNED 3+ / ELITE BAND / DIAMOND all read the
       old system and three of the four printed 0 every night.  These four count the
       consensus gates instead. -->
  <div class=tl><div class=tk>LOCK 2+</div><div class="tv mono ag2" id=t2>0</div></div>
  <div class=tl><div class=tk>TRIPLE</div><div class="tv mono ag3" id=t3>0</div></div>
  <div class=tl><div class=tk>NAMED 1</div><div class="tv mono" id=t5>0</div></div>
  <div class=tl><div class=tk>SUN</div><div class="tv mono" id=t4>0</div></div>
  <div class=tl><div class=tk>SHOWING</div><div class="tv mono" id=t1>0</div></div>
 </div></div>
<div id=gs class=gs></div>
<div class=wrap><table><thead><tr id=hh></tr></thead><tbody id=b></tbody></table>
<div class=empty id=em style="display:none">nothing matches that filter</div></div>
<script>
const R=__ROWS__, HASC=__HASCONF__==1;
const HASTBT=__HASTBT__==1, HASBAND=__HASBAND__==1;
const HASHRR=__HASHRR__==1;   // NIKKO-HRRSHOW
const HASLANE=__HASLANE__==1;   // NIKKO-LANECOL
// NIKKO-ALIGNDRAWER: ALIGN leads and SIGNALS gets a real column. The old comment
// below said flags belong one click down. On 29 graded boards the count is the
// strongest read on this board -- 3+ is 18.5% at 1.65x with halves 18.6/18.3, and
// stacked on HR% p90 it is 22.1% at 1.98x. It goes at the front, not in a drawer.
const COLS=[["BATTER","n"],["HR TIER","tier"]]
 .concat(HASTBT?[["TB TIER","tbt"]]:[])
 .concat(HASHRR?[["HRR TIER","hrrt"]]:[])   // NIKKO-HRRSHOW
 .concat(HASLANE?[["LANE","lnrk"]]:[])   // NIKKO-LANECOL: sorts on the lane rank
 // NIKKO-SIGWIRE: ALIGN removed. It is hr_align_n -- the count of app.py's _STK
 // fourteen, the same table WHAT IS ALIGNING was deleted for. On tonight's board it
 // read "0 --" beside bats carrying a 2x agreement badge, so the column was
 // contradicting the flag next to it. r.c is still on the payload for the exports.
 // NIKKO-WHATALIGNS: GATE is gone. It read 0 fires in the header strip and was
 // empty on every row -- an empty column costing width on every board. The gate
 // itself is untouched: a firing row still carries the green rail and bloom, the
 // GATE FIRES tile is still in the header, and hr_gate_rank is unchanged in the
 // data, the exports and the generator.
 .concat([["SIGNALS","f"],["HR%","hp"]])
 .concat(HASBAND?[["BAND","band"]]:[])
 .concat([["TONIGHT'S ARM","o"]]);
const hh=document.getElementById('hh');
COLS.forEach(([lab,k],i)=>{const th=document.createElement('th');th.textContent=lab;
 th.onclick=()=>sort(k,th);hh.appendChild(th)});
let cur=R.slice(), sk=null, sa=false;
const pips=n=>[0,1,2,3,4,5].map(i=>`<span class="pip${i<n?' on':''}"></span>`).join('')
 +`<span class="pv mono">${n}</span>`;
// NIKKO-ALIGNDRAWER: the measured cuts. 3+ 1.65x, 5+ 1.99x, and the halves split
// at 6+ (21.2/32.0) which is why nothing above 5 gets its own colour.
const align=n=>{n=+n||0;const k=n>=5?'a5':n>=3?'a3':n>=1?'a1':'a0';
 return `<span class="alg ${k}"><b class=mono>${n}</b><i>${n>=5?'STACKED':n>=3?'ALIGNED':n>=1?'':'--'}</i></span>`};
// NIKKO-WHATALIGNS: every flag, not four and a +2. This was slice(0,4) inside a
// nowrap flex row capped at 330px, so a bat with seven flags showed four. The count
// beside it is the whole read -- hiding three of them made the two disagree.
// NIKKO-SIGWIRE: chips are the measured legs now, not hr_edges. Each carries its
// family colour and its own slate percentile, so a union reads across the row
// without opening anything: two colours is a pair, three is a 1x1x1.
const _sgf={r:'RECENCY',a:'ARM',b:'BAT',m:'MATCHUP',x:'CONFIRMER',
 p:'PAIR \u2014 bat read x arm read, both above their cut'};   // NIKKO-PAIRSIG
// ===================== NIKKO-UNIONBAR =====================
// The glyph rides the chip. A union is the only kind that gets one, so a row
// with an emoji on it is a row where a BAT read and an ARM read both cleared --
// and a row of bare words is a row of single legs. That was the whole confusion.
const SIGX=__SIGX__;
const _ubx=k=>SIGX[k]||['','l','',''];
const _ubt=k=>{const x=_ubx(k);
 return (_UBKJS[x[1]]||'')+' \u2014 '+x[2]+'\n\n'+x[3];};
const _UBKJS={u:'PAIR',g:'READ',l:'LEG',f:'FLOOR'};
const chips=g=>{const a=(g||[]);
 if(!a.length)return '<span class=nof>--</span>';
 // unions first: the object that was graded leads the row, the legs follow.
 const s=a.slice().sort((p,q)=>(_ubx(q[0])[1]==='u')-(_ubx(p[0])[1]==='u'));
 return '<span class=sig>'+s.map(x=>{const X=_ubx(x[0]);
   return `<span class="sg sg${x[1]}${X[1]==='u'?' ubu':''}" `
   +`title="${esc(_ubt(x[0]))} \u00b7 p${x[2]} on tonight's slate">`
   +(X[0]?`<span class=ubg>${X[0]}</span>`:'')
   +`${esc(x[0])}<b>${x[2]}</b></span>`}).join('')+'</span>'};
// =================== end NIKKO-UNIONBAR ===================
// --- NIKKO-GAMESPLIT: the game tiles.  Built from the rows already on the page.
// Nothing here reads or writes a card, a drawer or a style rule.
var GM = '';
function gsdraw(){
 const el=document.getElementById('gs'); if(!el) return;
 const seen={}, order=[];
 (typeof ROWS!=='undefined'?ROWS:cur).forEach(r=>{
   const k=r.gm||'ALL'; if(!(k in seen)){seen[k]=[];order.push(k);} seen[k].push(r);});
 if(order.length<2){el.style.display='none';return;}
 el.style.display='';
 let h='<button class="gt'+(GM?'':' on')+'" data-g="">ALL'
      +'<b>'+((typeof ROWS!=='undefined'?ROWS:cur).length)+'</b></button>';
 order.sort().forEach(k=>{
   const rs=seen[k], arms=[];
   rs.forEach(r=>{const a=String(r.o||'').split(':')[0].trim();
                  if(a && arms.indexOf(a)<0) arms.push(a);});
   h+='<button class="gt'+(GM===k?' on':'')+'" data-g="'+esc(k)+'">'
     +esc(k)+'<b>'+rs.length+'</b>'
     +(arms.length?'<i>'+esc(arms.slice(0,2).join('  vs  '))+'</i>':'')
     +'</button>';});
 el.innerHTML=h;
 el.querySelectorAll('button.gt').forEach(btn=>{
   btn.onclick=()=>{GM=btn.getAttribute('data-g')||''; draw();};});
}
// ===================== NIKKO-GROUPFIX =====================
// What each group is, and what the reads inside it that need it are. Rates are the
// measured numbers on 56 graded nights against a 10.61% base -- not descriptions of
// intent, and where a read grades badly it says so.
const GROUPWHY={
 "THE READS":"The eighteen columns the nine locked reads gate on, each labelled with the term that reads it. All as-of -- only games played BEFORE tonight, so nothing here can see its own night. NOGB is the exception to the bars: it is ground-ball rate and LOWER clears, so a short bar is the good one. The composites the reads use are products or differences of these -- HARDxSLG is HARD x ARMSLG, DUE_EV is EV minus OWNHR, GROUNDED is HARD minus AIR.",
 "THE BAT":"One half of a pair. Every read here is a property of the BAT -- what it "
  +"does, before this arm is considered.",
 "POWER":"How hard and how high this bat hits it. Bat speed is a SEPARATE read from "
  +"hard-hit, not a proxy: it is the one power read with positive own-lift.",
 "MATCHUP":"Bat crossed with THIS arm. SLG-FIT is the confirmer -- above its median "
  +"2+ gates run 20.9%, below it the same gates run 5.0% and invert.",
 "THE ARM":"The other half of a pair. HR per 9 and Weak arm are the SAME number "
  +"(rho 1.00) under two names.",
 "RECENCY":"What this bat has done lately. Three of these are legs of live gates, "
  +"but on their own every one has NEGATIVE own-lift -- they find bats that already "
  +"homer. They earn their place in combination, not alone.",
 "THE LANES":"Three different objects, not one. Lane score is the ISO sort. "
  +"Cold-power and Longshot are two separate 5-seat pools; seat 0 means not in that "
  +"pool tonight.",
 "OPPORTUNITY / HRR":"H + R + RBI over 1.5 -- a VOLUME market, not a power one. "
  +"How often this bat comes up and whether there is an offense around it.",
 "CONTACT / TB":"Total bases. Contact and volume lead here; the HR reads do not."};
const ROWWHY={
 "Own HR rate":"This bat's own HR rate over PRIOR nights only, minimum 15 prior "
  +"appearances -- so a near-debut bat is blank, not scored 0.00%. The chalk test: "
  +"own-lift is a gate's rate MINUS this. A read that only finds bats who already "
  +"homer has no edge.",
 "Cold-power seat":"Seat 1-5 in the cold-power lane: bats with below-median recent "
  +"HR rate, capped 2 per arm. 21.11% over 199 calls, own rate 4.59%, own-lift "
  +"+16.19 -- the largest own-lift measured. 0 means not in the pool tonight.",
 "Longshot seat":"Seat 1-5 in the market-longshot lane: bottom-half season xISO, "
  +"priced long. 15.05% over 279 calls, 1.91x. Cheap power, NOT the same thing as "
  +"cold power. 0 means not in the pool tonight.",
 "Lane score":"The ISO lane: the slate percentile of ISO-vs-hand averaged with the "
  +"slate percentile of ISO-vs-mix. No fitting. Top 20 a night ran 19.30% over 1,119 "
  +"calls, 1.82x, and held in all four walk-forward folds.",
 "SLG-FIT":"The confirmer, and the pool floor. Above its median 2+ gates run 20.9% "
  +"(86 calls, p=0.002); below it the same gates run 5.0% against a 10.61% base -- "
  +"they invert, and the agreement badge is withheld there.",
 "HR last 3":"Leg of the L3-ARM gate at p70-90. Alone: own-lift -6.1. The gate it "
  +"belongs to runs 35.1%. It works in combination, not by itself.",
 "HR last 7":"Leg of the L7-TB5 gate at p70-90. Alone: own-lift -6.3.",
 "TB last 5":"Leg of the L7-TB5 gate at p70-90. Alone: own-lift -2.9.",
 "2+TB no HR L3":"Leg of the L3-ARM gate at p70-90. Damage the bat has not cashed. "
  +"Alone it is flat -- sort is unmeasurable and own-lift is -1.7.",
 "Hit streak":"0 for 69% of the board, so it barely ranks. Sort -0.05. It topped a "
  +"sweep at 1.47x on ONE night out of 56, which is what the night-coverage guard "
  +"now catches.",
 "Games since HR":"Own-lift -3.3 -- it finds bats that homer often, which is the "
  +"chalk it is supposed to avoid.",
 "Prior games":"How many prior appearances this bat has. Under 15, Own HR rate is "
  +"blank on purpose.",
 "Weak arm":"The same number as HR per 9, re-signed (rho 1.00). Keep one.",
 "HR per 9":"Home runs this arm allows per nine. Identical to Weak arm.",
 "Bat speed":"A DIFFERENT read from hard-hit, not a proxy -- rho 0.91 with itself "
  +"under its other name, but only 0.68-0.79 with hard-hit. Own-lift +0.8, and "
  +"+12.4 inside the depth slice. The strongest bat read there is.",
 "Hard hit %":"Own-lift -3.0. EV50 adds about +2.5 on top of it and nothing else does.",
 "Sweet spot %":"Sort 0.13, own-lift -3.8. It does not order bats for home runs.",
 "K per 9":"Runs BACKWARD as a standalone (sort -0.37). It is only a read as the "
  +"low half of the Contact pair.",
 "Exp PA":"Expected plate appearances. Sort 1.00 -- the cleanest ordering on the "
  +"board -- but own-lift +0.1: it finds bats who bat often, which is most of why "
  +"they homer often.",
 "Park":"Own-lift -1.4, and -3.2 inside the lane. Context, not a read.",
 "Weather":"Own-lift -0.0. Context, not a read."};
// =================== end NIKKO-GROUPFIX ===================
// NIKKO-SIGBAR: tonight's chips in the header band, strongest first. Click to filter
// the board to the bats carrying that chip; click again to clear. This is the
// reference panel's job done at the top of the page instead of inside an expander.
const SIGMETA=__SIGMETA__;   // NIKKO-SIGBAR: serialised from the Python table
var SBPICK='';
function _sb_draw(view){
 const el=document.getElementById('sigbar'); if(!el) return;
 const n={}, f={};
 view.forEach(r=>(r.sg||[]).forEach(x=>{n[x[0]]=(n[x[0]]||0)+1; f[x[0]]=x[1];}));
 const keys=Object.keys(n).sort((a,b)=>{
   const la=parseFloat((SIGMETA[a]||['','',''])[1])||0, lb=parseFloat((SIGMETA[b]||['','',''])[1])||0;
   return lb-la || n[b]-n[a];});
 if(!keys.length){el.innerHTML='';return;}
 // ===================== NIKKO-UNIONBAR =====================
 // The band is two groups now, not one undifferentiated row. UNIONS are the four
 // graded pairs -- bat read x arm read, both clearing their cut. LEGS are single
 // reads in a window: each is one COMPONENT of a consensus gate and none of them
 // is a call on its own. They were sitting side by side with nothing saying which
 // was which, which is exactly what made the band unreadable.
 // Every chip carries a hover card: what it reads, what it pairs with, what it
 // graded at. That is the reference panel's job, done where the chip is.
 const _ubU=keys.filter(k=>_ubx(k)[1]==='u'),_ubR=keys.filter(k=>_ubx(k)[1]==='g'),_ubL=keys.filter(k=>_ubx(k)[1]!=='u'&&_ubx(k)[1]!=='g');
 const _ubB=(k)=>{const m=SIGMETA[k]||['','',''], X=_ubx(k);
   return `<button class="sbc sg${f[k]}${SBPICK===k?' on':''}${X[1]==='u'?' ubu':''}" `
    +`data-k="${esc(k)}">`
    +(X[0]?`<span class=ubg>${X[0]}</span>`:'')
    +`${esc(k)}<b>${n[k]}</b>${m[1]?`<i>${esc(m[1])}</i>`:''}`
    +`<span class=ubp><em>${esc(k)}</em>`
    +`<s class="ubk ubk${X[1]}">${esc(_UBKJS[X[1]]||'')}</s>`
    +`<q>${esc(X[2])}</q>`
    +(m[0]?`<u>${esc(m[0])} \u00b7 ${esc(m[1])} the board</u>`:'')
    +`<i class=ubw>${esc(X[3])}</i>`
    +`<b class=ubh>${n[k]} bat${n[k]===1?'':'s'} on tonight's slate \u00b7 click to filter</b>`
    +`</span></button>`};
 el.innerHTML=(_ubU.length?'<span class=ubsep>PAIRS</span>'+_ubU.map(_ubB).join(''):'')+(_ubR.length?'<span class=ubsep>READS</span>'+_ubR.map(_ubB).join(''):'')
  +(_ubL.length?'<span class=ubsep>LEGS</span>'+_ubL.map(_ubB).join(''):'');
 // =================== end NIKKO-UNIONBAR ===================
 el.querySelectorAll('button.sbc').forEach(b=>{
   b.onclick=()=>{const k=b.getAttribute('data-k'); SBPICK=(SBPICK===k?'':k); draw();};});
}
function draw(){
 const b=document.getElementById('b');b.innerHTML='';
 // --- NIKKO-GAMESPLIT: everything below renders from `view` instead of `cur`.
 // view === cur when no game is picked, so the default page is unchanged.
 // NIKKO-SIGBAR: `view` was const. The chip filter has to reassign it, so it is a
 // let now -- nothing else about it changes. The band counts the UNFILTERED view so
 // the numbers do not collapse to 1 the moment you click a chip; the filter applies
 // after the count.
 let view = (typeof GM!=='undefined' && GM) ? cur.filter(r=>r.gm===GM) : cur;
 _sb_draw(view);
 if(SBPICK) view = view.filter(r=>(r.sg||[]).some(x=>x[0]===SBPICK));
 gsdraw();
 document.getElementById('t1').textContent=view.length;
 // NIKKO-AGFLOOR: the tiles count agreement now. LOCK 2+ is the flag -- but only
 // ABOVE the confirmer median. There it is 20.9% per leg over 86 calls (p=0.002)
 // against a 10.61% base. Below that median the same gates run 5.0% and the badge
 // is withheld, so a bat counted in this tile has already cleared the floor.
 document.getElementById('t2').textContent=view.filter(r=>(+r.ag||0)>=2).length;
 document.getElementById('t3').textContent=view.filter(r=>(+r.ag||0)>=3).length;
 document.getElementById('t5').textContent=view.filter(r=>(+r.ag||0)===1).length;
 document.getElementById('t4').textContent=view.filter(r=>r.sun).length;
 document.getElementById('em').style.display=view.length?'none':'block';
 view.forEach(r=>{
  // NIKKO-AGREEFLAG: the rail and the name flare follow AGREEMENT, not hr_gate_rank.
  // 3+ takes the amber treatment so a triple never reads as just another 2+.
  const _ag=+r.ag||0;
  const tr=document.createElement('tr');
  tr.className='r'+(_ag>=3?' fire trip':(_ag>=2?' fire':''));
  const _agb=_ag>=3?'<span class="agb a3" title="three consensus gates name this bat">3x</span>'
   :(_ag>=2?'<span class="agb a2" title="two consensus gates name this bat">2x</span>'
   :(_ag===1?'<span class="agb a1" title="one consensus gate names this bat">1x</span>':''));
  const _sun=r.sun?'<span class=sunm title="one gate, and SLG-FIT is p80+ on tonight\'s slate">&#9728;</span>':'';
  /* NIKKO-LINEUPTAG */
  const _luv=Array.isArray(r.lu)?r.lu:[];
  const _lu=!_luv.length?'':(_luv[0]==='lineup'
   ?`<span class="nklu lin" title="lineup posted${_luv[1]?' -- batting '+_luv[1]:''}">LU${_luv[1]?'&#8202;'+_luv[1]:''}</span>`
   :`<span class="nklu prj" title="no lineup posted yet -- this bat came off the active roster">PROJ</span>`);
  let c=`<td><span class=nm>${esc(r.n)}</span>${_agb}${_sun}${_lu}${r.t?`<span class=tm>${esc(r.t)}</span>`:''}</td>
   <td>${r.tier?`<span class="chip ${r.tier}">${esc(r.tier)}</span>`:''}</td>`;
  if(HASTBT)c+=`<td>${r.tbt?`<span class="chip tbt">${esc(r.tbt)}</span>`:''}</td>`;
  // NIKKO-HRRSHOW: this order MUST match COLS above, cell for cell.
  if(HASHRR)c+=`<td>${r.hrrt?`<span class="chip hrr ${esc(r.hrrt.toLowerCase())}">${esc(r.hrrt)}</span>`:''}</td>`;
  // NIKKO-LANECOL: this order MUST match COLS above, cell for cell.
  if(HASLANE)c+=`<td style="white-space:nowrap">${r.lnrk?`<span class=lnr>#${r.lnrk}</span>`:''}`
   +`${r.lnlow?`<span class="lns low">LOW ${r.lnlow}</span>`:''}`
   +`${r.lnshot?`<span class="lns shot">SHOT ${r.lnshot}</span>`:''}</td>`;
  // NIKKO-ALIGNDRAWER: this order MUST match COLS above, cell for cell.
  // NIKKO-SIGWIRE: the ALIGN cell went with the ALIGN header.
  c+=`<td>${chips(r.sg)}</td>`;   // NIKKO-SIGWIRE
  // NIKKO-WHATALIGNS: this emission order MUST match COLS above, cell for cell.
  // The GATE cell went with the GATE header.
  c+=`<td class="hp mono">${esc(r.hp)}</td>`;
  if(HASBAND)c+=`<td>${r.band?`<span class="chip ${r.band}">${esc(r.band)}</span>`:''}</td>`;
  c+=`<td class=op>${esc(r.o)}</td>`;
  tr.innerHTML=c;
  const dr=document.createElement('tr');dr.className='dr';dr.style.display='none';
  // NIKKO-ALIGNBAND: the alignment LEADS the panel -- the count, the ladder rung,
  // every flag as a chip, and which measured reads are firing on this bat. That is what
  // an alignment is. The bars below are the ingredients that feed it.
  // align(r.c) is the same function the ALIGN column calls, so the number and the colour
  // on the row and in the drawer cannot drift apart.
  const _fa=(r.sg||[]);   // NIKKO-SIGWIRE: the band shows the same chips as the row
  const _LX={'L1 BASE':'1.73x','L2 STRONG':'1.76x'};
  // NIKKO-LAYOUT2: _ref is assembled further down but consumed by the band wrapper, and
  // `let _ref` would be in its temporal dead zone at that point. Hoisted here.
  var _ref='';
  // NIKKO-LAYOUT2: the band is two columns now. Everything the old band built is the
  // left one; the reference built below drops into the right one, which used to be empty
  // space next to the pair list while the reference sat down the far side of the panel.
  // NIKKO-AGREEFLAG: name WHICH gates fired before anything else on the panel.
  // "why are we calling this bat" is answered here, in words, not by a count.
  const _agw=(r.agw||[]);
  const _aghd=_agw.length
   ? '<span class="agwho '+(_agw.length>=3?'a3':(_agw.length>=2?'a2':'a1'))+'">'
     +`<b>${_agw.length===1?'NAMED BY':'AGREED BY'} ${_agw.length}</b>`
     +_agw.map(x=>`<i>${esc(x)}</i>`).join('')+'</span>'
   : '<span class="agwho a0"><b>NO CONSENSUS GATE</b><i>none of the four name this bat</i></span>';
  // NIKKO-DRAWTRIM: the panel says WHO. Clicking a row scrolls it, and if the scroll
  // lands even slightly wrong the name you clicked goes behind the sticky header and
  // the open drawer belongs to nobody. The panel carries the name itself now.
  let _band='<div class=algband>'
   +`<p class=abnm>${esc(r.n)}${r.t?`<span class=abnmt>${esc(r.t)}</span>`:''}`
   +`${r.o?`<span class=abnmt>vs ${esc(r.o)}</span>`:''}</p>`
   +'<div class=abhead>'
   +'<span class=abt>UNIONS</span>'+_aghd   // NIKKO-UNIONBAR: was ALIGNMENT
   // NIKKO-SIGWIRE: the drawer's copy of the ALIGN badge went with the column.
   +(r.lad?`<span class="chip abl">${esc(r.lad)}${_LX[r.lad]?`<b>${_LX[r.lad]}</b>`:''}</span>`:'')
   // NIKKO-LAYOUT3: the "N of M measured reads firing" that used to sit here is gone.
   // It said exactly what the MEASURED READS line says, on the same panel, at the same
   // time. One counter, on the section that owns it.
   +'</div>';
  // NIKKO-LAYOUT3: six chips left an entire row of empty space beside them while the
  // measured reads sat alone under the pair list. They share the row now -- flags left,
  // reads right.
  // NIKKO-UNIONBAR: MEASURED READS deleted. It rendered the READS table -- zone+mix
  // agree / loc x arm / PROB + 3 CLEAN / zone top 5% -- which is the old caller-era
  // set and one of whose four legs is hr_prob. Nothing in the HR path selects on any
  // of it, so the panel was printing "1 of 4" about a system that is not running.
  // r.pr and r.np are still on the payload; nothing reads them.
  let _reads='';
  // ===================== NIKKO-UNIONBAR =====================
  // The chip row under the badge was one undifferentiated line, which is why a row
  // of three single LEGS sat under a heading that promised unions. Same split as the
  // header band: unions first with their glyph, legs after, each group named.
  const _ubU2=_fa.filter(x=>_ubx(x[0])[1]==='u'),_ubR2=_fa.filter(x=>_ubx(x[0])[1]==='g'),_ubL2=_fa.filter(x=>_ubx(x[0])[1]!=='u'&&_ubx(x[0])[1]!=='g');
  const _ubC=x=>{const X=_ubx(x[0]);
    return `<span class="sg sg${x[1]}${X[1]==='u'?' ubu':''}" title="${esc(_ubt(x[0]))}">`
     +(X[0]?`<span class=ubg>${X[0]}</span>`:'')
     +`${esc(x[0])}<b>${x[2]}</b></span>`};
  _band+='<div class=abtop>'
   +(_fa.length
     ? '<div class=abchips>'
       +(_ubU2.length?'<span class=ubsep>PAIRS</span>'+_ubU2.map(_ubC).join(''):'')
       +(_ubR2.length?'<span class=ubsep>READS</span>'+_ubR2.map(_ubC).join(''):'')
       +(_ubL2.length?'<span class=ubsep>LEGS</span>'+_ubL2.map(_ubC).join(''):'')
       +'</div>'
     : '<div class=abnone>no measured read fires on this bat tonight</div>')
   +_reads+'</div>';
  // =================== end NIKKO-UNIONBAR ===================
  // NIKKO-WHATALIGNS: the alignment, in the only form the word means -- which BAT
  // read met which ARM read. Left column is the bat, right is the arm, both with the
  // slate percentile app.py cut them on.
  // NIKKO-DRAWTRIM: WHAT IS ALIGNING removed. It rendered r.stk -- the fourteen
  // bat-read x arm-read pairs from app.py's _STK table. That table is the OLD
  // selector and is not in the HR path, so the panel was spending nine rows
  // answering "why this bat" with a number nothing selects on. r.stk and r.sof
  // are still built and still on the row payload; nothing on the page reads them.
  // NIKKO-LAYOUT3: built into the top row now, beside the flags. Nothing here.
  _band+='</div>';   // NIKKO-LAYOUT2: closes the LEFT half of the band
  // NIKKO-DRAWERREF: the reference rail. What each flag on THIS bat reads and what
  // it measured, then the reads that grade, then the traps -- beside the bat instead of
  // in an expander at the bottom of the page.
  // FLAGDEF is the LIVE _CF table in app.py, entry for entry. Anything retired there
  // (Hot, Power, Arsenal, Plat, AirHard -- all set to 1e9) is deliberately absent, so a
  // flag from an older board falls through to the 'not in the current set' line rather
  // than being described as if it still counted.
  const FLAGDEF={
   // NIKKO-DRAWERFIX: keyed on the LIVE _AL14 tokens (app.py L6857-6869), glyph
   // included. Every one is a PAIR: bat read x arm read, both above their cut,
   // within tonight's slate. [name, what it pairs, grade]. Graded over 35 nights
   // against an 11.06% base; "halves" is odd vs even nights -- when those two
   // disagree the chip is not something to lean on.
   '\u{1F5FA}Zone':["Zone","zone overlap p94 x pitch vuln p94","30.2% \u00b7 2.73x \u00b7 halves 28.7/32.0"],
   '\u{1F9F2}Mix':["Mix","bat ISO vs this arm's pitch mix p87 x arm xSLG allowed p87","23.3% \u00b7 2.10x \u00b7 halves 23.9/22.5"],
   '\u{1F32A}Air':["Air","barrel% p84 x hard air allowed p84","21.8% \u00b7 1.97x \u00b7 halves 20.0/23.9"],
   '\u2694Matchup':["Matchup","matchup-z p93 x pitch vuln p93","20.6% \u00b7 1.86x \u00b7 halves 26.1/16.0 \u2014 splits"],
   '\u{1F4C8}Form':["Form","recent xSLG p85 x weak arm p85","19.9% \u00b7 1.80x \u00b7 halves 18.9/21.1"],
   '\u{1F4CA}xWOBA':["xWOBA","xwOBA p86 x pen xwOBA allowed p86","19.5% \u00b7 1.77x \u00b7 halves 24.7/13.6 \u2014 splits"],
   '\u{1F4AA}Power':["Power","xISO p87 x HR per 9 p87","18.6% \u00b7 1.69x \u00b7 halves 20.9/16.3"],
   '\u{1F525}Hot':["Hot","recent xwOBA p80 x implied runs p80","18.1% \u00b7 1.64x \u00b7 dark 13 of 35 nights"],
   '\u{1F4A5}Damage':["Damage","xISO p85 x arsenal xSLG p85","17.7% \u00b7 1.60x \u00b7 dark 19 of 35 nights"],
   '\u{1F6E2}Barrel':["Barrel","barrel% p83 x barrels allowed p83","17.6% \u00b7 1.59x \u00b7 halves 19.3/15.7"],
   '\u{1F3AF}Contact':["Contact","contact score p88 x K per 9 LOW p88","16.4% \u00b7 1.48x \u00b7 halves 20.0/13.0"],
   '\u{1F634}Sleeper':["Sleeper","sleeper score p86 x GB allowed LOW p86","15.4% \u00b7 1.39x \u00b7 halves 24.1/6.8 \u2014 decoration"],
   '\u{1F3B2}Dart':["Dart","prosync rank 15-45, not vetoed","the second tier, not a read"]};
  // ===================== NIKKO-DRAWTRIM =====================
  // The rail, rebuilt on the agreement. GRADED is gone -- every row in it was a
  // caller-era number (LOCK, 3+/5+ pairs, 1+ caller) and none of those select any
  // more. The flag ESSAYS are gone too: one line per chip instead of three.
  //
  // [short, per-leg, own-lift, what it reads]. Own-lift is the gate's per-leg rate
  // MINUS the average own-HR rate of the bats it calls -- the chalk test. All four
  // are positive, which is what makes them a consensus set and not a list of the
  // biggest bats.
  // NIKKO-GATEFIX: the four figures here were 35.1 / 29.7 / 26.4 / 25.7 and none of
  // them reproduces. Measured over all 56 graded nights against a 10.61% base, using
  // the exact masks this file builds -- the same masks that DO reproduce the 20.9%
  // and 9.5% agreement tiers to the decimal. XBA-XHR is below the base: it is not a
  // gate on its own, it only contributes to the 2+ count.
  const GATEREF=[
   ["L3-ARM","14.3%","-2.8","hr L3 \u00b7 weak arm \u00b7 TB-no-HR L3   all p70-90"],
   ["L7-TB5","12.1%","-3.0","hr L7 \u00b7 TB L5   both p70-90"],
   ["FORM-ARS","11.3%","-1.3","form delta p70-90 \u00b7 arsenal match p40-70"],
   ["XBA-XHR","9.7%","-1.8","xBA p40-70 \u00b7 arm xHR diff p70-90   below base"]];
  // what each agreement tier landed at, per leg, over 55 graded nights. Own rate is
  // FLAT across the three (14.8 / 15.4 / 13.7) while the hit rate doubles -- the
  // gates are agreeing on better NIGHTS, not on better bats.
  // NIKKO-AGFLOOR: measured on 56 graded nights against a 10.61% base, split on the
  // confirmer median. The old rows here were card-level -- gate, then picker cut, then
  // the card's caps -- and had no business sitting under a board-width badge.
  const TIERREF=[["2 gates, in pool","20.9%","86 calls \u00b7 p=0.002"],
   ["2 gates, below pool","5.0%","60 calls \u00b7 inverts"],
   ["1 gate, in pool","9.5%","740 calls \u00b7 p=0.68"]];
  const POOLREF=[["top 2 a night","26.9%","52 calls \u00b7 p=0.001"],
   ["top 3 a night","24.2%","62 calls \u00b7 p=0.003"],
   ["top 5 a night","20.8%","77 calls \u00b7 p=0.012"]];
  const _fl=(r.f||'').split(/\s+/).filter(Boolean);
  const _wmg=(r.agw||[]), _wmv=+r.ag||0;
  _ref='<aside class=pref><p class=wmt>WHAT MATTERS<span>55 graded nights</span></p>';
  _ref+='<p class=wmh>THIS BAT</p>';
  _ref+='<div class="wmv '+(_wmv>=3?'a3':(_wmv>=2?'a2':(_wmv===1?'a1':(r.agx?'ax':'a0'))))+'">'
   +(_wmv>=3?'<b>AGREED BY 3</b><u>--</u><i>15 calls in 56 nights. too thin to price. read it as a 2+.</i>'
    :_wmv>=2?'<b>AGREED BY 2</b><u>20.9%</u><i>twice the board, in the pool. p=0.002 over 86 calls.</i>'
    :_wmv===1?'<b>NAMED BY 1</b><u>9.5%</u><i>below the board even in the pool. not a call.</i>'
    :r.agx?'<b>BELOW THE POOL</b><u>5.0%</u><i>gates name this bat, but under the confirmer median they invert.</i>'
    :'<b>NO CONSENSUS GATE</b><u>--</u><i>none of the four name this bat tonight.</i>')
   +'</div>';
  // ===================== NIKKO-READCHIPS =====================
  // The reads that fire on THIS bat, ranked by lift, above the four gates.
  // _fa is the same list the drawer chips are built from, so this panel
  // cannot disagree with the chips six inches to its left.
  const _rcF=_fa.filter(x=>{const k=_ubx(x[0])[1]; return k==='g'||k==='u';})
    .filter(x=>(SIGMETA[x[0]]||['','',''])[1])
    .sort((a,b)=>(parseFloat((SIGMETA[b[0]]||['','',''])[1])||0)
                -(parseFloat((SIGMETA[a[0]]||['','',''])[1])||0));
  // ===================== NIKKO-READLIT =====================
  // Which drawer rows the reads firing on THIS bat are gating on.  _rcF is
  // the same list the panel above is built from, so the lit rows and the
  // chips can never disagree.  Terms come out of the read's own definition
  // -- 3of4[EV7 g85, MIXISO g55, ...] -- so nothing has to be kept in step
  // by hand.  Composites have no row of their own and light their parts.
  const _RLX={'DUE_EV':['EV','OWNHR'],'HARDxSLG':['HARD','ARMSLG'],
              'GROUNDED':['HARD','AIR'],'SWEETxHARD':['SWEET','HARD'],
              'PULLxARM':['PULLAIR','ARMFB']};
  const _rdlit={};
  try{ _rcF.forEach(x=>{
    const _d=(_ubx(x[0])||['','',''])[2]||'';
    (_d.match(/\b[A-Z][A-Za-z0-9_]*\b/g)||[]).forEach(t=>{
      if(t==='OR'||t==='AND'||t==='NOT')return;
      (_RLX[t]||[t]).forEach(u=>{
        if(!_rdlit[u])_rdlit[u]=[];
        if(_rdlit[u].indexOf(x[0])<0)_rdlit[u].push(x[0]);});});});
  }catch(_e){}
  // =================== end NIKKO-READLIT ===================
  _ref+='<p class=wmh>READS ON THIS BAT</p>';
  if(_rcF.length){
    _ref+=_rcF.map(x=>{const m=SIGMETA[x[0]]||['','',''], X=_ubx(x[0]);
      return '<div class="wmg wmlit"><b>'+(X[0]||'')+' '+esc(x[0])+'</b>'
       +'<u>'+esc(m[0])+'</u><s>'+esc(m[1])+' the board</s>'
       +'<i>'+esc(_UBKJS[X[1]]||'')+' \u00b7 '+esc(X[2])+'</i></div>';}).join('');
  } else {
    _ref+='<div class=wmg><b>NONE</b><u>--</u><s></s>'
     +'<i>no locked read names this bat tonight</i></div>';
  }
  // =================== end NIKKO-READCHIPS ===================
  // ===================== NIKKO-RAILREADS =====================
  // THE FOUR GATES came out of the rail; THE READS took its place.
  // GATEREF is still defined above and is not touched, so the block
  // goes back with one revert.  The rows are the same objects the
  // grid was drawing -- same value, percentile, bar, read-lit class
  // and T1/T3 tag -- pulled out of r.d and rendered narrow.
  try{
    const _rrG=(r.d||[]).filter(g=>String(g.g||'').indexOf('THE READS')===0);
    _rrG.forEach(g=>{
      _ref+='<p class=wmh>WHAT THE NINE GATE ON</p>';
      _ref+='<div class=rrp>'+g.r.map(x=>{
        const kk=(x.k===undefined?1:x.k);
        const pp=kk===2?(100-x.p):x.p;
        const k=kk===2?'bad':(pp>=90?'top':(pp>=70?'hi':''));
        const _t=String(x.l||'').split('|')[0].trim();
        const _w=(typeof _rdlit!=='undefined'&&_rdlit[_t])||null;
        return '<div class="rw u'+kk+(_w?' rdlit':'')+'">'
         +'<div class=rt><span class=rl>'+x.l
         +(_w?'<span class=rdt>'+_w.join(' ')+'</span>':'')+'</span>'
         +'<span class="rv mono">'+x.v
         +'<span class="pv mono">'+x.p+'</span></span></div>'
         +'<div class=bar><div class="fl '+k+'" style="width:'
         +pp+'%"></div></div></div>';}).join('')+'</div>';
    });
  }catch(_rre){}
  // =================== end NIKKO-RAILREADS ===================
  // NIKKO-SIGBAR: WHAT EACH TIER HITS came off. It was slate-wide and said nothing
  // about the bat whose drawer is open -- a revolving door, as you put it. What is
  // here instead is every chip firing on THIS bat, with its own measured rate and its
  // percentile tonight.
  // ===================== NIKKO-UNIONBAR =====================
  // Everything from WHAT THIS BAT IS FIRING down came off.
  //   WHAT THIS BAT IS FIRING  -- the same chips already sitting in the band eight
  //     inches to the left, restated. Two copies of one list.
  //   the tier rows            -- their heading was display:none but TIERREF.map()
  //     kept rendering underneath it, so three unlabelled numbers hung in the rail.
  //   AND CUT TO THE TOP OF THE POOL -- board-wide, says nothing about the open bat.
  //   SIGNALS ON THIS BAT      -- FLAGDEF, the old _AL14 token table. Half its rows
  //     print "--" because those flags are retired in app.py.
  // What is left is the only thing the rail was ever for: is this bat called, by
  // which gates, and what did those gates grade at.
  _ref+='<p class=wmnote>Measured on 56 graded nights, base 10.61%. The gates were '
   +'chosen using every night, so 2+ is strong, not settled. Below the confirmer '
   +'median the same gates run 5.0% \u2014 that half is withheld, not shown as a call.</p>';
  // =================== end NIKKO-UNIONBAR ===================
  _ref+='</aside>';
  // =================== end NIKKO-DRAWTRIM ===================
  // NIKKO-LAYOUT2: band = [ left: count, chips, pairs, reads | right: WHAT MATTERS ].
  // .pg follows underneath at FULL width -- the rail used to eat a quarter of it, which
  // is what squeezed five scouting groups into four columns and a gap.
  const _bandwrap='<div class=algwrap><div class=algleft>'+_band+'</div>'
                 +'<div class=algright>'+_ref+'</div></div>';
  let h='<td colspan='+COLS.length+'><div class=pan>'+_bandwrap+'<div class=pbody><div class=pg>';
  if(r.d.length){r.d.forEach(g=>{
   // NIKKO-RAILREADS: THE READS draws in the rail now, not here.
   if(String(g.g||'').indexOf('THE READS')===0)return;
   const w=g.g.indexOf('ENGINE')===0;
   // ===================== NIKKO-GROUPFIX =====================
   // Every group says what it is. Five of the seven headings were nouns with no
   // referent -- THE LANES most of all, which is three different objects.
   h+=w?`<details class=wide><summary>${g.g}<span class=cnt>${g.r.length}</span></summary><div class=cols>`
       :`<div><p class=gg>${g.g}</p>`
        +(GROUPWHY[g.g]?`<p class=ggw>${esc(GROUPWHY[g.g])}</p>`:'');
   // =================== end NIKKO-GROUPFIX ===================
   g.r.forEach(x=>{
    // NIKKO-ALIGNDRAWER: k 0 = never gradeable (no bar at all), 1 = graded,
    // 2 = graded and BACKWARDS -- the bar is drawn from the other end.
    const kk=(x.k===undefined?1:x.k);
    const pp=kk===2?(100-x.p):x.p;
    const k=kk===2?'bad':(pp>=90?'top':(pp>=70?'hi':''));
    // tags stay SHORT -- a two-word tag wraps and makes the row twice as tall.
    // The legend at the foot of the panel says what the glyphs mean.
    // NIKKO-DRAWLOOK: VERDICT is {} since NIKKO-NOCHIPS, so kk is 0 on every
    // read and this printed UNVERIFIED beside all of them.  No tag when ungraded.
    const tag=kk===2?`<span class=inv>&#9660;${x.lf}</span>`
      :(x.lf&&parseFloat(x.lf)>=1.30?`<span class=grd>${x.lf}</span>`:'');
    // NIKKO-DRAWLOOK: the bar was suppressed whenever kk===0, which is now
    // EVERY read -- that is why the drawer stopped looking like the export.  The
    // bar is the percentile, it does not need a grade to be true.  And the
    // percentile prints bare, 71 not p71, the way the export prints it.
    // NIKKO-GROUPFIX: the read says what it is on hover. ROWWHY is keyed on the
    // display label, so a read that appears in two groups explains itself in both.
    const _gw=ROWWHY[x.l]?` title="${esc(ROWWHY[x.l])}"`:'';
    // NIKKO-READLIT: lit when a read firing on this bat gates on this
    // row's own term.  THE READS rows are named "TERM  |  what it is",
    // so the term is the part before the bar and the match is exact.
    const _rlt=String(x.l||'').split('|')[0].trim();
    const _rlw=(typeof _rdlit!=='undefined'&&_rdlit[_rlt])||null;
    const _rlc=_rlw?' rdlit':'';
    const _rlb=_rlw?`<span class=rdt>${_rlw.join(' ')}</span>`:'';
    h+=`<div class="rw u${kk}${_rlc}"${_gw}><div class=rt><span class=rl>${x.l}${_rlb}${tag}</span>
    <span class="rv mono">${x.v}<span class="pv mono">${x.p}</span></span></div>`
    +`<div class=bar><div class="fl ${k}" style="width:${pp}%"></div></div>`
    +'</div>'});
   h+=w?'</div></details>':'</div>'})}
  else h+='<div class=fz>no numeric reads on this board to expand</div>';
  if(r.x&&r.x.length){h+=`<details class=wide><summary>BOARD FIELDS<span class=cnt>${r.x.length}</span></summary>`
    +'<div class=cols style="column-count:4">';
   r.x.forEach(t=>{h+=`<div class="txr rw"><b>${esc(t.l)}</b><span>${esc(t.v)}</span></div>`});h+='</div></details>'}
  // NIKKO-ALIGNBAND: the FLAGS strip used to sit HERE, at the bottom of the panel
  // under the engine internals, repeating what the row already shows. It is the second
  // line of the band at the top now.
  // NIKKO-ALIGNDRAWER: say what the marks mean, once, at the foot of the panel.
  // NIKKO-DRAWLOOK: the legend explained grd / inv / unv glyphs.  VERDICT is {}
  // so none of the three can render.  A legend for nothing is noise on the card.
  h+='<div class=lgd>bar = percentile against every bat on tonight\'s board</div>';
  // NIKKO-DRAWERREF: three closers where there were two -- the first ends .pg, the
  // rail goes between, then .pbody and .pan close in turn.
  // NIKKO-LAYOUT2: _ref is in the band now, so the body closes .pg, .pbody, .pan.
  h+='</div></div></div></td>';dr.innerHTML=h;
  tr.onclick=()=>{const o=dr.style.display=='none';
   // accordion: one drawer at a time, so panels never stack on each other
   b.querySelectorAll('tr.dr').forEach(x=>x.style.display='none');
   b.querySelectorAll('tr.r.open').forEach(x=>x.classList.remove('open'));
   dr.style.display=o?'table-row':'none';
   tr.classList.toggle('open',o);
   if(o){dr.querySelectorAll('.fl').forEach(f=>{const w=f.style.width;f.style.width='0';
    requestAnimationFrame(()=>f.style.width=w)});
    // NIKKO-DRAWTRIM: was `- 88`, a hard-coded guess at everything above the table.
    // The game-split tiles add ~46px the moment there is more than one game, so the
    // row landed UNDERNEATH the sticky <th> and the name you clicked vanished. Park
    // the row against the TOP OF THE SCROLL CONTAINER, clear of the header, measured
    // rather than guessed.
    const wr=document.querySelector('.wrap');
    requestAnimationFrame(()=>{
     const th=wr.querySelector('th');
     const pad=(th?th.getBoundingClientRect().height:26)+8;
     wr.scrollTop+=tr.getBoundingClientRect().top-wr.getBoundingClientRect().top-pad;});}};
  b.appendChild(tr);b.appendChild(dr)});
}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,m=>
 ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]))}
function sort(k,th){
 if(sk===k)sa=!sa;else{sk=k;sa=false}
 [...hh.children].forEach(x=>x.className='');
 th.className=sa?'sa':'s';
 const num=v=>{const f=parseFloat(String(v).replace(/[^0-9.\-]/g,''));return isNaN(f)?-1e9:f};
 cur.sort((a,b)=>{let x=a[k],y=b[k];
  if(typeof x==='boolean'){x=x?1:0;y=y?1:0}
  else if(typeof x==='number'){}
  else if(k==='hp'){x=num(x);y=num(y)}
  else{x=String(x).toLowerCase();y=String(y).toLowerCase();
   return sa?(x<y?-1:x>y?1:0):(x>y?-1:x<y?1:0)}
  return sa?x-y:y-x});
 draw();
}
document.getElementById('q').oninput=e=>{
 const v=e.target.value.toLowerCase().trim();
 cur=v?R.filter(r=>(r.n+' '+r.t+' '+r.o+' '+r.f+' '+r.tier+' '+r.band).toLowerCase().includes(v)):R.slice();
 draw();
};
draw();
// ===================== NIKKO-SIDEPANEL =====================
// The column. Three jobs: get #sigbar out of .hd, keep a heading and a legend on
// it across redraws, and place the hover card.
(function(){
 const el=document.getElementById('sigbar'); if(!el) return;
 // .hd has backdrop-filter -> it is the containing block for position:fixed
 // descendants, so left:0 inside it means the header's left edge, not the
 // viewport's. Out to <body> it goes. Once.
 const _lr_move=()=>{ if(el.parentNode!==document.body)
   document.body.insertBefore(el, document.body.firstChild); };
 _lr_move();
 // _sb_draw rebuilds innerHTML on every draw(), which wipes anything added here --
 // so it is re-added whenever the children change. The guard makes it idempotent.
 const _lr_paint=()=>{
  if(!el.querySelector('.lrt')){
   const t=document.createElement('p'); t.className='lrt';
   t.innerHTML='<span class=lrd></span>WHAT IS FIRING<em>tonight</em>';
   el.insertBefore(t, el.firstChild);
  }
  if(!el.querySelector('.lrn')){
   const n=document.createElement('p'); n.className='lrn';
   n.innerHTML='<b>PAIRS</b> are graded objects \u2014 a bat read and an arm read '
    +'both clearing their cut on this bat tonight. <u>LEGS</u> are single reads: '
    +'each is one part of a consensus gate, and none of them is a call on its own. '
    +'Hover a row for what it reads and what it pairs with. Click to filter.';
   el.appendChild(n);
  }
 };
 new MutationObserver(_lr_paint).observe(el,{childList:true});
 _lr_paint();
 // a fixed card has to be told where the row is. Delegated, so it survives redraws.
 el.addEventListener('mouseover', e=>{
  const c=e.target.closest('.sbc'); if(!c) return;
  const p=c.querySelector('.ubp'); if(!p) return;
  const r=c.getBoundingClientRect();
  if(getComputedStyle(p).position!=='fixed') return;   // narrow layout: leave it
  const h=p.offsetHeight||0;
  // keep the whole card on screen when the row sits near the bottom of the viewport
  p.style.top=Math.round(Math.max(8, Math.min(r.top-6, window.innerHeight-h-12)))+'px';
 });
})();
// =================== end NIKKO-SIDEPANEL ===================
</script>"""
