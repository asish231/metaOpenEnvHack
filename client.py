"""TravelOps OpenEnv — Typed EnvClient."""

from __future__ import annotations

from typing import Any, Dict

from openenv.core.env_client import EnvClient
from openenv.core.client_types import StepResult

from .models import (
    Booking,
    TravelAction,
    TravelObservation,
    TravelState,
)


class TravelOpsEnv(EnvClient["TravelAction", "TravelObservation", "TravelState"]):
    """WebSocket client for the TravelOps environment."""

    # ── serialisation ────────────────────────────────────────────────────

    def _step_payload(self, action: TravelAction) -> dict:
        return action.model_dump()

    def _parse_result(self, payload: Dict[str, Any]) -> StepResult[TravelObservation]:
        obs_data = payload.get("observation", {})
        obs = TravelObservation(**obs_data)
        return StepResult(
            observation=obs,
            reward=payload.get("reward"),
            done=payload.get("done", False),
        )

    def _parse_state(self, payload: Dict[str, Any]) -> TravelState:
        return TravelState(**payload)
