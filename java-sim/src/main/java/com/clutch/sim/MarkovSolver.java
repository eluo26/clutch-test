package com.clutch.sim;

/**
 * Exact solver for the possession-state Markov chain.
 *
 * <p>State is {@code (k, d, o)}: {@code k} possessions remaining, {@code d} the home lead, {@code
 * o} which team has the ball. Terminal values at {@code k = 0} are 1 / 0 / overtime-probability
 * depending on the sign of {@code d}. Backward induction over {@code k} gives the exact win
 * probability for every state in one pass -- no simulation error, and the whole table is reusable.
 *
 * <p>This is the reason the service exists in Java rather than being another Python function: the
 * table is {@code (maxPossessions + 1) * (2 * MARGIN_CAP + 1) * 2} doubles, rebuilt whenever the
 * fitted possession model changes, and the JIT makes the inner loop roughly two orders of
 * magnitude faster than the pure-Python equivalent. The API keeps the Python version as a
 * fallback, so this is a speed dependency and never a correctness one -- and {@code
 * MarkovSolverTest} asserts the two agree.
 *
 * <p>Values are stored flat in a single {@code double[]} rather than a 3-D array: the inner loop
 * walks contiguous memory, which matters once the table is a few million entries.
 */
public final class MarkovSolver {

  /** Leads beyond this are decided for all practical purposes. */
  public static final int MARGIN_CAP = 45;

  private static final int MARGIN_STATES = 2 * MARGIN_CAP + 1;
  /** 2880 regulation seconds over roughly 200 total possessions. */
  public static final double SECONDS_PER_POSSESSION = 14.4;

  private final PossessionModel model;
  private final int maxPossessions;
  private final double[] table; // [k][ballIndex][marginIndex], flattened

  public MarkovSolver(PossessionModel model, int maxPossessions) {
    if (maxPossessions < 0) {
      throw new IllegalArgumentException("maxPossessions must be >= 0");
    }
    this.model = model;
    this.maxPossessions = maxPossessions;
    this.table = new double[(maxPossessions + 1) * 2 * MARGIN_STATES];
    solve();
  }

  public MarkovSolver(PossessionModel model) {
    this(model, 220);
  }

  private static int marginIndex(int d) {
    return Math.min(MARGIN_CAP, Math.max(-MARGIN_CAP, d)) + MARGIN_CAP;
  }

  private int idx(int k, boolean homeBall, int marginIdx) {
    return (k * 2 + (homeBall ? 0 : 1)) * MARGIN_STATES + marginIdx;
  }

  private void solve() {
    double[] outcomes = model.outcomeProbabilities();
    double oreb = model.orebProb();

    // k = 0: the buzzer has gone.
    for (int i = 0; i < MARGIN_STATES; i++) {
      int d = i - MARGIN_CAP;
      double v = d > 0 ? 1.0 : d < 0 ? 0.0 : model.overtimeHomeWinProb();
      table[idx(0, true, i)] = v;
      table[idx(0, false, i)] = v;
    }

    for (int k = 1; k <= maxPossessions; k++) {
      for (int i = 0; i < MARGIN_STATES; i++) {
        int d = i - MARGIN_CAP;

        double home = 0.0;
        double away = 0.0;
        for (int pts = 0; pts < outcomes.length; pts++) {
          double p = outcomes[pts];
          if (p == 0.0) {
            continue;
          }
          int homeNext = marginIndex(d + pts);
          int awayNext = marginIndex(d - pts);

          if (pts == 0) {
            // A miss can be rebounded by the offense, which keeps the ball.
            home +=
                p
                    * (oreb * table[idx(k - 1, true, homeNext)]
                        + (1.0 - oreb) * table[idx(k - 1, false, homeNext)]);
            away +=
                p
                    * (oreb * table[idx(k - 1, false, awayNext)]
                        + (1.0 - oreb) * table[idx(k - 1, true, awayNext)]);
          } else {
            home += p * table[idx(k - 1, false, homeNext)];
            away += p * table[idx(k - 1, true, awayNext)];
          }
        }
        table[idx(k, true, i)] = home;
        table[idx(k, false, i)] = away;
      }
    }
  }

  /** Home win probability with {@code possessionsLeft} trips remaining. */
  public double winProbability(int margin, int possessionsLeft, boolean homeHasBall) {
    int k = Math.max(0, Math.min(maxPossessions, possessionsLeft));
    return table[idx(k, homeHasBall, marginIndex(margin))];
  }

  public double winProbabilityFromClock(int margin, double secondsRemaining, boolean homeHasBall) {
    return winProbability(margin, possessionsRemaining(secondsRemaining), homeHasBall);
  }

  public static int possessionsRemaining(double secondsRemaining) {
    if (secondsRemaining <= 0) {
      return 0;
    }
    return Math.max(1, (int) Math.round(secondsRemaining / SECONDS_PER_POSSESSION));
  }

  public PossessionModel model() {
    return model;
  }

  public int maxPossessions() {
    return maxPossessions;
  }
}
