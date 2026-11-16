# Seeing a Home Run Before It Happens
## Deep audit — the literature, the physics, and what it says about this engine

Compiled 2026-08-03. Four parallel research streams: batted-ball physics, statistic
reliability, park geometry, and published prediction models. Every number is sourced.
Where sources disagree I say so.

---

## 0. The three findings that change what we are building

**1. The ceiling is far lower than it feels, and it is published.**

The best documented per-plate-appearance HR model — Singlearity-PA, an 87-feature
neural network trained on **1.72 million plate appearances** — beats a *league-average
constant* by **3.3% in cross-entropy**. That is the number. Not 30%, not 300%. Anything
claiming materially more should be assumed to be leaking until proven otherwise.

This reframes every result in this session. `hr_prob` producing 19.6% at 20 bats a night
against an 11.5% pool is, in that light, a real and substantial edge — not a failure.

**2. The odds-ratio / log5 construction actively fails for home runs.**

Morey & Cohen (*Journal of Sports Analytics*, 2015) tested log5 on 18 MLB seasons.
Bias effect size for batting average: d = 2.54. **For home run percentage: d = 17.55.**
log5 **overpredicted subsequent matchup HR performance in 18 of 18 seasons.**

Independently, on 1.72M PA:

| HR cross-entropy | value |
|---|---|
| league-average constant | 0.05627 |
| **log5 / odds ratio** | **0.05867** ← *worse than doing nothing* |
| Singlearity-PA | 0.05439 |

The defect: log5 regresses outliers toward **.500**, not toward the league mean. When
the league mean is 0.03, that is catastrophic. If any part of the engine multiplies a
batter rate by a pitcher rate and divides by league, it is adding error.

**3. The batter side dominates the pitcher side by 2.6× to 4×** — four independent methods.

| method | batter | pitcher | ratio |
|---|---|---|---|
| stabilization (to reliability) | HR rate 170 PA | HR rate 1,320 BF | 7.8× more data needed on the arm |
| logistic random-effects SD | σ = 0.523 | σ = 0.188 | 2.78× |
| Poisson GLMM coefficient | 1.0127 | 0.3841 | 2.64× |
| Q1→Q4 HR/air-ball spread | 7.70% → 15.68% | 10.92% → 12.90% | 4.0× |

Clemens, FanGraphs 2020, plainly: *"Batters didn't really hit more home runs in 2019
against pitchers who were more homer-prone in 2018."*

We spent this session building arsenal matching, pitch clouds, staff blending and zone
surfaces — all on the side of the matchup carrying roughly a quarter of the signal.

---

## 1. The master conversion: everything is feet of carry

> **≈ 3% change in HR rate per foot of carry.** (Nathan: 5 ft → 15%; 8.5 ft → 25%)

At 105 mph / 28°, sea level, 72°F:

| input | Δ carry | Δ HR rate |
|---|---|---|
| +1 mph exit velocity | **+4.4 ft** | **+13%** |
| +1° launch angle at LA 18° | +5.1 ft | +15% |
| +1° launch angle at the optimum (~29°) | ~0 | ~0 |
| +1° launch angle at LA 40° | −4.1 ft | −12% |
| **+1 mph effective tailwind** | **+3.9 ft** | **+12%** |
| +1 mph effective headwind | −4.5 ft | −13% |
| +1 °F | +0.31 ft | **+0.95%** |
| +1,000 ft elevation | +5.7 ft | +17% |
| **30° of spin-axis tilt (sidespin)** | **−8.7 ft** | **−26%** |
| +0.01 drag coefficient | −4.8 ft | −14% |

The check that validates the framework: 0.31 ft/°F × 3%/ft = **0.94%/°F**, against
independently measured **0.90–1.09%/°F** from three separate regressions (Nathan 0.96,
Albert 0.90, Callahan et al. *BAMS* 2023 at 1.09). The physics and the regressions close
on each other.

