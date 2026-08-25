# Modeling notes

Longer-form notes on the two win-probability models, what they assume, and
where they break. The README has the short version.

## 1. Brownian motion with drift

### Setup

Let $X(t)$ be the home team's lead at time $t$, with $t = 0$ at tip-off and
$t = 1$ at the final buzzer. Stern (1994) models the lead as Brownian motion
with drift $\mu$ and per-game variance $\sigma^2$:

$$X(1) - X(t) \sim \mathcal{N}\big(\mu s,\ \sigma^2 s\big), \qquad s = 1 - t$$

Two things follow immediately and are worth stating because they are what make
the model useful rather than merely tractable:

- **Variance scales linearly in time remaining**, so uncertainty about the
  final margin scales as $\sqrt{s}$. A 6-point lead is worth much more with
  five minutes left than with a half to play, and the model gets that shape for
  free rather than needing it fitted.
- **The current lead is a sufficient statistic.** How you got to +6 does not
  matter. This is a real assumption, not a convenience, and it is why the model
  ignores runs, momentum, and foul trouble.

### Estimating $\mu$ and $\sigma$

Under the model the final margin $X(1)$ is $\mathcal{N}(\mu, \sigma^2)$, so the
MLE is the sample mean and standard deviation of observed final margins. No
regression over intermediate states is needed: for a Brownian bridge the
endpoint carries all the information about $\mu$ and $\sigma$.

`fit_brownian_params` does exactly this, per season when a season is given.
`tests/test_winprob.py::test_fit_recovers_known_parameters` samples 20,000
margins from a known normal and checks both parameters come back.

Typical fitted values on real data: $\mu \approx 2.5$ to $3$, $\sigma \approx 13$
to $15$.

### Ties, and why the naive form is wrong

The textbook statement is $P(\text{home win}) = \Phi\!\big(\frac{d + \mu s}{\sigma\sqrt{s}}\big)$,
i.e. $P(X(1) > 0)$. But basketball scores are integers and a tie goes to
overtime, so $P(X(1) > 0)$ silently hands the entire probability of an exact tie
to the away team. The honest statement is

$$P(\text{home win}) = P\big(X(1) \ge 1\big) + \tfrac{1}{2} P\big(X(1) = 0\big)$$

With a half-point continuity correction on the normal approximation and
$m = d + \mu s$, $c = \sigma\sqrt{s}$, this collapses to

$$P = \tfrac{1}{2}\left[\Phi\!\left(\frac{m - 0.5}{c}\right) + \Phi\!\left(\frac{m + 0.5}{c}\right)\right]$$

which is the average of two half-point-shifted CDFs. The quick check that this
is right: with $\mu = 0$ it satisfies $P(m) + P(-m) = 1$ exactly, and the naive
form does not. That identity is asserted in
`test_symmetry_with_zero_drift`, and it is how the bug was caught.

### Possession value

Holding the ball tied with 10 seconds left is worth a great deal; holding it
tied in the first quarter is worth almost nothing. The model adds
`possession_value` points to the effective lead for whoever has the ball, faded
by $\sqrt{s}$:

$$m = d + \mu s + v \cdot \big(1 - 0.75\sqrt{s}\big) \cdot \operatorname{sign}$$

This is a shape imposed by hand, not fitted. It is the weakest part of the
Brownian model, and it is a large part of why the Markov chain exists.

### Where it breaks

Diffusion assumes many small increments. With one possession left there is
exactly one increment, of size 0, 1, 2 or 3. The model cannot represent "down 3
with the ball is much better than down 4 with the ball", which is one of the
most basic facts about NBA endgames.

## 2. Markov chain over possession states

### Setup

State $(k, d, o)$: $k$ trips remaining, home lead $d$, team in possession $o$.
Transitions are driven by a per-trip points distribution over $\{0, 1, 2, 3\}$
plus an offensive-rebound probability. Terminal values at $k = 0$ are 1, 0, or
the overtime probability by the sign of $d$. Solved by backward induction, so
the answer is exact and the whole table is reusable.

### Trips, not possessions

One step of the chain is a **trip** — a single shot opportunity. An offensive
rebound consumes a step and leaves the ball with the same team. That is not the
box-score definition of a possession, and conflating the two produces two
correlated bugs:

- the clock conversion uses 14.4 s/possession instead of 13.1 s/trip, so the
  chain thinks ~10% fewer opportunities remain than actually do;
- the rate fitting divides by $\text{FGA} + 0.44\,\text{FTA} - \text{OREB} + \text{TOV}$
  instead of $\text{FGA} + 0.44\,\text{FTA} + \text{TOV}$, inflating every rate
  by ~10%.

The tell is implied points per possession landing near 1.30 instead of 1.14.
`fit_possession_model` has a sanity gate that falls back to league-average
defaults if the fit lands outside $[0.85, 1.45]$.

