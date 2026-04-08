"""TravelOps OpenEnv — Typed Pydantic Models.

Defines Action, Observation, State, and supporting nested records for the
business-travel execution and disruption-recovery benchmark.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import Field

from openenv.core.env_server.types import Action, Observation, State


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    SEARCH_OPTIONS = "search_options"
    BOOK_OPTION = "book_option"
    CANCEL_BOOKING = "cancel_booking"
    WAIT = "wait"
    FINALIZE_TRIP = "finalize_trip"


class TravelMode(str, Enum):
    FLIGHT = "flight"
    TRAIN = "train"
    BUS = "bus"


class TripStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class DisruptionType(str, Enum):
    CANCELLATION = "cancellation"
    DELAY = "delay"


# ---------------------------------------------------------------------------
# Nested value objects
# ---------------------------------------------------------------------------

from pydantic import BaseModel


class TravelOption(BaseModel):
    """A bookable travel leg returned by a search."""
    option_id: str
    mode: TravelMode
    carrier: str
    origin: str
    destination: str
    departure_time: str          # ISO-style "HH:MM" in 24-h
    arrival_time: str
    duration_minutes: int
    price: float
    connection_id: Optional[str] = None  # for multi-leg linking


class Booking(BaseModel):
    """An active booking held by the traveller."""
    booking_id: str
    option: TravelOption
    status: str = "confirmed"    # confirmed | cancelled | disrupted


class PolicySummary(BaseModel):
    """Company travel-policy constraints for the scenario."""
    budget_cap: float
    preferred_carriers: List[str]
    min_connection_buffer_minutes: int = 60


class DisruptionEvent(BaseModel):
    """A disruption injected by the scenario at a specific sim-time."""
    disruption_type: DisruptionType
    affected_booking_id: Optional[str] = None
    affected_carrier: Optional[str] = None
    affected_origin: Optional[str] = None
    affected_destination: Optional[str] = None
    delay_minutes: Optional[int] = None       # for delay-type
    message: str = ""
    trigger_time: str = "00:00"               # sim-time "HH:MM"


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------

class TravelAction(Action):
    """Agent action sent to the environment each step."""
    action_type: ActionType = Field(..., description="Which action to perform")

    # search fields
    origin: Optional[str] = Field(None, description="Origin city for search")
    destination: Optional[str] = Field(None, description="Destination city for search")
    earliest_departure: Optional[str] = Field(None, description="Earliest departure HH:MM")
    latest_arrival: Optional[str] = Field(None, description="Latest arrival HH:MM")
    allowed_modes: Optional[List[TravelMode]] = Field(None, description="Allowed travel modes")

    # booking fields
    option_id: Optional[str] = Field(None, description="Option ID to book")
    booking_id: Optional[str] = Field(None, description="Booking ID for cancel")

    # wait field
    wait_minutes: Optional[int] = Field(None, description="Minutes to advance clock")


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

class TravelObservation(Observation):
    """Observation returned by reset() and step()."""
    current_city: str = Field(..., description="Traveller's current city")
    current_time: str = Field(..., description="Simulated time HH:MM")
    deadline: str = Field(..., description="Must arrive by HH:MM")
    remaining_budget: float = Field(..., description="Budget left (INR)")
    active_bookings: List[Booking] = Field(default_factory=list)
    last_search_results: List[TravelOption] = Field(default_factory=list)
    active_disruption: Optional[DisruptionEvent] = Field(None)
    trip_status: TripStatus = Field(default=TripStatus.NOT_STARTED)
    task_brief: str = Field("", description="Human-readable task description")
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class TravelState(State):
    """Full episode state (superset of State base)."""
    scenario_id: str = ""
    traveler_profile: str = "business"
    policy_violations: List[str] = Field(default_factory=list)
    milestones_awarded: Dict[str, bool] = Field(default_factory=dict)
    pending_disruptions: List[DisruptionEvent] = Field(default_factory=list)
    action_history: List[Dict[str, Any]] = Field(default_factory=list)
    done_reason: str = ""
