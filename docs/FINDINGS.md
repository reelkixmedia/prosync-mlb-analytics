# The audit, run against your actual files

Not commands this time — answers. I pulled `app_now.py`, `slipforge.py` and
`graded_all.csv` off your machine and ran the whole package here.
**35 nights, 9,072 bat-nights, 2026-06-24 → 2026-08-03, plus 08-17.**
HR base 11.03%, 1.5TB base 32.46%, 1.5TB-no-homer base 23.54%.

---

## 1. SLG-FIT does not run your HR draw. It never has.

This is the answer to your first question, measured on `app_now.py` (19,072
lines, 280 NIKKO tags):

```
slgfit_arm    7 live mentions | 0 on an HR frame, 2 on a TB frame, 5 elsewhere
   L11940  [TB] tb_df_gen['slgfit_arm'] = pd.to_numeric(
   L12243  [TB] _sfa = pd.to_numeric(tb_df_gen.get('slgfit_arm'), ...)
   L17027  [--] (the drawer column list — display only)
slg_fit       1 live mention  | 0 on an HR frame
arm_slg_mix   1 live mention  | 0 on an HR frame

>> VERDICT: SLG-FIT IS COMPUTED, BUT ONLY ON THE TB FRAME.
```

It is built at L11928 by `_NKSF.arsenal_merge`, written to `tb_df_gen`, and read
once more at L12243 — all inside the total-bases generator. The HR pool
(`hr_df_pool`, 26 rebinds from L10395 to L13146) never sees the column. **That is
how a lever can call 16 of 19 homers on 08-17 and still not be the thing choosing
your HR legs.** It isn't selecting them. It's describing them, on the other
frame.

NK-FIVE, same question, counted on HR frames only:

```
iso_hand_mult        0 mentions on an HR frame
loc_fit              0 mentions on an HR frame
pitch_vuln_score     4
hr_arsenal_match     9
zone_overlap        14
a literal 4-of-5 NK-FIVE rule in the chain: NO
```

Two of the five gates are not readable on the HR frame at all, and the 4-of-5
rule is not there — only scattered score terms.

*One caution on my own instrument:* the first version of `hraudit` answered this
by line number and told me SLG-FIT **was** in the HR chain. It was wrong. The TB
generator sits physically between the first and last `hr_df_pool` rebind, so
`tb_df_gen` lines fall inside the HR line range. The shipped version checks which
dataframe each line actually touches and prints `[HR]` / `[TB]` per mention.

---

## 2. What actually wins slips

Exact combinatorics, walk-forward, then bootstrapped over nights. `p10` is the
10th percentile of the worst direction — what a bad stretch looks like.

**3-leg 1.5TB slips** (board at random: 3.44%)

| sort by | depth | fwd | rev | boot p10 |
|---|---|---|---|---|
| **hr_score** | 10 | 13.41% | 10.49% | **+3.37** |
| hr_spot | 10 | 11.06% | 12.47% | +3.07 |
| sleeper_score | 20 | 7.50% | 7.97% | +2.58 |
| mix_woba | 20 | 7.85% | 7.66% | +2.18 |
| contact_score | 40 | 6.54% | 6.58% | +1.68 |
| tb_score | 40 | 6.42% | 6.26% | +1.44 |

**2-leg HR slips** (board at random: 1.26%)

| sort by | depth | fwd | rev | boot p10 |
|---|---|---|---|---|
| **hr_spot** | 10 | 4.44% | 5.83% | **+1.53** |
| mix_woba | 10 | 4.85% | 5.93% | +1.43 |
| sleeper_score | 20 | 3.40% | 3.53% | +1.07 |
| hr_prob | 10 | 5.25% | 6.20% | +1.04 |

Two things worth sitting with.

**`hr_score` top 10 is the best 1.5TB sort on the board — 3.9x random.** That is
not a mistake: a homer clears 1.5 TB, and 27.5% of your cashing TB legs are
homers. But it is the same pool your HR leg draws from, so a slip built that way
is three bets on one idea. Your own comment at L10521 already measured this
("independence 1.12 / 0.86 / 0.60"). `contact_score` and `tb_score` at depth 40
survive at +1.68 / +1.44 and name genuinely different bats — that is the lane
that diversifies the slip.

