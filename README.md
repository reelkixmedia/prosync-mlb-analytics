# Pro-Sync Prop Engine: MLB home-run and total-bases prediction

A daily sports-analytics pipeline and Streamlit app that ranks every MLB batter on
the slate by his chance of homering, or of reaching 1.5+ total bases, in that night's
game. The next morning it grades its own picks against the box scores. The
interesting part is less the app than the loop around it. The pipeline joins public
Statcast, MLB Stats API, weather and odds data into a feature board of about 300
columns per batter per night. It scores the board, saves a snapshot, grades the
snapshot after the games, and re-measures each signal and the probability calibration
against the growing record of graded nights.

Built by **Nikko Echevarria** with AI-assisted development (Claude Code), over the
2026 MLB season.

---

## What it does

- **Builds a nightly board.** Each batter in tonight's lineups is matched with the
  opposing starter, the bullpen, the park and the forecast weather.
- **Scores two outcomes.** `hr_score` / `hr_prob` estimate the chance of a home run;
  `tb_score` and contact lanes target 1.5+ total bases, which is mostly a different
  axis (contact and plate appearances rather than power).
- **Shows its reasoning.** A custom HTML board (`board_html.py`) lists the signals
  behind each ranked bat: arsenal match, zone fit, barrel floor, park/weather and
  calibration band.
- **Grades itself.** Each morning, scripts label last night's board with actual
  outcomes (`graded_full_YYYY-MM-DD.csv`). They re-fit the probability calibration
  and run hit-rate audits on every signal, with split-half and null checks.

## Data sources (all public)

| Source | Used for |
|---|---|
| MLB Stats API (`statsapi.mlb.com`) | schedule, probable pitchers, confirmed lineups, rosters, season stats |
| Baseball Savant / Statcast CSVs | batter x pitch-type splits, pitch usage and per-pitch quality, barrel %, EV, launch angle, bat speed, spray |
| Open-Meteo (`ballpark_weather.py`) | game-time temperature and wind at each park, converted to an HR environment multiplier |
| the-odds-api.com | game totals, used to derive team implied runs as a game-environment feature |

## How the scoring works

**Arsenal match (two-sided pitch fit).** For each batter, `build_pitch_vulnerability`
takes his expected slugging against each pitch type and weights it by how often
tonight's starter throws that pitch. It then adjusts for how good *this* pitcher's
version of that pitch is, measured as SLG and whiff rate allowed relative to the
league baseline. Minimum samples (25 PA batter / 20 PA pitcher per pitch) keep thin
splits out. Starter and bullpen mixes are computed separately (`hr_arsenal_match_sp`,
`hr_arsenal_match_pen`).

**Barrel gating.** Power skill is a multiplicative floor rather than an additive term:
`hr_barrel_floor = clip((barrel% - 6.5) / 2.5, 0.08, 1.0)`. A bat without real barrel
skill can't reach the top of the board on matchup alone. Missing barrel data is
handled explicitly rather than treated as zero.

**Composite.** `hr_raw` blends batter skill (0.30), matchup (0.48), environment (0.10)
and the pitch-fit term. It is scaled by data completeness and a whiff penalty, then
gated by the barrel floor. Park factors and the weather multiplier enter the
environment term.

**Calibration bands.** The raw score is mapped to a probability through
`hr_calibration.json`, a monotone, regressed band map fitted by
`model/hr_calibration_fit.py` on graded nights. The included file was fitted on 19
nights / 6,134 bat-nights. It shows the raw scores ran hot at the top: the band
predicting about 22.5% was re-mapped to 20.1%, and the top band (about 63%) to 41.5%,
with each correction shrunk 50% toward the model. The refit runs every morning in
`scripts/grade_morning.sh`, so the bands follow the season instead of going stale.

