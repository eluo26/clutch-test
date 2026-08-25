package com.clutch.sim;

import com.clutch.sim.SimDtos.CurvePoint;
import com.clutch.sim.SimDtos.CurveRequest;
import com.clutch.sim.SimDtos.CurveResponse;
import com.clutch.sim.SimDtos.EndgameRequest;
import com.clutch.sim.SimDtos.EndgameResponse;
import com.clutch.sim.SimDtos.WinProbabilityRequest;
import com.clutch.sim.SimDtos.WinProbabilityResponse;
import jakarta.validation.Valid;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/** HTTP surface for the solver. Everything here is stateless apart from {@link SolverCache}. */
@RestController
public class SimController {

  private final SolverCache solvers;

  public SimController(SolverCache solvers) {
    this.solvers = solvers;
  }

  @GetMapping("/health")
  public Map<String, Object> health() {
    return Map.of(
        "status", "ok",
        "service", "clutch-sim",
        "cachedModels", solvers.size(),
        "marginCap", MarkovSolver.MARGIN_CAP);
  }

  @PostMapping("/api/sim/win-probability")
  public WinProbabilityResponse winProbability(@Valid @RequestBody WinProbabilityRequest req) {
    long started = System.nanoTime();
    PossessionModel model =
        req.model() == null ? PossessionModel.DEFAULT : req.model().toModel();
    MarkovSolver solver = solvers.get(model);
    double wp = solver.winProbability(req.margin(), req.possessionsLeft(), req.homeHasBall());
    return new WinProbabilityResponse(
        wp,
        req.margin(),
        req.possessionsLeft(),
        req.homeHasBall(),
        model.pointsPerPossession(),
        "exact-backward-induction",
        (System.nanoTime() - started) / 1000);
  }

  /**
   * Endgame win probability under a deliberate-fouling policy, with the exact chain's answer
   * alongside it so a caller can see how much the fouling assumption is worth.
   */
  @PostMapping("/api/sim/endgame")
  public EndgameResponse endgame(@Valid @RequestBody EndgameRequest req) {
    long started = System.nanoTime();
    PossessionModel model =
        req.model() == null ? PossessionModel.DEFAULT : req.model().toModel();

    double mc =
        new EndgameSimulator(model)
            .winProbability(
                req.margin(),
                req.secondsRemaining(),
                req.homeHasBall(),
                req.trials(),
                req.foulDownBy() == 0 ? 6 : req.foulDownBy(),
                req.foulSeconds() == 0 ? 35.0 : req.foulSeconds());

    double exact =
        solvers
            .get(model)
            .winProbabilityFromClock(req.margin(), req.secondsRemaining(), req.homeHasBall());

    double se = Math.sqrt(Math.max(mc * (1 - mc), 1e-9) / req.trials());
    return new EndgameResponse(
        mc, exact, req.trials(), se, "monte-carlo", (System.nanoTime() - started) / 1000);
  }

  /** Batch-score a whole game's win-probability curve in one round trip. */
  @PostMapping("/api/sim/curve")
  public CurveResponse curve(@RequestBody CurveRequest req) {
    long started = System.nanoTime();
    PossessionModel model =
        req.model() == null ? PossessionModel.DEFAULT : req.model().toModel();
    MarkovSolver solver = solvers.get(model);

    double[] out = new double[req.points().size()];
    for (int i = 0; i < out.length; i++) {
      CurvePoint p = req.points().get(i);
      out[i] = solver.winProbabilityFromClock(p.margin(), p.secondsRemaining(), p.homeHasBall());
    }
    return new CurveResponse(
        out, "exact-backward-induction", (System.nanoTime() - started) / 1000);
  }

  @ExceptionHandler(IllegalArgumentException.class)
  public ResponseEntity<Map<String, String>> badRequest(IllegalArgumentException exc) {
    return ResponseEntity.badRequest().body(Map.of("error", exc.getMessage()));
  }
}
