"""TravelOps OpenEnv — Core Environment Logic.

Business-travel execution and disruption-recovery benchmark with 3 scenarios:
  T1_DIRECT_ON_TIME          — simple direct booking
  T2_PREDEPARTURE_CANCELLATION — recovery after cancellation
  T3_DELAY_MISSED_CONNECTION  — multimodal rerouting under delay
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, List, Optional

from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

# Relative import when running behind FastAPI (server package)
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import (
    ActionType,
    Booking,
    DisruptionEvent,
    DisruptionType,
    PolicySummary,
    TravelAction,
    TravelMode,
    TravelObservation,
    TravelOption,
    TravelState,
    TripStatus,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _hhmm_to_minutes(t: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def _minutes_to_hhmm(m: int) -> str:
    """Convert minutes since midnight to 'HH:MM'."""
    m = max(0, m)
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


# ── scenario data ───────────────────────────────────────────────────────────

def _make_scenarios() -> Dict[str, Dict[str, Any]]:
    """Fixed, deterministic scenario fixtures (India intercity network)."""

    return {
        # ─── T1: Direct on-time ─────────────────────────────────────────
        "T1_DIRECT_ON_TIME": {
            "description": (
                "Book a direct flight from Bangalore to Mumbai for a "
                "client meeting. No disruptions expected."
            ),
            "origin": "Bangalore",
            "destination": "Mumbai",
            "start_time": "06:00",
            "deadline": "14:00",
            "budget": 12000.0,
            "policy": PolicySummary(
                budget_cap=12000.0,
                preferred_carriers=["IndiGo", "Air India"],
                min_connection_buffer_minutes=60,
            ),
            "options": [
                TravelOption(
                    option_id="T1_OPT1",
                    mode=TravelMode.FLIGHT,
                    carrier="IndiGo",
                    origin="Bangalore",
                    destination="Mumbai",
                    departure_time="08:00",
                    arrival_time="10:00",
                    duration_minutes=120,
                    price=5500.0,
                ),
                TravelOption(
                    option_id="T1_OPT2",
                    mode=TravelMode.FLIGHT,
                    carrier="Air India",
                    origin="Bangalore",
                    destination="Mumbai",
                    departure_time="09:30",
                    arrival_time="11:30",
                    duration_minutes=120,
                    price=7200.0,
                ),
                TravelOption(
                    option_id="T1_OPT3",
                    mode=TravelMode.TRAIN,
                    carrier="IRCTC",
                    origin="Bangalore",
                    destination="Mumbai",
                    departure_time="06:30",
                    arrival_time="18:30",
                    duration_minutes=720,
                    price=2800.0,
                ),
                TravelOption(
                    option_id="T1_OPT4",
                    mode=TravelMode.BUS,
                    carrier="RedBus",
                    origin="Bangalore",
                    destination="Mumbai",
                    departure_time="06:00",
                    arrival_time="22:00",
                    duration_minutes=960,
                    price=1800.0,
                ),
            ],
            "disruptions": [],  # none
        },

        # ─── T2: Pre-departure cancellation ─────────────────────────────
        "T2_PREDEPARTURE_CANCELLATION": {
            "description": (
                "Book a flight from Delhi to Chennai. After booking, "
                "the flight is cancelled before departure — rebook."
            ),
            "origin": "Delhi",
            "destination": "Chennai",
            "start_time": "05:00",
            "deadline": "16:00",
            "budget": 15000.0,
            "policy": PolicySummary(
                budget_cap=15000.0,
                preferred_carriers=["IndiGo", "Vistara", "Air India"],
                min_connection_buffer_minutes=60,
            ),
            "options": [
                TravelOption(
                    option_id="T2_OPT1",
                    mode=TravelMode.FLIGHT,
                    carrier="Vistara",
                    origin="Delhi",
                    destination="Chennai",
                    departure_time="07:00",
                    arrival_time="09:30",
                    duration_minutes=150,
                    price=8500.0,
                ),
                TravelOption(
                    option_id="T2_OPT2",
                    mode=TravelMode.FLIGHT,
                    carrier="IndiGo",
                    origin="Delhi",
                    destination="Chennai",
                    departure_time="09:00",
                    arrival_time="11:30",
                    duration_minutes=150,
                    price=6800.0,
                ),
                TravelOption(
                    option_id="T2_OPT3",
                    mode=TravelMode.FLIGHT,
                    carrier="Air India",
                    origin="Delhi",
                    destination="Chennai",
                    departure_time="11:00",
                    arrival_time="13:30",
                    duration_minutes=150,
                    price=9200.0,
                ),
                TravelOption(
                    option_id="T2_OPT4",
                    mode=TravelMode.TRAIN,
                    carrier="IRCTC",
                    origin="Delhi",
                    destination="Chennai",
                    departure_time="06:00",
                    arrival_time="22:00",
                    duration_minutes=960,
                    price=3500.0,
                ),
            ],
            "disruptions": [
                DisruptionEvent(
                    disruption_type=DisruptionType.CANCELLATION,
                    affected_carrier="Vistara",
                    affected_origin="Delhi",
                    affected_destination="Chennai",
                    message="Vistara DEL→MAA flight cancelled due to crew shortage.",
                    trigger_time="06:30",
                ),
            ],
        },

        # ─── T3: Delay → missed connection ─────────────────────────────
        "T3_DELAY_MISSED_CONNECTION": {
            "description": (
                "Two-leg trip: Hyderabad → Delhi → Chandigarh. "
                "First leg is delayed 90 min, causing a missed connection. "
                "Agent must find alternative routing."
            ),
            "origin": "Hyderabad",
            "destination": "Chandigarh",
            "start_time": "05:00",
            "deadline": "18:00",
            "budget": 20000.0,
            "policy": PolicySummary(
                budget_cap=20000.0,
                preferred_carriers=["IndiGo", "Air India", "Vistara"],
                min_connection_buffer_minutes=60,
            ),
            "options": [
                # Leg 1 options: HYD → DEL
                TravelOption(
                    option_id="T3_LEG1_OPT1",
                    mode=TravelMode.FLIGHT,
                    carrier="IndiGo",
                    origin="Hyderabad",
                    destination="Delhi",
                    departure_time="06:00",
                    arrival_time="08:15",
                    duration_minutes=135,
                    price=6500.0,
                    connection_id="LEG1",
                ),
                TravelOption(
                    option_id="T3_LEG1_OPT2",
                    mode=TravelMode.FLIGHT,
                    carrier="Air India",
                    origin="Hyderabad",
                    destination="Delhi",
                    departure_time="08:00",
                    arrival_time="10:15",
                    duration_minutes=135,
                    price=7800.0,
                    connection_id="LEG1",
                ),
                # Leg 2 options: DEL → IXC
                TravelOption(
                    option_id="T3_LEG2_OPT1",
                    mode=TravelMode.FLIGHT,
                    carrier="Air India",
                    origin="Delhi",
                    destination="Chandigarh",
                    departure_time="09:30",
                    arrival_time="10:30",
                    duration_minutes=60,
                    price=4500.0,
                    connection_id="LEG2",
                ),
                TravelOption(
                    option_id="T3_LEG2_OPT2",
                    mode=TravelMode.FLIGHT,
                    carrier="Vistara",
                    origin="Delhi",
                    destination="Chandigarh",
                    departure_time="12:00",
                    arrival_time="13:00",
                    duration_minutes=60,
                    price=5200.0,
                    connection_id="LEG2",
                ),
                TravelOption(
                    option_id="T3_LEG2_OPT3",
                    mode=TravelMode.TRAIN,
                    carrier="IRCTC",
                    origin="Delhi",
                    destination="Chandigarh",
                    departure_time="11:00",
                    arrival_time="14:30",
                    duration_minutes=210,
                    price=1200.0,
                    connection_id="LEG2",
                ),
                TravelOption(
                    option_id="T3_LEG2_OPT4",
                    mode=TravelMode.BUS,
                    carrier="HRTC",
                    origin="Delhi",
                    destination="Chandigarh",
                    departure_time="10:30",
                    arrival_time="15:30",
                    duration_minutes=300,
                    price=800.0,
                    connection_id="LEG2",
                ),
            ],
            "disruptions": [
                DisruptionEvent(
                    disruption_type=DisruptionType.DELAY,
                    affected_carrier="IndiGo",
                    affected_origin="Hyderabad",
                    affected_destination="Delhi",
                    delay_minutes=90,
                    message="IndiGo HYD→DEL delayed 90 min due to weather.",
                    trigger_time="05:45",
                ),
            ],
        },
    }


SCENARIOS = _make_scenarios()
SCENARIO_IDS = list(SCENARIOS.keys())


# ── environment ─────────────────────────────────────────────────────────────

class TravelOpsEnvironment(Environment):
    """OpenEnv Environment for business-travel benchmarking."""

    def __init__(self) -> None:
        self._scenario_idx: int = 0
        self._state: TravelState = TravelState(episode_id="", step_count=0)
        self._scenario: Dict[str, Any] = {}
        self._sim_minutes: int = 0
        self._budget_spent: float = 0.0
        self._bookings: List[Booking] = []
        self._last_search: List[TravelOption] = []
        self._disruption_fired: bool = False
        self._done: bool = False
        self._cumulative_reward: float = 0.0
        self._current_city: str = ""
        self._options_map: Dict[str, TravelOption] = {}
        self._booking_counter: int = 0

    # ── interface ────────────────────────────────────────────────────────

    def reset(self, scenario_id: Optional[str] = None) -> TravelObservation:
        """Start (or restart) an episode for a given scenario."""
        if scenario_id and scenario_id in SCENARIOS:
            self._scenario_idx = SCENARIO_IDS.index(scenario_id)
        sid = SCENARIO_IDS[self._scenario_idx % len(SCENARIO_IDS)]
        self._scenario = copy.deepcopy(SCENARIOS[sid])

        self._state = TravelState(
            episode_id=str(uuid.uuid4())[:12],
            step_count=0,
            scenario_id=sid,
        )
        self._state.milestones_awarded = {
            "discovery": False,
            "compliant_itinerary": False,
            "recovery": False,
            "completion": False,
        }
        self._state.pending_disruptions = copy.deepcopy(
            self._scenario.get("disruptions", [])
        )

        self._sim_minutes = _hhmm_to_minutes(self._scenario["start_time"])
        self._budget_spent = 0.0
        self._bookings = []
        self._last_search = []
        self._disruption_fired = False
        self._done = False
        self._cumulative_reward = 0.0
        self._current_city = self._scenario["origin"]
        self._booking_counter = 0

        # build option lookup
        self._options_map = {
            o.option_id: o for o in self._scenario["options"]
        }

        # advance scenario index for next call
        self._scenario_idx += 1

        return self._build_observation(reward=0.0, info_msg="Episode started. Review your task brief and search for options.")

    def step(self, action: TravelAction) -> TravelObservation:
        """Execute one agent action."""
        if self._done:
            return self._build_observation(reward=0.0, info_msg="Episode already done.")

        self._state.step_count += 1
        self._state.action_history.append(action.model_dump())

        # ── check disruptions ──
        self._check_disruptions()

        # ── dispatch ──
        handler = {
            ActionType.SEARCH_OPTIONS: self._handle_search,
            ActionType.BOOK_OPTION: self._handle_book,
            ActionType.CANCEL_BOOKING: self._handle_cancel,
            ActionType.WAIT: self._handle_wait,
            ActionType.FINALIZE_TRIP: self._handle_finalize,
        }.get(action.action_type)

        if handler is None:
            return self._build_observation(reward=0.0, info_msg="Unknown action type.")

        return handler(action)

    @property
    def state(self) -> TravelState:
        return self._state

    # ── action handlers ──────────────────────────────────────────────────

    def _handle_search(self, action: TravelAction) -> TravelObservation:
        origin = action.origin or self._current_city
        destination = action.destination or self._scenario["destination"]
        modes = set(action.allowed_modes) if action.allowed_modes else None

        results: List[TravelOption] = []
        for opt in self._scenario["options"]:
            if opt.origin != origin:
                continue
            if opt.destination != destination:
                continue
            if modes and opt.mode not in modes:
                continue
            # filter by departure time
            opt_dep = _hhmm_to_minutes(opt.departure_time)
            if action.earliest_departure:
                if opt_dep < _hhmm_to_minutes(action.earliest_departure):
                    continue
            if action.latest_arrival:
                opt_arr = _hhmm_to_minutes(opt.arrival_time)
                if opt_arr > _hhmm_to_minutes(action.latest_arrival):
                    continue
            # account for delays on disrupted options
            actual_opt = self._apply_delay_to_option(opt)
            results.append(actual_opt)

        self._last_search = results

        # milestone: discovery
        reward = 0.0
        if results and not self._state.milestones_awarded.get("discovery"):
            self._state.milestones_awarded["discovery"] = True
            reward = 0.2
            self._cumulative_reward += reward

        msg = f"Found {len(results)} option(s) from {origin} to {destination}."
        return self._build_observation(reward=reward, info_msg=msg)

    def _handle_book(self, action: TravelAction) -> TravelObservation:
        oid = action.option_id
        if not oid or oid not in self._options_map:
            return self._build_observation(reward=0.0, info_msg=f"Invalid option_id '{oid}'.")

        # duplicate check
        for bk in self._bookings:
            if bk.option.option_id == oid and bk.status == "confirmed":
                return self._build_observation(reward=0.0, info_msg="Option already booked.")

        opt = self._apply_delay_to_option(self._options_map[oid])

        # check if departure is in the future
        if _hhmm_to_minutes(opt.departure_time) < self._sim_minutes:
            return self._build_observation(reward=0.0, info_msg="Cannot book: departure already passed.")

        price = opt.price
        policy: PolicySummary = self._scenario["policy"]

        # budget check
        if self._budget_spent + price > policy.budget_cap:
            self._state.policy_violations.append("budget_exceeded")
            return self._build_observation(reward=0.0, info_msg="Booking would exceed budget cap.")

        # preferred-carrier check (warn but allow)
        carrier_compliant = opt.carrier in policy.preferred_carriers

        self._booking_counter += 1
        bid = f"BK{self._booking_counter:03d}"
        booking = Booking(booking_id=bid, option=opt, status="confirmed")
        self._bookings.append(booking)
        self._budget_spent += price

        # milestone: compliant itinerary
        reward = 0.0
        if not self._state.milestones_awarded.get("compliant_itinerary"):
            if self._itinerary_reaches_destination() and carrier_compliant:
                self._state.milestones_awarded["compliant_itinerary"] = True
                reward = 0.3
                self._cumulative_reward += reward

        msg = f"Booked {bid}: {opt.carrier} {opt.origin}→{opt.destination} at ₹{price:.0f}."
        if not carrier_compliant:
            msg += " (non-preferred carrier)"
        return self._build_observation(reward=reward, info_msg=msg)

    def _handle_cancel(self, action: TravelAction) -> TravelObservation:
        bid = action.booking_id
        found = None
        for bk in self._bookings:
            if bk.booking_id == bid and bk.status == "confirmed":
                found = bk
                break
        if found is None:
            return self._build_observation(reward=0.0, info_msg=f"No active booking '{bid}'.")

        found.status = "cancelled"
        self._budget_spent -= found.option.price  # refund
        return self._build_observation(reward=0.0, info_msg=f"Cancelled {bid}. ₹{found.option.price:.0f} refunded.")

    def _handle_wait(self, action: TravelAction) -> TravelObservation:
        minutes = action.wait_minutes or 30
        minutes = max(0, min(minutes, 480))  # cap at 8 hours
        self._sim_minutes += minutes

        # check disruptions after advancing time
        self._check_disruptions()

        # auto-advance city if departing booking has passed
        self._auto_advance_city()

        deadline_min = _hhmm_to_minutes(self._scenario["deadline"])
        if self._sim_minutes >= deadline_min and self._current_city != self._scenario["destination"]:
            self._done = True
            self._state.done_reason = "deadline_expired"
            return self._build_observation(reward=0.0, info_msg="Deadline expired — trip failed.")

        return self._build_observation(reward=0.0, info_msg=f"Waited {minutes} min. Time is now {_minutes_to_hhmm(self._sim_minutes)}.")

    def _handle_finalize(self, action: TravelAction) -> TravelObservation:
        if self._current_city != self._scenario["destination"]:
            return self._build_observation(reward=0.0, info_msg="Cannot finalize: not at destination.")

        deadline_min = _hhmm_to_minutes(self._scenario["deadline"])
        if self._sim_minutes > deadline_min:
            self._done = True
            self._state.done_reason = "finalized_late"
            return self._build_observation(reward=0.0, info_msg="Arrived after deadline — trip scored as late.")

        # milestone: completion
        reward = 0.0
        if not self._state.milestones_awarded.get("completion"):
            self._state.milestones_awarded["completion"] = True
            reward = 0.3
            self._cumulative_reward += reward

        self._done = True
        self._state.done_reason = "finalized_on_time"
        score = self._compute_final_score()
        return self._build_observation(
            reward=reward,
            info_msg=f"Trip finalized on time! Final score: {score:.2f}",
        )

    # ── disruption logic ─────────────────────────────────────────────────

    def _check_disruptions(self) -> None:
        """Fire pending disruptions whose trigger_time ≤ sim_minutes."""
        still_pending = []
        for d in self._state.pending_disruptions:
            if _hhmm_to_minutes(d.trigger_time) <= self._sim_minutes:
                self._fire_disruption(d)
            else:
                still_pending.append(d)
        self._state.pending_disruptions = still_pending

    def _fire_disruption(self, d: DisruptionEvent) -> None:
        self._disruption_fired = True
        # mark matching bookings
        for bk in self._bookings:
            if bk.status != "confirmed":
                continue
            opt = bk.option
            match = (
                (d.affected_carrier is None or opt.carrier == d.affected_carrier)
                and (d.affected_origin is None or opt.origin == d.affected_origin)
                and (d.affected_destination is None or opt.destination == d.affected_destination)
            )
            if match:
                if d.disruption_type == DisruptionType.CANCELLATION:
                    bk.status = "cancelled"
                    self._budget_spent -= opt.price
                elif d.disruption_type == DisruptionType.DELAY:
                    # update option times
                    dep = _hhmm_to_minutes(opt.departure_time) + (d.delay_minutes or 0)
                    arr = _hhmm_to_minutes(opt.arrival_time) + (d.delay_minutes or 0)
                    bk.option = opt.model_copy(update={
                        "departure_time": _minutes_to_hhmm(dep),
                        "arrival_time": _minutes_to_hhmm(arr),
                    })
                    bk.status = "disrupted"

        # Store as active disruption in state for the agent to see
        self._state.action_history.append({"disruption": d.model_dump()})

    def _apply_delay_to_option(self, opt: TravelOption) -> TravelOption:
        """Return option with delays applied (from fired disruptions only)."""
        for d in self._scenario.get("disruptions", []):
            if _hhmm_to_minutes(d.trigger_time) > self._sim_minutes:
                continue
            if d.disruption_type != DisruptionType.DELAY:
                continue
            if (d.affected_carrier and opt.carrier == d.affected_carrier
                    and (d.affected_origin is None or opt.origin == d.affected_origin)
                    and (d.affected_destination is None or opt.destination == d.affected_destination)):
                dep = _hhmm_to_minutes(opt.departure_time) + (d.delay_minutes or 0)
                arr = _hhmm_to_minutes(opt.arrival_time) + (d.delay_minutes or 0)
                return opt.model_copy(update={
                    "departure_time": _minutes_to_hhmm(dep),
                    "arrival_time": _minutes_to_hhmm(arr),
                })
        return opt

    # ── city advancement ─────────────────────────────────────────────────

    def _auto_advance_city(self) -> None:
        """Move traveller city forward based on completed legs."""
        for bk in self._bookings:
            if bk.status not in ("confirmed", "disrupted"):
                continue
            arr_min = _hhmm_to_minutes(bk.option.arrival_time)
            if (bk.option.origin == self._current_city
                    and self._sim_minutes >= arr_min):
                self._current_city = bk.option.destination

    # ── itinerary checks ─────────────────────────────────────────────────

    def _itinerary_reaches_destination(self) -> bool:
        """Check if confirmed bookings form a chain to the destination."""
        city = self._current_city
        dest = self._scenario["destination"]
        confirmed = [bk for bk in self._bookings if bk.status in ("confirmed", "disrupted")]
        # simple greedy chain
        changed = True
        while changed:
            changed = False
            for bk in confirmed:
                if bk.option.origin == city:
                    city = bk.option.destination
                    changed = True
                    if city == dest:
                        return True
        return city == dest

    # ── scoring ──────────────────────────────────────────────────────────

    def _compute_final_score(self) -> float:
        """Deterministic grader score in [0.0, 1.0]."""
        score = 0.0
        milestones = self._state.milestones_awarded

        # discovery: 0.15
        if milestones.get("discovery"):
            score += 0.15

        # compliant_itinerary: 0.25
        if milestones.get("compliant_itinerary"):
            score += 0.25

        # recovery: 0.25 (only counts if disruption scenario)
        has_disruptions = len(self._scenario.get("disruptions", [])) > 0
        if has_disruptions:
            if milestones.get("recovery"):
                score += 0.25
        else:
            # no disruptions → grant recovery points automatically
            score += 0.25

        # completion: 0.20
        if milestones.get("completion"):
            score += 0.20

        # cost efficiency bonus: up to 0.10
        policy: PolicySummary = self._scenario["policy"]
        if self._budget_spent <= policy.budget_cap * 0.6:
            score += 0.10
        elif self._budget_spent <= policy.budget_cap * 0.8:
            score += 0.05

        # action efficiency: up to 0.05
        if self._state.step_count <= 6:
            score += 0.05
        elif self._state.step_count <= 9:
            score += 0.02

        # penalties
        if self._state.policy_violations:
            score -= 0.10 * len(self._state.policy_violations)

        return max(0.0, min(1.0, round(score, 4)))

    # ── observation builder ──────────────────────────────────────────────

    def _build_observation(self, reward: float, info_msg: str) -> TravelObservation:
        # find active disruption to surface
        active_disruption = None
        if self._disruption_fired:
            for d_dict in reversed(self._state.action_history):
                if "disruption" in d_dict:
                    active_disruption = DisruptionEvent(**d_dict["disruption"])
                    break

        # after disruption, check recovery milestone
        if (self._disruption_fired
                and not self._state.milestones_awarded.get("recovery")
                and self._itinerary_reaches_destination()):
            self._state.milestones_awarded["recovery"] = True
            reward += 0.2
            self._cumulative_reward += 0.2

        score = self._compute_final_score() if self._done else None

        obs = TravelObservation(
            current_city=self._current_city,
            current_time=_minutes_to_hhmm(self._sim_minutes),
            deadline=self._scenario["deadline"],
            remaining_budget=self._scenario["policy"].budget_cap - self._budget_spent,
            active_bookings=[bk for bk in self._bookings],
            last_search_results=self._last_search,
            active_disruption=active_disruption,
            trip_status=(
                TripStatus.COMPLETED if self._done and "on_time" in (self._state.done_reason or "")
                else TripStatus.FAILED if self._done
                else TripStatus.IN_PROGRESS if self._bookings
                else TripStatus.NOT_STARTED
            ),
            task_brief=self._scenario["description"],
            done=self._done,
            reward=reward,
            metadata={
                "info": info_msg,
                "cumulative_reward": round(self._cumulative_reward, 4),
                "scenario_id": self._state.scenario_id,
                "step": self._state.step_count,
                **({"final_score": score} if score is not None else {}),
            },
        )
        return obs