**Optimal launch angle falls as exit velocity rises:**

    optimal LA ≈ 29.1° − 0.145 × (EV − 100)

And the HR *window* — degrees of launch angle that clear a 380 ft fence:

| EV | LA window |
|---|---|
| 100 | 29.0–30.5° (**1.5°**) |
| 105 | 19.5–39.5° (20°) |
| 110 | 15.5–43.5° (28°) |
| 115 | 12.5–45.5° (33°) |

Exit velocity is not one input among many. It buys *tolerance*.

---

## 2. The biggest thing missing from this engine: spray angle

**At fixed exit velocity and launch angle, spray angle explains 58% of the variance in
fly-ball distance** (Nathan 2020, Tropicana only so the atmosphere is constant):

| factor | σ (ft) | share of variance |
|---|---|---|
| **adjusted spray angle** | **12.7** | **58%** |
| ball-to-ball drag | 6.1 | 13% |
| backspin | 5.5 | 11% |
| sidespin | 5.1 | 9% |
| measurement noise | 5.4 | 9% |

The mechanism is sidespin. An opposite-field ball carries slice, tilting the Magnus
vector sideways instead of up — 30° of tilt costs 8.7 ft, 50° costs 24.8 ft. Distance is
maximised **slightly to the pull side of dead center**.

| batted ball | HR rate |
|---|---|
| all batted balls | 4.2% |
| all fly balls | 14.5% |
| **pulled fly balls** | **37.3%** |
| center-field fly balls | 9.2% |
| **opposite-field fly balls** | **4.6%** |
| barrels | 43.1% |
| **pulled barrels** | **65.4%** |

On 95–105 mph fly balls — wOBA: **pulled .812**, straightaway .079, opposite .289.

**It is a stable skill.** Year-over-year r² = 0.316; against a multi-year baseline
**r² = 0.624**. League average pull rate on 95–105 mph flies ≈ 32%; Paredes has run 65.1%.

**Three warnings:**

- **xwOBAcon is blind to spray and mis-prices it.** Pulled fly balls beat their xwOBAcon
  by **+.263**. Every xISO/xSLG surface built this session inherits that bias.
- **Pull and lift are antagonistic.** ~0.09–0.1 mph of EV lost per degree away from pure
  pull, and pull-side contact produces *lower* launch angles. Not independent features.
- **Breaking balls generate 3–4× the pulled-fly-ball rate of sinkers** (2023: sweeper
  12.1%, slider 9.1%, curve 8.5%, sinker 3.3%). The one *pitcher* feature feeding the
  largest *batter* effect — and it is a usage number, so it is stable.

---

## 3. Why our recency work came back empty — the research agrees

**The measurement problem.** HR/PA has a stabilization constant of **170 PA**. A 10-day
window (~40 PA) is **19% reliability**. Worse, the quantization step exceeds the signal.
At a league-average 3.5% HR/PA over 40 PA, a perfectly average hitter:

| HR in 40 PA | probability | implied "rate" |
|---|---|---|
| 0 | 24.1% | 0.0% |
| 1 | 34.9% | 2.5% |
| 2 | 24.7% | 5.0% |
| 3 | 11.3% | 7.5% |

He goes homerless a quarter of the time and posts 7.5%+ sixteen percent of the time. The
instrument resolves in 2.5-point steps against a true-talent spread of about ±1.7.
**The tick marks are bigger than the thing being measured.**

**Reliability of a 10-day window:**

| signal | events in ~40 PA | constant | reliability |
|---|---|---|---|
| **bat speed** | 92 swings | 3 swings | **97%** |
| chase rate | 156 pitches | 55 pitches | 74% |
| contact% | 92 swings | 40 swings | 70% |
| exit velocity / hard-hit% | 27 BBE | ~40 BBE | 40% |
| barrel% | 27 BBE | ~50 BBE | 35% |
| **HR/PA** | **1.4 HR** | **170 PA** | **19%** |
| ISO | 36 AB | 160 AB | 18% |

