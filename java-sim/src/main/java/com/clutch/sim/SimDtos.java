package com.clutch.sim;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;

/** Request and response payloads for {@link SimController}. */
public final class SimDtos {

  private SimDtos() {}

  /** Optional per-request override of the possession-outcome distribution. */
  public record ModelSpec(
      double pThree,
      double pTwo,
      double pAndOne,
      double pTwoFt,
      double pOneFt,
      double orebProb) {

    public PossessionModel toModel() {
      return new PossessionModel(pThree, pTwo, pAndOne, pTwoFt, pOneFt, orebProb, 0.5);
    }
  }

  public record WinProbabilityRequest(
      @Min(-99) @Max(99) int margin,
      @Min(0) @Max(400) int possessionsLeft,
      boolean homeHasBall,
      ModelSpec model) {}

  public record WinProbabilityResponse(
      double winProbability,
      int margin,
      int possessionsLeft,
      boolean homeHasBall,
      double pointsPerPossession,
      String method,
      long elapsedMicros) {}

  public record EndgameRequest(
      @Min(-99) @Max(99) int margin,
      @Min(0) @Max(2880) double secondsRemaining,
      boolean homeHasBall,
      @Min(1000) @Max(500_000) int trials,
      @Min(0) @Max(20) int foulDownBy,
      @Min(0) @Max(300) double foulSeconds,
      ModelSpec model) {}

  public record EndgameResponse(
      double winProbability,
      double exactChainWinProbability,
      int trials,
      double standardError,
      String method,
      long elapsedMicros) {}

  /** One point of a win-probability curve, for batch scoring a whole game. */
  public record CurvePoint(int margin, double secondsRemaining, boolean homeHasBall) {}

  public record CurveRequest(java.util.List<CurvePoint> points, ModelSpec model) {}

  public record CurveResponse(double[] winProbabilities, String method, long elapsedMicros) {}
}
