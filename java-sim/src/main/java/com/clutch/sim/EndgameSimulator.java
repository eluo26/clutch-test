package com.clutch.sim;

import java.util.concurrent.ThreadLocalRandom;

/**
 * Monte Carlo endgame simulator.
 *
 * <p>The exact chain in {@link MarkovSolver} assumes possessions are homogeneous, which stops being
 * true in the last minute: the trailing team fouls deliberately, so possessions get short and the
 * leading team's trips turn into free throws. That behaviour is a *policy*, not a transition
 * matrix, and it is much easier to simulate than to solve.
 *
 * <p>So: exact DP for the general case, Monte Carlo for the deliberate-fouling endgame. This is the
 * part that actually needs a compiled language -- a hundred thousand trials per request is
 * unremarkable here and painful in Python.
 */
public final class EndgameSimulator {

  private final PossessionModel model;

  public EndgameSimulator(PossessionModel model) {
    this.model = model;
  }

  /**
   * Simulate to the buzzer with a deliberate-fouling policy for the trailing team.
   *
   * @param margin home lead now
   * @param secondsRemaining seconds left in regulation
   * @param homeHasBall who is in possession
   * @param trials number of Monte Carlo trials
   * @param foulDownBy trail by this much or less, inside {@code foulSeconds}, and start fouling
   * @param foulSeconds clock threshold at which the fouling policy switches on
   * @return home win probability
   */
  public double winProbability(
      int margin,
      double secondsRemaining,
      boolean homeHasBall,
      int trials,
      int foulDownBy,
      double foulSeconds) {

    if (trials <= 0) {
      throw new IllegalArgumentException("trials must be positive");
    }
    double[] outcomes = model.outcomeProbabilities();
    double[] cumulative = new double[outcomes.length];
    double running = 0.0;
    for (int i = 0; i < outcomes.length; i++) {
      running += outcomes[i];
      cumulative[i] = running;
    }

    int homeWins = 0;
    for (int t = 0; t < trials; t++) {
      ThreadLocalRandom rng = ThreadLocalRandom.current();
      int d = margin;
      double clock = secondsRemaining;
      boolean home = homeHasBall;

      while (clock > 0) {
        // Trailing team fouls to stop the clock once the game is late and close.
        boolean defenceTrails = home ? d > 0 : d < 0;
        boolean fouling =
            clock <= foulSeconds && defenceTrails && Math.abs(d) <= foulDownBy;

        int points;
        double elapsed;
        if (fouling) {
          // Two free throws; the clock barely moves.
          points = 0;
          for (int shot = 0; shot < 2; shot++) {
            if (rng.nextDouble() < 0.78) {
              points++;
            }
          }
          elapsed = 4.0 + rng.nextDouble() * 3.0;
        } else {
          double r = rng.nextDouble();
          points = outcomes.length - 1;
          for (int i = 0; i < cumulative.length; i++) {
            if (r < cumulative[i]) {
              points = i;
              break;
            }
          }
          // A trailing offense hurries; a leading one bleeds clock.
          boolean offenceTrails = home ? d < 0 : d > 0;
          double base = MarkovSolver.SECONDS_PER_POSSESSION;
          elapsed =
              clock <= foulSeconds
                  ? (offenceTrails ? 6.0 + rng.nextDouble() * 5.0 : 18.0 + rng.nextDouble() * 6.0)
                  : Math.max(2.0, base + rng.nextGaussian() * 4.0);
        }

        d += home ? points : -points;
        clock -= elapsed;

        boolean offensiveRebound = points == 0 && !fouling && rng.nextDouble() < model.orebProb();
        if (!offensiveRebound) {
          home = !home;
        }
      }

      if (d > 0) {
        homeWins++;
      } else if (d == 0 && rng.nextDouble() < model.overtimeHomeWinProb()) {
        homeWins++;
      }
    }
    return (double) homeWins / trials;
  }
}
