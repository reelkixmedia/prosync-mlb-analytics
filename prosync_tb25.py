#!/usr/bin/env python3
"""prosync_tb25.py -- the walk-forward-validated 2.5TB ranker.

WHY
  The engine ranked 2.5TB with sleeper_score. Measured out-of-sample against a flag count whose
  SIGNALS were themselves chosen walk-forward (prop_ranker_wf.py, 12 ranked nights, no night sees
  itself), the gap was not close:

      depth    tb_score/sleeper    validated flag count
      top 3         25.0%                36.1%      +11.1
      top 5         21.7%                35.0%      +13.3
      top 8         21.9%                34.4%      +12.5
      top 12        23.6%                34.0%      +10.4
      top 20        23.3%                32.1%       +8.8

  Both columns out-of-sample, so neither side has a fitting advantage. This is the honest gap.

THE FLAGS
  Every signal below was selected on >=90%% of ranked nights when the selection ran walk-forward
  against the 2.5TB outcome, drawn from a 21-signal pool with NOTHING banned. What 2.5TB kept that
  multi-hit did not is the interesting part -- pull_air_rate, avg_launch_ang, platoon_mult and
  r_xiso are all EXTRA-BASE levers: loft, pull and platoon are what turn a hit into a double. The
  contact signals multi-hit wanted (ld_percent, k_percent) were dropped by 2.5TB almost every night.

  Power is shared by both props, which is why nothing here is excluded on a theory.

USAGE
  import prosync_tb25 as _t25;  df = _t25.apply(df)
  Sets sleeper_score to the validated ranking on the SAME 0-100 percentile scale, so slp_conf,
  exclude_from_sleepers and the tier weighting downstream all keep working. The original is kept
  as sleeper_score_prev so the two can be compared on a live slate.
"""
import numpy as np
import pandas as pd

PCT = 0.70   # slate-relative flag threshold, same as every other validated flag

# (canonical, aliases, invert)  -- invert = LOW value is the good one
FLAGS = [
    ("avg_ev",           ("avg_ev", "exit_velocity_avg", "avgEV"),        False),
    ("brl_percent",      ("brl_percent", "barrel_batted_rate"),           False),
    ("hard_hit_pct",     ("hard_hit_pct", "hard_hit_percent"),            False),
    ("xiso",             ("xiso", "x_iso"),                               False),
    ("r_xiso",           ("r_xiso",),                                     False),
    ("avg_launch_ang",   ("avg_launch_ang", "launch_angle_avg"),          False),
    ("pull_air_rate",    ("pull_air_rate", "pull_air_pct"),               False),
    ("contact_score",    ("contact_score",),                              False),
    ("hr_arsenal_match", ("hr_arsenal_match",),                           False),
    ("pitch_vuln_score", ("pitch_vuln_score",),                           False),
    ("platoon_mult",     ("platoon_mult",),                               False),
    ("p_k_per_9",        ("p_k_per_9",),                                  True),
    ("batting_order",    ("batting_order",),                              True),
    # HITS AXIS (added after multihit_axis_test.py). Selected on 100%% of ranked nights for 2.5TB --
    # even a power prop needs the ball to land. babip is the batter's own rate; def_eff and
    # babip_allowed describe the team doing the FIELDING. Note 2.5TB ignored sprint_speed and
    # park_hit_idx entirely (0%% and 8%%), which is why those are NOT here: running does not
    # manufacture extra bases. That asymmetry is the real difference between the TB props.
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
    """Replace sleeper_score with the validated flag-count ranking. Guarded: on any failure the
    original sleeper_score is left exactly as it was."""
    try:
        n = len(df)
        if n < 12: return df
        cnt = pd.Series(0.0, index=df.index)
        used = []
        for name, aliases, inv in FLAGS:
            s = _series(df, aliases)
            if s is None: continue
            if name == "batting_order":
                s = s.replace(0, np.nan)      # 0 means "lineup not posted", not slot 0
            if s.notna().sum() < max(12, int(0.25 * n)): continue
            v = -s if inv else s
            thr = v.quantile(PCT)
            if not np.isfinite(thr): continue
            cnt += (v >= thr).fillna(False).astype(float)
            used.append(name)
        if len(used) < 5:
            return df                          # too thin a slate to trust; leave the old ranking
        df["tb25_flag_count"] = cnt.astype(int)
        df["tb25_flags_used"] = len(used)
        if "sleeper_score" in df.columns and "sleeper_score_prev" not in df.columns:
            df["sleeper_score_prev"] = df["sleeper_score"]
        # same 0-100 percentile scale the rest of the app expects. Ties broken by the OLD score so
        # equal-flag bats keep a stable, sensible order instead of shuffling arbitrarily.
        prev = pd.to_numeric(df.get("sleeper_score_prev", pd.Series(0.0, index=df.index)),
                             errors="coerce").fillna(0.0)
        blended = cnt * 1000.0 + prev
        df["sleeper_score"] = (blended.rank(pct=True) * 100).round(1)
        return df
    except Exception:
        return df
