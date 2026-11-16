#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prosync_tbclean.py -- the total-base ordering, with the homers actually stripped.

Written by wirepatch.py. Imported by app.py at the NIKKO-TBCLEAN tag.

THE RULE IS MECHANICAL, NOT ASPIRATIONAL. Every input a family uses must be on
ALLOW. Anything on TAINT is refused by name, and `attach()` records the refusal
on the frame so the app can print it. Saying "homers stripped" in a comment is
not stripping homers -- that is what v1-v4 of the analysis did while using
hard_hit_percent, brl_percent, hr_weak_arm, hr_loft_match, p_hr_per_9 and
p_airhard_allowed.

WHICH ORDERING gets used is read from tb_selector.json, which `assemble.py
--wire` writes from the graded measurement. If that file is missing the default
is BEST, because on the last measured run BLEND was the WORST of the six at
ticket depth and defaulting to a blend is how that happened.
"""

import json
import os

import numpy as np
import pandas as pd

VERSION = "prosync_tbclean v1"

TAINT = {
    "hr_prob", "hr_score", "hr_value", "hr_conviction", "hr_matchup_z",
    "hr_loft_match", "hr_weak_arm", "hr_arsenal_match", "hr_align_rank",
    "hr_al14_rank", "nk_callers", "nk_pair",
    "xiso", "r_xiso", "iso_hand_mult", "mix_iso_blend", "mix_iso_sp",
    "brl_percent", "hard_hit_percent", "blasts_contact", "fb_rate",
    "flyballs_percent", "sleeper_score",
    "p_hr_per_9", "p_brl_allowed", "p_airhard_allowed", "worst_pitch_xslg",
    "ars_xslg", "ars_xslg_v2", "ars_xiso_v2", "p_fb_allowed",
}

ALLOW = {
    "contact_score", "xba", "ba", "batting_avg", "xwoba", "r_xwoba", "woba",
    "babip", "tb15_rate", "ab", "pa", "k_percent", "bb_percent",
    "on_base_percent", "obp", "xobp", "ld_rate", "_ld_window",
    "ev50", "zone_overlap", "loc_fit", "implied_runs", "p_k_per_9",
    "p_xslg_allowed", "pitch_vuln_score", "pen_xwoba_allowed", "p_gb_allowed",
    "p_net_lean", "p_whip", "p_xwoba_allowed", "p_hitsupp_m_val",
}

ALIASES = {
    "ld_rate": ["ld_rate", "linedrives_percent", "ld_percent", "ld_pct", "LD%",
                "linedrive_rate", "line_drive_percent"],
    "la_avg": ["la_avg", "avg_launch_ang", "launch_angle_avg", "avg_launch_angle",
               "launch_angle", "LA"],
    "on_base_percent": ["on_base_percent", "obp", "on_base_pct", "xobp", "OBP"],
    "bb_percent": ["bb_percent", "walk_percent", "bb_pct", "BB%"],
    "ev50": ["ev50", "ev_50", "median_ev", "avg_hit_speed"],
    "batting_avg": ["batting_avg", "ba", "avg"],
    "p_xslg_allowed": ["p_xslg_allowed", "p_slg_allowed"],
    "pen_xwoba_allowed": ["pen_xwoba_allowed", "p_xwoba_allowed"],
    "contact_score": ["contact_score", "tb_contact_score"],
}

FAMILIES = [
    ("CONTACT", [("contact_score", 1, "p_k_per_9", -1),
                 ("xba", 1, "p_xslg_allowed", 1),
                 ("on_base_percent", 1, "pen_xwoba_allowed", 1),
                 ("k_percent", -1, "p_k_per_9", -1),
                 ("xwoba", 1, "pitch_vuln_score", 1)]),
    ("LINEDRIVE", [("ld_rate", 1, "pitch_vuln_score", 1),
                   ("ld_rate", 1, "p_gb_allowed", -1),
                   ("_ld_window", 1, "p_xslg_allowed", 1),
                   ("ev50", 1, "_ld_window", 1)]),
    ("XBH", [("babip", 1, "implied_runs", 1),
             ("r_xwoba", 1, "pitch_vuln_score", 1),
             ("ev50", 1, "p_xslg_allowed", 1),
             ("ld_rate", 1, "implied_runs", 1)]),
    ("BATBALL", [("batting_avg", 1, "zone_overlap", 1),
                 ("contact_score", 1, "p_xslg_allowed", 1),
                 ("k_percent", -1, "ev50", 1),
                 ("xwoba", 1, "p_net_lean", 1)]),
]

SELECTOR_FILE = "tb_selector.json"


def _num(d, c):
    if c in d.columns:
        return pd.to_numeric(d[c], errors="coerce")
    return pd.Series(np.nan, index=d.index, dtype="float64")


def _resolve(d, canon, need=0.15):
    if canon in d.columns and _num(d, canon).notna().mean() >= need:
        return canon
    for c in ALIASES.get(canon, []):
        if c in d.columns and pd.to_numeric(d[c], errors="coerce").notna().mean() >= need:
            return c
    return None


def prepare(d):
    """Copy every canonical read onto its canonical name and build the derived
    ones. Returns (frame, resolution report)."""
    d = d.copy()
    rep = []
    for canon in sorted(set(list(ALIASES.keys()))):
        got = _resolve(d, canon)
        if got is None:
            rep.append((canon, None))
            continue
        if got != canon:
            d[canon] = pd.to_numeric(d[got], errors="coerce")
        rep.append((canon, got))
    la = _resolve(d, "la_avg")
    if la is not None:
        # the DOUBLES launch window. Line drives and gappers live near 10-20
        # degrees, home runs near 25-35. A bump centred at 14 with sigma 8 is
        # near zero by 32, so this read is high for the bat that squares it up
        # and low for the bat that lifts it out -- an extra-base read that
        # structurally excludes the homer.
        d["_ld_window"] = np.exp(-((pd.to_numeric(d[la], errors="coerce") - 14.0) / 8.0) ** 2)
        rep.append(("_ld_window", la))
    return d, rep


def _pctl(d, c, hi=1):
    r = _num(d, c).rank(pct=True)
    return r if hi > 0 else (1.0 - r)


def family_scores(d, min_fill=0.15):
    """One score per family plus the audit of what was used and what was refused."""
    out, used, refused = {}, {}, []
    for key, pairs in FAMILIES:
        parts, u = [], []
        for a, sa, b, sb in pairs:
            if a in TAINT or b in TAINT:
                refused.append((key, a if a in TAINT else b, "HR-tainted"))
                continue
            if a not in ALLOW or b not in ALLOW:
                refused.append((key, a if a not in ALLOW else b, "not on the allow list"))
                continue
            ok = True
            for c in (a, b):
                if c not in d.columns or _num(d, c).notna().mean() < min_fill:
                    ok = False
            if not ok:
                continue
            parts.append(_pctl(d, a, sa) * _pctl(d, b, sb))
            u.append("%s x %s" % (a, b))
        if parts:
            out[key] = sum(parts) / float(len(parts))
            used[key] = u
    return out, used, refused


def _rotate(d, fam):
    """The round robin. Family one gives up its best bat, family two gives up
    its best bat, and so on around the table, skipping anyone already taken.
    A bat that is second on four families never outranks a bat that is first on
    one -- the opposite of a blend, and the thing that produces DIFFERENT bats."""
    keys = list(fam.keys())
    n = len(d)
    out = np.full(n, np.nan)
    order = {}
    for k in keys:
        s = fam[k].to_numpy()
        s = np.where(np.isnan(s), -np.inf, s)
        order[k] = np.argsort(-s, kind="stable")
    ptr = dict((k, 0) for k in keys)
    taken, slot = set(), 0
    while slot < n:
        moved = False
        for k in keys:
            while ptr[k] < n and order[k][ptr[k]] in taken:
                ptr[k] += 1
            if ptr[k] >= n:
                continue
            i = int(order[k][ptr[k]])
            ptr[k] += 1
            taken.add(i)
            out[i] = -float(slot)
            slot += 1
            moved = True
            if slot >= n:
                break
        if not moved:
            break
    return pd.Series(out, index=d.index)


def read_selector(default="BEST"):
    try:
        if os.path.exists(SELECTOR_FILE):
            with open(SELECTOR_FILE) as f:
                j = json.load(f)
            k = str(j.get("selector", default)).upper()
            return k, j
    except Exception:
        pass
    return default, {}


def attach(df, out_col="_tb_clean", selector=None):
    """Attach a 0-100 ordering built ONLY from allowed inputs. Never raises:
    on any failure the frame comes back exactly as it went in, without out_col,
    and the caller's existing score column keeps the lane."""
    try:
        if df is None or len(df) == 0:
            return df
        d, rep = prepare(df)
        fam, used, refused = family_scores(d)
        if not fam:
            return df
        sel = (selector or read_selector()[0]).upper()
        pcts = dict((k, v.rank(pct=True)) for k, v in fam.items())
        if sel in fam:
            score = pcts[sel]
        elif sel == "BLEND":
            score = sum(pcts.values()) / float(len(pcts))
        elif sel == "ROTATE":
            score = _rotate(d, fam).rank(pct=True)
        else:                                   # BEST, and the fallback
            sel = "BEST"
            score = pd.concat(list(pcts.values()), axis=1).max(axis=1)
        out = df.copy()
        out[out_col] = (score.rank(pct=True) * 100.0).fillna(0.0).values
        for k, v in fam.items():
            out["_tbf_" + k] = (v.rank(pct=True) * 100.0).fillna(0.0).values
        out.attrs["tbclean"] = dict(selector=sel, used=used, refused=refused,
                                    resolved=rep, families=list(fam.keys()))
        return out
    except Exception:
        return df


def explain(df):
    a = getattr(df, "attrs", {}).get("tbclean")
    if not a:
        return "tbclean did not run"
    bits = ["selector %s" % a["selector"],
            "families %s" % "/".join(a["families"]),
            "%d pairs" % sum(len(v) for v in a["used"].values())]
    return "  ".join(bits)
