#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
slipforge.py -- a SEPARATE slip engine. No app.py. One file, whole board,
                callers instead of rankings, assembly that concentrates.

READ ONLY on your data. Writes nothing. Run from ~/mlb_analytics.

    python slipforge.py                          # tonight, from the newest board CSV
    python slipforge.py --board boards/boards_2026-08-16.csv
    python slipforge.py --shape 3tb --slips 3
    python slipforge.py --replay                 # backtest on every graded board
    python slipforge.py --replay --shape 3tb

WHY THIS EXISTS
---------------
You asked for a system to race the generator. This is it, built from what was
MEASURED tonight -- on your own 1,588 bet legs and your own boards -- not from
theory:

  ASSEMBLY (your ledger, 21 nights, same legs, same caps):
      your actual first-3 slips        3 slips won,  3 winning nights
      concentrated pairing             6 slips won,  5 winning nights
      random pairing                   1.4 / 1.3
  Winning slips were CONSTRUCTIBLE from legs you had already bet on 19 of 22
  nights; your slips cashed on 11. Pairing, not calling, threw away 9 nights.
  So this engine pairs strongest-with-strongest, exactly, and prints why.

  HR CALLERS (validated on your actual bets / your boards):
      STACK9      hr_stack_n >= 9            29.6%  on your bets (n=27)
      LANES       hr_lanes.json conditions   21-25% floors, out of fold
      DEEP CARRY  deep-family alignment past the chalk window
                                             21.3%, 1.03 bats/night past rank 100
      SUBZONE     zone_overlap BOTTOM 12% with real power
                                             19.8%, 1.76x (the longshot lane)
      POWER TOP   power composite top 2%     15.9%, 1.49x
  The longshot lanes are first-class callers here, not an afterthought --
  DEEP CARRY and SUBZONE exist precisely because most homers are not chalk.
      MODEL-X     hr_model_v1.json, 14-feature logistic on the 49-night record
                  OOF top-5 22.4%; 73% of its picks are bats no caller names
                  (21.3% on those); caller-top5 OR model-top5 held a homer on
                  88% of nights vs 67% for callers alone. Top five a night.

  TB CALLERS:
      ZONE TOP    zone_overlap top decile    70.0% on 535 graded legs
      STRIP-ARM   STRIP bat + an arm that allows contact (ars_xba_v2 top-40%)
                  50.5% tb15 / 40.5% stripped on 42 nights -- 53.5% in AUGUST
      STRIP       the no-homer contact lane  45.9% tb15, 34.6% with HR DELETED
                  xba p80 x platoon edge x low-K bat. 61% new bats vs the other
                  callers; holds 43.3% on the quiet half of nights. This is the
                  hedge for the 08-15 mode: board homers die, this lane doesn't.
      LOWK        contact bat vs low-K arm   43.7% on 355 of your bets
      LANES       tb_lanes.json conditions   41-48% floors
  No power column touches the TB side. Your HR-flavored TB legs hit 17.2%.
  ZONE-TOP10's clears need the homer 38% of the time; STRIP's only 25% -- same
  headline rate, different weather. (Doubles-rate "XBH bats" measured 28.9% solo
  on the stripped grade -- below the bar, NOT wired. When ars_xba_v2 lands on
  the board, measure xba x ars_xba_v2 on the 49-night record before pricing.)

  LEG PROBABILITIES are the MEASURED rates above -- never the display number.
  Your display was measured tonight: HR "18%" hits 12.5%, HR "22%" hits 18.3%,
  TB "29%" hits 39.2%. This file prices legs at what they actually did.

