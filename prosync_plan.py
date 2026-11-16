#!/usr/bin/env python3
"""prosync_plan.py -- portfolio slip planning. The three modes generator_sim.py measured.

WHY THIS EXISTS
  The generator picks legs ONE AT A TIME, which can only ever express "take the next best bat."
  But which slips you build is a PORTFOLIO question -- how many slips a given bat anchors changes
  the whole night's shape, and that cannot be decided one leg at a time. These builders plan the
  full set of HR pairs for a slate at once, then the generator consumes the plan.

MEASURED (generator_sim.py, 4000 simulated nights, calibration verified first)
    mode          wins/night          nights paid       max slips on one bat
    concentrate   1.67 [1.60-1.75]    60.2%             8.0
    log           1.43 [1.38-1.49]    64.0%             5.6      <- default
    coverage      1.27 [1.23-1.31]    65.6%             3.5

  These are a genuine frontier -- none dominates. concentrate wins the most tickets, coverage pays
  on the most nights, log keeps 86%% of concentrate's tickets while paying ~4 more nights per 100.

  Two things that did NOT survive and are deliberately absent:
    - conviction+anchor: DOMINATED (1.60 tickets AND 56.0%% nights -- concentrate beat it on both).
      It paired an anchor with a deliberately weaker partner, losing ticket probability, while
      still reusing anchors 9.4 times, so it never bought the diversification it paid for.
    - anchor-all (every slip on the best bat): 75.4%% blank nights and it did not even lead on
      tickets. One bet wearing thirty tickets.

  NOTE: this optimizes HIT RATE only. It cannot see payout. A concentrate slate is chalkier and
  pays less per ticket; that tradeoff is not measured here.
"""
import itertools
import numpy as np

NSIM = 1500          # inner monte-carlo draws for the greedy objectives
MODES = ("log", "coverage", "concentrate")

def _probs(df):
    """conviction (measured tier x flag-count HR rate) if present, else hr_prob."""
    import pandas as pd
    if "ps_cell_prob" in df.columns:
        p = pd.to_numeric(df["ps_cell_prob"], errors="coerce") / 100.0
        if p.notna().sum() >= 5:
            return p
    return pd.to_numeric(df.get("hr_prob"), errors="coerce")

def _greedy(p, slips, objective, rng):
    n = len(p)
    if n < 2: return []
    O = (rng.random((NSIM, n)) < p[None, :])
    pairs = list(itertools.combinations(range(n), 2))
    A = np.array([a for a, b in pairs]); B = np.array([b for a, b in pairs])
    PW = O[:, A] & O[:, B]
    taken = np.zeros(len(pairs), dtype=bool); out = []
    if objective == "coverage":
        cur = np.zeros(NSIM, dtype=bool)
        for _ in range(slips):
            gain = ((~cur)[:, None] & PW).mean(axis=0); gain[taken] = -1.0
            k = int(np.argmax(gain))
            if gain[k] <= 0: break
            cur = cur | PW[:, k]; taken[k] = True; out.append(pairs[k])
    else:  # log growth
        PWf = PW.astype(np.float32); wins = np.zeros(NSIM, dtype=np.float32)
        for _ in range(slips):
            obj = np.log1p(wins[:, None] + PWf).mean(axis=0); obj[taken] = -1e9
            k = int(np.argmax(obj))
            if obj[k] <= -1e8: break
            wins = wins + PWf[:, k]; taken[k] = True; out.append(pairs[k])
    return out

def build_plan(df, mode="log", slips=10, pool=40, seed=None, order_col=None):
    """Return a list of (player_id_a, player_id_b) HR pairs, best-first.

    order_col is the user's HR PULL MODE column (hr_value / hr_rankpick / hr_confidence /
    hr_conviction). It decides WHICH BATS make the candidate pool and in what order.

    THIS SEPARATION IS THE WHOLE POINT. Pull mode = which bats. Build mode = how to pair them.
    The first version ignored order_col entirely and always ranked by ps_cell_prob, which meant
    that whenever a plan was active the pull mode silently did nothing -- the user could switch
    between Pecking Order, Confidence and Value and get identical slips.

    Note the pool ORDER and the portfolio PROBABILITIES are deliberately different columns.
    hr_value and hr_rankpick are scores, not probabilities -- feeding them to the Monte Carlo would
    produce nonsense -- so _p stays ps_cell_prob (or hr_prob) for the math while order_col decides
    membership.

    Guarded by design: any failure returns [] and the generator falls back to its normal draw.
    """
    try:
        import pandas as pd
        mode = str(mode).lower().strip()
        if mode not in MODES: mode = "log"
        p_all = _probs(df)
        if p_all is None or p_all.notna().sum() < 4: return []
        d = df.loc[p_all.notna()].copy()
        d["_p"] = p_all.loc[p_all.notna()].values
        if "player_id" not in d.columns: return []
        d = d.dropna(subset=["player_id"])
        _ord = None
        if order_col and order_col in d.columns:
            _ord = pd.to_numeric(d[order_col], errors="coerce")
        if _ord is not None and _ord.notna().sum() >= 4:
            d = d.assign(_ord=_ord).sort_values("_ord", ascending=False).head(int(pool))
        else:
            d = d.sort_values("_p", ascending=False).head(int(pool))
        if len(d) < 2: return []
        p = np.clip(d["_p"].to_numpy(dtype=float), 1e-4, 0.99)
        pid = d["player_id"].to_numpy()
        rng = np.random.default_rng(seed)
        if mode == "concentrate":
            k = 2
            while k < len(p) and (k * (k - 1)) // 2 < slips: k += 1
            idx = list(itertools.combinations(range(k), 2))[:slips]
        else:
            idx = _greedy(p, int(slips), mode, rng)
        return [(pid[a], pid[b]) for a, b in idx]
    except Exception:
        return []