**Independent replications of our null:**

- Razzball 2015, 7,169 three-game and 10,236 five-game instances: recent form improved
  HR projection accuracy by **0.0% to 0.2%**. HR correlation with prior three games: 4.7%.
- BYU 2025 Bayesian matchup model: a 40/30/20/10 recency window bought **0.001 nats**.
- FanGraphs 2025, 127,216 twenty-game stretch pairs, corrected for the same-season
  baseline artifact: the entire hot-hand effect is **~3 points of wOBA**.

**The useful reframe.** The residual value in a hot streak is mostly *information about
true talent the prior didn't have* — a swing change, an injury, an aging inflection —
not a transient state. The fix is not a better hotness feature; it is a **faster-updating
true-talent estimate**. Bat speed is exactly that: 3-swing stabilization, ~92 swings per
10 days, 97% reliability, and measured on whiffs too, so mechanical change shows up
weeks before barrel rate or ISO moves.

**A free win at our window length:** at small samples the best summary of a hitter's
exit-velocity distribution is **not the mean**. Andrews (FanGraphs 2023): 300+ BIP use
"best speed"; 100+ use EV81; **at 30–110 BIP use EV96** — the 96th percentile. Mean EV
over 27 batted balls has a standard error of 2.7 mph against a league true-talent spread
of 2.5–3.0. It is a coin flip.

---

## 4. The pitcher side: most of what we model is noise

| pitcher metric | year-over-year r | stabilization |
|---|---|---|
| **launch angle allowed** | **0.80** | — |
| avg fly-ball distance allowed | 0.55 (with HR/FB) | — |
| barrel% allowed | 0.42 (with HR/FB) | 131 BBE |
| EV on flies/liners allowed | 0.32 | — |
| **HR/FB** | **0.06** | 400 FB |
| HR rate | — | 1,320 BF |

**Pitcher HR/FB has a year-to-year correlation of 0.06.** This is why xFIP exists — it
discards a pitcher's actual home runs and substitutes *fly balls × league HR/FB*.

**Barrel rate allowed must be regressed ~9× harder than a hitter's** (pitcher S ≈ 131 BBE
vs hitter S ≈ 15 BBE).

**Not significant for pitcher HR/FB** (Wolfersberger 2011, model R² = 0.10): FB%, GB%,
LD%, swing rates, in-zone contact%, first-strike%. Only K/9 (−), BB/9 (+), O-Contact% (−),
IFFB% (−), fastball velocity (−) and park survive.

**Implication:** `p_hr_per_9`, `p_brl_allowed` and `worst_pitch_xslg` are outcome measures
on the unstable side. The stable substitutes are **launch angle allowed**, **fly-ball
distance allowed**, and **pitch usage**.

---

## 5. Park: sector geometry, not a park factor number

**The Camden Yards natural experiment** — same city, same air, same roster, one wall
moved, twice, in opposite directions:

| window | RHB HR park factor | rank |
|---|---|---|
| 2019–2021 (old wall) | **131** | 2nd highest in MLB |
| 2022–2024 (wall back 26½ ft, up 6 ft) | **79** | 4th lowest in MLB |

**A 52-point swing from one sector's geometry** — the same magnitude as the *entire*
league-wide handedness spread. The LHB effect was 6–8× smaller (110 → 106), exactly what
the pulled-fly-ball asymmetry predicts. Losses 2022–24: Mountcastle 11, Hays 8, Mateo 7
(all right-handed); lefties O'Hearn 3, Henderson 2, Cowser 1.

**Handedness-split spread** (FanGraphs 5-year regressed, off the halved scale): LHB
0.76×–1.34×; RHB 0.80×–1.28×.

