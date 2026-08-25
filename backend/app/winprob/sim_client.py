"""Client for the Java Markov simulator service (``java-sim/``).

The Java service owns the heavy batch work: solving the possession-state chain
over a large state space and running Monte Carlo endgame simulations. It is an
*optional* dependency -- every call here degrades to the pure-Python solver in
:mod:`app.winprob.markov` if the service is not running, so a fresh clone works
with nothing but Python installed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings
from app.winprob import markov

log = logging.getLogger(__name__)


@dataclass
class SimResult:
    win_probability: float
    source: str  # "java-sim" or "python-fallback"
    detail: dict | None = None


class SimClient:
    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.sim_service_url).rstrip("/")
        self.timeout = timeout or settings.sim_service_timeout_seconds
        self._healthy: bool | None = None

    # -- health -----------------------------------------------------------
    def health(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/health", timeout=self.timeout)
            self._healthy = r.status_code == 200
        except Exception:  # noqa: BLE001 - any transport error means "not up"
            self._healthy = False
        return bool(self._healthy)

    # -- solve ------------------------------------------------------------
    def win_probability(
        self,
        margin: int,
        possessions_left: int,
        home_has_ball: bool = True,
        model: markov.PossessionModel | None = None,
    ) -> SimResult:
        payload = {
            "margin": int(margin),
            "possessionsLeft": int(possessions_left),
            "homeHasBall": bool(home_has_ball),
        }
        if model is not None:
            payload["model"] = {
                "pThree": model.p_three,
                "pTwo": model.p_two,
                "pAndOne": model.p_and_one,
                "pTwoFt": model.p_two_ft,
                "pOneFt": model.p_one_ft,
                "orebProb": model.oreb_prob,
            }
        try:
            r = httpx.post(
                f"{self.base_url}/api/sim/win-probability",
                json=payload,
                timeout=self.timeout,
            )
            r.raise_for_status()
            body = r.json()
            return SimResult(
                win_probability=float(body["winProbability"]),
                source="java-sim",
                detail=body,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("sim service unavailable (%s); using python fallback", exc)
            solver = markov.default_solver() if model is None else markov.MarkovSolver(model)
            return SimResult(
                win_probability=solver.win_probability(
                    margin, possessions_left, home_has_ball
                ),
                source="python-fallback",
            )


_client: SimClient | None = None


def get_sim_client() -> SimClient:
    global _client
    if _client is None:
        _client = SimClient()
    return _client