No price, no break-even, no EV. Slips WON is the only score. 3-leg shapes only.
"""

import argparse
import glob
import json
import os
import re
import sys
import warnings
from itertools import combinations

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None

VERSION = ("slipforge v2.19 -- SLG-FIT: the bat vs THIS ARM'S ACTUAL PITCH MIX (his idea) = 48.4% at 10-deep, 44.2% at 20-deep, against 34.1% for the board's worst-pitch read. PREVIOUS: v2.18 -- NK-FIVE (his eyeball rule: iso-hand/vuln/loc-fit/arsenal-match p80 + zone p70, 4 of 5, ON CALLED BATS ONLY = 43.7% vs 41.3% callers, halves 42.2/45.2) + NIKKO-ARMFORM: six arm reads that were sitting unused in arsenal_v2.csv are merged; xSLG is the right form, not xISO (37.4 vs 36.4). PREVIOUS: v2.17 -- HR-FOUND + THE PIN LIST IS THE THIRTY. The "
           "10-night missed-homer autopsy found the column no caller read: the "
           "board's own hr_value (missed homers pct .58 vs .27). HR-FOUND "
           "(hr_value p75 & iso_hand p60, uncalled only) = 13.6%/13.7 Aug on "
           "1,282 ledger legs, ~26/night; POOL RECALL of the night's homers "
           "6.8 -> 10.4 (+52%). And boards/tb_pinlist.txt is now written every "
           "run with THE THIRTY, so the app's Custom TB 'Pin list' mode selects "
           "from exactly these 30, tiered and stacked")
GRADED = re.compile(r"graded_full_(\d{4}-\d{2}-\d{2})\.csv$")
BOARD_ANY = re.compile(r"^boards_(\d{4}-\d{2}-\d{2})[A-Za-z0-9_\-]*\.csv$")
SHAPES = {"1hr2tb": (1, 2), "2hr1tb": (2, 1), "3hr": (3, 0), "3tb": (0, 3),
          "2hr": (2, 0), "1hr1tb": (1, 1)}

# measured leg rates, provenance in the header. Conservative side of each read.
P_HR = {"STACK9": 0.26, "LANE": 0.21, "DEEP": 0.19, "SUBZONE": 0.17, "POWERTOP": 0.16,
        "SWING": 0.18, "MODELX": 0.21, "PENDOOR": 0.15, "FOUND": 0.14}
P_TB = {"ZONETOP": 0.50, "STRIPARM": 0.50, "SLGFIT": 0.48, "MATCH5": 0.47, "STRIP": 0.46, "BLOWUP": 0.46, "NKFIVE": 0.44, "TBMODEL": 0.44, "LANE": 0.44, "LOWK": 0.43}
MULTI_BONUS = 0.02          # a bat two callers name, capped
P_CAP_HR, P_CAP_TB = 0.30, 0.55

POWER_COLS = [("xiso", 1), ("brl_percent", 1), ("mix_iso_blend", 1),
              ("mix_iso_sp", 1), ("ev50", 1), ("flyballs_percent", 1)]
CONTACT_COLS = [("contact_score", 1), ("xba", 1), ("batting_avg", 1),
                ("k_percent", -1), ("babip", 1), ("ld_rate", 1), ("xwoba", 1)]

DEF_HR_LANES = [dict(name="MIXB_WPX", a="mix_iso_blend", sa=1, b="worst_pitch_xslg", sb=1, cut=0.12),
                dict(name="ZONE_VULN", a="zone_overlap", sa=1, b="pitch_vuln_score", sb=1, cut=0.03),
                dict(name="SLEEP_HRARM", a="sleeper_score", sa=1, b="p_hr_per_9", sb=1, cut=0.12),
                dict(name="ISO_ARS", a="xiso", sa=1, b="ars_xslg", sb=1, cut=0.12)]
DEF_TB_LANES = [dict(name="CONTACT_XSLG", a="contact_score", sa=1, b="p_xslg_allowed", sb=1, cut=0.06),
                dict(name="AVG_ZONE", a="batting_avg", sa=1, b="zone_overlap", sb=1, cut=0.08),
                dict(name="LOWK_EV", a="k_percent", sa=-1, b="ev50", sb=1, cut=0.16),
                dict(name="AB_LOWK", a="ab", sa=1, b="p_k_per_9", sb=-1, cut=0.10),
                dict(name="LD_GB", a="ld_rate", sa=1, b="p_gb_allowed", sb=-1, cut=0.13)]


def rule_(ch="-", n=100):
    print(ch * n)


def head(t):
    print("")
    print("=" * 100)
    print("  " + t)
    print("=" * 100)


def num(d, c):
    if c in d.columns:
        return pd.to_numeric(d[c], errors="coerce")
    return pd.Series(np.nan, index=d.index, dtype="float64")


def have(d, c, n=0.20):
    return c in d.columns and num(d, c).notna().mean() >= n


def pct(d, c, s=1):
    r = num(d, c).rank(pct=True)
    return r if s > 0 else (1.0 - r)


def name_col(d):
    for c in ("player", "player_name", "name", "batter"):
        if c in d.columns:
            return c
    return None


def load_lanes(path, default):
    try:
        if os.path.exists(path):
            j = json.load(open(path))
            got = [l for l in (j.get("lanes") or []) if l.get("kind", "pair") == "pair"]
            if got:
                return got
    except Exception:
        pass
    return default


def composite(d, cols):
    parts = [pct(d, c, s) for c, s in cols if have(d, c)]
    if not parts:
        return pd.Series(0.5, index=d.index)
    return (sum(parts) / len(parts)).rank(pct=True)


# ======================= SAVANT BAT-TRACKING MERGE ===========================
# Drop Baseball Savant's bat-tracking CSV (Download CSV on the leaderboard, or
# append ?csv=true) into this folder or boards/ as savant_bat_tracking.csv or
# bat-tracking*.csv. If present, its swing columns are merged onto the board by
# name and the SWING caller arms itself. Absent, nothing changes.

def savant_merge(B):
    path = None
    for pat in ("savant_bat_tracking.csv", "bat-tracking*.csv", "bat_tracking*.csv",
                "boards/savant_bat_tracking.csv", "boards/bat-tracking*.csv"):
        got = sorted(glob.glob(pat))
        if got:
            path = got[-1]
            break
    if path is None:
        return B, False
    try:
        S = pd.read_csv(path, low_memory=False)
    except Exception:
        return B, False
    scol = next((c for c in S.columns if c.lower() in
                 ("name", "player", "last_name, first_name", "player_name")), None)
    nc = name_col(B)
    if scol is None or nc is None:
        return B, False

    def norm(x):
        x = str(x).strip().lower()
        if "," in x:                       # "Last, First" -> "first last"
            last, first = [t.strip() for t in x.split(",", 1)]
            x = first + " " + last
        return re.sub(r"[^a-z ]", "", x)

    S = S.copy()
    S["_k"] = S[scol].map(norm)
    B = B.copy()
    B["_k"] = B[nc].map(norm)
    keep = [c for c in ("bat_speed", "avg_bat_speed", "fast_swing_rate",
                        "hard_swing_rate", "squared_up_per_swing", "squared_up_rate",
                        "blasts", "blasts_per_swing", "blast_per_swing",
                        "blast_per_bat_contact", "attack_angle",
                        "ideal_attack_angle_rate", "attack_direction",
                        "swing_length") if c in S.columns]
    if not keep:
        return B.drop(columns=["_k"]), False
    M = S.drop_duplicates("_k").set_index("_k")[keep]
    for c in keep:
        B["sv_" + c] = B["_k"].map(pd.to_numeric(M[c], errors="coerce"))
    hit = B[["sv_" + c for c in keep]].notna().any(axis=1).mean()
    print("  [savant] merged %s -- %d swing column(s), %.0f%% of bats matched"
          % (os.path.basename(path), len(keep), 100 * hit))
    return B.drop(columns=["_k"]), hit >= 0.3


# ===================== MATCHUP MERGE (zone x pitch-type) =====================
# If the zone CSVs sit in ~/mlb_analytics (zone_batter_2025.csv / zone_pitcher_
# 2025.csv, 2024 as fallback) and the board carries a pitcher id, this computes
# mz_fit -- the batter's own damage in THIS pitcher's actual pitch x zone mix --
# and the MZ-ZONE caller arms. Measured on 35 graded nights: mz top10 AND zone
# top10 = 26.4% HR (2.26x). mz alone without the zone half is BASE -- the AND is
# the signal.
_MZ = {"ready": False}


def _mz_load():
    if _MZ["ready"]:
        return _MZ
    try:
        bz = []
        pz = []
        for f in ("zone_batter_2025.csv", "zone_batter_2024.csv"):
            if os.path.exists(f):
                bz.append(pd.read_csv(f))
        for f in ("zone_pitcher_2025.csv", "zone_pitcher_2024.csv"):
            if os.path.exists(f):
                pz.append(pd.read_csv(f))
        if not bz or not pz:
            _MZ["ready"] = None
            return _MZ
        bzd = (pd.concat(bz).groupby(["batter", "pitch_type", "zone"])
               .agg(n=("n", "sum"), xw=("xwoba", "mean")).reset_index())
        pzd = (pd.concat(pz).groupby(["pitcher", "pitch_type", "zone"])["n"]
               .sum().reset_index())
        _MZ["lg_ptz"] = bzd.groupby(["pitch_type", "zone"]).apply(
            lambda t: np.average(t.xw, weights=t.n)).to_dict()
        _MZ["lg_pt"] = bzd.groupby("pitch_type").apply(
            lambda t: np.average(t.xw, weights=t.n)).to_dict()
        _MZ["bpt"] = bzd.groupby(["batter", "pitch_type"]).apply(
            lambda t: (float(np.average(t.xw, weights=t.n)), int(t.n.sum()))).to_dict()
        _MZ["bcell"] = {(r.batter, r.pitch_type, r.zone): (r.xw, r.n)
                        for r in bzd.itertuples()}
        pu = {}
        for r in pzd.itertuples():
            pu.setdefault(r.pitcher, []).append((r.pitch_type, r.zone, r.n))
        _MZ["pu"] = pu
        _MZ["ready"] = True
    except Exception:
        _MZ["ready"] = None
    return _MZ


_PIDS = {"m": None}


def _pname_norm(s):
    """'Jesús Luzardo : L' / 'Jesus Luzardo' -> same key. Strips the hand tag,
    accents, case, extra space."""
    import unicodedata
    s = str(s).strip()
    s = re.sub(r"\s*[:(]\s*[LRS]\s*[)]?\s*$", "", s)
    s = re.sub(r"\s+", " ", s)
    s = "".join(ch for ch in unicodedata.normalize("NFKD", s)
                if not unicodedata.combining(ch))
    return s.casefold()


def _pid_map():
    """pitcher NAME -> MLBAM id, from pitcher_ids.csv (built off the graded
    record: 153 starters, zero ambiguous names). Looked for next to this file,
    in the cwd, and in ~/mlb_analytics{,/boards}."""
    if _PIDS["m"] is not None:
        return _PIDS["m"]
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (here, os.getcwd(), os.path.expanduser("~/mlb_analytics"),
              os.path.expanduser("~/mlb_analytics/boards")):
        f = os.path.join(d, "pitcher_ids.csv")
        if os.path.exists(f):
            try:
                t = pd.read_csv(f)
                _PIDS["m"] = dict(zip(t.iloc[:, 0].astype(str).map(_pname_norm),
                                      pd.to_numeric(t.iloc[:, 1], errors="coerce")))
                return _PIDS["m"]
            except Exception:
                pass
    _PIDS["m"] = {}
    return _PIDS["m"]


_ARS = {"ready": False}


def _ars_load():
    """arsenal_v2.csv (arm-level: ars_xba_v2 = contact this arsenal allows) and
    batter_arsenal_v2.csv (bat x pitch_type xISO) for iso_fit. Searched next to
    this file, cwd, boards/, ~/mlb_analytics{,/boards}. Absent -> skipped."""
    if _ARS["ready"] is not False:
        return _ARS
    _ARS["ready"] = None
    dirs = [os.path.dirname(os.path.abspath(__file__)), os.getcwd(), "boards",
            os.path.expanduser("~/mlb_analytics"), os.path.expanduser("~/mlb_analytics/boards")]
    fa = next((os.path.join(d, "arsenal_v2.csv") for d in dirs
               if os.path.exists(os.path.join(d, "arsenal_v2.csv"))), None)
    fb = next((os.path.join(d, "batter_arsenal_v2.csv") for d in dirs
               if os.path.exists(os.path.join(d, "batter_arsenal_v2.csv"))), None)
    try:
        if fa:
            A = pd.read_csv(fa)
            _ARS["xba"] = dict(zip(A["pitcher_id"].astype(int), A["ars_xba_v2"]))
            # NIKKO-ARMFORM 2026-08-18 -- arsenal_v2.csv carries SEVEN arm reads and
            # only ars_xba_v2 was ever merged. Measured on 50 graded nights, the most
            # hittable fifth of arms by each read, 1.5TB (board base 32.1%):
            #     ars_xslg_v2 37.4%  (Aug 37.1, halves 37.4/37.3)  <- best, dead stable
            #     ars_rv100_v2(low) 36.7   ars_xwoba_v2 36.5   ars_xiso_v2 36.4
            #     ars_xba_v2 36.1  <- the only one wired until now
            #     worst_pitch_xslg 34.1  <- the board's headline arm read, weakest
            # HIS QUESTION ANSWERED: xSLG, not xISO. 1.5TB pays on singles too, and
            # stripping them (ISO) costs a point. Merged, not yet priced into a lane.
            for _c in ("ars_xslg_v2", "ars_xiso_v2", "ars_xwoba_v2", "ars_rv100_v2",
                       "ars_whiff_v2", "ars_k_v2", "ars_hh_v2"):
                if _c in A.columns:
                    _ARS[_c] = dict(zip(A["pitcher_id"].astype(int), A[_c]))
        # NIKKO-SLGFIT 2026-08-18 -- HIS IDEA: "should we be doing that against all
        # arsenals individually instead of lumping them together -- maybe they don't
        # hit the pitcher's worst pitch but they hit sliders very well."
        # slg_fit = SUM_p ( arm's usage of pitch p x this BAT's est_SLG vs pitch p ).
        # MEASURED, 50 graded nights, 1.5TB (board 32.1%, callers 41.3%):
        #     slg_fit x armSLG  top-10/nt  48.4%  (Aug 45.3, halves 50.8/46.0)
        #     slg_fit x armSLG  top-20/nt  44.2%  (Aug 43.2, halves 45.2/43.2)
        #     slg_fit alone     top-10     45.0%    iso_fit_tb top-10 45.2%
        #     arm's own-mix SLG top-10     35.8%    worst_pitch_xslg  34.1%
        # Beating the whole caller stack, and beating the single-worst-pitch read by
        # FOURTEEN points. SLG not ISO: 1.5TB pays on singles, ISO throws them away.
        fu = next((os.path.join(d, "pitch_usage.csv") for d in dirs
                   if os.path.exists(os.path.join(d, "pitch_usage.csv"))), None)
        if fu:
            U = pd.read_csv(fu)
            ncol = next((c for c in ("last_name, first_name", "name", "player_name")
                         if c in U.columns), None)
            if ncol is not None and "pitch_type" in U.columns:
                U["_k"] = U[ncol].map(lambda x: _pname_norm(
                    " ".join(reversed([p.strip() for p in str(x).split(",")]))))
                U["_w"] = pd.to_numeric(U.get("pitch_usage"), errors="coerce").fillna(0.0)
                _mix, _asl = {}, {}
                for k, g in U.groupby("_k"):
                    w = g["_w"]
                    if float(w.sum()) <= 0:
                        continue
                    _mix[k] = dict(zip(g["pitch_type"], (w / w.sum()).tolist()))
                    es = pd.to_numeric(g.get("est_slg"), errors="coerce")
                    ok = es.notna() & (w > 0)
                    if ok.any():
                        _asl[k] = float(np.average(es[ok], weights=w[ok]))
                _ARS["mix"] = _mix
                _ARS["armslg"] = _asl
        if fb:
            BA = pd.read_csv(fb)
            _ARS["iso"] = {(int(r.batter_id), r.pitch_type): (r.xiso_vs, r.pa)
                           for r in BA.itertuples() if not pd.isna(r.xiso_vs)}
            _ARS["slg"] = {(int(r.batter_id), r.pitch_type): (r.est_slg, r.pa)
                           for r in BA.itertuples() if not pd.isna(getattr(r, "est_slg", np.nan))}
            try:
                _ARS["lg_slg"] = BA.groupby("pitch_type").apply(
                    lambda g: np.average(g["est_slg"].dropna(),
                                         weights=g.loc[g["est_slg"].notna(), "pa"])).to_dict()
            except Exception:
                _ARS["lg_slg"] = {}
            _ARS["lg_iso"] = BA.groupby("pitch_type").apply(
                lambda g: np.average(g["xiso_vs"].dropna(),
                                     weights=g.loc[g["xiso_vs"].notna(), "pa"])).to_dict()
        if fa or fb:
            _ARS["ready"] = True
    except Exception:
        _ARS["ready"] = None
    return _ARS


def _resolve_pid(B):
    for c in ("opp_pitcher_id_true", "opp_pitcher_id", "opp_sp_id"):
        if c in B.columns and pd.to_numeric(B[c], errors="coerce").notna().mean() > 0.2:
            return pd.to_numeric(B[c], errors="coerce")
    namec = next((c for c in ("opp_pitcher", "opp_sp_name", "opp_pitcher_name",
                              "opp_starter") if c in B.columns
                  and B[c].notna().mean() > 0.2), None)
    pmap = _pid_map()
    if namec and pmap:
        s = B[namec].astype(str).map(_pname_norm).map(pmap)
        if s.notna().mean() > 0.2:
            return pd.to_numeric(s, errors="coerce")
    return None


def arsenal_merge(B):
    """Adds ars_xba_v2 (STRIP-ARM's arm axis) and iso_fit (bat's per-pitch xISO
    weighted by tonight's arm's actual mix -- the #2 feature in the HR model).
    Pitch-type usage reuses the zone files already loaded for mz_fit."""
    A = _ars_load()
    if not A["ready"]:
        return B
    pid = _resolve_pid(B)
    if pid is None or "player_id" not in B.columns:
        return B
    B = B.copy()
    if "xba" in A and "ars_xba_v2" not in B.columns:
        B["ars_xba_v2"] = pid.map(A["xba"])
    for _c in ("ars_xslg_v2", "ars_xiso_v2", "ars_xwoba_v2", "ars_rv100_v2",
               "ars_whiff_v2", "ars_k_v2", "ars_hh_v2"):   # NIKKO-ARMFORM
        if _c in A and _c not in B.columns:
            B[_c] = pid.map(A[_c])
    M = _mz_load()
    if "iso" in A and M["ready"] and "iso_fit" not in B.columns:
        # per-pitcher pitch-TYPE usage, collapsed from the (pt, zone, n) mix
        pu_t = {}
        for p, mix in M["pu"].items():
            tot = sum(n for _pt, _z, n in mix)
            d = {}
            for pt, _z, n in mix:
                d[pt] = d.get(pt, 0.0) + n / tot
            pu_t[p] = d

        def ifit(b, p):
            mix = pu_t.get(p)
            if not mix:
                return np.nan
            s = w = 0.0
            for pt, u in mix.items():
                c = A["iso"].get((b, pt))
                v = c[0] if c and c[1] >= 20 else A["lg_iso"].get(pt, 0.145)
                s += u * v
                w += u
            return s / w if w else np.nan
        bb = pd.to_numeric(B["player_id"], errors="coerce").fillna(-1).astype(int).values
        pp = pid.fillna(-1).astype(int).values
        B["iso_fit"] = [ifit(b, p) for b, p in zip(bb, pp)]
    # ===================== NIKKO-SLGFIT =====================
    # The bat's expected SLUGGING against THIS arm's actual pitch mix, plus the
    # arm's own mix-weighted SLG allowed. Keyed off the pitcher NAME (pitch_usage
    # carries "Last, First"), so it works on every board that names the starter.
    try:
        _mix = A.get("mix") or {}
        _bslg = A.get("slg") or {}
        _lgs = A.get("lg_slg") or {}
        _armslg = A.get("armslg") or {}
        # --- NIKKO-ISOFIT: the ISO tables are already loaded above and have
        # never been used.  Same shape as slg / lg_slg. ---
        _biso = A.get("iso") or {}
        _lgi = A.get("lg_iso") or {}
        _namec = next((c for c in ("opp_pitcher", "opp_sp_name", "opp_pitcher_name")
                       if c in B.columns), None)
        if _mix and _bslg and _namec:
            _ak = B[_namec].astype(str).map(_pname_norm)
            _bid = pd.to_numeric(B["player_id"], errors="coerce")

            def _sfit(_b, _a):
                m = _mix.get(_a)
                if not m or pd.isna(_b):
                    return np.nan
                tot = wsum = 0.0
                for _pt, _w in m.items():
                    _base = _lgs.get(_pt)
                    if _base is None:
                        continue
                    _v = _bslg.get((int(_b), _pt))
                    _x = _v[0] if (_v and _v[1] >= 15 and not pd.isna(_v[0])) else _base
                    tot += _w * _x; wsum += _w
                return tot / wsum if wsum > 0 else np.nan

            B["slg_fit"] = [_sfit(_b, _a) for _b, _a in zip(_bid, _ak)]
            B["arm_slg_mix"] = _ak.map(_armslg)
            _r1 = num(B, "slg_fit").rank(pct=True)
            _r2 = num(B, "arm_slg_mix").rank(pct=True)
            B["slgfit_arm"] = 0.90 * _r1 + 0.10 * _r2  # NIKKO-BATWEIGHT: was (_r1+_r2)/2.0.
            # _r2 is one value per ARM, identical for a whole lineup, so at 50% it buried
            # bat-vs-bat separation.  Changed for DECORRELATION at equal measured rate --
            # top10 went 5.4 -> ~8.0 distinct arms, 36 nights.  NOT a rate claim.

            # --- NIKKO-ISOFIT: the same function, the ISO payload.  Same arm
            # usage weights, same pa >= 15 gate, same league fallback per pitch.
            # est_slg -> xiso_vs is the only thing that changes.
            def _ifit(_b, _a):
                m = _mix.get(_a)
                if not m or pd.isna(_b):
                    return np.nan
                tot = wsum = 0.0
                for _pt, _w in m.items():
                    _base = _lgi.get(_pt)
                    if _base is None:
                        continue
                    _v = _biso.get((int(_b), _pt))
                    _x = _v[0] if (_v and _v[1] >= 15 and not pd.isna(_v[0])) else _base
                    tot += _w * _x; wsum += _w
                return tot / wsum if wsum > 0 else np.nan

            B["iso_fit"] = [_ifit(_b, _a) for _b, _a in zip(_bid, _ak)]
            _r3 = num(B, "iso_fit").rank(pct=True)
            B["isofit_arm"] = (_r3 + _r2) / 2.0
            # --- end NIKKO-ISOFIT ---
    except Exception:
        pass
    # ===================== end NIKKO-SLGFIT =====================
    got = [c for c in ("ars_xba_v2", "ars_xslg_v2", "iso_fit", "slg_fit", "slgfit_arm")
           if c in B.columns
           and pd.to_numeric(B[c], errors="coerce").notna().mean() > 0.15]
    if got:
        print("  [arsenal] merged: %s" % ", ".join(got))
    return B


_TBMODEL = {"m": False}


def _tb_model_load():
    """tb_model_v1.json -- the FULL-SLATE TB machine, trained on all 12,399
    graded TB bat-games (90 features, night-grouped CV). OOF: top-10 44.5%,
    top-15 44.6%, top-20 44.0% (Aug 42.7) -- a flat shelf, the deepest
    sustained TB read measured. The app's own tb_prob at 20-deep: 39.7%."""
    if _TBMODEL["m"] is not False:
        return _TBMODEL["m"]
    _TBMODEL["m"] = None
    dirs = [os.path.dirname(os.path.abspath(__file__)), os.getcwd(), "boards",
            os.path.expanduser("~/mlb_analytics"), os.path.expanduser("~/mlb_analytics/boards")]
    f = next((os.path.join(d, "tb_model_v1.json") for d in dirs
              if os.path.exists(os.path.join(d, "tb_model_v1.json"))), None)
    if f:
        try:
            _TBMODEL["m"] = json.load(open(f))
        except Exception:
            _TBMODEL["m"] = None
    return _TBMODEL["m"]


def tb_model_scores(B):
    mj = _tb_model_load()
    if not mj:
        return None
    z = pd.Series(float(mj.get("intercept", 0.0)), index=B.index)
    seen = 0
    for c, w in mj["features"].items():
        if c in B.columns and pd.to_numeric(B[c], errors="coerce").notna().mean() > 0.1:
            z = z + w * pd.to_numeric(B[c], errors="coerce").rank(pct=True).fillna(0.5)
            seen += 1
        else:
            z = z + w * 0.5
    return z if seen >= 10 else None


_MODEL = {"m": False}


def _model_load():
    """hr_model_v1.json -- the 14-feature logistic fit on all 49 graded nights.
    OOF (night-grouped, never scored a night it trained on): top-5 22.4% HR,
    >=1 of top-5 homered on 71% of nights, and the model's picks are mostly
    DIFFERENT bats from the callers (its non-caller picks hit 21.3%). The union
    of model top-5 and caller top-5 held a homer on 88% of the 49 nights."""
    if _MODEL["m"] is not False:
        return _MODEL["m"]
    _MODEL["m"] = None
    dirs = [os.path.dirname(os.path.abspath(__file__)), os.getcwd(), "boards",
            os.path.expanduser("~/mlb_analytics"), os.path.expanduser("~/mlb_analytics/boards")]
    f = next((os.path.join(d, "hr_model_v1.json") for d in dirs
              if os.path.exists(os.path.join(d, "hr_model_v1.json"))), None)
    if f:
        try:
            _MODEL["m"] = json.load(open(f))
        except Exception:
            _MODEL["m"] = None
    return _MODEL["m"]


def model_scores(B):
    """Within-night pct-rank the model's features (missing -> 0.5), dot the
    coefficients. Returns a Series or None."""
    mj = _model_load()
    if not mj:
        return None
    z = pd.Series(float(mj.get("intercept", 0.0)), index=B.index)
    seen = 0
    for c, w in mj["features"].items():
        if c in B.columns and pd.to_numeric(B[c], errors="coerce").notna().mean() > 0.1:
            z = z + w * pd.to_numeric(B[c], errors="coerce").rank(pct=True).fillna(0.5)
            seen += 1
        else:
            z = z + w * 0.5
    return z if seen >= 8 else None


def matchup_merge(B):
    M = _mz_load()
    if not M["ready"]:
        return B
    pidc = next((c for c in ("opp_pitcher_id_true", "opp_pitcher_id", "opp_sp_id")
                 if c in B.columns and pd.to_numeric(B[c], errors="coerce").notna().mean() > 0.2),
                None)
    if pidc is None:
        # LIVE-BOARD FALLBACK -- the live export ships without opp_pitcher_id_true,
        # which was leaving MZ-ZONE (the best AND-read on the board) dark on game
        # nights. Map the opponent starter NAME through pitcher_ids.csv instead.
        namec = next((c for c in ("opp_pitcher", "opp_sp_name", "opp_pitcher_name",
                                  "opp_starter")
                      if c in B.columns and B[c].notna().mean() > 0.2), None)
        pmap = _pid_map()
        if namec and pmap:
            B = B.copy()
            B["_pid_fb"] = B[namec].astype(str).map(_pname_norm).map(pmap)
            if B["_pid_fb"].notna().mean() > 0.2:
                pidc = "_pid_fb"
                print("  [matchup] no pitcher-id column live -- mapped %s by name "
                      "(pitcher_ids.csv)" % namec)
    if pidc is None or "player_id" not in B.columns:
        return B
    def mzv(b, p):
        mix = M["pu"].get(p)
        if not mix:
            return np.nan
        tot = sum(n for _pt, _z, n in mix)
        sacc = w = 0.0
        for pt, z, n in mix:
            u = n / tot
            c = M["bcell"].get((b, pt, z))
            if c and c[1] >= 8:
                v = c[0]
            else:
                t = M["bpt"].get((b, pt))
                v = t[0] if t and t[1] >= 25 else M["lg_ptz"].get((pt, z), M["lg_pt"].get(pt, 0.32))
            sacc += u * v
            w += u
        return sacc / w if w > 0 else np.nan
    bb = pd.to_numeric(B["player_id"], errors="coerce").fillna(-1).astype(int).values
    pp = pd.to_numeric(B[pidc], errors="coerce").fillna(-1).astype(int).values
    B = B.copy()
    B["mz_fit"] = [mzv(b, p) for b, p in zip(bb, pp)]
    cvr = float(pd.Series(B["mz_fit"]).notna().mean())
    if cvr >= 0.15:
        print("  [matchup] mz_fit on %.0f%% of the board (pitcher id: %s)" % (100 * cvr, pidc))
    return B


# ========================= LIVING PRICES (calibration) =======================
# Prices drift with the season (August: ZONE-TOP10 measured 39.5% vs its era
# .50; STRIP-ARM 50.9%). Every generate now re-measures each caller on the
# TRAILING 20 graded nights (shrunk toward the era price, K=150 pseudo-legs)
# and scales its calls accordingly. Cached per day in prices_cache.json.
# Walk-forward replay: NEUTRAL on the 3-slip anchors (identical slips), so this
# is honesty, not a claimed edge -- it matters in the deep book ordering and in
# what YOU read off the card. (The xba assembly tiebreak tested WORSE
# out-of-sample, -2pts, and is NOT wired.)
_CAL = {"state": None, "building": False}
_TAGMAP = {"ZONE-TOP10": ("TB", "ZONETOP"), "STRIP-ARM": ("TB", "STRIPARM"),
           "STRIP-CONTACT": ("TB", "STRIP"), "LOWK-ARM": ("TB", "LOWK"),
           "BLOWUP": ("TB", "BLOWUP"), "NK-FIVE": ("TB", "NKFIVE"), "SLG-FIT": ("TB", "SLGFIT"),
           "STACK9": ("HR", "STACK9"), "DEEP-CARRY": ("HR", "DEEP"),
           "SUBZONE": ("HR", "SUBZONE"), "POWER-TOP": ("HR", "POWERTOP"),
           "SWING": ("HR", "SWING"), "MODEL-X": ("HR", "MODELX"),
           "PEN-DOOR": ("HR", "PENDOOR"), "HR-FOUND": ("HR", "FOUND")}


_FORM = {"key": None, "sets": None}
_FORM_MULT = {0: 0.90, 1: 1.05, 2: 1.05, 3: 0.85}


def _form_key(n):
    return _FORM_MULT[min(int(n), 3)]


def _trail_form(B):
    """Trailing-10-graded-night ACTUAL homer count per board bat, by name.
    MEASURED on 48 replayed nights (called bats, August rates): chalk with 1-2
    recent homers 20.2%, cold chalk (0) 15.9%, overheated chalk (3+) 12.7%;
    mid with 2 recent 15.6% -- chalk-level. 'The engine calls too many chalk
    bats that DO NOT homer nightly' (2026-08-17): the form multiplier is the
    one reordering of the SIXTEEN that BEAT price-first in replay (Aug
    homers-in-16 3.40 vs 3.20, season 3.54 vs 3.42). ORDERING ONLY -- the
    leg's measured price is never touched."""
    try:
        gf = sorted(glob.glob("boards/graded_full_*.csv"))[-10:]
        if not gf:
            return {}
        if _FORM["key"] != gf[-1]:
            sets_ = []
            for f in gf:
                try:
                    g = pd.read_csv(f, low_memory=False)
                    ncol = next((c for c in ("name", "player_name", "batter_name")
                                 if c in g.columns), None)
                    if ncol is None or "hr_hit" not in g.columns:
                        continue
                    hh = num(g, "hr_hit")
                    sets_.append(set(g.loc[hh > 0, ncol].map(_pname_norm)))
                except Exception:
                    continue
            _FORM["key"], _FORM["sets"] = gf[-1], sets_
        ncol = next((c for c in ("name", "player_name", "batter_name")
                     if c in B.columns), None)
        if ncol is None or not _FORM["sets"]:
            return {}
        return {i: sum(1 for s in _FORM["sets"]
                       if _pname_norm(B.loc[i, ncol]) in s) for i in B.index}
    except Exception:
        return {}


def _living_prices():
    if _CAL["state"] is not None or _CAL["building"]:
        return _CAL["state"] or {}
    _CAL["building"] = True
    try:
        gf = sorted(glob.glob("boards/graded_full_*.csv"))[-20:]
        if len(gf) < 8:
            _CAL["state"] = {}
            return {}
        import datetime as _dt
        cachef = "prices_cache.json"
        key = os.path.basename(gf[-1])
        if os.path.exists(cachef):
            try:
                cj = json.load(open(cachef))
                if cj.get("key") == key:
                    _CAL["state"] = cj["mult"]
                    return _CAL["state"]
            except Exception:
                pass
        tag_n = {}
        tag_h = {}
        for f in gf:
            g = pd.read_csv(f, low_memory=False)
            yh = num(g, "hr_hit")
            yt = num(g, "tb15_hit")
            gc = g[yh.notna() | yt.notna()].reset_index(drop=True)
            if len(gc) < 40:
                continue
            hh = num(gc, "hr_hit")
            tt = num(gc, "tb15_hit")
            for calls, out in ((call_hr(gc, DEF_HR_LANES), hh), (call_tb(gc, DEF_TB_LANES), tt)):
                for i, (_p, w) in calls.items():
                    t0 = str(w[0]).split(":")[0]
                    if t0 not in _TAGMAP or pd.isna(out.get(i, np.nan)):
                        continue
                    tag_n[t0] = tag_n.get(t0, 0) + 1
                    tag_h[t0] = tag_h.get(t0, 0) + int(out[i] > 0)
        K = 150.0
        mult = {}
        for t0, (side, key2) in _TAGMAP.items():
            era = (P_TB if side == "TB" else P_HR).get(key2)
            n = tag_n.get(t0, 0)
            if not era or n < 25:
                continue
            rate = (tag_h.get(t0, 0) + K * era) / (n + K)
            mult[t0] = round(rate / era, 4)
        _CAL["state"] = mult
        try:
            json.dump({"key": key, "mult": mult}, open(cachef, "w"))
        except Exception:
            pass
        got = ", ".join("%s x%.2f" % (k, v) for k, v in sorted(mult.items()) if abs(v - 1) >= 0.03)
        if got:
            print("  [living] trailing-20 reprice: %s" % got)
        return mult
    except Exception:
        _CAL["state"] = {}
        return {}
    finally:
        _CAL["building"] = False


def _apply_living(calls, cap):
    m = _living_prices()
    if not m:
        return calls
    out = {}
    for i, (p, w) in calls.items():
        t0 = str(w[0]).split(":")[0]
        out[i] = (min(cap, p * m[t0]), w) if t0 in m else (p, w)
    return out


# ============================== THE CALLERS ==================================

def call_hr(B, lanes):
    """Every HR caller reads the WHOLE board. Returns {idx: (p, [why])}."""
    calls = {}

    def add(idx, p, why):
        if idx in calls:
            p0, w = calls[idx]
            calls[idx] = (min(max(p0, p) + MULTI_BONUS, P_CAP_HR), w + [why])
        else:
            calls[idx] = (p, [why])

    # STACK9 -- nine or more alignments agree. 29.6% on the bets.
    if have(B, "hr_stack_n"):
        for i in B.index[num(B, "hr_stack_n").fillna(0) >= 9]:
            add(i, P_HR["STACK9"], "STACK9")
    # LANES -- the config conditions, strict, board percentiles.
    for L in lanes:
        a, b = L.get("a"), L.get("b")
        if not (have(B, a) and have(B, b)):
            continue
        cut = float(L.get("cut", 0.10))
        f = (pct(B, a, L.get("sa", 1)) >= 1 - cut) & (pct(B, b, L.get("sb", 1)) >= 1 - cut)
        for i in B.index[f.fillna(False)]:
            add(i, P_HR["LANE"], "LANE:" + str(L.get("name", "?"))[:12])
    # DEEP CARRY -- deep-family alignment on a bat OUTSIDE the chalk window.
    if have(B, "hr_al14_deep_n"):
        rank_pos = (pct(B, "nk_hr_pick", 1) if have(B, "nk_hr_pick")
                    else pct(B, "hr_prob", 1) if have(B, "hr_prob")
                    else pd.Series(0.5, index=B.index))
        deep = (num(B, "hr_al14_deep_n").fillna(0) >= 1) & (rank_pos < 0.75)
        for i in B.index[deep.fillna(False)]:
            add(i, P_HR["DEEP"], "DEEP-CARRY")
    # SUBZONE -- the longshot lane: hidden from the zone read, real power.
    if have(B, "zone_overlap"):
        pw = composite(B, POWER_COLS)
        sub = (pct(B, "zone_overlap", 1) <= 0.12) & (pw >= 0.60)
        for i in B.index[sub.fillna(False)]:
            add(i, P_HR["SUBZONE"], "SUBZONE")
    # POWER TOP -- the crossed-composite read: pure power leaders.
    pw = composite(B, POWER_COLS)
    for i in B.index[pw >= 0.98]:
        add(i, P_HR["POWERTOP"], "POWER-TOP")
    # MZ-ZONE -- their pitches he hits, in zones he hits them. 26.4% (2.26x) on
    # 35 graded nights at top-decile x top-decile; mz without zone is base.
    if have(B, "mz_fit", 0.15) and have(B, "zone_overlap"):
        f = (pct(B, "mz_fit", 1) >= 0.90) & (pct(B, "zone_overlap", 1) >= 0.90)
        for i in B.index[f.fillna(False)]:
            add(i, 0.24, "MZ-ZONE")
    # LONGSHOT LANES -- ranked WITHIN the sub-chalk universe (hr_prob below the
    # night's p60, base 8.5%, 44% of all homers). Both-halves validated:
    #   mixb top15 x wpx top30 of leftovers   14.9%  (1.75x, floor 12.0)
    #   mz top20 x zone top20 of leftovers    14.3%  (1.68x, floor 10.9)
    #   zone top10 of leftovers               13.5%  (floor 11.6)
    if have(B, "hr_prob"):
        _lm = (pct(B, "hr_prob", 1) < 0.60)
        def _lr(cname, sgn=1):
            v = num(B, cname).where(_lm)
            r = v.rank(pct=True)
            return r if sgn > 0 else (1.0 - r)
        if have(B, "mix_iso_blend") and have(B, "worst_pitch_xslg"):
            f = _lm & (_lr("mix_iso_blend") >= 0.85) & (_lr("worst_pitch_xslg") >= 0.70)
            for i in B.index[f.fillna(False)]:
                add(i, 0.13, "LONG-MIXWPX")
        if have(B, "mz_fit", 0.15) and have(B, "zone_overlap"):
            f = _lm & (_lr("mz_fit") >= 0.80) & (_lr("zone_overlap") >= 0.80)
            for i in B.index[f.fillna(False)]:
                add(i, 0.13, "LONG-MZZONE")
        if have(B, "zone_overlap"):
            f = _lm & (_lr("zone_overlap") >= 0.90)
            for i in B.index[f.fillna(False)]:
                add(i, 0.12, "LONG-ZONE")
    # SWING -- Savant bat-tracking: fast, squared-up swings whose results have
    # not caught up. Selects on swing MECHANICS, not outcomes -- a different
    # axis from every xiso/barrel read. Dormant until the Savant CSV is merged.
    sv_spd = next((c for c in ("sv_bat_speed", "sv_avg_bat_speed") if have(B, c)), None)
    sv_sq = next((c for c in ("sv_blast_per_swing", "sv_blasts_per_swing", "sv_blasts",
                              "sv_squared_up_per_swing", "sv_squared_up_rate")
                  if have(B, c)), None)
    if sv_spd and sv_sq:
        f = (pct(B, sv_spd, 1) >= 0.85) & (pct(B, sv_sq, 1) >= 0.85)
        for i in B.index[f.fillna(False)]:
            add(i, P_HR["SWING"], "SWING")
    # MODEL-X -- the 14-feature logistic (hr_model_v1.json) fit on the 49-night
    # graded record, judged out-of-fold only: top-5 22.4% HR, a top-5 homer on
    # 71% of nights, and 73% of its picks are bats NO other caller names (those
    # hit 21.3%). Callers alone put a homer in their top-5 on 67% of nights;
    # the UNION of the two top-5s did it on 88%. It reads iso_hand_mult,
    # iso_fit (bat xISO vs tonight's arm mix -- arsenal_merge), the mix_iso
    # pair, ground-ball suppression, zone_overlap, arm HR/9 and form. Top FIVE
    # a night, exactly as measured -- priced at the model-only rate.
    # PEN-DOOR -- the second HR window. On 2026-08-16, 44% of the slate's homers
    # came in innings 6+ off relievers -- the window every read above ignores
    # (mz/arsenal/p_* are starter-only). Measured on the 49 nights: power bat
    # (xiso p75+) walking into an HR-prone pen (pen_hr_per_pa top tertile of
    # the night) homers at 15.9% (1.50x base), split-half 16.0/15.9, ~12 bats a
    # night -- and 75% are bats NO other caller names (13.8% on that new-bat
    # subset). Priced at the measured rate; rides the DEPTH tier of the book.
    if have(B, "xiso") and have(B, "pen_hr_per_pa"):
        f = (pct(B, "xiso", 1) >= 0.75) & (pct(B, "pen_hr_per_pa", 1) >= 2.0 / 3.0)
        for i in B.index[f.fillna(False)]:
            add(i, P_HR["PENDOOR"], "PEN-DOOR")
    ms = model_scores(B)
    if ms is not None:
        for i in ms.nlargest(5).index:
            add(i, P_HR["MODELX"], "MODEL-X")
    # WEATHER VETO -- ballpark_weather.py (Open-Meteo: temp vs 70F baseline,
    # wind against each park's CF bearing, domes neutral). Measured on the 49
    # nights: the module is LIVE (168 distinct mults, park-independent) and its
    # SUPPRESSION tail is real -- mult<0.97 bats homer at 0.68x base, and
    # caller-named bats under it hit 6.8% vs 14.6% for the rest (4/59). The
    # boost side saturates in summer (40% of bats >1.06, no lift) so ONLY the
    # tail is wired -- a reprice, never a removal: the bat stays visible with
    # the tag, the assembly just stops paying caller rates for cold air.
    if have(B, "weather_hr_mult"):
        wv = num(B, "weather_hr_mult")
        for i in list(calls.keys()):
            v = wv.get(i, np.nan)
            if not pd.isna(v) and v < 0.97:
                p0, ws = calls[i]
                calls[i] = (min(p0, 0.10), ws + ["WX-SUPPRESSED"])
    # ENV-TOUGH VETO -- Nikko's 2026-08-16 thesis, measured before wiring: an HR
    # call into a TOUGH starter (p_hr_per_9 bottom 40% of the night) AND a TOUGH
    # pen (pen_hr_per_pa bottom 40%) hits 8.0% on 87 called legs -- HALF the
    # caller average -- and 13.8% vs 19.1% inside the 21-slip book. Repriced to
    # the measured rate, never removed. Anchor replay with this veto: IDENTICAL
    # slips won (19/144 both arms) -- it costs nothing and cleans the deep book
    # and every hand-pick. The BOOST side (both-vulnerable +bonus) tested WORSE
    # (reshuffled anchors) and is NOT wired. TB is untouched on purpose: contact
    # bats vs tough arms measured 43.8% -- ABOVE the TB caller average.
    if have(B, "p_hr_per_9") and have(B, "pen_hr_per_pa"):
        _sp = num(B, "p_hr_per_9").rank(pct=True)
        _pn = num(B, "pen_hr_per_pa").rank(pct=True)
        for i in list(calls.keys()):
            s, q = _sp.get(i, np.nan), _pn.get(i, np.nan)
            if not (pd.isna(s) or pd.isna(q)) and s < 0.40 and q < 0.40:
                p0, ws = calls[i]
                calls[i] = (min(p0, 0.08), ws + ["ENV-TOUGH"])
    # HR-FOUND -- 2026-08-17: "those same 10 nights of homers... test how to
    # actually find every single one of those bats. Maybe we don't have
    # something we should have." We DID have it and never read it: the board's
    # own hr_value column. The 10-night missed-homer autopsy (251 homers, 167
    # missed by every caller): missed homers sat at hr_value pct .58 vs .27
    # for uncalled non-homers (+31, the widest gap of any column on the
    # board), with chal_brl and ld_rate +20 behind it. The rule, validated on
    # the FULL 50-night ledger, UNCALLED bats only: hr_value p75 AND
    # iso_hand_mult p60 -> 13.6% homered (Aug 13.7%, A/B stable), ~26 bats a
    # night. POOL RECALL of the night's homers: 6.8 -> 10.4 per night (+52%),
    # the largest recall gain in the project. Priced at the measured 0.14 --
    # long-book territory -- so it feeds the LONG-ONLY depth tier, the DEPTH
    # CALLS print, the bench, and the app's book. Assembled slip count
    # measured unchanged today; the recall is the raw material pairing needs.
    try:
        if have(B, "hr_value") and have(B, "iso_hand_mult"):
            _fv = num(B, "hr_value").rank(pct=True)
            _fi = num(B, "iso_hand_mult").rank(pct=True)
            for i in B.index[((_fv >= 0.75) & (_fi >= 0.60)).fillna(False)]:
                if i not in calls:
                    add(i, P_HR["FOUND"], "HR-FOUND")
    except Exception:
        pass
    calls = _apply_living(calls, P_CAP_HR)
    return calls


def call_tb(B, lanes):
    """TB callers. Contact, zone, bat-to-ball. No power column anywhere.
    PA-VOLUME GUARD: a 1.5TB leg lives on plate appearances. If the board knows
    the lineup slot, bats hitting 8th-9th are excluded from TB calls (3-4 PAs
    against 4-5 for the top six). HR calls are untouched -- one swing is enough."""
    calls = {}
    slot_col = next((c for c in ("lineup_slot", "batting_order", "proj_slot", "slot",
                                 "lineup_spot") if c in B.columns
                     and num(B, c).notna().mean() >= 0.5), None)
    deep_slot = (num(B, slot_col) >= 8) if slot_col else pd.Series(False, index=B.index)

    def add(idx, p, why):
        if bool(deep_slot.get(idx, False)):
            return                          # 8th-9th hitters: not enough PAs for 1.5TB
        if idx in calls:
            p0, w = calls[idx]
            calls[idx] = (min(max(p0, p) + MULTI_BONUS, P_CAP_TB), w + [why])
        else:
            calls[idx] = (p, [why])

    if have(B, "zone_overlap"):
        # AS MEASURED: zone_overlap's top TEN BATS hit 70.0% on 535 graded legs.
        # A decile of a 300-bat board is 30 bats -- three times looser than the
        # read that was actually measured. Top ten, exactly.
        _zt = num(B, "zone_overlap").nlargest(10).index
        for i in _zt:
            add(i, P_TB["ZONETOP"], "ZONE-TOP10")
    # XWOBA-VULN TIGHT -- the reconstruction of the dead 77% flag: elite bat
    # (xwoba p93+) meeting an arsenal it eats (pitch_vuln p93+). Board-wide truth
    # on 35 graded nights: 43.8%, floor 40.1%, ~9 bats a night. The 77% on his
    # bets was this condition passing through the app's full stack on 53 legs --
    # priced here at what the CONDITION does, not the legend.
    if have(B, "xwoba") and have(B, "pitch_vuln_score"):
        f = (pct(B, "xwoba", 1) >= 0.93) & (pct(B, "pitch_vuln_score", 1) >= 0.93)
        for i in B.index[f.fillna(False)]:
            add(i, 0.44, "XW-VULN")
    if have(B, "contact_score") and have(B, "p_k_per_9"):
        f = (pct(B, "contact_score", 1) >= 0.80) & (pct(B, "p_k_per_9", -1) >= 0.70)
        for i in B.index[f.fillna(False)]:
            add(i, P_TB["LOWK"], "LOWK-ARM")
    # STRIPPED-TB -- the no-homer lane, per spec: "contact bats that clear 1.5tb
    # with homeruns stripped." Selected on A-nights, CONFIRMED on B-nights
    # (stripped 35.3% / 33.7%), then read on all 28 stripped-graded nights:
    # 45.9% tb15, 34.6% still clears with the HR bases DELETED from the box
    # score, only ~25% of its clears need the homer (ZONE-TOP10: 38%). 61% of
    # its bats are new vs the other TB callers and it holds 43.3% on the quiet
    # half of nights. Archetype it actually picks: Jung Hoo Lee, Arraez,
    # Burleson, Schanuel, Freeman. Priced at the measured tb15, not the stripped
    # floor -- a homer still cashes the leg; stripping is how the bat is CHOSEN.
    if have(B, "xba") and have(B, "platoon_mult") and have(B, "k_percent"):
        f = ((pct(B, "xba", 1) >= 0.80) & (pct(B, "platoon_mult", 1) >= 0.70)
             & (pct(B, "k_percent", -1) >= 0.60))
        # STRIP-ARM -- the same contact bat when tonight's ARM also allows
        # contact (ars_xba_v2, arsenal v2, top-40% of the night's arms). On the
        # 42 stripped-graded nights: 50.5% tb15, 40.5% with the homer deleted --
        # and 53.5% in August, when everything else on the board went quiet.
        # ~2.6 bats a night. Plain STRIP stays 0.46 for the rest.
        arm = (pct(B, "ars_xba_v2", 1) >= 0.60) if have(B, "ars_xba_v2") else None
        for i in B.index[f.fillna(False)]:
            if arm is not None and bool(arm.get(i, False)):
                add(i, P_TB["STRIPARM"], "STRIP-ARM")
            else:
                add(i, P_TB["STRIP"], "STRIP-CONTACT")
    for L in lanes:
        a, b = L.get("a"), L.get("b")
        if not (have(B, a) and have(B, b)):
            continue
        cut = float(L.get("cut", 0.10))
        f = (pct(B, a, L.get("sa", 1)) >= 1 - cut) & (pct(B, b, L.get("sb", 1)) >= 1 - cut)
        for i in B.index[f.fillna(False)]:
            add(i, P_TB["LANE"], "LANE:" + str(L.get("name", "?"))[:12])
    # TB-MODEL -- the full-slate machine (tb_model_v1.json), per 2026-08-17:
    # "you're not seeing the entire slate properly." Trained on every graded TB
    # bat-game; out-of-fold its shelf is FLAT: 44.5% at 10-deep, 44.6% at 15,
    # 44.0% at 20 -- there really are 20+ callable TB bats a night, and this
    # finds them (the app's tb_prob at the same depth: 39.7%). Top FIFTEEN a
    # night at the measured rate.
    try:
        _tms = tb_model_scores(B)
        if _tms is not None:
            _tms = _tms.where(~deep_slot, other=np.nan)
            # AVG-FLOOR per 2026-08-17: "average AND power, NOT JUST POWER."
            # Bottom-third contact bats (xba pct < .33) leave the model's picks;
            # next model ranks back-fill. Measured: cash flat (+0.4 Aug, inside
            # noise), HR-dependence of landers 39% -> 37%. Composition wire --
            # never costs a measured point; kill on a word.
            if have(B, "xba"):
                _tms = _tms.where(num(B, "xba").rank(pct=True) >= 0.33,
                                  other=np.nan)
            globals()["_LAST_TBMODEL"] = _tms
            for i in _tms.nlargest(15).index:
                add(i, P_TB["TBMODEL"], "TB-MODEL")
    except Exception:
        pass
    # BLOWUP -- the Cabrera-game mechanism, per 2026-08-17: "Cardinals-Cubs
    # ALONE had 8 hitters land 1.5TB." Lineup slots 1-6 against the night's
    # WORST arm (armv = mean pct of xSLG-allowed, low-K, HR-prone). Replayed on
    # 48 graded nights: 46.4% tb15 on 179 legs (Aug 44.2%), ~4 legs a night.
    # Worst arm ONLY -- the 2nd and 3rd worst measured 40.8/40.9 and stay out.
    try:
        _bp = next((c for c in ("opp_pitcher", "opp_sp", "opposing_pitcher",
                                "pitcher") if c in B.columns), None)
        if _bp and slot_col and have(B, "p_xslg_allowed"):
            _armv = (num(B, "p_xslg_allowed").rank(pct=True)
                     + (1 - num(B, "p_k_per_9").rank(pct=True))
                     + num(B, "p_hr_per_9").rank(pct=True)) / 3.0
            _worst = _armv.groupby(B[_bp]).mean().idxmax()
            _sl = num(B, slot_col)
            for i in B.index[(B[_bp] == _worst) & _sl.between(1, 6)]:
                add(i, P_TB["BLOWUP"], "BLOWUP")
    except Exception:
        pass
    # SLG-FIT -- HIS PER-PITCH IDEA, 2026-08-18, and the best TB read in the
    # project outside the two 50% micro-lanes. slgfit_arm = mean pct of the bat's
    # est_SLG vs this arm's ACTUAL mix and the arm's own mix-weighted SLG allowed.
    # MEASURED, 50 nights, 1.5TB: top-10/nt 48.4% (Aug 45.3, halves 50.8/46.0);
    # top-20/nt 44.2% (Aug 43.2, halves 45.2/43.2). The board's single-worst-pitch
    # read grades 34.1% -- fourteen points behind.
    try:
        if have(B, "slgfit_arm"):
            _sfa = num(B, "slgfit_arm").where(~deep_slot, other=np.nan)
            globals()["_LAST_SLGFIT"] = _sfa
            for i in _sfa.nlargest(10).index:
                add(i, P_TB["SLGFIT"], "SLG-FIT")
    except Exception:
        pass
    # NK-FIVE -- HIS EYEBALL RULE, 2026-08-18: "iso vs hand 80+, pitch vuln 80+,
    # loc fit 80+, arsenal match 80+, zone overlap 70+." Measured on 38 replayed
    # nights, and it is the FIRST read that beats the caller stack on its own
    # terms: bats the callers ALREADY name that clear 4 of his 5 gates land
    # 43.7% (Aug 41.1, halves 42.2 / 45.2 -- both above the 41.3% caller
    # average) on 15.4 legs a night. The same gate on bats NOBODY called lands
    # 37.7% -- so this is a PRIORITY INSIDE the pool, not an admission rule, and
    # it is wired that way: it only lifts bats a caller already named.
    # All five 5-of-5: 42.5%. Four-of-five is the better cut and the deeper one.
    try:
        _nf = None
        for _c, _cut in (("iso_hand_mult", .80), ("pitch_vuln_score", .80),
                         ("loc_fit", .80), ("hr_arsenal_match", .80),
                         ("zone_overlap", .70)):
            if have(B, _c):
                _s = (num(B, _c).rank(pct=True) >= _cut).fillna(False).astype(int)
                _nf = _s if _nf is None else (_nf + _s)
        if _nf is not None:
            for i in B.index[(_nf >= 4) & ~deep_slot]:
                if i in calls:                      # priority, not admission
                    add(i, P_TB["NKFIVE"], "NK-FIVE")
    except Exception:
        pass
    # MATCH-5 -- NIKKO'S SPEC, 2026-08-17: "bats in great matchups, with great
    # zones, against vulnerable pitching, where hitters have experience hitting
    # those pitches." Composite of night-pct: zone_overlap + pitch_vuln +
    # p_xslg_allowed + low p_k_per_9 + ars_xba_v2, top FIVE a night. Measured on
    # the 49-night record: 47.9% tb15 (A/B 50.0/45.8) and 49.3% in AUGUST --
    # where ZONE-TOP10 fell to 39.5%. The most regime-proof TB read on the
    # board, and it is HIS. (The same composite at 20-deep measures 41.2% --
    # the honest frontier; the TWENTY prints nightly with tiers marked.)
    try:
        _m5 = (pct(B, "zone_overlap", 1).fillna(0.5) + pct(B, "pitch_vuln_score", 1).fillna(0.5)
               + pct(B, "p_xslg_allowed", 1).fillna(0.5) + pct(B, "p_k_per_9", -1).fillna(0.5)
               + pct(B, "ars_xba_v2", 1).fillna(0.5)) / 5.0
        _m5 = _m5.where(~deep_slot, other=np.nan)
        globals()["_LAST_SPEC"] = _m5
        for i in _m5.nlargest(5).index:
            add(i, P_TB["MATCH5"], "MATCH-5")
    except Exception:
        pass
    calls = _apply_living(calls, P_CAP_TB)
    return calls


# ============================== THE ASSEMBLY =================================

def game_key(B):
    if "team_abbrev" in B.columns and "opponent" in B.columns:
        return (B["team_abbrev"].astype(str) + "|" + B["opponent"].astype(str)).map(
            lambda s: "|".join(sorted(s.split("|"))))
    return pd.Series([str(i) for i in B.index], index=B.index)


def assemble(B, hr_calls, tb_calls, shape, nslips, hr_cap=2, tb_cap=1, topk=14):
    """EXACT greedy on P(slip wins) = product of measured leg rates, then a swap
    pass on P(>=1) + 0.5*P(>=2). Strongest with strongest FIRST -- the policy
    that doubled slips won when replayed on the ledger. Caps: an HR bat on at
    most hr_cap slips, a TB bat on tb_cap, one leg per game per slip."""
    nhr, ntb = SHAPES[shape]
    gm = game_key(B)
    _fm = _trail_form(B)
    H = sorted(hr_calls.items(),
               key=lambda kv: -(kv[1][0] * _form_key(_fm.get(kv[0], 0))))[:topk]
    T = sorted(tb_calls.items(), key=lambda kv: -kv[1][0])[:topk]
    use_h, use_t = {}, {}
    slips = []

    def ok(legs):
        gs = [gm.loc[i] for i, _p, _w in legs]
        return len(set(gs)) == len(gs)

    def cands():
        hh = [(i, p, w) for i, (p, w) in H if use_h.get(i, 0) < hr_cap]
        tt = [(i, p, w) for i, (p, w) in T if use_t.get(i, 0) < tb_cap]
        for hc in combinations(hh, nhr):
            for tc in combinations(tt, ntb):
                legs = list(hc) + list(tc)
                ids = [i for i, _p, _w in legs]
                if len(set(ids)) < len(ids) or not ok(legs):
                    continue
                yield legs, float(np.prod([p for _i, p, _w in legs]))

    for _s in range(nslips):
        best, bp = None, -1.0
        for legs, p in cands():
            if p > bp:
                best, bp = legs, p
        if best is None:
            break
        for i, _p, _w in best[:nhr]:
            use_h[i] = use_h.get(i, 0) + 1
        for i, _p, _w in best[nhr:]:
            use_t[i] = use_t.get(i, 0) + 1
        slips.append((best, bp))

    # swap pass: try replacing any single leg to raise P(>=1) + 0.5*P(>=2)
    def night_score(sl):
        ps = [p for _l, p in sl]
        p1 = 1.0 - float(np.prod([1 - p for p in ps]))
        p2 = p1 - sum(p * float(np.prod([1 - q for j, q in enumerate(ps) if j != k]))
                      for k, p in enumerate(ps))
        return p1 + 0.5 * max(p2, 0.0)

    improved = True
    guard = 0
    while improved and guard < 20:
        improved = False
        guard += 1
        for si, (legs, _p) in enumerate(list(slips)):
            for li in range(len(legs)):
                pool = H if li < nhr else T
                capd, cap = (use_h, hr_cap) if li < nhr else (use_t, tb_cap)
                cur = legs[li]
                for j, (jp, jw) in pool:
                    if j == cur[0] or capd.get(j, 0) >= cap:
                        continue
                    trial = legs[:li] + [(j, jp, jw)] + legs[li + 1:]
                    ids = [i for i, _q, _w in trial]
                    if len(set(ids)) < len(ids) or not ok(trial):
                        continue
                    new = list(slips)
                    new[si] = (trial, float(np.prod([q for _i, q, _w in trial])))
                    if night_score(new) > night_score(slips) + 1e-9:
                        capd[cur[0]] -= 1
                        capd[j] = capd.get(j, 0) + 1
                        slips = new
                        improved = True
                        break
                if improved:
                    break
            if improved:
                break
    return slips


def night_probs(slips):
    ps = [p for _l, p in slips]
    p1 = 1.0 - float(np.prod([1 - p for p in ps])) if ps else 0.0
    p2 = 0.0
    if len(ps) >= 2:
        p2 = p1 - sum(p * float(np.prod([1 - q for j, q in enumerate(ps) if j != k]))
                      for k, p in enumerate(ps))
    return p1, max(p2, 0.0)


# ============================== SLATE MODE ===================================
# For 12-20 slips a night the anchor greedy is the wrong shape -- it would
# re-bet the same five bats. A slate is TIERED so it bets the whole board:
#   ANCHOR  (~30%)  exact greedy, strongest-with-strongest -- the measured-best
#                   shots, same policy that doubled slips won on the ledger.
#   MID     (~35%)  greedy again but bats already used twice (HR) / once (TB)
#                   are EXCLUDED from entry -- fresh names, still caller-priced.
#   DEPTH   (rest)  HR legs drawn from the sub-chalk callers (LONG-*, SUBZONE,
#                   DEEP-CARRY, and unused MODEL-X) paired with solid TB legs --
#                   the barbell that puts 12-15% longshots ON slips instead of
#                   leaving them in a caption. Most homers are not chalk.
# Slate caps: an HR bat on at most 3 slips, a TB bat on 2. Every leg keeps its
# MEASURED price; a DEPTH slip prints 5-8% because that is what it is.

def assemble_slate(B, hr_calls, tb_calls, nhr, ntb, nslips):
    gm = game_key(B)
    hr_cap = 3 if nslips > 6 else 2
    tb_cap = 2 if nslips > 6 else 1
    use_h, use_t = {}, {}
    seen = set()
    DEPTH_TAGS = ("LONG-", "SUBZONE", "DEEP-CARRY", "PEN-DOOR", "HR-FOUND")

    def greedy(H, T, n, tier, entry_h=None, entry_t=None):
        """entry_h/entry_t: a bat may START another slip in this tier only while
        its total slate use is under this -- checked PER SLIP, which is what
        actually forces fresh names as the tier fills."""
        got = []
        eh = entry_h if entry_h is not None else hr_cap
        et = entry_t if entry_t is not None else tb_cap
        for _s in range(n):
            best, bp = None, -1.0
            hh = [(i, p, w) for i, (p, w) in H if use_h.get(i, 0) < min(eh, hr_cap)]
            tt = [(i, p, w) for i, (p, w) in T if use_t.get(i, 0) < min(et, tb_cap)]
            for hc in combinations(hh, nhr):
                for tc in combinations(tt, ntb):
                    legs = list(hc) + list(tc)
                    ids = [i for i, _p, _w in legs]
                    if len(set(ids)) < len(ids) or frozenset(ids) in seen:
                        continue
                    gs = [gm.loc[i] for i in ids]
                    if len(set(gs)) < len(gs):
                        continue
                    p = float(np.prod([q for _i, q, _w in legs]))
                    if p > bp:
                        best, bp = legs, p
            if best is None:
                break
            ids = [i for i, _p, _w in best]
            seen.add(frozenset(ids))
            for i, _p, _w in best[:nhr]:
                use_h[i] = use_h.get(i, 0) + 1
            for i, _p, _w in best[nhr:]:
                use_t[i] = use_t.get(i, 0) + 1
            got.append((best, bp, tier))
        return got

    _fm = _trail_form(B)
    Hall = sorted(hr_calls.items(),
                  key=lambda kv: -(kv[1][0] * _form_key(_fm.get(kv[0], 0))))
    Tall = sorted(tb_calls.items(), key=lambda kv: -kv[1][0])
    # THE SIXTEEN constraint: ANCHOR and MID HR legs shuffle through at most the
    # top 16 caller-named bats (alignments-first by price). DEPTH keeps the full
    # sub-chalk book (LONG/SUBZONE/DEEP/PEN-DOOR) below them. Computed here so
    # the app's book (forgewire) inherits it with no signature change.
    _sixteen_idx = set(i for i, _pw in Hall[:16])
    H16 = [(i, pw) for i, pw in Hall if i in _sixteen_idx]
    nA = max(1, int(round(nslips * 0.30)))
    nB = max(0, int(round(nslips * 0.35)))
    nC = max(0, nslips - nA - nB)
    if nslips <= 3:
        nA, nB, nC = nslips, 0, 0

    out = []
    # ANCHOR: the measured-best shots, exactly as the 3-slip mode builds them.
    out += greedy(H16[:14], Tall[:14], nA, "ANCHOR", entry_h=2, entry_t=1)

    # MID: same pricing, but a bat can only START a mid slip while its total
    # use is under 2 (HR) / 1 (TB) -- fresh names, checked per slip.
    if nB:
        got = greedy(H16, Tall[:40], nB, "MID", entry_h=2, entry_t=1)
        out += got
        short = nB - len(got)
        if short > 0:
            out += greedy(H16, Tall[:40], short, "MID")
    # DEPTH: the HR leg comes from the sub-chalk callers ONLY (LONG-*, SUBZONE,
    # DEEP-CARRY) -- the 12-19% book where most homers actually live. TB legs
    # may reuse one strong bat (barbell: longshot HR + solid TB).
    if nC:
        # LONG-ONLY DEPTH, per 2026-08-17 "there still is NO value or long":
        # the DEPTH HR leg now comes from the TRUE longshot book (price <=
        # 0.165: LONG-*, SUBZONE, PEN-DOOR) -- DEEP-CARRY at 0.19 was eating
        # every depth slot. SLIP-LEVEL replay, 48 nights x 14 slips: 0.81 slips
        # won/night vs 0.75 (Aug 0.60 vs 0.53), Aug nights cashed 60% vs 53%.
        # The one spread change that won SLIPS, not just pool counts.
        Hd = [(i, (p, w)) for i, (p, w) in Hall
              if any(str(x).startswith(DEPTH_TAGS) for x in w) and p <= 0.165]
        got = greedy(Hd if nhr else Hall[:40], Tall[:40], nC, "DEPTH",
                     entry_h=1, entry_t=2)
        out += got
        short = nC - len(got)
        if short > 0:                      # depth book ran dry -- fill from MID rules
            out += greedy(Hall[:40], Tall[:40], short, "MID")
    return [(l, p) for l, p, _t in out], [t for _l, _p, t in out]


# ============================== NIGHT CARD ===================================
# Regime instrument, 2026-08-16. Measured on 48 nights: the ORACLE of picking
# the right shape nightly wins 27 slips vs 19 for always-1HR+1TB -- real
# headroom -- but the pre-game reads below captured only +1 slip / +1 night
# out-of-sample (three independent reads, all pointing the same way). That is
# DIRECTION, not certification, so this prints and LOGS its lean every night
# and steers NOTHING. When ~100 live nights exist, the log certifies it into
# an autopilot or kills it. Instrument first, automate on evidence.
NC_TRAIL_MED = 0.1061   # 48-night median of trailing-7 league HR
NC_IMP_MED = 4.314      # 48-night median slate implied total
NC_WX_MED = 0.032       # 48-night median suppressed-air share
NC_THIN_CALLS = 28      # bottom-quartile HR-caller supply


def night_card(B, boards_dir="boards"):
    reads = {}
    try:
        gf = sorted(glob.glob(os.path.join(boards_dir, "graded_full_*.csv")))[-7:]
        rs = []
        for f in gf:
            g = pd.read_csv(f, low_memory=False)
            v = num(g, "hr_hit")
            if v.notna().sum() > 40:
                rs.append(float(v.mean()))
        reads["trail7_hr"] = float(np.mean(rs)) if len(rs) >= 3 else np.nan
    except Exception:
        reads["trail7_hr"] = np.nan
    wx = num(B, "weather_hr_mult")
    reads["wx_suppressed_share"] = float((wx < 0.97).mean()) if wx.notna().mean() > .3 else np.nan
    spv = num(B, "p_hr_per_9")
    reads["vuln_sp_share"] = float((spv.rank(pct=True) >= 2 / 3).mean()) if spv.notna().mean() > .3 else np.nan
    imp = num(B, "implied_runs")
    reads["implied_mean"] = float(imp.mean()) if imp.notna().mean() > .3 else np.nan
    hc = call_hr(B, load_lanes("hr_lanes.json", DEF_HR_LANES))
    tc = call_tb(B, load_lanes("tb_lanes.json", DEF_TB_LANES))
    reads["hr_calls"] = len(hc)
    reads["stack9"] = sum(1 for _i, (_p, w) in hc.items() if "STACK9" in w)
    reads["tb_calls"] = len(tc)
    reads["striparm"] = sum(1 for _i, (_p, w) in tc.items() if "STRIP-ARM" in w)
    votes = 0
    votes += 1 if (not np.isnan(reads["trail7_hr"]) and reads["trail7_hr"] >= NC_TRAIL_MED) else 0
    votes += 1 if (not np.isnan(reads["implied_mean"]) and reads["implied_mean"] >= NC_IMP_MED) else 0
    votes += 1 if (not np.isnan(reads["wx_suppressed_share"]) and reads["wx_suppressed_share"] <= NC_WX_MED) else 0
    lean = "HR shapes (1hr1tb / 2hr)" if votes >= 2 else "TB shapes (3tb / STRIP-led)"
    thin = reads["hr_calls"] <= NC_THIN_CALLS
    rule_("-")
    print("  NIGHT CARD (advisory -- logs itself, steers nothing yet)")
    t7 = reads["trail7_hr"]
    print("    league HR last 7 graded nights: %s   slate wx suppressed: %s   vuln-SP share: %s"
          % ("%.1f%%" % (100 * t7) if not np.isnan(t7) else "n/a",
             "%.0f%%" % (100 * reads["wx_suppressed_share"]) if not np.isnan(reads["wx_suppressed_share"]) else "n/a",
             "%.0f%%" % (100 * reads["vuln_sp_share"]) if not np.isnan(reads["vuln_sp_share"]) else "n/a"))
    print("    caller supply: %d HR (%d STACK9) / %d TB (%d STRIP-ARM)   slate implied: %s"
          % (reads["hr_calls"], reads["stack9"], reads["tb_calls"], reads["striparm"],
             "%.1f" % reads["implied_mean"] if not np.isnan(reads["implied_mean"]) else "n/a"))
    print("    LEAN: %s  (%d of 3 regime votes)%s"
          % (lean, votes, "   *THIN BOARD -- consider fewer/TB-only slips*" if thin else ""))
    print("    track record so far: +1 slip / +1 night per 24 nights out-of-sample -- watch it, don't worship it")
    try:
        row = dict(date=datetime_date_str(), lean=("HR" if votes >= 2 else "TB"), votes=votes, thin=int(thin), **{k: round(v, 4) if isinstance(v, float) and not np.isnan(v) else v for k, v in reads.items()})
        lg = "nightcard_log.csv"
        old = pd.read_csv(lg) if os.path.exists(lg) else None
        if old is not None:
            old = old[old["date"] != row["date"]]
        pd.concat([old, pd.DataFrame([row])], ignore_index=True).to_csv(lg, index=False)
    except Exception:
        pass
    return lean


def datetime_date_str():
    import datetime as _dt
    return _dt.date.today().isoformat()


# ================================ MODES ======================================

def shape_legs(args):
    """(nhr, ntb) from --shape, or a CUSTOM pair from --hr-legs/--tb-legs.
    Custom is validated: 2-3 legs total, and never 2xTB-only (does not pay)."""
    if getattr(args, "hr_legs", None) is None and getattr(args, "tb_legs", None) is None:
        return SHAPES[args.shape]
    nh = int(getattr(args, "hr_legs", 0) or 0)
    nt = int(getattr(args, "tb_legs", 0) or 0)
    if not (2 <= nh + nt <= 3) or (nh, nt) == (0, 2):
        print("  [custom] %dHR+%dTB is not a playable shape (2-3 legs, no 2xTB-only)"
              " -- using --shape %s instead." % (nh, nt, args.shape))
        return SHAPES[args.shape]
    return nh, nt


LOG = "slipforge_log.csv"


def log_slips(board_path, B, slips, shape, nhr):
    """Append tonight's slate to slipforge_log.csv -- the live week is only a
    test if it is graded. One row per leg; --grade reads this back."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(board_path))
    d = m.group(1) if m else "unknown"
    nc = name_col(B)
    rows = []
    for si, (legs, p) in enumerate(slips):
        for li, (i, lp, why) in enumerate(legs):
            rows.append(dict(date=d, slip="S%d" % (si + 1), shape=shape,
                             prop=("HR" if li < nhr else "TB"),
                             player=(str(B.loc[i, nc]) if nc else str(i)),
                             p=round(float(lp), 3), callers="+".join(why[:3]),
                             slip_p=round(float(p), 4)))
    if not rows:
        return
    df = pd.DataFrame(rows)
    old = None
    if os.path.exists(LOG):
        try:
            old = pd.read_csv(LOG)
            old = old[~((old["date"] == d) & (old["shape"] == shape))]  # regenerate = replace
        except Exception:
            old = None
    out = pd.concat([old, df], ignore_index=True) if old is not None else df
    out.to_csv(LOG, index=False)
    print("  [log] %s -- %d legs for %s (%s). Regenerating tonight replaces tonight."
          % (LOG, len(df), d, shape))


def run_grade(args):
    head("SLIPFORGE LIVE-WEEK GRADE -- %s vs the graded boards" % LOG)
    if not os.path.exists(LOG):
        print("  no %s yet. Generate some nights first." % LOG)
        return 2
    Lg = pd.read_csv(LOG)
    tot = wins = 0
    nights = nwin = 0
    legs_n = {"HR": [0, 0], "TB": [0, 0]}
    for d, g in Lg.groupby("date"):
        gb = glob.glob("boards/graded_full_%s.csv" % d)
        if not gb:
            continue
        G = pd.read_csv(gb[0], low_memory=False)
        nc = name_col(G)
        if nc is None:
            continue
        key = G[nc].astype(str).str.strip().str.lower()
        hr = dict(zip(key, num(G, "hr_hit")))
        tb = dict(zip(key, num(G, "tb15_hit")))
        night_w = 0
        for _key, sl in g.groupby(["shape", "slip"]):
            ok, graded = True, True
            for _, r in sl.iterrows():
                v = (hr if r["prop"] == "HR" else tb).get(str(r["player"]).strip().lower())
                if v is None or pd.isna(v):
                    graded = False
                    break
                legs_n[r["prop"]][0] += 1
                legs_n[r["prop"]][1] += int(v > 0)
                if not v > 0:
                    ok = False
            if not graded:
                continue
            tot += 1
            wins += 1 if ok else 0
            night_w += 1 if ok else 0
        nights += 1
        nwin += 1 if night_w else 0
    rule_()
    print("  %-30s %8d" % ("nights graded", nights))
    print("  %-30s %8d" % ("slips graded", tot))
    print("  %-30s %8d   (%.2f%%)" % ("slips WON", wins, 100.0 * wins / max(tot, 1)))
    print("  %-30s %5d/%d" % ("nights with a winner", nwin, max(nights, 1)))
    for pr, (n, k) in legs_n.items():
        if n:
            print("  %-30s %7.1f%%   (%d legs)" % ("%s legs hit" % pr, 100.0 * k / n, n))
    print("")
    print("  Head-to-head: your app slips for the same nights are in your own ledger --")
    print("  same nights, same score, one table each. The week decides it.")
    return 0


def run_board(path, args):
    B = pd.read_csv(path, low_memory=False)
    B, _sv = savant_merge(B)
    B = matchup_merge(B)
    B = arsenal_merge(B)
    nc = name_col(B)
    hr_l = load_lanes("hr_lanes.json", DEF_HR_LANES)
    tb_l = load_lanes("tb_lanes.json", DEF_TB_LANES)
    hc = call_hr(B, hr_l)
    tc = call_tb(B, tb_l)
    head("SLIPFORGE -- %s  (%d bats on the board)" % (os.path.basename(path), len(B)))
    print("  HR callers named %d bats; TB callers named %d. Whole board read; no rank list."
          % (len(hc), len(tc)))
    try:
        night_card(B)
    except Exception as _nce:
        print("  [nightcard] skipped: %s" % _nce)
    # THE SIXTEEN -- per 2026-08-17: "give me 16 Homer bats a night for the
    # generator to shuffle through... alignments stay the main engine, the blend
    # is the tiebreaker." Construction: every CALLER-named bat first (the
    # alignments/lanes/stacks/PEN-DOOR engine), ordered by living price with the
    # MODEL-X blend breaking ties; if callers name fewer than 16, the blend
    # fills the rest. The book's ANCHOR and MID HR legs draw ONLY from these 16
    # (see assemble_slate); DEPTH keeps the sub-chalk book. Band mix printed so
    # chalk-heaviness is visible every night.
    try:
        _s_ms = model_scores(B)
        if _s_ms is None:
            _s_ms = pd.Series(0.0, index=B.index)
        _s_bl = _s_ms.rank(pct=True)
        _s_fm = _trail_form(B)
        _s_called = sorted(hc.items(),
                           key=lambda kv: (-(kv[1][0] * _form_key(_s_fm.get(kv[0], 0))),
                                           -float(_s_bl.get(kv[0], 0))))
        _sixteen = [i for i, _pw in _s_called[:16]]
        if len(_sixteen) < 16:
            for i in _s_bl.nlargest(60).index:
                if i not in _sixteen:
                    _sixteen.append(i)
                if len(_sixteen) >= 16:
                    break
        _s_hp = num(B, "hr_prob").rank(pct=True)
        _bands = {"chalk": 0, "mid": 0, "deep": 0}
        rule_("-")
        print("  THE SIXTEEN (the generator's HR pool tonight; alignments first, "
              "hot form moves up, model breaks ties):")
        for i in _sixteen:
            _nm = str(B.loc[i, nc])[:20] if nc else str(i)
            _hpv = float(_s_hp.get(i, 0.5))
            _bd = "chalk" if _hpv >= 0.8 else ("mid" if _hpv >= 0.5 else "deep")
            _bands[_bd] += 1
            _tag = "+".join(hc[i][1][:2])[:34] if i in hc else "model-fill"
            _fv = min(int(_s_fm.get(i, 0)), 3)
            print("     %-22s %5s f%d%s %s" % (_nm, _bd, _fv,
                                               "+" if _fv >= 3 else " ", _tag))
        print("  band mix: %d chalk / %d mid / %d deep" % (_bands["chalk"], _bands["mid"], _bands["deep"]))
        globals()["_LAST_SIXTEEN"] = set(_sixteen)
    except Exception as _ee:
        print("  [sixteen] skipped: %s" % _ee)
    # THE TB THIRTY -- per 2026-08-17: "I guarantee we find at least 30 total
    # base legs worth being able to put on our slips every single day." Here
    # they are, every day, with the HONEST measured tiers attached:
    #   *  ranks 1-5            ~45-47% each (OOF)  -- the 2x1.5TB pairing tier:
    #      two of these = ~23-25% a slip, HIS 1-in-4 two-leg bar, met only here
    #   ^  ELITE mark (any rank) = model top-20 AND pitch_vuln p80 AND xwoba
    #      p70 -- the best volume tier found: 15/night at 46.3% (45.1% Aug)
    #   ranks 6-30              ~43% season, ~40% August (OOF) -- real legs,
    #      but two of them = ~18% and three = ~7%; the bar lives at the top
    try:
        _sp = globals().get("_LAST_TBMODEL")
        _hdr = ("  THE TB THIRTY (full-slate model; * top-5 ~46%, ^ elite "
                "vuln+xwoba 46/45 Aug, rest ~43/40):")
        if _sp is None:
            _sp = globals().get("_LAST_SPEC")
            _hdr = "  THE TB THIRTY (your spec: zones x vuln x arm x arsenal; 1-5 ~48%, 6-30 ~40%):"
        if _sp is not None:
            _t30 = _sp.nlargest(30).index
            _vp = num(B, "pitch_vuln_score").rank(pct=True)
            _xp = num(B, "xwoba").rank(pct=True)
            # STACK, per 2026-08-17: "only off the data supplied through each
            # individual hitter... discount a qualified hitter where 1 or 2
            # measurables don't stack." s0-s8 = how many of the 8 signature
            # measurables this bat clears TONIGHT (xwoba p70, vuln p70, mix p70,
            # contact p60, xba p60, zone p60, K<=p40, weak-arm p70). Measured
            # inside the 30: stack 7+ lands 46.8% (42.3 Aug) vs 41.5% at
            # stack<=2. Printed for HIS selection; the assembler tiebreak on it
            # was replayed and LOST slips (0.69 vs 0.80/night) -- display only.
            _stk = pd.Series(0, index=B.index, dtype=int)
            for _c, _d, _cut in (("xwoba", 1, .70), ("pitch_vuln_score", 1, .70),
                                 ("mix_woba", 1, .70), ("contact_score", 1, .60),
                                 ("xba", 1, .60), ("zone_overlap", 1, .60),
                                 ("k_percent", -1, .40), ("p_xslg_allowed", 1, .70)):
                if have(B, _c):
                    _pp = num(B, _c).rank(pct=True)
                    _stk = _stk + ((_pp >= _cut) if _d > 0 else
                                   (_pp <= _cut)).fillna(False).astype(int)
            print(_hdr)
            _ln = []
            for _k, _i in enumerate(_t30):
                _nm = str(B.loc[_i, nc])[:14] if nc else str(_i)
                _el = "^" if (_k < 20 and float(_vp.get(_i, 0)) >= 0.8
                              and float(_xp.get(_i, 0)) >= 0.7) else ""
                _ln.append("%2d.%s%s%s s%d" % (_k + 1, _nm, "*" if _k < 5 else "",
                                               _el, int(_stk.get(_i, 0))))
            for _row in range(0, 30, 4):
                print("     " + "   ".join("%-24s" % x for x in _ln[_row:_row + 4]))
            # PIN-LIST EXPORT, per 2026-08-17: "rewire 'pin list' to be this 30
            # bats." The app's Custom TB mode "📌 Pin list" reads
            # boards/tb_pinlist.txt (one name per line, # comments ignored) and
            # prices each pinned bat individually on its own prior-night record.
            # So the THIRTY is written there on every run -- select the Pin
            # list mode in Custom and the pool IS this list, tiers and stacks
            # in the comments.
            try:
                if os.path.isdir("boards"):
                    with open(os.path.join("boards", "tb_pinlist.txt"), "w",
                              encoding="utf-8") as _pf:
                        _pf.write("# THE TB THIRTY -- %s -- written by %s\n"
                                  % (os.path.basename(str(path)),
                                     VERSION.split("--")[0].strip()))
                        _pf.write("# * top-5 pairing tier   ^ elite vuln+xwoba"
                                  "   sN measurables stacked tonight\n")
                        for _k, _i in enumerate(_t30):
                            _fnm = str(B.loc[_i, nc]) if nc else str(_i)
                            _fel = "^" if (_k < 20 and float(_vp.get(_i, 0)) >= 0.8
                                           and float(_xp.get(_i, 0)) >= 0.7) else ""
                            _pf.write("%-24s # %2d %s%s s%d\n"
                                      % (_fnm, _k + 1, "*" if _k < 5 else "",
                                         _fel, int(_stk.get(_i, 0))))
                    print("  [pin] boards/tb_pinlist.txt <- THE THIRTY "
                          "(the app's 📌 Pin list mode reads this file)")
            except Exception as _pe:
                print("  [pin] export skipped: %s" % _pe)
    except Exception as _te:
        print("  [thirty] skipped: %s" % _te)
    nhr, ntb = shape_legs(args)
    shape_lbl = args.shape if (args.hr_legs is None and args.tb_legs is None) \
        else "custom%dhr%dtb" % (nhr, ntb)
    if args.slips > 3:
        slips, tiers = assemble_slate(B, hc, tc, nhr, ntb, args.slips)
    else:
        slips = assemble(B, hc, tc, args.shape, args.slips, args.hr_cap, args.tb_cap) \
            if (args.hr_legs is None and args.tb_legs is None) else \
            assemble_slate(B, hc, tc, nhr, ntb, args.slips)[0]
        tiers = ["ANCHOR"] * len(slips)
    if isinstance(slips, tuple):
        slips, tiers = slips
    print("")
    for si, (legs, p) in enumerate(slips):
        print("  SLIP %d [%s] -- %.1f%% (measured-rate pricing)"
              % (si + 1, tiers[si] if si < len(tiers) else "ANCHOR", 100 * p))
        for li, (i, lp, why) in enumerate(legs):
            nm = str(B.loc[i, nc])[:22] if nc else str(i)
            prop = "HR " if li < nhr else "1.5TB"
            print("     %-5s %-22s %4.0f%%   %s" % (prop, nm, 100 * lp, " + ".join(why[:3])))
        print("")
    p1, p2 = night_probs(slips)
    distinct = len({i for legs, _p in slips for i, _lp, _w in legs})
    rule_()
    print("  NIGHT: P(>=1 slip wins) %.0f%%   P(>=2) %.0f%%   shape %s x%d   %d distinct bats"
          % (100 * p1, 100 * p2, shape_lbl, len(slips), distinct))
    if not args.no_log:
        log_slips(path, B, slips, shape_lbl, nhr)
    longs = [(i, v) for i, v in hc.items() if any(w.startswith("LONG") for w in v[1])]
    if longs and nc:
        longs = sorted(longs, key=lambda kv: -kv[1][0])[:8]
        print("  DEPTH CALLS (sub-chalk HR, 12-15% measured): "
              + " - ".join("%s(%s)" % (str(B.loc[i, nc])[:16], v[1][0][:11]) for i, v in longs))
    bench_h = sorted(hc.items(), key=lambda kv: -kv[1][0])[args.slips * 2:args.slips * 2 + 5]
    if bench_h and nc:
        print("  HR bench: " + ", ".join("%s(%s)" % (str(B.loc[i, nc])[:16], w[0][:10])
                                         for i, (p, w) in bench_h))
    return 0


def run_replay(args):
    files = sorted(glob.glob("boards/graded_full_*.csv"))
    if not files:
        print("  no graded boards under boards/.")
        return 2
    hr_l = load_lanes("hr_lanes.json", DEF_HR_LANES)
    tb_l = load_lanes("tb_lanes.json", DEF_TB_LANES)
    head("SLIPFORGE REPLAY -- every graded board, shape %s, %d slips a night"
         % (args.shape, args.slips))
    print("  Slips are built EXACTLY as the live mode builds them -- same callers, same")
    print("  pricing, same assembly -- then graded on hr_hit / tb15_hit. Slips won is the")
    print("  only number that comes out of this.")
    print("")
    nhr, ntb = SHAPES[args.shape]
    tot = wins = nights = nwin = 0
    hr_used = hr_hitn = tb_used = tb_hitn = 0
    for f in files:
        B = pd.read_csv(f, low_memory=False)
        yh = num(B, "hr_hit")
        yt = num(B, "tb15_hit")
        cov = yh.notna() if nhr else yt.notna()
        if ntb:
            cov = cov & yt.notna()
        Bc = B[cov].reset_index(drop=True)
        if len(Bc) < 40:
            continue
        Bc = matchup_merge(Bc)
        Bc = arsenal_merge(Bc)
        hc = call_hr(Bc, hr_l)
        tc = call_tb(Bc, tb_l)
        slips = assemble(Bc, hc, tc, args.shape, args.slips, args.hr_cap, args.tb_cap)
        if not slips:
            continue
        nights += 1
        w = 0
        for legs, _p in slips:
            good = True
            for li, (i, _lp, _why) in enumerate(legs):
                hit = (num(Bc, "hr_hit").iloc[i] if li < nhr
                       else num(Bc, "tb15_hit").iloc[i])
                if li < nhr:
                    hr_used += 1
                    hr_hitn += int(hit > 0)
                else:
                    tb_used += 1
                    tb_hitn += int(hit > 0)
                if not hit > 0:
                    good = False
            w += 1 if good else 0
        tot += len(slips)
        wins += w
        nwin += 1 if w else 0
    rule_()
    print("  %-30s %8d" % ("nights", nights))
    print("  %-30s %8d" % ("slips built", tot))
    print("  %-30s %8d   (%.2f%%)" % ("slips WON", wins, 100.0 * wins / max(tot, 1)))
    print("  %-30s %5d/%d   (%.0f%%)" % ("nights with a winner", nwin, nights,
                                         100.0 * nwin / max(nights, 1)))
    if hr_used:
        print("  %-30s %7.1f%%" % ("HR legs hit", 100.0 * hr_hitn / hr_used))
    if tb_used:
        print("  %-30s %7.1f%%" % ("TB legs hit", 100.0 * tb_hitn / tb_used))
    print("")
    print("  Compare against the app's own record the same way you graded it before")
    print("  (slipcheck.py): 141 slips, 7 won, 4.96 percent, 9 percent of nights. Same shape, same caps.")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default=None)
    ap.add_argument("--replay", action="store_true")
    ap.add_argument("--grade", action="store_true",
                    help="grade slipforge_log.csv against the graded boards")
    ap.add_argument("--no-log", dest="no_log", action="store_true")
    ap.add_argument("--shape", default="1hr2tb", choices=sorted(SHAPES))
    ap.add_argument("--slips", type=int, default=3)   # >3 switches to SLATE mode (tiered)
    ap.add_argument("--hr-legs", dest="hr_legs", type=int, default=None,
                    help="CUSTOM shape: HR legs per slip (with --tb-legs; 2-3 total)")
    ap.add_argument("--tb-legs", dest="tb_legs", type=int, default=None,
                    help="CUSTOM shape: 1.5TB legs per slip (with --hr-legs)")
    ap.add_argument("--hr-cap", dest="hr_cap", type=int, default=2)
    ap.add_argument("--tb-cap", dest="tb_cap", type=int, default=1)
    a = ap.parse_args()

    print("")
    print("#" * 100)
    print("#  %s" % VERSION)
    print("#  measured-rate pricing. slips won is the score. 3-leg shapes only.")
    print("#" * 100)

    if a.grade:
        return run_grade(a)
    if a.replay:
        return run_replay(a)
    b = a.board
    if not b:
        cand = []
        for p in glob.glob("boards/*.csv"):
            m = BOARD_ANY.match(os.path.basename(p))
            if m:
                cand.append((m.group(1), os.path.getmtime(p), p))
        if not cand:
            print("\n  no live board found under boards/. Pass --board <file>.")
            return 2
        nw = max(x[0] for x in cand)
        b = max([x for x in cand if x[0] == nw], key=lambda t: t[1])[2]
    return run_board(b, a)


if __name__ == "__main__":
    sys.exit(main())
