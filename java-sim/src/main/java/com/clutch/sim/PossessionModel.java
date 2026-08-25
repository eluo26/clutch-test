package com.clutch.sim;

/**
 * Outcome distribution for a single possession.
 *
 * <p>Probabilities are over points scored by the team in possession. {@code orebProb} is the
 * chance the offense retains the ball after a miss, which is what makes the chain non-alternating
 * and is the single most important detail for endgame accuracy.
 *
 * <p>Deliberately dependency-free: this class and {@link MarkovSolver} compile and run with plain
 * {@code javac}, so the maths can be exercised without a Spring context.
 */
public record PossessionModel(
    double pThree,
    double pTwo,
    double pAndOne,
    double pTwoFt,
    double pOneFt,
    double orebProb,
    double overtimeHomeWinProb) {

  /**
   * League-average defaults: 1.138 points per possession. Must stay in step with
   * {@code DEFAULT_POSSESSION_MODEL} in {@code backend/app/winprob/markov.py} -- the Python
   * fallback and this solver are meant to return the same numbers.
   */
  public static final PossessionModel DEFAULT =
      new PossessionModel(0.105, 0.275, 0.025, 0.075, 0.048, 0.135, 0.5);

  public PossessionModel {
    if (pThree < 0 || pTwo < 0 || pAndOne < 0 || pTwoFt < 0 || pOneFt < 0) {
      throw new IllegalArgumentException("probabilities must be non-negative");
    }
    if (orebProb < 0 || orebProb >= 1) {
      throw new IllegalArgumentException("orebProb must be in [0, 1)");
    }
    double scored = pThree + pTwo + pAndOne + pTwoFt + pOneFt;
    if (scored > 1.0) {
      throw new IllegalArgumentException("scoring probabilities sum to more than 1: " + scored);
    }
  }

  public double pEmpty() {
    return Math.max(0.0, 1.0 - (pThree + pTwo + pAndOne + pTwoFt + pOneFt));
  }

  /** Probability of each possession outcome, indexed by points scored (0..3). */
  public double[] outcomeProbabilities() {
    return new double[] {pEmpty(), pOneFt, pTwo + pTwoFt, pThree + pAndOne};
  }

  public double pointsPerPossession() {
    double[] p = outcomeProbabilities();
    double sum = 0.0;
    for (int pts = 0; pts < p.length; pts++) {
      sum += pts * p[pts];
    }
    return sum;
  }
}
