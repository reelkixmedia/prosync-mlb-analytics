# THE CORE DISSECTION — what actually makes this engine win more parlays

*2026-08-16 · grounded in the 49-night graded record, the ledger forensics, the model build, and two measurements run fresh for this question. No price, no EV — slips won is the only score.*

---

## The frame: where a parlay is actually won and lost

A slip is a product of 2-3 probabilities. That means the engine has exactly five places it can gain: the **probability of each leg** (calling), the **truth of the number attached to it** (pricing), the **way legs interact** (correlation), the **choice of which legs share a slip and which slips share a night** (assembly/portfolio), and the **decision of when the whole machine is trustworthy** (regime + feedback). Everything in the system is one of those five. Here is each one dissected, with what's measured, what's saturated, and what's still on the table — ranked at the end.

---

## 1. Calling — near the ceiling; stop mining here

The evidence is now overwhelming that per-bat calling is not where the next win lives. Your caller pool's top-5 hits 25.7% on the 49-night record; MODEL-X hits 22.4–25.3% out-of-fold; the strongest published public system posts 23.8% on its top-5 across 136,000 batter-games. Three independent systems — your hand-built callers, a cross-validated model, and the public state of the art — all converge on the same number, and your own daily audit says 92% of nights already had 3+ called winners on the board. When three different roads end at the same wall, the wall is real: single-bat HR prediction at ~2.2–2.5x base is where the information in pre-game data runs out.

What still worked here was **coverage, not rate**: the model's picks were 73% different bats from the callers at nearly the same rate, and the UNION held a homer on 88% of nights vs 67% for callers alone. The lesson generalizes — add *independent* selectors, not better versions of the same selector. But the marginal gain of a fourth selector is smaller than the third's. This layer is harvested.

**Verdict: maintain, don't mine.** New hand-crafted signals are now the lowest-yield work in the system.

## 2. Pricing — right idea, frozen in time

Measured-rate pricing was the single biggest honesty upgrade the engine got, but the prices are era-averages, and August proved eras end: 2hr collapsed from 13.7% to 6.9%/slip, STACK9 held 25.8%, ZONE-TOP10 dropped 10 points on quiet nights while STRIP held. The prices were right *on average* and wrong *tonight*. Every point of miscalibration compounds in a product — a 2-leg slip squares it.

**The upgrade: living calibration.** Every caller's price becomes a rolling re-measurement over the last ~20 graded nights (with the era-average as the shrinkage prior so thin windows don't whipsaw). Plus a drift alarm: any caller running 8-10 points under its price over its last 100 legs gets flagged in the console before it costs a month. This is mechanical, cheap, and it converts the August forensic — which took an audit to find — into something the engine notices in week one.

## 3. Correlation — measured tonight, and the answer redirects the whole theory

The classic parlay theory says: find positively correlated legs, stack them, and beat the product. I tested it on your record tonight — every same-game called pair across the 49 nights, joint hit rate against the product of their own empirical marginals:

HR+HR same team 0.92x · HR+HR opposite 1.05x · TB+TB same team 1.05x · TB+TB opposite 0.97x · HR+TB same team 0.98x · HR+TB opposite 0.89x — on 1,000-2,600 pairs per cell. **Flat. Game-level correlation on these props is ~zero.** Your own 08-14 no-correlation study was right, and it holds on the fuller record with called legs. Same-lineup stacking is not the lever; the one-per-game rule costs nothing and buys variance control. Close that door and stop paying it attention.

But correlation didn't disappear — it moved up a level. **The correlation that kills your parlays is night-level and league-wide: the regime.** In August the board homered 22% less, and every HR leg on every slip co-failed through that shared cause — 1hr1tb went 15.2% → 2.2%. That IS correlation, just not the kind you can stack; it's the kind you must *condition on*. Which is the next section.

## 4. Regime conditioning — the highest-leverage upgrade nobody's board does

The engine currently bets the same shape mix every night as if every night were the same game. The record says nights differ in ways that are **visible before first pitch**: slate-wide temperature and wind (your weather module — its suppression tail measured 0.68x), how many vulnerable starters the board carries, the league's rolling 7-day HR rate, how many bats the callers actually named, and whether a 3-called-winner ticket is even constructible (8% of nights it wasn't).

