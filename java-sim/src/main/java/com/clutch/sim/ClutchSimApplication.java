package com.clutch.sim;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Clutch simulation service.
 *
 * <p>Runs on port 8081 by default (see {@code application.yml}) and is called by the FastAPI
 * backend at {@code CLUTCH_SIM_SERVICE_URL}. The API degrades to a pure-Python solver whenever this
 * process is not running, so it is safe to start, stop, or skip entirely.
 */
@SpringBootApplication
public class ClutchSimApplication {

  public static void main(String[] args) {
    SpringApplication.run(ClutchSimApplication.class, args);
  }
}
