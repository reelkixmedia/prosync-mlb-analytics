#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prosync_assemble.py -- the assembler. Drop-in for prosync_plan.build_plan.

Written by wirepatch.py. Imported by app.py at the NIKKO-ASSEMBLE-WIRE tag,
on the 'Top bats' branch, which until now planned NOTHING -- `_mode` came out
None, `_gen_hr_plan` came out [], and every slip was built by a sharpened
random draw with a diversity penalty. There was no assembler.

THE OBJECTIVE, AND WHY IT IS NOT E[wins]
----------------------------------------
Writing X for the number of winning tickets,

    E[X] = P(X>=1) + P(X>=2) + P(X>=3) + ...

so maximising E[X] lets the optimiser dump mass into the 3-plus-simultaneous
-winners layer nobody cares about. On a reference simulation the max-E[X]
portfolio put 61% of its expected-count budget there and was beaten on BOTH
P(>=1) and P(>=2) by a portfolio with a LOWER E[X]. Ranking tickets by the
product of their legs and taking the top N is the same mistake in a cheaper
form: it produces N near-identical tickets off the same three bats.

  1  P(>=1) is SUBMODULAR over the set of tickets. For S subset T and a new
     ticket e, the marginal is P(e wins AND none of the chosen do), and the
     chosen set only grows, so the marginal only shrinks. No independence is
     assumed anywhere in that argument -- it holds under leg reuse. So greedy
     carries the standard 1 - 1/e guarantee.
  2  P(>=2) is NOT submodular: the first ticket has zero marginal, so greedy
     on it has no guarantee and in practice collapses onto duplicates.
  3  So: SEED greedy on P(>=1), then REPAIR with swap local search on
     P(>=1) + lam*P(>=2).
  4  EXPOSURE CAP. No bat on more than about a quarter of the tickets. There is
     a clean interior optimum: too few and you are forced down the ranking, too
     many and the tickets die together.
  5  OVERLAP CAP. No two tickets share more than legs-1 legs.

Sources: Nemhauser-Wolsey-Fisher; Hunter, Vielma & Zaman, "Picking Winners in
Daily Fantasy Sports Using Integer Programming"; Liu & Teo, POM 32 (2023).

RETURN CONTRACT
    build_plan(...) -> list of lists of player_id, one list per slip.
    app.py pops one id per HR leg off the front of each list. Extra ids are
    harmless; a short list just means the draw fills the rest, which is the
    same behaviour as today.

