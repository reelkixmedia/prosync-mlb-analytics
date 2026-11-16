#!/usr/bin/env python3
"""hrmodel.py -- a home-run model built from the measurement, not the engine.

WHY START OVER

  Every read tested on 2026-08-31 failed the same way: it shared 60-75% of its
  bats with hr_score, so its rate was hr_score's rate wearing a different name.
  The pairs, the unions, the arm lane, the hard-hit x arsenal x fly-ball
  triple -- all of them were recombinations of columns the old engine had
  already combined.  Recombining a composite cannot beat the composite.

  So nothing derived by the old system is allowed in here.  No hr_score, no
  sleeper_score, no nk_*, no mix_*, no ps_*, no eng_*, no *_rank, no *_score.
  Only things that were MEASURED: exit velocity, launch angle, bat speed,
  batted-ball direction, what the arm actually allows, the park, the weather,
  and the chances.

WHAT A HOME RUN ACTUALLY REQUIRES

  It is a physics event with four gates, and the old ranking treated all four
  as "higher is better", which is wrong for two of them.

  1. EXIT VELOCITY.  Monotone -- harder is better, and there is a hard floor.
     A ball under about 95 mph off the bat essentially cannot leave the park.
     ev50 (the median of his hard contact) reads this better than avg_ev,
     which is dragged down by mishits.

  2. LAUNCH ANGLE.  *** NOT MONOTONE. ***  The home-run window is roughly
     25-32 degrees.  Below it the ball is a line drive, above it a pop-up.
     Ranking launch angle high-to-low rewards the pop-up hitter exactly as
     much as the slugger.  Every previous run in this project did that.
     Here it is scored as DISTANCE FROM THE WINDOW, which is the baseball.

  3. DIRECTION.  Pulled air is where the fences are shortest.  pull_air_rate
     is the direct measurement; ground-ball rate is its enemy -- a ground ball
     has a home-run probability of zero, so gb rate enters NEGATIVE.

  4. THE PITCH AND THE PLACE.  What this arm gives up in the air
     (p_airhard_allowed, p_fb_allowed, p_hr_per_9), the park, the weather,
     and how many times he bats.

HOW IT IS FITTED, AND WHY YOU CAN BELIEVE THE NUMBER

  Ridge logistic regression, within-night z-scores so no night's conditions
  leak into another's, and TWO-FOLD BY CALENDAR: fit on the first half of the
  nights, score the second; fit on the second, score the first.  Every night
  in the reported number was scored by a model that never saw it.  That is
  the whole point -- a model evaluated on its own training data will beat
  hr_score every time and mean nothing.

  Then the null: shuffle who homered, within night, REFIT THE WHOLE THING,
  and score out of sample again.  That measures what this procedure produces
  when there is nothing to find, which is the only bar a fitted model can be
  held to.

  And a head-to-head against hr_score on the identical rows, so the
  comparison is not against a different slate.

    python3 nk/hrmodel.py
    python3 nk/hrmodel.py --market tb
    python3 nk/hrmodel.py --show-coef      what the model actually learned
    python3 nk/hrmodel.py --nulls 10       slower, firmer bar
"""
import argparse, glob, math, os, re, shutil, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W = 100

# Anything the old engine derived.  A model built out of these is a model of
# the old engine.
BLOCK = re.compile(
    r"^(hr_|tb_|nk_|ps_|eng_|slp_|hrr_|al_|sleeper|contact_score|pitch_vuln|"
    r"mix_|fit_|loc_fit|zone_|chal_|pair|deep|agree|amp|carry|gate|stack|"
    r"diamond|dagger|dart|cband|ladder|spot|tier|band|flag|call|ship|lane|"
    r"sel$|rank$|score$|prob$|pick)", re.I)