**Park factors need heavy regression even at three years** — Birnbaum: **~34%** toward
league average (empirically 38%, range 28–49%). One month of 2025 put Camden at 187; its
full season was 121; regressed, 106.

**Wall height converts to distance at the cotangent of the descent angle:**

| descent angle | ball type | ft of distance per ft of wall |
|---|---|---|
| 20° | hard line drive | **2.75** |
| 25° | low line-drive HR | 2.14 |
| 45° | typical fly | 1.00 |
| 55° | high fly | 0.70 |

Confirmed at Coors 2016: of the balls the raised fence stopped, **14 were low drives and
3 were high flies**. A fence is ~5× more likely to stop a hard-hit drive. So wall height
taxes exactly the low-launch pull hitters the spray finding identifies.

**Wind is park-specific by a factor of 50.** 10 mph blowing out is **+50% HR at Wrigley**
and **+1% at Oracle**. The effective wind on a given ball is:

    effective_wind = wind_speed × cos(θ)

θ = angle between wind direction and spray direction. A 10 mph crosswind creates a
**42-foot spread** across the outfield. A scalar "wind out/in" throws away most of it.

**The most valuable data line in this document.** Baseball Savant exposes a per-home-run
endpoint with a **30-park binary matrix** — for every near-HR batted ball, whether it
would have left in each park:

    https://baseballsavant.mlb.com/leaderboard/home-runs?type=details&player_type=Batter&year=2026&player_id=<id>&csv=true

Fields include `exit_velocity, launch_angle, hr_distance`, one column per park
(`laa, bal, bos, cws, ...`), and `hr_cat` ∈ {Doubter, Mostly Gone, No Doubter}.
MLB-authoritative distance-and-height-by-angle, free, at exactly the HR boundary. It can
be inverted to recover sector geometry without digitising a single park.

---

## 6. What is documented not to work

| # | thing | finding |
|---|---|---|
| 1 | **log5 / odds ratio on HR** | bias d = 17.55; overpredicted 18/18 seasons; log loss *worse* than a constant |
| 2 | **batter-vs-pitcher head-to-head** | 1,500 PA vs all pitchers beats 25 PA vs the specific arm. Even 60 targeted PA fails to outweigh 1,500 random |
| 3 | **hot/cold streaks** | 0.0–0.2% improvement; 4.7% correlation; 0.001 nats |
| 4 | **times-through-order for HR** | +0.003 per pass, credible interval covers zero |
| 5 | **pitcher HR/FB as skill** | R² = 0.10; y/y r = 0.06; needs 1,320 BF |
| 6 | **pitcher batted-ball profile** | FB%, GB%, LD%, swing rates, in-zone contact all *not significant* |
| 7 | **individual platoon splits** | need 2,000 PA vs LHP (RHB) / 1,000 (LHB) / 600 (switch). Nobody clears it in-season |
| 8 | **"beats his xHR" as a skill** | first-half error → second-half error r² = 0.08 |
| 9 | **single-season park factors** | 2025 raw range 58 to 187 |
| 10 | **squared-up rate as power** | correlation with HR/FB = **0.000**. It is a strikeout-avoidance stat — Arráez leads the league |
| 11 | **accuracy / precision as HR metrics** | at a 3% per-PA base rate, "always predict no" beats most published classifiers. Use log loss, Brier, calibration |
| 12 | **day/night splits, revenge spots** | no credible quantitative support found anywhere |

Item 7 vindicates killing the Platoon flag. Item 10 means any bat-tracking feature must
use **blast** (r = 0.528 with HR/FB), never squared-up.

---

## 7. What this engine's own data has established

On 36 nights and 8,379 bat-nights:

- **`hr_prob` is not a power list.** Against season xISO on ~192 batted balls — a
  low-noise power benchmark — it gains **+0.038 in-tier AUC (p = 0.002)** and **+4.7
  points in the deep band (p = 0.007)**. Nothing else tested did either.