**From-scratch model (`model/hrmodel.py`).** This is a separate, deliberately
independent HR model. It runs a ridge-penalised logistic regression solved by IRLS in
NumPy (no scikit-learn). It is built only from *measured* inputs: EV, hard-hit %,
bat speed, pulled-air rate, GB/FB %, recent xISO, what the arm allows, park, weather,
implied runs and expected PA. A regex blocklist keeps out every column the
hand-built engine derived, so the model can't simply learn the old score. Design
choices:
- Launch angle and attack angle are scored as *distance from a window* (25-32 deg),
  not "higher is better", because the HR relationship is not monotone.
- Features are z-scored within each night so one night's conditions don't leak into
  another's.
- Evaluation is **two-fold by calendar**: the model is fit on one half of the nights
  and scores the other, so every reported number is out of sample.
- A **shuffled-outcome null** shuffles who homered within each night, refits the
  whole procedure and scores it out of sample. This sets the bar the real result
  has to clear.
- The model is compared head-to-head with `hr_score` on identical rows, and a
  `--lock` mode freezes weights for forward testing.

## Evaluation methodology

- **Nightly grading.** Every board is saved before first pitch and labelled the next
  morning. Grading runs in the morning, not at night, so late West Coast games aren't
  counted as misses. `graded_full_*.csv` keeps the full live feature set plus outcomes.
- **Rates against base, not raw counts.** Each selector is judged by its hit rate
  against that night's board base rate, at fixed depths (top 5 / 10 / 20).
- **Robustness checks.** Results are split in half (by date) and must hold in both
  halves. Bootstrap over nights gives 10th-percentile outcomes. Re-pairing and
  leave-one-out nulls catch leakage. Decile monotonicity checks show whether a
  column ranks or only gates.
- **Scoring rules.** At an ~11% per-game base rate, accuracy is meaningless. The
  research notes argue for log loss, Brier score and calibration instead.

## Results and key findings

All numbers are quoted from the write-ups in `docs/`.

**Per-bat calling is near a ceiling.** On the 49-night graded record
(`docs/ENGINE-CORE-DISSECTION.md`, 2026-08-16):
- The engine's top-5 hit a home run **25.7%** of the time. A cross-validated model
  scored **22.4-25.3%** out of fold, and the strongest public system found posts
  **23.8%** on its top-5 across 136,000 batter-games.
- Three independent approaches landing on the same number suggests that pre-game
  data runs out at roughly 2.2-2.5x the base rate.
- The model's picks were **73% different bats** from the engine's at a similar hit
  rate. The union of the two contained a homer on **88%** of nights, against **67%**
  for the engine alone. Adding independent selectors helped; refining the same one
  did not.

**Honest negatives, from the engine's own data** (`docs/HR-RESEARCH-AUDIT.md`, 36
nights / 8,379 bat-nights):
- **Pitch-type matching did not hold up.** Batters who homered had faced their
  best-matching pitch type **32%** of the time, against a **30%** re-pairing null on
  467 homers. An earlier "52%" turned out to be leakage: a leave-one-out test showed
  the outcome had been baked into the feature. The arsenal-match signal described
  above is kept as a re-ranking term, not a headline edge.
- **Every recency (hot-streak) window failed**, consistent with published work. HR
  rate needs about 170 PA to stabilise, and a 10-day window holds about 40.
- **What did hold up:** `hr_prob` added **+0.038 in-tier AUC (p = 0.002)** over a
  season-xISO power benchmark. Its ranking still separated homers past rank 50
  (**15.9% vs 11.2%**), where **65%** of all homers fell. The board, though, was only
  reading the top 50.

**Self-audits found real bugs** (`docs/FINDINGS.md`, 35 nights / 9,072 bat-nights,
HR base 11.03%):
- One signal (SLG-FIT) was computed only on the total-bases frame and never reached
  the HR pool. The audit tool's first version got this wrong: it went by line
  numbers, and the TB generator sits physically inside the HR code's line range. It
  was rebuilt to track which dataframe each line touches.
- For the no-homer 1.5 TB outcome, expected plate appearances was the strongest read
  (+9.2 pp, z = 5.9). Strikeout rate reads *inverted*, and 50 power columns read as
  noise. Contact and power are different axes.