**`hr_prob` survives at +1.04 but `hr_spot` beats it at +1.53.** The banned lever
isn't even the best one. Nothing to reverse.

---

## 3. The Arraez lane, measured

The 1.5TB-no-homer column, p70+ vs the rest, base 23.54%:

| read | no-HR rate | gap | z |
|---|---|---|---|
| **exp_pa** | 30.7% | +9.2 | 5.9 |
| contact_score | 28.1% | +6.6 | 6.0 |
| sleeper_score | 28.1% | +6.5 | 5.9 |
| tb_score | 27.9% | +6.2 | 5.7 |
| batting_avg | 27.5% | +5.6 | 4.6 |
| xba | 27.2% | +5.2 | 4.2 |

And from `rawaudit`, the TB verdicts: **`k_percent` reads INVERT** — top decile
16.6%, bottom decile 27.3%, monotonicity −0.82. Low strikeout rate is the read.
Meanwhile 50 columns read KILL for the no-homer prop, including `hr_score`,
`zone_overlap`, `hr_arsenal_match`, `loc_fit` and `ps_flag_count` — every one of
them a homer lever. The contact path to two bases is a different axis from the
power path, and the board is currently full of levers that only see the second
one.

**On `exp_pa`.** You said it reads nothing into homers, and the data agrees —
it's nowhere in the HR shortlist. But for the no-homer TB lane it is the single
strongest read on the board, +9.2pp with z=5.9 holding both halves. That makes
sense mechanically: an Arraez gets to two bases by getting more chances to
single, and plate appearances is the count of chances. It isn't a skill read, and
it should never touch the HR engine. Your call whether the TB engine gets it —
but that is the number.

---

## 4. The three-lane slip

| slip shape | won | A half | B half |
|---|---|---|---|
| board at random ×3 | 3.6% | 3.2% | 4.0% |
| **3 legs all from NK-FIVE 4-of-5** | **15.4%** | 15.1% | 15.7% |
| 3 legs all from Arraez profile | 6.8% | 6.6% | 6.9% |
| one from each lane | 6.0% | 5.9% | 6.1% |
| 3 legs all from xBA p75+ | 5.2% | 5.3% | 5.1% |

**NK-FIVE 4-of-5 is the best TB lane on your board — 4.3x random, halves 0.6
apart, on 13.9 bats a night.** Three legs from it beat one-from-each by more than
2x. So the honest answer to the three-lane idea is: it loses to just using
NK-FIVE three times. The lane overlap explains it — NK-FIVE shares only 14-19% of
its bats with the xBA and Arraez lanes, so mixing them swaps NK-FIVE bats for
weaker ones.

The irony is worth naming: **NK-FIVE — your eyeball rule — is the best total-bases
lane measured, and it is not wired into the HR pool where you built it for.**

*What I could not measure:* SLG-FIT. `slipforge._ars_load()` needs the Statcast
arsenal files in your WSL tree, which aren't on the Windows side. Every one of
these scripts builds SLG-FIT automatically when you run them in
`~/mlb_analytics` — the lanes and shortlists will re-rank with it included.

---

## 5. The 14 alignments — nothing is dead

Zero KILLs. All 13 buildable alignments beat base on both halves.