It never raises. On any failure it returns [] and app.py takes the old path.
"""

import itertools

import numpy as np
import pandas as pd

VERSION = "prosync_assemble v1 -- greedy on P(>=1), repair on P(>=1)+lam*P(>=2)"


def _num(d, c):
    if c in d.columns:
        return pd.to_numeric(d[c], errors="coerce")
    return pd.Series(np.nan, index=d.index, dtype="float64")


def leg_p(d, order_col, base=None, lo=0.03, hi=0.42):
    """A probability per bat. If the board carries a calibrated hr_prob, use it.
    Otherwise map the ORDER COLUMN's within-board rank onto a decaying curve
    anchored on the board's own base rate. The assembler only needs a MONOTONE
    and roughly-scaled p -- every comparison it makes is between tickets drawn
    from this same pool -- but the scale still matters for the P(>=2) term, so
    it is anchored rather than invented."""
    p = _num(d, "hr_prob")
    if p.notna().mean() >= 0.6 and float(p.max()) <= 1.0 and float(p.min()) >= 0.0:
        v = p.clip(lo, hi)
        if v.notna().mean() >= 0.6:
            return v.fillna(lo).to_numpy()
    s = _num(d, order_col)
    if s.notna().mean() < 0.5:
        for c in ("hr_value", "hr_score", "nk_hr_pick"):
            s = _num(d, c)
            if s.notna().mean() >= 0.5:
                break
    r = s.rank(pct=True, ascending=False).fillna(1.0).to_numpy()   # 0 = best
    b = float(base) if base else 0.10
    # exponential decay through the board, normalised so the MEAN equals the base
    curve = np.exp(-3.2 * r)
    curve = curve * (b / max(curve.mean(), 1e-9))
    return np.clip(curve, lo, hi)


def _tq(t, p):
    q = 1.0
    for i in t:
        q *= p[i]
    return q


def _portfolio(tickets, p, trials=6000, seed=11):
    if not tickets:
        return 0.0, 0.0
    keys = sorted(set(i for t in tickets for i in t))
    kx = dict((k, j) for j, k in enumerate(keys))
    P = np.array([p[k] for k in keys])
    rng = np.random.default_rng(seed)
    O = rng.random((trials, len(keys))) < P[None, :]
    wins = np.zeros(trials, dtype=np.int32)
    for t in tickets:
        cols = [kx[i] for i in t]
        wins += O[:, cols].all(axis=1).astype(np.int32)
    return float((wins >= 1).mean()), float((wins >= 2).mean())


def _candidates(idx, p, legs, game, same_game="allow", topn=22, keep=1200):
    poolx = sorted(idx, key=lambda i: -p[i])[:topn]
    out = []
    for comb in itertools.combinations(poolx, legs):
        if game is not None:
            g = [game[i] for i in comb]
            if same_game == "never" and len(set(g)) < len(g):
                continue
            if same_game == "only" and len(set(g)) == len(g):
                continue
        out.append(tuple(comb))
    out.sort(key=lambda t: -_tq(t, p))
    return out[:keep]


def assemble(cands, p, N, cap, overlap, lam=1.0, rounds=2, scan=400):
    if not cands:
        return []
    q = np.array([_tq(t, p) for t in cands])
    order = list(np.argsort(-q))
    chosen, used = [], {}

    def ok(t):
        for i in t:
            if used.get(i, 0) + 1 > cap:
                return False
        for c in chosen:
            if len(set(c) & set(t)) > overlap:
                return False
        return True

    for _ in range(N):
        best, bestv = None, -1.0
        for pass_no in (0, 1):
            look = order[:scan] if pass_no == 0 else order
            if pass_no == 1 and best is not None:
                break
            for j in look:
                t = cands[j]
                if not ok(t):
                    continue
                # marginal gain in P(>=1), exact under leg independence:
                # condition on t's legs all winning, then require every already
                # chosen ticket to fail.
                g = q[j]
                for c in chosen:
                    sh = set(c) & set(t)
                    qc = 1.0
                    for i in c:
                        qc *= 1.0 if i in sh else p[i]
                    g *= (1.0 - qc)
                if g > bestv:
                    best, bestv = j, g
        if best is None:
            break
        t = cands[best]
        chosen.append(t)
        for i in t:
            used[i] = used.get(i, 0) + 1
    if len(chosen) < 2:
        return chosen

    def obj(sel):
        a, b = _portfolio(sel, p, trials=4000)
        return a + lam * b

    cur = obj(chosen)
    for _ in range(rounds):
        improved = False
        for slot in range(len(chosen)):
            base = [c for k, c in enumerate(chosen) if k != slot]
            bu = {}
            for c in base:
                for i in c:
                    bu[i] = bu.get(i, 0) + 1
            for j in order[:scan]:
                t = cands[j]
                if t in base:
                    continue
                if any(bu.get(i, 0) + 1 > cap for i in t):
                    continue
                if any(len(set(c) & set(t)) > overlap for c in base):
                    continue
                trial = base + [t]
                v = obj(trial)
                if v > cur + 1e-5:
                    chosen, cur, improved = trial, v, True
                    break
            if improved:
                break
        if not improved:
            break
    return chosen


def _game_key(d):
    for a, b in (("team_abbrev", "opponent"), ("team", "opponent"),
                 ("team_abbrev", "opp"), ("team", "opp")):
        if a in d.columns and b in d.columns:
            x = d[a].astype(str)
            y = d[b].astype(str)
            return ["|".join(sorted((u, v))) for u, v in zip(x, y)]
    for c in ("game_id", "gamePk", "game"):
        if c in d.columns:
            return d[c].astype(str).tolist()
    return None


def build_plan(df, mode="greedy_repair", slips=12, pool=40, order_col="hr_value",
               legs=2, cap=None, overlap=None, lam=1.0, same_game="allow",
               base=None, verbose=False):
    """Returns list-of-lists of player_id, one per slip. [] on any failure."""
    try:
        if df is None or len(df) == 0 or "player_id" not in df.columns:
            return []
        d = df.copy().reset_index(drop=True)
        oc = order_col if order_col in d.columns else None
        if oc is None:
            for c in ("hr_al14_rank", "nk_hr_pick", "hr_value", "hr_score"):
                if c in d.columns:
                    oc = c
                    break
        if oc is None:
            return []
        d = d.sort_values(oc, ascending=False).head(int(pool)).reset_index(drop=True)
        if len(d) < legs + 1:
            return []
        p = leg_p(d, oc, base=base)
        game = _game_key(d)
        N = max(int(slips), 1)
        cap = int(cap) if cap else max(2, int(round(0.25 * N)))
        overlap = int(overlap) if overlap is not None else max(legs - 1, 0)
        cands = _candidates(list(range(len(d))), p, legs, game, same_game=same_game)
        tickets = assemble(cands, p, N, cap, overlap, lam=lam)
        if not tickets:
            return []
        pid = d["player_id"].tolist()
        out = [[int(pid[i]) for i in t] for t in tickets]
        while len(out) < N:
            out.append([])
        if verbose:
            a, b = _portfolio(tickets, p)
            print("[assemble] %d tickets, cap %d, overlap %d, P(>=1) %.3f P(>=2) %.3f"
                  % (len(tickets), cap, overlap, a, b))
        return out[:N]
    except Exception:
        return []
