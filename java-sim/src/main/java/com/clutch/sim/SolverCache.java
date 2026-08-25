package com.clutch.sim;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;

/**
 * Keeps one solved table per distinct possession model.
 *
 * <p>Building the table is the expensive part (a few million multiply-adds); reading it is a single
 * array index. Almost every request uses the same fitted model, so caching turns the service into a
 * lookup after the first call.
 */
@Component
public class SolverCache {

  private final Map<PossessionModel, MarkovSolver> cache = new ConcurrentHashMap<>();

  public SolverCache() {
    cache.put(PossessionModel.DEFAULT, new MarkovSolver(PossessionModel.DEFAULT));
  }

  public MarkovSolver get(PossessionModel model) {
    return cache.computeIfAbsent(model, MarkovSolver::new);
  }

  public MarkovSolver getDefault() {
    return get(PossessionModel.DEFAULT);
  }

  public int size() {
    return cache.size();
  }
}