- The strongest pairwise signal (zone fit x vulnerable arm) hit **31.2%** on about
  3.6 bats a night, with both halves at 30.6 / 31.7. The bat side alone hit 22.0% and
  the arm side alone 16.9%.

**Calibration drift is real.** In August the board homered 22% less, and some
selectors fell about 10 points on quiet nights. The prices were right on average but
wrong on the night, which is why calibration became a rolling refit with a planned
drift alarm. Game-level correlation between same-game picks measured flat
(0.89-1.05x on 1,000-2,600 pairs per cell). The correlation that matters is
night-level regime.

## Architecture and automation

```
app.py                  Streamlit app (~21.5k lines): data loading, feature joins, scoring, board UI
board_html.py           custom HTML/JS board renderer (signal drawers, chips, palette)
ballpark_weather.py     park coordinates/orientation + Open-Meteo -> HR weather multiplier
prosync_select.py       selection lanes over the scored board
prosync_tb15/tb25/tbclean/tb_opportunity.py   total-bases scoring lanes
prosync_spot/plan/assemble.py                 matchup-led "spot" ranking and portfolio-level card assembly
slipforge.py            standalone, read-only combination builder/evaluator over the board and graded history
model/hrmodel.py        ridge logistic regression via IRLS, two-fold-by-calendar, null bar
model/hr_calibration_fit.py   fits the monotone calibration band map
scripts/daily.sh        morning pipeline: preflight -> grade -> refresh inputs -> audit -> weekly re-validation -> launch
scripts/grade_morning.sh      next-morning graders + calibration refit
scripts/autodaily.sh    idempotent once-per-day wrapper for an hourly Windows scheduler starting WSL
sample_data/            3 graded nights (public player stats + outcomes) and a calibration file
docs/                   three research write-ups the findings above come from
```

`daily.sh` reports every step as OK / SKIP / FAIL with a duration and prints a
summary table. A missing input is reported loudly rather than skipped silently.
Statcast refreshes are rate-limited by marker files, and the long 13-month zone
rebuild only runs when its outputs are more than 72 hours old. `autodaily.sh` exists
because WSL isn't always running. A Windows task fires it hourly, and a marker file
makes sure the day runs exactly once and is retried if it fails.

**Scope of this repo.** This is a curated snapshot. The automation scripts also call
about 30 data-refresh, backfill and grading scripts from the working install
(Statcast fetchers, zone builders, graders) that aren't included here. Those steps
will report `SKIP` / `FAIL` until they're supplied. The app itself starts without
data and shows clear "missing input" messages.

## How to run

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # add your the-odds-api.com key (optional; odds features stay empty without it)
streamlit run app.py
```

Run the from-scratch model against graded boards (it reads `<repo>/boards/graded_full_*.csv`):

```bash
mkdir -p boards && cp sample_data/graded_full_*.csv boards/
python model/hrmodel.py --nulls 2          # 3 sample nights: runs end to end, far too few nights to mean anything
python model/hrmodel.py --show-coef
```

Verified for this snapshot: every `.py` file compiles, and all modules import on
Python 3.11. `hrmodel.py` runs end to end on the sample nights. `streamlit run`
starts headless and the app executes without exceptions, reporting its missing
input CSVs.

## What I'd do next

1. **Regime conditioning.** Build a pre-game "night card" (slate weather, count of
   vulnerable starters, rolling league HR rate, board depth) to decide when to trust
   the board.
2. **Exposure modelling.** Treat expected PA as a continuous multiplier, and blend
   starter and bullpen matchups by each one's expected share of plate appearances.
3. **Living calibration.** Use rolling re-measurement with a shrinkage prior, drift
   alarms, and a weekly model retrain on the growing record.
4. **Spray-angle and park-geometry features.** Pulled-air rate per hitter, wind as a
   vector against the pull field, and per-sector park geometry.
5. **Engineering.** Break the 21k-line `app.py` into a tested package (data /
   features / scoring / UI). Replace hand-applied patches with version control and
   unit tests. Report log loss and Brier score on every refit.

---

*Not affiliated with MLB or Baseball Savant. For research and portfolio purposes.*