The upgrade is a **night card** computed before betting: a small set of pre-game regime reads that answers two questions. *What shape does tonight favor?* (quiet regime → TB-heavy, STRIP-ARM-led — it held 53.5% in August while everything else died; loud regime → the HR shapes earn their slots back). *Is tonight worth full size?* (a thin-board flag when callers name too few bats — pressing a bad board is how 0-14 nights happen at full volume). Nothing here is new data; it's columns and counts the system already produces, aggregated to the night level and allowed to steer the book's tier mix. On the 49-night record this is worth more than any single caller improvement, because it addresses the only correlation that's actually real.

## 5. Exposure — the biggest untapped LEG-level edge left

Every probability in the system is a per-GAME number, but a bat doesn't get "a game" — he gets 3, 4, or 5 plate appearances, and roughly 40% of them come against relievers the matchup engine never looks at. Two concrete holes:

**Plate-appearance volume is treated as a cutoff, not a multiplier.** The slot 8-9 guard was the crude version and it worked. The real version: a leg's probability scales with expected PAs (batting_order × expected game length — leadoff vs 7th is a ~25% exposure difference), continuously, on both props. For 1.5TB especially, PA count is close to half the battle.

**The bullpen is invisible.** mz_fit and every arm read models the starter; innings 6-9 are faced blind. You already built pen_mix_v2, pen_threat, pen_hr_per_pa — they sit on the board barely used. A bat's true night is a weighted blend: starter matchup × (share of PAs vs starter) + bullpen quality × (share vs pen). A great read on a starter who leaves after 4 innings is half the read the price assumes. Wiring exposure properly upgrades every leg a few honest points, and points compound in products.

## 6. Assembly and portfolio — good policy, immature optimizer

Strongest-with-strongest doubled slips won on the ledger replay; the tiered book solved breadth. What remains is that the book is built greedily, slip by slip, with no global pass: the swap optimization exists only in 3-slip mode, and the 12-20-slip day has no portfolio-level objective at all. The mature version treats the whole day as one decision: maximize expected slips-won (or P(≥k)) across the entire book subject to exposure caps — a hill-climb over the full 21-slip book is an afternoon of code and typically worth a point or two, which at your volume is real. Second piece: the book should rebuild on lineup confirmation automatically (scratched bats silently weaken served slips today; the SCRATCH concept belongs in the wire).

## 7. The feedback spine — the upgrade that protects all the others

Every finding this month was produced by manual forensics: the August decay, the display-vs-truth gap, the dead columns, the caller drift. The engine should run its own autopsy nightly: grade yesterday, update rolling caller rates, retrain MODEL-X weekly on the growing record, alarm on drift, and print a one-line verdict ("STACK9 holding · ZONE-TOP10 12 under price on last 60 — repricing · board thin tonight"). A system that measures itself compounds; a system that waits for audits decays between them. This is the difference between a good month and a good season.

---

## The ranked answer

If I could only change five things, in order of expected slips-won:

**1. Regime conditioning (the night card).** The only real correlation in the system is league-regime co-failure, and it's steerable before first pitch. Shape mix and size follow the night, not habit.

**2. Exposure modeling (PA volume as a multiplier + the bullpen blend).** The last few honest points available per leg, and they multiply through every product on every slip.

**3. Living calibration + drift alarms + weekly model retrain.** Prices that breathe with the season; an engine that catches its own August in week one.

**4. Portfolio-level book optimization + lineup-confirm rebuild.** Squeeze the assembly that's already the system's proven strength.

**5. Data plumbing.** Native opp_pitcher_id_true in the export, the dropped columns (gb/ld/pull) restored for the model, chunked statcast pulls so zone_overlap and surge never time out.

And three things I would explicitly NOT spend another hour on, because the record says they're spent: new hand-crafted HR signals (three systems converged at the same ceiling), game-level stacking (measured flat tonight, 0.89-1.05x), and variety mechanics (variety is now an assembly property, solved by the book).

The one-line theory: **calling is a solved commodity at ~2.3x base — everyone competent converges there. Parlays are won in the layers above it: betting the right shape on the right night, pricing legs at tonight's truth instead of the season's average, giving every leg its real plate-appearance exposure, and letting the machine grade itself. That's where this engine goes from good to the thing nobody else has.**