# (board column candidates, label, how it enters, why -- in baseball)
FEAT = [
 (["ev_asof", "ev50"], "EV", "hi",
  "mean exit velo on his batted balls BEFORE tonight. the cleanest read of "
  "how hard he actually hits it"),
 (["hard_asof", "ev95percent", "hard_hit_percent", "hard_hit_pct"], "HARD%", "hi",
  "share of contact over 95 mph -- the floor a ball has to clear to go out"),


 (["la_asof", "avg_launch_ang", "avg_hit_angle"], "LAUNCH", "window:25:32",
  "mean launch angle, scored as distance FROM the 25-32 window. NOT "
  "monotone -- under it is a line drive, over it is a pop-up"),
 (["attack_asof", "attack_angle"], "ATTACK", "window:8:16",
  "how he swings, not what he hit. slower to change than results"),
 (["batspd_asof", "avg_bat_speed", "bat_speed"], "BAT SPD", "hi",
  "the input to exit velo, and the more stable half of power"),
 (["pullair_asof", "pull_air_rate"], "PULL-AIR", "hi",
  "pulled AND in the air -- where the fences are shortest. the home-run "
  "swing, measured off the spray coordinates"),
 (["gb_asof", "gb_percent", "gb_rate"], "GB%", "lo",
  "a ground ball has a home-run probability of exactly zero. NEGATIVE"),
 (["fb_asof", "flyballs_percent", "fb_rate"], "FB%", "hi",
  "balls in the air are the only ones eligible"),


 (["xiso_L30_asof", "iso_L30", "r_xiso"], "ISO L30", "hi",
  "expected ISO per batted ball over the last month -- power, recent"),
 (["xiso_L7_asof", "iso_L7"], "ISO L7", "hi",
  "the same over a week. form, not talent"),
 (["ev_L7_asof"], "EV L7", "hi",
  "exit velo over the last week. beside season EV the model can read the "
  "gap itself, which beats a hand-built one"),
 (["pullair_L30_asof"], "PULL-AIR L30", "hi",
  "is he pulling it in the air lately, or is that a March habit"),
 (["p_hr_per_9"], "ARM HR/9", "hi",
  "what this arm actually gives up. the most direct arm read"),
 (["p_airhard_allowed"], "ARM AIR-HARD", "hi",
  "hard contact in the air allowed -- the arm-side mirror of pull-air"),
 (["p_fb_allowed"], "ARM FB", "hi",
  "fly balls allowed. a ground-ball arm suppresses the event entirely"),

 (["p_xslg_allowed", "p_xslg_allowed_sv"], "ARM xSLG", "hi",
  "expected slug allowed -- damage, not luck"),
 (["park_factor"], "PARK", "hi",
  "fence distance and altitude, in one number"),
 (["weather_hr_mult"], "WEATHER", "hi",
  "air density and wind. a real physical term on carry"),
 (["implied_runs"], "RUNS", "hi",
  "the market's view of the whole game environment"),
 (["exp_pa", "pa_proj"], "CHANCES", "hi",
  "*** opportunity, not skill. in the model because more plate appearances "
  "really is more chances; --no-opp drops it"),
]
OUTC = {"hr": ["hr_hit", "homered", "is_hr"],
        "tb": ["tb_hit", "tb2", "is_tb"],
        "hrr": ["hrr_hit", "is_hrr"]}


def hdr(t, ch="="):
    print(ch * W); print(t); print(ch * W)


def rule():
    print("-" * W)


