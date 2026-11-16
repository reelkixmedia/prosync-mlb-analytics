#!/usr/bin/env python3
"""prosync_tb_opportunity.py -- rank 1.5TB legs by OPPORTUNITY, the signal that actually separates.

WHY THIS EXISTS
  1.5TB is an OPPORTUNITY prop, not a skill prop. Measured on 24 graded nights (tb_findable.py):
  plate appearances is the #1 signal by 21 points -- the bats that clear 2 bases are the ones who
  BAT the most (top of order, high total, 5 PA not 3.5). The engine ranked TB legs by contact skill
  (contact_score, 38%%). Opportunity ranks them at ~48%% pre-game (tb_opportunity.py) -- a ten-point
  lift on the exact leg that was killing the homer slips.

  Live, with a CONFIRMED lineup, the slot term is exact rather than a projection, so the live rate
  should run a few points above the ~48%% measured on reconstructed slots.

WHAT IT PRODUCES
  df['tb_opp']    opportunity-first 1.5TB score: projected PA (lineup slot + team total) as the
                  spine, plus matchup (Zone-fit), a light contact/power floor, and BABIP.
  df['tb_opp_n']  how many terms were live.

  Guarded: falls back to tb_prob (or contact_score) if the inputs are missing.
"""
import numpy as np
import pandas as pd

def _z_night(df, s, inv=False):
    """slate-relative z-score; df must carry a per-slate grouping via _slate_key or fall back to all."""
    v = pd.to_numeric(s, errors="coerce")
    if v.notna().sum() < max(12, int(0.3*len(df))):
        return None
    mu, sd = v.mean(), v.std()
    if not sd or sd != sd:
        return None
    z = (v - mu) / sd
    return (-z if inv else z).fillna(0.0)

def apply(df):
    """Add tb_opp to df. Never raises."""
    try:
        n = len(df)
        if n < 8:
            df["tb_opp"] = pd.to_numeric(df.get("tb_prob", df.get("contact_score")), errors="coerce").fillna(0.0)
            df["tb_opp_n"] = 0
            return df
        score = pd.Series(0.0, index=df.index)
        used = 0

        # --- the spine: projected plate appearances ---
        # lineup slot (1 best); prefer the real batting_order, else any projected slot column.
        slot = None
        for c in ("batting_order", "_slotproj", "slot"):
            if c in df.columns:
                s = pd.to_numeric(df[c], errors="coerce").replace(0, np.nan)
                if s.notna().mean() > 0.3:
                    slot = s
                    break
        if slot is not None:
            proj_pa = (6.0 - slot.clip(1, 9)).clip(lower=0)   # slot 1 -> 5 PA proxy, slot 9 -> 0
            z = _z_night(df, proj_pa)
            if z is not None:
                score = score + z * 1.0
                used += 1
        # team total amplifies PA (more runs = more turns of the lineup)
        if "implied_runs" in df.columns:
            z = _z_night(df, df["implied_runs"])
            if z is not None:
                score = score + z * 0.5
                used += 1

        # --- the LEARNED recipe (tb_model.py, logistic, walk-forward) ---
        # A model that weighted all 16 candidate signals optimally landed on: BABIP, xBA,
        # contact_score, projected PA, implied_runs. These are the weights it chose, normalized.
        # PA + implied_runs are the opportunity spine above; these are the skill/matchup layer.
        # NIKKO-NONHR: re-weighted on the measured NON-HOMER outcome (boards/tb_extrabase.py,
        # 26 nights). The old weights were fit on ANY 1.5TB clear -- which counts homers, so
        # they rewarded power. Against tb15_hit_nonhr specifically:
        #   non-HR clear rate by power tier: low 23.5% | mid 22.3% | high 23.7%  -> POWER ADDS ZERO
        #   top-12 non-HR: xBA 28.6% (top-8 34.4%) | contact 26.1% | BA 25.5% | doubles/AB 18.2%
        #   corr vs non-HR: contact +.115 | xba +.091 | BA +.062 | K% -.069 | xISO +.015 | brl -.006
        # A bat who clears 1.5TB by homering is a bat you would have taken on the HR board --
        # using him as the "safe" anchor double-counts the homer leg and correlates the slip.
        # NOTE: a doubles rate tested WEAK (top-12 18.2%, r=+.033). The non-HR path to 1.5TB is
        # mostly MULTIPLE HITS, not doubles -- so rank hit-getters, not doubles hitters.
        # NIKKO-TB-POWER-BACK: xISO restored at HALF the xBA weight. The earlier removal was
        # measured against tb15_hit_NONHR (clears excluding homers), where power genuinely adds
        # nothing -- but the BET is the full 1.5TB, where a homer clears it outright. Swept
        # split-half against that outcome (boards/selection_fixes.py, top-12/night, B half):
        #   +0.00 xISO 39.1% | +0.30 41.7% | +0.50 **42.3%** | +1.00 41.7%   (B base 32.9%)
        # +3.2 points, and the non-HR column FALLING as the full column rises (32.6 -> 28.5)
        # is the mechanism confirming itself: the gain arrives through homers, which pay the
        # same as a double. Deliberately DAMPED, not lead: full weight gives back 0.6, and a
        # power-led TB ranker collapses into the 2.5TB board and stops decorrelating the slip.
        for c, inv, w in [("xba", False, 1.0),
                          ("contact_score", False, 0.65),
                          ("xiso", False, 0.50),
                          ("babip", False, 0.5),
                          ("batting_avg", False, 0.45),
                          ("k_percent", True, 0.30),
                          ("pitch_vuln_score", False, 0.2)]:
            if c in df.columns:
                z = _z_night(df, df[c], inv)
                if z is not None:
                    score = score + z * w
                    used += 1

        if used < 2:
            df["tb_opp"] = pd.to_numeric(df.get("tb_prob", df.get("contact_score")), errors="coerce").fillna(0.0)
            df["tb_opp_n"] = 0
            return df
        df["tb_opp"] = score.round(3)
        df["tb_opp_n"] = used
        return df
    except Exception:
        try:
            df["tb_opp"] = pd.to_numeric(df.get("tb_prob", df.get("contact_score")), errors="coerce").fillna(0.0)
            df["tb_opp_n"] = 0
        except Exception:
            pass
        return df