| alignment | bats/nt | HR rate | halves | z | verdict |
|---|---|---|---|---|---|
| **ZONE_VULN** | 3.6 | **31.2%** | 30.6 / 31.7 | 7.1 | KEEP |
| AIR_AIRARM | 5.4 | 23.9% | 24.1 / 23.8 | 5.5 | LOOSEN 0.16→0.20 (wider) |
| MIX_XSLG | 4.4 | 23.5% | 24.7 / 22.4 | 4.9 | KEEP |
| MATCHUP_VULN | 4.7 | 21.3% | 17.5 / 25.0 | 4.1 | KEEP |
| H1_POWER_ARS | 3.1 | 20.6% | 22.4 / 19.0 | 3.1 | KEEP |
| XWOBA_PEN | 4.3 | 19.7% | 20.0 / 19.5 | 3.4 | KEEP |
| FORM_WEAKARM | 4.7 | 19.4% | 19.2 / 19.5 | 3.4 | LOOSEN (wider) |
| POWER_HRARM | 4.5 | 18.9% | 20.5 / 17.3 | 3.1 | LOOSEN 0.13→0.30 |
| BARREL_HARD | 5.9 | 18.4% | 17.6 / 19.2 | 3.3 | KEEP |
| SLEEPER_GB | 4.2 | 18.2% | 20.0 / 16.9 | 2.8 | KEEP — **bat only** |
| HOT_RUNS | 4.6 | 18.0% | 20.6 / 13.6 | 2.8 | LOOSEN 0.20→0.25 |
| CONTACT_LOWK | 4.5 | 15.8% | 14.3 / 17.3 | 1.9 | LOOSEN (wider) |
| MIXSP_NETLEAN | 4.2 | 14.3% | 14.5 / 14.1 | 1.2 | LOOSEN — **bat only** |

**ZONE_VULN at 31.2% on 3.6 bats a night is the sharpest single thing on your
board**, and it's a genuine pair — bat side alone 22.0%, arm side alone 16.9%,
together 31.2%.

Two are bat-only: SLEEPER_GB (18.0% bat / 11.9% arm / 18.2% pair) and
MIXSP_NETLEAN (19.7% / 9.2% / 14.3% — the arm half actively *costs* you there).

The count columns all confirm agreement is real and monotone — `chalk_n ≥ 4`
reads 30.8% on 1.5 bats a night — but all three are **tie-flooded**:
`rank(min) ≤ 150` returns all 259 bats. They gate. They cannot rank at depth.
Anything that sorts by them with `method='min'` is sorting by nothing.

---

## 6. Two patchers, and one of them you don't need

**`armfix.py` — already done. Skip it.** Your `app_now.py` L2578 already carries
`*(1-_sh)`, tagged `NIKKO-SPINEFIX`. The script now detects this and says so
instead of failing on a missing anchor. I found this bug against an older copy;
you'd already fixed it.

**`alcut.py` — retagged.** Its tag was `NIKKO-ALCUT`, and your file already
carries `NIKKO-ALCUTS` (21 hits, your 45-night chip-table retune). `NIKKO-ALCUT`
is a substring of it, so the guard would have aborted forever. Tag is now
`NIKKO-ALGATE`, verified absent from your file. **But hold off** — with zero
KILLs, all it would do is apply the six cut changes, and three of those are
*wider at a lower rate*. Read section 2 of `alignaudit.py` and decide per
alignment; it now marks those `WIDER (lower rate)`.

**Still live and worth a look:** `NIKKO-PLATOONFIX` is not installed, and
`app_now.py` L10481 still runs `hr_df_pool = hr_df[hr_df['platoon_mult'] >=
0.98]`. That veto cuts ~43% of the board for the +0.2pp we measured.

---

## The short version

1. SLG-FIT and NK-FIVE both live on the TB frame. Wiring either into
   `hr_df_pool` is the highest-value change available.
2. NK-FIVE 4-of-5 is your best TB lane at 15.4% of 3-leg slips. Three legs from
   it beats mixing lanes.
3. Sort HR by `hr_spot` top 10 (+1.53 p10). Sort TB by `hr_score` top 10 if you
   accept the correlation with your HR leg, `contact_score` top 40 if you want
   the slip diversified.
4. The Arraez lane is real and it is a different axis: `exp_pa`,
   `contact_score`, low `k_percent`. The homer levers read KILL on it.
5. Nothing in `_AL14` is dead. Six cuts are misconfigured; three of the six trade
   rate for coverage, so read before you apply.
6. The three count columns gate, they never rank. Fix any `method='min'` sort.