- **Its ranking keeps working past where the board stops reading it.** Among bats it
  ranked 51st and worse, its own ordering still separates homers at **15.9% vs 11.2%**,
  and **65% of all homers are in that band.** The signal does not stop at rank 50; the
  engine does.
- **Coverage is the real weakness** — 106 distinct names over 36 nights, 85% repeats.
- **Pitch-type matching is dead** — 32% vs a 30% re-pairing null on 467 homers;
  leave-one-out proved the old 52% was the answer key.
- **Zone damage survived** at ~4σ, but the full location-surface build did not beat power
  once power was divided out.
- **Every recency window failed**, consistent with the literature above.

---

## 8. Build order, in expected-value sequence

**1. Use the whole ranking.** `hr_prob` orders bats correctly to at least rank ~200 and
the board discards everything past 50. Free — no new data, no new model.

**2. Spray angle.** 58% of distance variance, 8× HR rate pulled vs oppo, stable skill
(r² = 0.62). Build pulled-air-ball rate per hitter, point-in-time, plus the arm's
breaking-ball usage that feeds it.

**3. Sector park geometry × handedness**, from the Savant 30-park matrix rather than
digitised outlines.

**4. Wind as a vector with `cos(θ)` to the hitter's pull field, with a per-park gain.**

**5. Replace pitcher outcome stats with stable ones** — launch angle allowed (y/y 0.80),
fly-ball distance allowed, pitch usage. Regress the arm's barrel rate ~9× harder.

**6. EV96 instead of mean EV** at our window lengths; bat speed as the fast-updating
state variable.

**7. Delete any odds-ratio combination of batter × pitcher HR rates.** If a normalised
form is wanted, use Haechrel's n-outcome normalisation (SABR *BRJ* 2014, validated on
44,209 PA at χ² p = 0.95), never the two-outcome ratio.

**Calibration target.** Per-game HR probability is ~11–12% for a regular with 4.1 PA and
**28–35% for elite bats**. Our best selector reaches 19.6%. The gap between 19.6% and the
high-20s is the honest headroom — and by the published ceiling, most of it is in
*identifying* the elite spot, not in discovering a hidden bat.

---

## Principal sources

Nathan, *The Physics of Baseball* (baseball.physics.illinois.edu) — trajectory
calculator, drag/lift coefficients, seam height, humidor, temperature ·
Nathan, *Contributions to Variation in Fly Ball Distances*, FanGraphs 2020 ·
Callahan, Dominy, DeSilva & Mankin, *Global Warming, Home Runs, and the Future of
America's Pastime*, **BAMS** 104(5), 2023 ·
Carleton, *It's a Small Sample Size After All*, Baseball Prospectus, via the FanGraphs
Sabermetrics Library · Tango, regression constants and the odds-ratio method ·
Morey & Cohen, *Bias in the log5 estimation of batter/pitcher matchups*, **J. Sports
Analytics** 1(1), 2015 · Haechrel, *Matchup Probabilities in Major League Baseball*,
**SABR BRJ** Fall 2014 · Brill, Deshpande & Wyner, TTO penalty, **JQAS** 2023 ·
Green & Zwiebel, *The Hot-Hand Fallacy*, **Management Science** 64(11), 2018 ·
Miller & Sanjurjo, **Econometrica** 86(6), 2018 ·
Clemens, *An Overdue Barrel Rate Refresher* and *Fly Ball Pull Rate*, FanGraphs ·
Andrews, *The Doomed Search for a Perfect Way To Interpret Exit Velocity Data*,
FanGraphs 2023 · Wolfersberger, *What Factors Affect HR/FB Rate?*, FanGraphs 2011 ·
Birnbaum, *Regressing Park Factors*, 2020 · Petriello, Camden Yards 2022 and Statcast
park factors, MLB.com · Kagan, Coors fence, Wrigley wind, park orientation, The Hardball
Times · Baseball Savant home-run and park-factor leaderboards.
