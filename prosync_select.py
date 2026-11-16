#!/usr/bin/env python3
"""prosync_select.py -- the validated selection layer. Imported by app.py, safe to run alone.

THE ARCHITECTURE (all walk-forward validated on 10 unseen nights)

  GATE  ->  RANK BY FLAG COUNT  ->  SURFACE DAGGERS  ->  cut at whatever depth you want

  1. THE GATE (one, light). Elite-arm zone veto: a bat facing a top-quartile (stingy) arm with a
     poor zone fit is removed BEFORE ranking. Cleared bats beat vetoed by +3.8 as the floor
     tightens. It is the only gate that validated; everything else is a flag or a dagger.

  2. RANK BY FLAG COUNT. Every bat scored by how many of the flags it fires, each cut at the
     slate's own p70. Flag count is MONOTONIC with homer rate -- more flags fired = better homer
     position (>=8 flags 18.8%, >=10 21.7%, >=12 28.9% vs 11.6% base). Ties break by power.
     This is not a top-N: the RANKING is the flag system, and you scroll down as far as you want
     volume. #1 fired the most flags = best positioned.

     EQUAL WEIGHT, FULL SET -- both settled by test:
       - weighting the flags (by solo lift, or 2-tier) did NOT beat equal weight out of sample.
       - the correlated power flags (avg_ev/hard_hit/brl/xiso, r~0.9) are NOT redundant: the full
         set beat an 8-flag dedup 28.0%% vs 20.7%% at the top, and a depth-free greedy KEPT two
         0.90-correlated power flags. Their agreement is a confidence vote -- a bat firing all
         four power flags is a surer masher than one firing a single facet. Keep them all.

  3. DAGGERS surface separately. Value/mid bats rank LOW on flags by construction (they cannot
     fire the power flags -- that is what makes them value), so a pure count buries exactly the
     longshots wanted. 2-3 are pulled out by a band-relative score and tagged. Value dagger =
     band-relative power + arm + game total + loft, 23.3%% (2.78x its base); mid = band-rel power,
     26.7%%. Spot alone fails at 3.3%% -- all pieces required.

  DEGRADES INSTEAD OF BREAKING: the flag threshold is a FRACTION of AVAILABLE flags, so a dead
  feed loosens the bar rather than silently tightening it. Every stage is wrapped -- a failure
  disables the layer and leaves the board untouched.

Standalone:  source ~/mlb_analytics/env/bin/activate && python3 prosync_select.py
"""
import os, re, unicodedata, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
_HERE = os.path.dirname(os.path.abspath(__file__))
_BOARDS = os.path.join(_HERE, "boards")

# The flags, each with the live column names it may appear under (first match wins). Grouped so
# the value-vs-power logic and the daggers can reason about families -- NOT to weight them.
FLAGS = [
    ("avg_ev",            "power",  ("avg_ev","ev","exit_velo","exit_velocity","ev50")),
    ("hard_hit_pct",      "power",  ("hard_hit_pct","hardhit_percent","hard_hit_percent","hh")),
    ("brl_percent",       "power",  ("brl_percent","barrel_pct","barrels_per_bbe_percent","barrel_batted_rate")),
    ("xiso",              "power",  ("xiso","est_iso","expected_iso")),
    ("r_xiso",            "form",   ("r_xiso","recent_xiso")),
    ("avg_launch_ang",    "loft",   ("avg_launch_ang","launch_angle","attack_angle")),
    ("pull_air_rate",     "loft",   ("pull_air_rate","pull_air","pulled_air_rate")),
    ("hr_loft_match",     "loft",   ("hr_loft_match","loft_match")),
    ("pitch_vuln_score",  "matchup",("pitch_vuln_score","pitch_vuln","vuln_score")),
    ("hr_arsenal_match",  "matchup",("hr_arsenal_match","arsenal_match")),
    ("zone_fit",          "matchup",("zone_fit","loc_fit","zf_EV")),
    ("platoon_mult",      "spot",   ("platoon_mult","platoon")),
    ("implied_runs",      "spot",   ("implied_runs","implied_total","team_total")),
    ("p_hr_per_9",        "arm",    ("p_hr_per_9","p_hr9","hr_per_9")),
    ("p_fb_allowed",      "arm",    ("p_fb_allowed","pitcher_fb_allowed")),
    ("p_airhard_allowed", "arm",    ("p_airhard_allowed","p_air_hard_allowed")),
]
POWER_F = [n for n, g, _ in FLAGS if g == "power"]
ARM_F   = [n for n, g, _ in FLAGS if g == "arm"]
LOFT_F  = [n for n, g, _ in FLAGS if g == "loft"]