An alternative formulation keeps $k$ as true possessions and folds putbacks
into a geometric mixture within a single step. That is arguably cleaner and
removes the ambiguity entirely; it is not what is implemented here.

### Properties it reproduces

| State | Model | Why it is right |
|---|---|---|
| Down 4, 1 trip, with ball | 0.000 | You cannot score 4 points on one trip. |
| Down 3, 1 trip, with ball | > 0 | You can. |
| Tied, 1 trip, with ball | ~0.76 | Last shot to win, else overtime. |
| Tied, 101 trips, with ball | ~0.52 | Possession is nearly worthless with a half to play. |

Note the **parity effect**: with an even number of trips remaining the two teams
split them evenly and possession is worth almost nothing, so possession value
oscillates rather than decaying smoothly. That is a genuine property of an
alternating chain, not an artifact, but it is why the tests compare odd $k$ to
odd $k$.

### Where it breaks

The chain assumes possessions are homogeneous. In the last minute they are not:
the trailing team fouls deliberately, so trips become short and turn into free
throws. That is a *policy*, not a transition matrix. It is handled by
`EndgameSimulator` on the Java side by Monte Carlo instead of being solved.

## 3. Overtime

`app/winprob/clock.py`. The failure mode this exists to prevent is treating
`seconds_remaining <= 0` as "game over", which makes the curve snap to 100% the
instant anyone leads in overtime.

The subtlety is that boundary values are ambiguous: `seconds_remaining == 0` is
both the final buzzer of regulation and the tip of OT1; `-300` is both the end
of OT1 and the start of OT2. The disambiguator is the score — **an overtime
period only ever begins from a tie** — so at a boundary a non-zero margin means
the game is over and a zero margin means five more minutes.

In overtime, home-court drift is dropped (that edge is spent by the time a game
gets there) and variance scales as $300/2880$ of a full game. One consequence
worth knowing: the $\sqrt{s}$ scaling gives an OT margin standard deviation
around 4.5 points where the real figure is closer to 6, so the Brownian model
runs slightly overconfident in overtime. In practice the blend hands overtime
entirely to the chain, so this rarely surfaces.

## 4. Calibration

Reported by `app/winprob/calibration.py`: Brier score, Brier skill against the
base rate, log loss, ECE/MCE over reliability bins, and everything again sliced
by time remaining.

Two decisions that matter more than they look:

- **Forecasts are sampled on a fixed clock grid, not per event.** Events cluster
  around free throws and timeouts. Per-event sampling silently over-weights
  those moments and makes the reliability diagram a statement about free
  throws.
- **The grid stops short of the buzzer.** At 0 seconds the outcome is settled,
  so scoring it hands every model a free perfect forecast. Overtime is excluded
  for the same reason: it is only reachable from a tie, where every model says
  50% and is right half the time by construction.

Results on the 100-game synthetic sample, 30-second grid:

| Model | Brier | Skill | Log loss | ECE | Clutch Brier |
|---|---|---|---|---|---|
| Brownian | 0.1661 | +0.326 | 0.485 | 0.037 | 0.061 |
| Markov | 0.1660 | +0.327 | 0.489 | 0.036 | 0.063 |
| Blend | 0.1663 | +0.325 | 0.487 | 0.037 | 0.063 |

The honest reading: **on this data the three are indistinguishable**. The Markov
chain has a marginally better calibration error and a marginally worse log loss.
The differences are well inside noise at 100 games. The place a difference
should show up is the final two minutes of close games, which this sample has
too few of to resolve — pull a few hundred real games and the comparison becomes
meaningful.

Reported numbers are also **in-sample**: $\mu$ and $\sigma$ are fitted on the
same games being scored. For a headline number, fit on one season and score
another via `backtest(..., fit_on="2022-23")`.

## 5. What is missing

In rough order of expected value:

1. **Team strength.** Both models treat the two teams as equal apart from home
   court, so the tip-off probability is ~55% for every game. A pre-game prior
   from ratings would show up immediately in the Q1 bucket, currently the
   weakest at +0.07 skill.
2. **A fitted possession-value term** instead of the hand-set 0.55 and the
   hand-set $\sqrt{s}$ fade.
3. **Pace-aware trip counts.** Trips remaining is computed from a league-average
   13.1 s/trip; a slow game genuinely has fewer opportunities left than the
   clock suggests.
4. **Deliberate fouling in the main path.** The Java `EndgameSimulator` models
   it, but the default blend does not call it.
5. **Out-of-sample fitting by default**, with the API exposing which season the
   parameters came from.

## References

- Stern, H. (1994). *A Brownian Motion Model for the Progress of Sports Scores.*
  Journal of the American Statistical Association, 89(427), 1128–1134.
- Brier, G. W. (1950). *Verification of Forecasts Expressed in Terms of
  Probability.* Monthly Weather Review, 78(1), 1–3.
- Gneiting, T. & Raftery, A. (2007). *Strictly Proper Scoring Rules,
  Prediction, and Estimation.* JASA, 102(477), 359–378.