def fit_logit(X, y, lam=1.0, iters=25):
    """Ridge logistic by IRLS.  No sklearn -- one less thing to install and
    one less version to argue with."""
    import numpy as np
    n, p = X.shape
    Xb = np.hstack([np.ones((n, 1)), X])
    b = np.zeros(p + 1)
    R = np.eye(p + 1) * lam
    R[0, 0] = 0.0
    for _ in range(iters):
        z = Xb @ b
        z = np.clip(z, -30, 30)
        mu = 1.0 / (1.0 + np.exp(-z))
        wgt = np.clip(mu * (1 - mu), 1e-6, None)
        g = Xb.T @ (y - mu) - R @ b
        H = (Xb * wgt[:, None]).T @ Xb + R
        try:
            step = np.linalg.solve(H, g)
        except np.linalg.LinAlgError:
            break
        b = b + step
        if np.max(np.abs(step)) < 1e-7:
            break
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="hr", choices=("hr", "tb", "hrr"))
    ap.add_argument("--min-cover", type=float, default=0.50,
                    help="drop a feature present on less than this share of rows")
    ap.add_argument("--lam", type=float, default=25.0,
                    help="ridge strength. higher = flatter, less overfit")
    ap.add_argument("--nulls", type=int, default=6,
                    help="full refits on shuffled outcomes. the bar for a "
                         "FITTED model has to be a fitted null.")
    ap.add_argument("--no-opp", action="store_true",
                    help="drop the opportunity term (exp_pa)")
    ap.add_argument("--show-coef", action="store_true")
    ap.add_argument("--lock", action="store_true",
                    help="fit on every graded night as it stands TODAY, write "
                         "the coefficients to nk/history/hrmodel_locked.json "
                         "with today's date, and stop. Nights after that date "
                         "are the forward test and nothing else is.")
    ap.add_argument("--score", default=None,
                    help="score one board CSV with the locked model and write "
                         "hrm_score / hrm_rank onto it")
    ap.add_argument("--grade", action="store_true",
                    help="grade the locked model on nights AFTER the lock date")
    ap.add_argument("--apply", action="store_true",
                    help="with --score, actually write the board")
    ap.add_argument("--compare", default="hr_score",
                    help="the incumbent to beat, head to head on the same rows")
    a = ap.parse_args()
    import numpy as np, pandas as pd
    import warnings
    warnings.filterwarnings("ignore")

    hdr("HRMODEL   %s" % time.strftime("%Y-%m-%d %H:%M"))
    files = sorted(glob.glob(os.path.join(ROOT, "boards", "graded_full_*.csv")))
    if not files:
        print("  no boards/graded_full_*.csv"); return 1
    frames, dates = [], []
    for p in files:
        m = re.search(r"(20\d\d-\d\d-\d\d)", os.path.basename(p))
        if not m: continue
        try: d = pd.read_csv(p, low_memory=False)
        except Exception: continue
        frames.append(d); dates.append(m.group(1))
    lens = [len(f) for f in frames]
    j = pd.concat(frames, ignore_index=True, sort=False)
    j["_d"] = np.repeat(np.array(dates, dtype=object), lens)

    yc = next((c for c in OUTC[a.market] if c in j.columns), None)
    if yc is None:
        yc = next((c for c in OUTC["hr"] if c in j.columns), None)
    if yc is None:
        print("  no graded outcome column on the boards."); return 1
    keep = pd.to_numeric(j[yc], errors="coerce").notna()
    j = j[keep].reset_index(drop=True)
    y = (pd.to_numeric(j[yc], errors="coerce").fillna(0).to_numpy(float) > 0).astype(float)
    nights = sorted(set(j["_d"]))
    print("  %d night(s), %d bat-night(s), base %.2f%%   outcome column '%s'"
          % (len(nights), len(j), 100 * y.mean(), yc))
    print()

    # ---- build the feature matrix
    print("  FEATURES -- what each one is, in baseball")
    rule()
    cols, labs, whys, used = [], [], [], []
    for cands, lab, how, why in FEAT:
        if a.no_opp and lab == "CHANCES": continue
        c = next((x for x in cands if x in j.columns
                  and pd.to_numeric(j[x], errors="coerce").notna().mean() >= a.min_cover),
                 None)
        if c is None:
            av = [x for x in cands if x in j.columns]
            cv = (pd.to_numeric(j[av[0]], errors="coerce").notna().mean()
                  if av else 0.0)
            print("  %-12s MISSING   (%s)  %s" % (lab, ", ".join(cands)[:44],
                  "on %.0f%% of rows, need %.0f%%" % (100 * cv, 100 * a.min_cover)
                  if av else "not on the graded boards"))
            continue
        if BLOCK.match(c) and not c.endswith("_asof") and lab not in ("ARM HR/9",):
            print("  %-12s BLOCKED   %s is an engine column" % (lab, c)); continue
        v = pd.to_numeric(j[c], errors="coerce").to_numpy(float)
        if how.startswith("window:"):
            _, lo, hi = how.split(":")
            lo, hi = float(lo), float(hi)
            mid = (lo + hi) / 2.0
            v = -np.abs(v - mid)          # closer to the window = higher
        elif how == "lo":
            v = -v
        cols.append(v); labs.append(lab); whys.append((lab, c, how, why))
        used.append(c)
        print("  %-12s %-22s %-14s %.0f%% of rows"
              % (lab, c, {"hi": "higher better", "lo": "NEGATIVE"}.get(how, how),
                 100 * np.isfinite(v).mean()))
    print()
    if len(cols) < 4:
        print("  only %d usable feature(s).  Not enough to fit anything."
              % len(cols)); return 1

    for lab, c, how, why in whys:
        print("  %-12s %s" % (lab, why))
    print()

    # ---- within-night z, so a hot night cannot look like a good bat
    X = np.vstack(cols).T
    dn = j["_d"].to_numpy()
    Z = np.zeros_like(X)
    for k in range(X.shape[1]):
        s = pd.Series(X[:, k])
        g = s.groupby(dn)
        Z[:, k] = ((s - g.transform("mean")) / (g.transform("std") + 1e-9)).to_numpy()
    Z = np.nan_to_num(Z, nan=0.0, posinf=0.0, neginf=0.0)
    Z = np.clip(Z, -4, 4)

    cut = nights[len(nights) // 2]
    fh = (dn < cut)
    print("  two-fold by calendar: fit on %d night(s), score the other %d, then"
          % (len(set(dn[fh])), len(set(dn[~fh]))))
    print("  swap.  every row below was scored by a model that never saw it.")
    print()

    def oos_scores(yy):
        out = np.zeros(len(yy))
        for tr, te in ((fh, ~fh), (~fh, fh)):
            b = fit_logit(Z[tr], yy[tr], lam=a.lam)
            out[te] = np.hstack([np.ones((te.sum(), 1)), Z[te]]) @ b
        return out

    def decile_rate(sc, yy, frac):
        r = pd.Series(sc).groupby(dn).rank(pct=True).to_numpy()
        m = r >= 1 - frac
        return (100.0 * yy[m].mean() if m.sum() else float("nan")), int(m.sum())

    sc = oos_scores(y)

    # ---- the incumbent, on the identical rows
    inc = None
    if a.compare and a.compare in j.columns:
        inc = pd.to_numeric(j[a.compare], errors="coerce").to_numpy(float)

    LOCKF = os.path.join(HERE, "history", "hrmodel_locked.json")
    import json

    def zboard(d, feats):
        """same within-night z as the fit, on one board."""
        import numpy as _np
        M, ok = [], []
        for lab, col, how in feats:
            if col not in d.columns:
                M.append(_np.zeros(len(d))); ok.append(False); continue
            v = pd.to_numeric(d[col], errors="coerce").to_numpy(float)
            if how.startswith("window:"):
                _, lo, hi = how.split(":")
                v = -_np.abs(v - (float(lo) + float(hi)) / 2.0)
            elif how == "lo":
                v = -v
            mu, sd = _np.nanmean(v), _np.nanstd(v)
            z = (v - mu) / (sd + 1e-9)
            M.append(_np.nan_to_num(z, nan=0.0)); ok.append(True)
        return _np.clip(_np.vstack(M).T, -4, 4), ok

    if a.lock:
        b = fit_logit(Z, y, lam=a.lam)
        r5 = decile_rate(sc, y, 0.05)[0]; r10 = decile_rate(sc, y, 0.10)[0]
        r20 = decile_rate(sc, y, 0.20)[0]
        rec = {"locked_on": time.strftime("%Y-%m-%d"), "market": a.market,
               "lam": a.lam, "outcome": yc,
               "features": [[labs[k], used[k], whys[k][2]] for k in range(len(labs))],
               "intercept": float(b[0]),
               "coef": {labs[k]: float(b[1 + k]) for k in range(len(labs))},
               "fit_nights": len(nights), "fit_rows": int(len(y)),
               "base": float(100 * y.mean()),
               "claim_out_of_sample": {"top5": r5, "top10": r10, "top20": r20},
               "note": "the claim is the history that produced it. only nights "
                       "AFTER locked_on are the test."}
        os.makedirs(os.path.dirname(LOCKF), exist_ok=True)
        json.dump(rec, open(LOCKF, "w"), indent=1)
        hdr("LOCKED", "-")
        print("  %s" % os.path.relpath(LOCKF, ROOT))
        print("  fitted on %d night(s), %d bat-night(s), %d feature(s)"
              % (len(nights), len(y), len(labs)))
        print("  the claim, out of sample on that history:")
        print("     top 5%%  %.2f%%   top 10%%  %.2f%%   top 20%%  %.2f%%   base %.2f%%"
              % (r5, r10, r20, 100 * y.mean()))
        print()
        print("  Nights from %s forward are the test.  Everything before it is"
              % rec["locked_on"])
        print("  the claim, and a claim is not evidence.")
        print("     python3 nk/hrmodel.py --score boards/boards_<date>.csv --apply")
        print("     python3 nk/hrmodel.py --grade")
        return 0

    if a.score or a.grade:
        if not os.path.exists(LOCKF):
            print("  no locked model.  python3 nk/hrmodel.py --lock"); return 1
        L = json.load(open(LOCKF))
        feats = [(x[0], x[1], x[2]) for x in L["features"]]
        cf = np.array([L["coef"][f[0]] for f in feats], float)
        if a.score:
            p = a.score if os.path.isabs(a.score) else os.path.join(ROOT, a.score)
            if not os.path.exists(p): print("  no %s" % a.score); return 1
            d = pd.read_csv(p, low_memory=False)
            ZB, okf = zboard(d, feats)
            miss = [f[1] for f, o in zip(feats, okf) if not o]
            sc2 = L["intercept"] + ZB @ cf
            d["hrm_score"] = sc2
            d["hrm_rank"] = pd.Series(sc2).rank(ascending=False,
                                                method="first").astype(int)
            hdr("SCORED  %s" % os.path.basename(p), "-")
            print("  locked %s, %d feature(s), %d missing on this board%s"
                  % (L["locked_on"], len(feats), len(miss),
                     (": " + ", ".join(miss[:6])) if miss else ""))
            if len(miss) > len(feats) // 3:
                print("  MORE THAN A THIRD OF THE MODEL IS MISSING HERE.  The")
                print("  score is not comparable to the locked claim.")
            nm = next((c for c in ("name", "player_name") if c in d.columns), None)
            top = d.nsmallest(12, "hrm_rank")
            if nm:
                for _, r in top.iterrows():
                    print("   %2d  %-26s %8.3f" % (r["hrm_rank"], str(r[nm])[:26],
                                                   r["hrm_score"]))
            if a.apply:
                shutil.copy2(p, p + ".prehrm")
                d.to_csv(p, index=False)
                print("  WROTE hrm_score / hrm_rank onto the board.")
            else:
                print("  Nothing written.  Add --apply.")
            return 0
        # ---- grade
        hdr("FORWARD GRADE -- only nights after %s" % L["locked_on"], "-")
        fwd = [(dt, p) for dt, p in zip(dates, files) if dt > L["locked_on"]]
        if not fwd:
            print("  no graded night after %s yet." % L["locked_on"])
            print("  the claim was top 10%%  %.2f%% on a %.2f%% base."
                  % (L["claim_out_of_sample"]["top10"], L["base"]))
            print("  Come back when nights have accumulated.  A read needs"); 
            print("  roughly 30 of them before its rate means anything.")
            return 0
        tot = {}
        for dt, p in fwd:
            d = pd.read_csv(p, low_memory=False)
            oc = next((c for c in OUTC[a.market] if c in d.columns), None)
            if oc is None: continue
            yy = (pd.to_numeric(d[oc], errors="coerce").fillna(0).to_numpy() > 0)
            ZB, _ = zboard(d, feats)
            s2 = L["intercept"] + ZB @ cf
            rk = pd.Series(s2).rank(pct=True).to_numpy()
            for f in (0.05, 0.10, 0.20):
                m = rk >= 1 - f
                k = tot.setdefault(f, [0, 0])
                k[0] += int(yy[m].sum()); k[1] += int(m.sum())
            k = tot.setdefault("base", [0, 0])
            k[0] += int(yy.sum()); k[1] += len(yy)
        print("  %d night(s) since the lock" % len(fwd))
        print()
        print("  %-10s %8s %8s   %s" % ("cut", "rate", "legs", "the claim was"))
        rule()
        for f in (0.05, 0.10, 0.20):
            h, n = tot.get(f, [0, 0])
            cl = L["claim_out_of_sample"]["top%d" % int(f * 100)]
            print("  top %-6s %7.2f%% %8d   %.2f%%"
                  % ("%d%%" % int(f * 100), 100.0 * h / max(n, 1), n, cl))
        h, n = tot.get("base", [0, 0])
        print("  %-10s %7.2f%% %8d   %.2f%%" % ("base", 100.0 * h / max(n, 1),
                                                n, L["base"]))
        print()
        if n < 2000:
            print("  %d forward bat-night(s) is too few to conclude anything."
                  % n)
            print("  This is a progress report, not a verdict.")
        return 0

    hdr("OUT OF SAMPLE -- the model vs the board it was built from", "-")
    print("  %-22s %9s %9s %9s %9s" % ("", "top 5%", "top 10%", "top 20%", "top 33%"))
    rule()
    fr = [0.05, 0.10, 0.20, 0.33]
    row = []
    for f in fr:
        r, n = decile_rate(sc, y, f)
        row.append(r)
    print("  %-22s %8.2f%% %8.2f%% %8.2f%% %8.2f%%" % ("HRMODEL (out of sample)",
          row[0], row[1], row[2], row[3]))
    if inc is not None:
        irow = [decile_rate(inc, y, f)[0] for f in fr]
        print("  %-22s %8.2f%% %8.2f%% %8.2f%% %8.2f%%" % (a.compare, *irow))
        print("  %-22s %+8.2f %+8.2f %+8.2f %+8.2f"
              % ("difference", *(row[i] - irow[i] for i in range(4))))
    print("  %-22s %8.2f%% %8.2f%% %8.2f%% %8.2f%%"
          % ("board base", 100 * y.mean(), 100 * y.mean(), 100 * y.mean(),
             100 * y.mean()))
    print()

    # ---- halves, separately
    print("  the same numbers, each half scored by the model fitted on the other")
    rule()
    print("  %-22s %9s %9s %9s" % ("", "top 5%", "top 10%", "top 20%"))
    for nm, msk in (("first half", fh), ("second half", ~fh)):
        rr = []
        for f in fr[:3]:
            r = pd.Series(sc).groupby(dn).rank(pct=True).to_numpy()
            m = (r >= 1 - f) & msk
            rr.append(100.0 * y[m].mean() if m.sum() else float("nan"))
        print("  %-22s %8.2f%% %8.2f%% %8.2f%%   (base %.2f%%)"
              % (nm, rr[0], rr[1], rr[2], 100 * y[msk].mean()))
    print()

    # ---- the fitted null: shuffle, REFIT, score out of sample
    if a.nulls > 0:
        rng = np.random.default_rng(31415)
        srt = np.argsort(dn, kind="stable")
        best = []
        for _ in range(int(a.nulls)):
            o = np.lexsort((rng.random(len(y)), dn))
            ys = np.empty_like(y); ys[srt] = y[o]
            s2 = oos_scores(ys)
            best.append(decile_rate(s2, ys, 0.10)[0])
        best = np.array(best, float)
        print("  THE BAR: %d full refits on shuffled outcomes, scored out of"
              % int(a.nulls))
        print("  sample the same way.  Top decile on noise ran %.2f--%.2f%%,"
              % (float(best.min()), float(best.max())))
        print("  median %.2f%%, against a %.2f%% base.  This is what the WHOLE"
              % (float(np.median(best)), 100 * y.mean()))
        print("  PROCEDURE -- feature choice, z-scoring, ridge, two folds --")
        print("  produces when there is nothing in the data to find.")
        print()

    if a.show_coef:
        b = fit_logit(Z, y, lam=a.lam)
        order = np.argsort(-np.abs(b[1:]))
        print("  WHAT IT LEARNED  (fitted on everything, for reading only --")
        print("  the numbers above are the out-of-sample ones)")
        rule()
        print("  %-12s %9s   %s" % ("feature", "weight", "direction"))
        for k in order:
            print("  %-12s %+9.4f   %s" % (labs[k], b[1 + k],
                  "toward a homer" if b[1 + k] > 0 else "away from one"))
        print()
        print("  A weight near zero is the model saying that column adds")
        print("  nothing once the others are in. That is worth as much as a")
        print("  big one -- it is how you find out what to stop carrying.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