CELL_PROB = {
    "premium": {(0,5):5.8,(6,7):7.1,(8,9):15.5,(10,11):17.5,(12,13):30.9,(14,16):33.3},
    "chalk":   {(0,5):11.7,(6,7):13.9,(8,9):17.5,(10,11):21.1,(12,13):25.6,(14,16):25.0},
    "mid":     {(0,5):9.5,(6,7):14.9,(8,9):15.7,(10,11):None,(12,13):None,(14,16):None},
    "value":   {(0,5):8.2,(6,7):11.7,(8,9):None,(10,11):None,(12,13):None,(14,16):None},
}
BAND_BASE = {"premium":16.3,"chalk":16.0,"mid":10.8,"value":8.4}
DAGGER_RATE = {"value":23.3,"mid":26.7}

def _nrm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)
def _num(df, c):
    if c not in df.columns: return pd.Series(np.nan, index=df.index, dtype=float)
    v = df[c]
    if isinstance(v, pd.DataFrame): v = v.iloc[:, 0]
    return pd.to_numeric(v, errors="coerce")
def _resolve(df, names):
    for c in names:
        if c in df.columns and _num(df, c).notna().mean() > 0.30:
            return _num(df, c)
    return None
def _z(s):
    sd = s.std()
    return ((s - s.mean())/sd).fillna(0.0) if (sd and sd == sd and sd > 0) else pd.Series(0.0, index=s.index)


def repair_pitcher_id(df, log=print):
    """opp_pitcher NAME -> id via the active-only key. Idempotent. The feed id agreed with
    Statcast truth only 85-89%% of the time; name collisions against retired players are why."""
    if "opp_pitcher_id_prev" in df.columns:
        return df
    key_path = os.path.join(_HERE, "pitcher_key_v1.csv")
    if not os.path.exists(key_path):
        log("[prosync] pitcher_key_v1.csv missing -- run build_pitcher_key.py. Keeping existing id.")
        return df
    if "opp_pitcher" not in df.columns:
        return df
    try:
        K = pd.read_csv(key_path)
        K = K[K.get("ambiguous", 0) == 0]
        m = dict(zip(K["name_norm"], K["pitcher_id"]))
        resolved = df["opp_pitcher"].map(lambda x: m.get(_nrm(x)))
        old = _num(df, "opp_pitcher_id")
        both = old.notna() & resolved.notna()
        changed = int((old[both] != resolved[both]).sum())
        df["opp_pitcher_id_prev"] = old
        df["opp_pitcher_id"] = resolved.fillna(old)
        log("[prosync] pitcher id: resolved %.0f%% by name, corrected %d wrong-pitcher rows"
            % (resolved.notna().mean()*100, changed))
    except Exception as e:
        log("[prosync] pitcher id repair failed (%s) -- keeping existing id" % e)
    return df


def join_arm_profile(df, log=print):
    """p_fb_allowed / p_airhard_allowed. The gate and the dagger both need these."""
    p = os.path.join(_BOARDS, "pitcher_contact_v2.csv")
    if not os.path.exists(p): return df
    try:
        d = pd.read_csv(p).drop_duplicates("opp_pitcher_id_true")
        d = d.rename(columns={"opp_pitcher_id_true": "opp_pitcher_id"})
        d["opp_pitcher_id"] = pd.to_numeric(d["opp_pitcher_id"], errors="coerce")
        df["opp_pitcher_id"] = pd.to_numeric(df["opp_pitcher_id"], errors="coerce")
        add = [c for c in d.columns if c != "opp_pitcher_id" and c not in df.columns]
        if add:
            df = df.merge(d[["opp_pitcher_id"] + add], on="opp_pitcher_id", how="left")
            log("[prosync] arm profile joined on %.0f%% of bats" % (_num(df,"p_fb_allowed").notna().mean()*100))
    except Exception as e:
        log("[prosync] arm profile join failed: %s" % e)
    return df


