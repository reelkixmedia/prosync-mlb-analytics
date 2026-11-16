#!/usr/bin/env python3
"""
hr_calibration_fit.py  —  READ-ONLY.

Reads graded HR snapshots (hr_snapshots/hr_snap_*.json — each has hr_pct predicted +
homered actual) and fits the actual-vs-predicted curve. Outputs the calibration
correction to apply to hr_prob so predicted == actual (20% means 20%).

Reports:
  - per-band predicted vs actual homer rate (the miscalibration)
  - the overall multiplier (actual/predicted) — the "~30% hot" number, measured
  - an isotonic-style monotone band map you can apply
  - a single global shrink factor (simplest correction) + per-band factors

USAGE:  python3 hr_calibration_fit.py  [--dir hr_snapshots] [--min-graded 3]
"""
import argparse, glob, json, os, sys
from collections import defaultdict

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--dir", default="hr_snapshots")
    ap.add_argument("--min-graded", type=int, default=3, dest="min_graded")
    ap.add_argument("--regression", type=float, default=0.5,
                    help="shrink each band's correction toward the model by this much (0=full correction, 1=no correction). 0.5 = gentle.")
    ap.add_argument("--out", default="hr_calibration.json")
    ap.add_argument("--no-write", action="store_true")
    a=ap.parse_args()
    files=sorted(glob.glob(os.path.join(a.dir,"hr_snap_*.json")))
    if not files: print(f"❌ no hr_snap_*.json in {a.dir}/"); sys.exit(1)

    # collect (predicted_prob, homered) pairs from graded snapshots only
    pts=[]; graded_nights=0
    for f in files:
        try: snap=json.load(open(f))
        except Exception: continue
        # a snapshot is "graded" if any homered flag is True OR file is from a past date
        vals=list(snap.values())
        if not vals: continue
        any_marked=any(v.get('homered') for v in vals)
        if not any_marked:   # ungraded (today's, not yet marked) — skip
            continue
        graded_nights+=1
        for v in vals:
            p=v.get('hr_pct'); h=v.get('homered')
            if p is None: continue
            pts.append((float(p)/100.0, 1 if h else 0))
    if graded_nights < 1:
        print(f"no graded snapshots yet (found {len(files)} files, none marked). "
              f"Grade a few nights first."); sys.exit(0)
    if len(pts) < 50:
        print(f"⚠️ only {len(pts)} graded predictions across {graded_nights} nights — thin. "
              f"Read direction, recalibrate lightly."); 

    n=len(pts); homers=sum(h for _,h in pts)
    base_pred=sum(p for p,_ in pts)/n; base_act=homers/n
    print("="*68); print(f"HR CALIBRATION FIT — {graded_nights} graded nights, {n} predictions, {homers} homers"); print("="*68)
    print(f"\n  OVERALL:  predicted avg {base_pred*100:.1f}%   actual {base_act*100:.1f}%   "
          f"-> model runs {base_pred/base_act:.2f}x {'HOT (over-predicts)' if base_pred>base_act else 'COLD (under-predicts)'}")
    print(f"  global shrink factor = {base_act/base_pred:.3f}  (multiply hr_prob by this to fix the average)")

    # per-band
    bands=[(0,0.05),(0.05,0.10),(0.10,0.15),(0.15,0.20),(0.20,0.25),(0.25,1.01)]
    print(f"\n  {'band':<12} {'n':>5} {'pred%':>7} {'actual%':>8} {'factor':>8}")
    print("  "+"-"*44)
    band_factor={}
    for lo,hi in bands:
        sub=[(p,h) for p,h in pts if lo<=p<hi]
        if not sub: continue
        npred=sum(p for p,_ in sub)/len(sub); nact=sum(h for _,h in sub)/len(sub)
        fac=(nact/npred) if npred>0 else 1.0
        band_factor[(lo,hi)]=fac
        flag="  ← over" if fac<0.85 else ("  ← under" if fac>1.15 else "")
        print(f"  {lo*100:.0f}-{hi*100:>3.0f}%      {len(sub):>5} {npred*100:6.1f}% {nact*100:7.1f}% {fac:7.2f}x{flag}")

    # monotone (isotonic-lite): enforce non-decreasing actual rate across bands
    print(f"\n  CALIBRATED BAND MAP (monotone — what each predicted band SHOULD read):")
    prev=0.0; mono=[]
    for lo,hi in bands:
        sub=[(p,h) for p,h in pts if lo<=p<hi]
        if not sub: continue
        nact=sum(h for _,h in sub)/len(sub)
        nact=max(nact,prev)  # enforce monotone up
        prev=nact; mono.append((lo,hi,nact))
        print(f"     predicted {lo*100:.0f}-{hi*100:.0f}%  ->  true ~{nact*100:.1f}%")

    # ── write hr_calibration.json: (predicted-midpoint%, calibrated%) anchors, regressed ──
    if not a.no_write and mono:
        reg = max(0.0, min(1.0, a.regression))
        anchors = []
        for lo, hi, true_rate in mono:
            mid = (lo + hi) / 2.0
            # regress the calibrated rate toward the model's own midpoint (identity) by `reg`
            cal = mid + (true_rate - mid) * (1.0 - reg)
            anchors.append([round(mid*100, 2), round(cal*100, 2)])
        # enforce monotone after regression
        for i in range(1, len(anchors)):
            if anchors[i][1] < anchors[i-1][1]:
                anchors[i][1] = anchors[i-1][1]
        out = {"anchors": anchors, "regression": reg, "nights": graded_nights,
               "n": n, "generated": __import__("datetime").date.today().isoformat()}
        json.dump(out, open(a.out, "w"), indent=2)
        print(f"\n  ✓ wrote {a.out}  (regression {reg}) — restart the app to apply.")
        print(f"    curve: " + "  ".join(f"{x:.0f}%->{y:.1f}%" for x,y in anchors))

    print("\n" + "="*68)
    print("Apply the GLOBAL SHRINK as the simple fix (one multiply, robust on thin data),")
    print("or the per-band factors for a sharper correction once you have ~10+ graded nights.")
    print("Re-run after each week of grading; the factor should drift toward 1.00 as the")
    print("model self-corrects. NOTE: pre-zone-fit boards inflate HR — expect the factor to")
    print("move once zone-fit-scored nights dominate the sample.")

if __name__ == "__main__":
    main()
