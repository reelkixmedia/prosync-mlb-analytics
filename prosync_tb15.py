#!/usr/bin/env python3
"""prosync_tb15.py -- the walk-forward-validated 1.5TB ranker.

WHY NOT JUST USE sleeper_score
  sleeper_score out-ranked tb_score on 1.5TB at 4 of 5 depths, but that is a trap. A homer is 4
  total bases, so a power ranker clears the 1.5TB bar trivially -- it looks strong on this prop
  while surfacing the SAME names the 2.5TB board already gave you. Ranking 1.5TB on power collapses
  two boards into one and throws away the distinct thing 1.5TB is for: the high-contact bat who
  reaches 2 bases without needing to run into one.

  So 1.5TB gets its OWN flags, selected walk-forward against the 1.5TB outcome specifically.

MEASURED (tb25_incumbent.py, out-of-sample, selection walk-forward too)
      depth   tb_score (stale)  contact_score  sleeper_score  THESE FLAGS
      top 3        41.7%            41.7%          38.9%         44.4%
      top 5        35.0%            41.7%          43.3%         43.3%
      top 8        36.5%            36.5%          39.6%         44.8%
      top 12       37.5%            38.2%          42.4%         47.9%
      top 20       37.1%            42.9%          45.8%         42.9%

  Wins at the top of the board, where slip legs are drawn. sleeper_score catches up by top 20 --
  another sign that its edge here is the power shortcut rather than 1.5TB skill.

WHAT IT KEPT vs WHAT 2.5TB KEPT
  Shared: avg_ev, brl_percent, hard_hit_pct, xiso, contact_score, pitch_vuln, arsenal, slot, p_K/9.
  2.5TB-only: pull_air_rate, avg_launch_ang, platoon_mult, r_xiso -- the EXTRA-BASE levers.
  1.5TB-only: hr_loft_match.
  Power is shared because power genuinely helps every TB prop. The difference is that 1.5TB does
  not pay for loft/pull/platoon, so those are dropped instead of quietly inflating the same names.

USAGE
  import prosync_tb15 as _t15;  df = _t15.apply(df)
  Rewrites tb_score on the SAME 0-100 percentile scale. Original kept as tb_score_prev.
"""
import numpy as np
import pandas as pd

PCT = 0.70

# (canonical, aliases, invert)
FLAGS = [
    ("contact_score",    ("contact_score",),                              False),
    ("avg_ev",           ("avg_ev", "exit_velocity_avg", "avgEV"),        False),
    ("hard_hit_pct",     ("hard_hit_pct", "hard_hit_percent"),            False),
    ("brl_percent",      ("brl_percent", "barrel_batted_rate"),           False),
    ("xiso",             ("xiso", "x_iso"),                               False),
    ("hr_loft_match",    ("hr_loft_match",),                              False),
    ("hr_arsenal_match", ("hr_arsenal_match",),                           False),
    ("pitch_vuln_score", ("pitch_vuln_score",),                           False),
    ("p_k_per_9",        ("p_k_per_9",),                                  True),
    ("batting_order",    ("batting_order",),                              True),
    # HITS AXIS (added after multihit_axis_test.py). Selected on 92-100%% of ranked nights for
    # 1.5TB and worth +10.0 pts at top 5 (43.3 -> 53.3). The engine never knew whether a ball in
    # play actually falls: babip is the batter's own rate, def_eff / babip_allowed are the team
    # doing the FIELDING. A hit is a hit only if the defense does not catch it.
    ("babip",            ("babip",),                                      False),
    ("def_eff",          ("def_eff",),                                    True),
    ("babip_allowed",    ("babip_allowed",),                              False),
]

def _series(df, aliases):
    for a in aliases:
        if a in df.columns:
            v = df[a]
            if isinstance(v, pd.DataFrame): v = v.iloc[:, 0]
            return pd.to_numeric(v, errors="coerce")
    return None

def apply(df):
    """Replace tb_score with the validated 1.5TB ranking. Guarded: unchanged on any failure."""
    try:
        n = len(df)
        if n < 12: return df
        cnt = pd.Series(0.0, index=df.index); used = []
        for name, aliases, inv in FLAGS:
            s = _series(df, aliases)
            if s is None: continue
            if name == "batting_order":
                s = s.replace(0, np.nan)      # 0 = lineup not posted
            if s.notna().sum() < max(12, int(0.25 * n)): continue
            v = -s if inv else s
            thr = v.quantile(PCT)
            if not np.isfinite(thr): continue
            cnt += (v >= thr).fillna(False).astype(float)
            used.append(name)
        if len(used) < 5: return df
        df["tb15_flag_count"] = cnt.astype(int)
        df["tb15_flags_used"] = len(used)
        if "tb_score" in df.columns and "tb_score_prev" not in df.columns:
            df["tb_score_prev"] = df["tb_score"]
        prev = pd.to_numeric(df.get("tb_score_prev", pd.Series(0.0, index=df.index)),
                             errors="coerce").fillna(0.0)
        df["tb_score"] = ((cnt * 1000.0 + prev).rank(pct=True) * 100).round(1)
        return df
    except Exception:
        return df