def apply(df, core_n=30, dagger_n=3, log=print):
    """Add the selection layer. Never raises -- a failure leaves df untouched.
    core_n = how deep the board cuts on the flag ranking (adjustable; the ranking is the same
    regardless, this only moves where 'selected' stops). dagger_n = daggers per band (2-3)."""
    try:
        if df is None or not len(df): return df
        df = repair_pitcher_id(df, log=log)
        df = join_arm_profile(df, log=log)

        # ---- tiers on season power, cut on tonight's slate
        pw = _resolve(df, ("xiso","est_iso"))
        if pw is None: pw = _resolve(df, ("hard_hit_pct","hardhit_percent"))
        if pw is None or pw.notna().sum() < 20:
            log("[prosync] no usable power column -- layer disabled"); return df
        q88,q70,q35 = pw.quantile(.88), pw.quantile(.70), pw.quantile(.35)
        df["ps_tier"] = np.where(pw>=q88,"premium",np.where(pw>=q70,"chalk",np.where(pw>=q35,"mid","value")))

        # ---- resolve + fire the flags at slate p70 (equal weight, full set)
        fired, have, resolved = {}, [], {}
        for nm, grp, names in FLAGS:
            s = _resolve(df, names)
            if s is None or s.notna().sum() < 25 or s.nunique() < 5: continue
            have.append(nm); resolved[nm] = s
            fired[nm] = (s >= s.quantile(0.70)).fillna(False)
        if len(have) < 6:
            log("[prosync] only %d flags usable -- layer disabled" % len(have)); return df
        cnt = sum(fired[c].astype(int) for c in have)
        df["ps_flag_count"] = cnt
        df["ps_flags_avail"] = len(have)
        df["ps_flags"] = [" ".join(c for c in have if fired[c].iloc[i]) for i in range(len(df))]
        # readable token per flag, so the board can show WHICH flags fired (all of them), not just
        # a count. Matches the app's emoji style so it reads next to the old columns.
        _DISP = {"avg_ev":"\U0001F4A5EV","hard_hit_pct":"\U0001F528HH","brl_percent":"\U0001F3AFBrl",
                 "xiso":"⚡xISO","r_xiso":"\U0001F4C8Form","avg_launch_ang":"\U0001F680Loft",
                 "pull_air_rate":"↗Pull","hr_loft_match":"\U0001F388LoftM","pitch_vuln_score":"\U0001F3AFVuln",
                 "hr_arsenal_match":"\U0001F3F9Ars","zone_fit":"\U0001F4CDZone","platoon_mult":"⚔Plat",
                 "implied_runs":"\U0001F4CATotal","p_hr_per_9":"\U0001F4A3Arm","p_fb_allowed":"\U0001FA81FBarm",
                 "p_airhard_allowed":"\U0001F4A8AirHard"}
        df["ps_flags_disp"] = [" ".join(_DISP.get(c, c) for c in have if fired[c].iloc[i])
                               for i in range(len(df))]
        df["ps_count_ok"] = (cnt >= 0.75*len(have))    # the quality mark, a fraction not a fixed 12

        # ---- THE GATE: elite-arm zone veto (runs before ranking)
        gate_reason = pd.Series("", index=df.index, dtype=object)
        armq = _resolve(df, ("p_fb_allowed","p_hr_per_9"))     # stingy = LOW allowed
        zone = _resolve(df, ("zone_fit","loc_fit","zf_EV"))
        vetoed = pd.Series(False, index=df.index)
        if armq is not None and zone is not None:
            elite = armq <= armq.quantile(0.25)                # top-quartile (stingiest) arms
            zbad  = zone < zone.quantile(0.70)
            vetoed = (elite & zbad).fillna(False)
            gate_reason[vetoed] = "elite arm + poor zone fit"
        df["ps_gate_vetoed"] = vetoed
        df["ps_gate_reason"] = gate_reason

        # ---- RANK by flag count, power breaks ties. Vetoed bats sink below everyone.
        powz = sum(_z(resolved[c]) for c in POWER_F if c in resolved)
        if isinstance(powz, int): powz = pd.Series(0.0, index=df.index)
        tie = powz.rank(pct=True).fillna(0.0)
        rank_score = cnt + tie*0.001 - vetoed.astype(int)*100     # veto = pushed to the bottom
        df["ps_rank_score"] = rank_score.round(4)
        df["ps_rank"] = rank_score.rank(ascending=False, method="first").astype(int)

        # ---- daggers (band-relative), surfaced so the ranking cannot bury them
        relpow = pd.Series(0.0, index=df.index)
        for t in ("premium","chalk","mid","value"):
            m = (df["ps_tier"] == t)
            if m.sum() < 8: continue
            acc = pd.Series(0.0, index=df.index)
            for c in POWER_F:
                s = resolved.get(c)
                if s is None or s[m].notna().sum() < 5: continue
                acc.loc[m] = acc.loc[m] + _z(s[m])
            relpow.loc[m] = acc.loc[m]
        arm  = sum(_z(resolved[c]) for c in ARM_F if c in resolved)
        if isinstance(arm, int): arm = pd.Series(0.0, index=df.index)
        loft = sum(_z(resolved[c]) for c in LOFT_F if c in resolved)
        if isinstance(loft, int): loft = pd.Series(0.0, index=df.index)
        total = _z(resolved["implied_runs"]) if "implied_runs" in resolved else pd.Series(0.0, index=df.index)
        df["ps_dagger_value"] = (relpow + arm + total + loft).round(3)
        df["ps_dagger_mid"]   = relpow.round(3)

        # ---- SELECT: core = top core_n by rank (non-vetoed), + daggers per band
        sel = pd.Series(False, index=df.index)
        typ = pd.Series("", index=df.index, dtype=object)
        core_idx = df.index[(df["ps_rank"] <= core_n) & (~vetoed)]
        sel.loc[core_idx] = True; typ.loc[core_idx] = "CORE"
        for t, scol in (("value","ps_dagger_value"), ("mid","ps_dagger_mid")):
            m = df.index[(df["ps_tier"] == t) & (~vetoed)]
            if not len(m): continue
            top = df.loc[m, scol].nlargest(min(dagger_n, len(m))).index
            for i in top:
                if not sel.loc[i]: typ.loc[i] = "DAGGER-%s" % t[0].upper()
                sel.loc[i] = True
        df["ps_selected"] = sel
        df["ps_pick_type"] = typ

        # ---- the "why" line: tier, flags fired, and the measured rate of that cell
        def _cell(tier, c):
            for (lo,hi), v in CELL_PROB.get(tier, {}).items():
                if lo <= c <= hi: return v
            return None
        probs = [_cell(t,c) for t,c in zip(df["ps_tier"], df["ps_flag_count"])]
        df["ps_cell_prob"] = [p if p is not None else np.nan for p in probs]
        df["ps_band_base"] = df["ps_tier"].map(BAND_BASE)
        why = ["%s %d/%d flags -> %s%%" % (t, c, len(have), ("%.1f"%p) if p is not None else "thin")
               for t,c,p in zip(df["ps_tier"], df["ps_flag_count"], probs)]
        df["ps_why"] = why
        isd = df["ps_pick_type"].astype(str).str.startswith("DAGGER")
        df.loc[isd, "ps_why"] = ["DAGGER %s -> %.1f%% (band base %.1f%%)"
                                 % (t, DAGGER_RATE.get(t,0), BAND_BASE.get(t,0)) for t in df.loc[isd,"ps_tier"]]

        comp = df.loc[sel, "ps_tier"].value_counts().to_dict()
        log("[prosync] %d flags live (bar %d), gate vetoed %d, selected %d: %s"
            % (len(have), int(np.ceil(0.75*len(have))), int(vetoed.sum()), int(sel.sum()),
               " ".join("%s %d" % (k,v) for k,v in comp.items())))
    except Exception as e:
        log("[prosync] selection layer failed (%s) -- board unchanged" % e)
    return df


if __name__ == "__main__":
    import glob, sys
    lv = sorted(glob.glob(os.path.join(_BOARDS, "boards_2026-*.csv")))
    if not lv:
        print("no live board found in boards/"); sys.exit(1)
    b = pd.read_csv(lv[-1])
    print("board: %s  (%d bats)" % (os.path.basename(lv[-1]), len(b)))
    b = apply(b)
    if "ps_selected" not in b.columns:
        print("layer did not run"); sys.exit(1)
    s = b[b["ps_selected"]].sort_values("ps_rank")
    cols = [c for c in ("ps_rank","name","ps_tier","ps_pick_type","ps_flag_count","ps_cell_prob","ps_why")
            if c in s.columns]
    print("\n%d selected (core_n=30 + daggers):\n" % len(s))
    print(s[cols].head(40).to_string(index=False))
