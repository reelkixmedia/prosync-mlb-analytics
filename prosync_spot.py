#!/usr/bin/env python3
"""prosync_spot.py -- the SPOT score: rank HR legs by elite MATCHUP, not season tier.

WHY THIS EXISTS
  Measured on 24 graded nights (spot_vs_tier.py): ranking the HR board by SPOT catches ~50%% more
  of the night's actual homers than ranking by tier -- 85 vs 55 in the top 15. The homers are
  spread across the board (58%% are mid/value), and SPOT finds the spread while tier fishes the 42%%
  that is chalk.

  SPOT is the batter-in-the-best-position-to-punish-this-pitcher signal, built ONLY from matchup
  and hittable-arm inputs. Season power is deliberately excluded so it cannot collapse into the
  tier ranking it beats. A light power floor is the one nod to the batter's own bat -- a slap
  hitter in a perfect spot still cannot homer.

WHAT IT PRODUCES
  df['hr_spot']   slate-relative z-sum of the spot signals, with the power floor applied
  df['hr_spot_n'] how many signals were live (transparency; 0 = fell back to hr_prob)

  Guarded: if the signals are missing it falls back to hr_prob so the pull mode still functions.
"""
import numpy as np
import pandas as pd

# (column, invert)  -- invert=True means a LOW value is the good matchup
SPOT_SIGNALS = [
    ("pitch_vuln_score", False),   # batter vs this pitcher's stuff -- the matchup signal, 1.38x
    ("hr_arsenal_match", False),   # batter slug vs the arsenal, 1.26x
    ("p_hr_per_9",       False),   # pitcher hittability
    ("p_xslg_allowed",   False),   # pitcher gets punished
    ("p_fb_allowed",     False),   # fly-ball arm -- the best "he could go deep here" tell
    ("implied_runs",     False),   # game environment / team total
    ("platoon_mult",     False),   # hand edge
    ("park_factor",      False),   # the yard
    # NIKKO-ZONE-OVERLAP: batter damage-by-zone x where this arm throws x what he allows
    # there. 1.58x held-out, and +6.2 points stacked on pitch_vuln (20.8% vs 14.6%).
    ("zone_overlap",     False),   # the interaction, not either side alone
]
POWER_FLOOR = 0.140   # xISO -- low enough to keep value bats, high enough to drop slap hitters
# NIKKO-SPOT-COLDVETO: recency veto -- an ice-cold bat in a great matchup is still cold. Mirrors the validated
# hr_prob cold veto (recent xISO<0.07 AND season xISO<0.220 -> a proven masher's quiet stretch
# is exempt). Sinks by -5 (same magnitude as the no-power floor) so a frozen, non-power bat
# drops off the top of the spot board no matter how good the matchup looks.
COLD_RXISO    = 0.07
COLD_XISO_MAX = 0.220
COLD_PEN      = -5.0

def apply(df):
    """Add hr_spot to df. Never raises -- on any failure hr_spot falls back to hr_prob."""
    try:
        n = len(df)
        if n < 8:
            df["hr_spot"] = pd.to_numeric(df.get("hr_prob"), errors="coerce").fillna(0.0)
            df["hr_spot_n"] = 0
            return df
        spot = pd.Series(0.0, index=df.index)
        used = 0
        for c, inv in SPOT_SIGNALS:
            if c not in df.columns:
                continue
            v = pd.to_numeric(df[c], errors="coerce")
            if v.notna().sum() < max(12, int(0.30 * n)):
                continue
            mu, sd = v.mean(), v.std()
            if not sd or sd != sd:
                continue
            z = (v - mu) / sd
            spot = spot + (-z if inv else z).fillna(0.0)
            used += 1
        if used < 3:
            df["hr_spot"] = pd.to_numeric(df.get("hr_prob"), errors="coerce").fillna(0.0)
            df["hr_spot_n"] = 0
            return df
        # power floor: bats under the floor sink to the bottom but are not deleted
        xi = pd.to_numeric(df.get("xiso"), errors="coerce").fillna(0.0)
        pen = np.where(xi >= POWER_FLOOR, 0.0, -5.0)
        # NIKKO-SPOT-COLDVETO: sink an ice-cold, non-proven bat even in a great matchup (recency veto). Guarded --
        # only fires when r_xiso has real coverage; a masher (xiso>=COLD_XISO_MAX) is never vetoed.
        cold = np.zeros(len(df))
        rxi = pd.to_numeric(df.get("r_xiso"), errors="coerce")
        if rxi.notna().sum() >= max(12, int(0.30 * n)):
            cold = np.where((rxi.fillna(1.0).values < COLD_RXISO) & (xi.values < COLD_XISO_MAX), COLD_PEN, 0.0)
        df["hr_spot"] = (spot + pen + cold).round(3)
        df["hr_spot_n"] = used
        return df
    except Exception:
        try:
            df["hr_spot"] = pd.to_numeric(df.get("hr_prob"), errors="coerce").fillna(0.0)
            df["hr_spot_n"] = 0
        except Exception:
            pass
        return df
