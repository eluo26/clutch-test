package com.clutch.sim;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

/**
 * Properties the chain must satisfy. These are the assertions that would catch an off-by-one in the
 * backward induction, which is by far the easiest thing to get wrong here.
 */
class MarkovSolverTest {

  private final MarkovSolver solver = new MarkovSolver(PossessionModel.DEFAULT, 220);

  @Test
  void buzzerIsDecisive() {
    assertEquals(1.0, solver.winProbability(1, 0, true), 1e-12);
    assertEquals(0.0, solver.winProbability(-1, 0, false), 1e-12);
    assertEquals(0.5, solver.winProbability(0, 0, true), 1e-12);
  }

  @Test
  void probabilitiesStayInUnitInterval() {
    for (int k = 0; k <= 220; k += 7) {
      for (int d = -MarkovSolver.MARGIN_CAP; d <= MarkovSolver.MARGIN_CAP; d += 3) {
        for (boolean ball : new boolean[] {true, false}) {
          double p = solver.winProbability(d, k, ball);
          assertTrue(p >= 0.0 && p <= 1.0, "out of range at k=" + k + " d=" + d);
        }
      }
    }
  }

  @Test
  void morePointsIsNeverWorse() {
    for (int k = 0; k <= 60; k++) {
      for (int d = -20; d < 20; d++) {
        assertTrue(
            solver.winProbability(d + 1, k, true) >= solver.winProbability(d, k, true) - 1e-12,
            "monotonicity broken at k=" + k + " d=" + d);
      }
    }
  }

  @Test
  void havingTheBallHelps() {
    // Compared at odd possession counts on purpose. The chain alternates, so
    // an even number of possessions left splits the remaining trips evenly and
    // possession is worth almost nothing; the last-shot advantage only exists
    // when one team gets the extra trip.
    double late = solver.winProbability(0, 1, true) - solver.winProbability(0, 1, false);
    double early = solver.winProbability(0, 101, true) - solver.winProbability(0, 101, false);
    assertTrue(late > 0, "possession should be worth something");
    assertTrue(late > early, "possession should matter more late than early");
    assertTrue(early < 0.10, "possession should barely matter with a half to play");
  }

  @Test
  void aLeadDecaysTowardEvenWithTimeRemaining() {
    // A 6-point lead is nearly safe with one possession left and much less so
    // with a full half to play.
    assertTrue(solver.winProbability(6, 1, false) > 0.95);
    assertTrue(solver.winProbability(6, 100, false) < 0.80);
  }

  @Test
  void symmetryUnderSignFlip() {
    // Swapping which team leads AND which has the ball must mirror the answer.
    for (int k = 1; k <= 40; k++) {
      for (int d = 1; d <= 15; d++) {
        double home = solver.winProbability(d, k, true);
        double mirrored = 1.0 - solver.winProbability(-d, k, false);
        assertEquals(home, mirrored, 1e-9, "asymmetry at k=" + k + " d=" + d);
      }
    }
  }

  @Test
  void offensiveReboundingIsWorthSomething() {
    PossessionModel noOreb =
        new PossessionModel(0.128, 0.303, 0.035, 0.098, 0.052, 0.0, 0.5);
    MarkovSolver without = new MarkovSolver(noOreb, 60);
    // Down 2 with the ball and one possession left: a second chance can only help.
    assertTrue(solver.winProbability(-2, 1, true) >= without.winProbability(-2, 1, true));
  }

  @Test
  void endgameSimulatorTracksTheExactChainWhenNobodyFouls() {
    // With the fouling policy switched off, the Monte Carlo simulator and the
    // exact chain are estimating the same quantity and must agree.
    EndgameSimulator sim = new EndgameSimulator(PossessionModel.DEFAULT);
    double mc = sim.winProbability(3, 120, true, 200_000, 0, 0.0);
    double exact = solver.winProbabilityFromClock(3, 120, true);
    assertEquals(exact, mc, 0.03, "monte carlo diverged from the exact chain");
  }
}
