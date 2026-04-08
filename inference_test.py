#!/usr/bin/env python3
"""TravelOps OpenEnv — Hackathon Inference Script.

Runs all 3 benchmark tasks using an LLM via the OpenAI client.
Emits structured [START], [STEP], [END] logs per hackathon spec.

Environment variables:
    API_BASE_URL  — LLM API endpoint
    MODEL_NAME    — model identifier
    ZAI_API_KEY   — Z.ai API key (fallback: OPENAI_API_KEY or HF_TOKEN)
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

# ── ensure project root is importable ───────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import (
    ActionType,
    TravelAction,
    TravelMode,
)
from server.travel_ops_environment import TravelOpsEnvironment, SCENARIO_IDS

# ── LLM client setup ───────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()  # Load variables from .env

API_BASE_URL = os.environ.get("API_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
MODEL_NAME = os.environ.get("MODEL_NAME", "GLM-4.7-Flash")
API_KEY = (
    os.environ.get("ZAI_API_KEY")
    or os.environ.get("OPENAI_API_KEY")
    or os.environ.get("HF_TOKEN", "")
)

try:
    from zai import ZaiClient
    client = ZaiClient(api_key=API_KEY)
    LLM_AVAILABLE = True
except Exception as e:
    LLM_AVAILABLE = False
    client = None
    print(f"Error loading ZaiClient: {e}", file=sys.stderr)

MAX_STEPS = 12

# ── system prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a business-travel operations agent. You interact with a travel environment by outputting **one JSON action per turn**.

### Action schema (choose exactly one action_type per step):

1. **search_options** — Search for travel options.
   Required: origin, destination
   Optional: earliest_departure (HH:MM), latest_arrival (HH:MM), allowed_modes (list of "flight"/"train"/"bus")

2. **book_option** — Book a specific travel option.
   Required: option_id (from search results)

3. **cancel_booking** — Cancel an existing booking.
   Required: booking_id

4. **wait** — Advance simulated clock.
   Required: wait_minutes (integer, 1-480)

5. **finalize_trip** — Declare the trip complete (must be at destination city).

### Rules:
- Stay within the budget.
- Prefer carriers listed in the policy.
- Meet the deadline.
- After a disruption, cancel affected bookings and rebook.
- When at the destination, finalize immediately.

### Output format — ONLY valid JSON, nothing else:
{"action_type": "...", ...fields...}
"""


def _build_user_message(obs_dict: dict, step: int) -> str:
    """Format observation into a concise user prompt."""
    lines = [
        f"[Step {step}]",
        f"City: {obs_dict['current_city']}  Time: {obs_dict['current_time']}  Deadline: {obs_dict['deadline']}",
        f"Budget remaining: ₹{obs_dict['remaining_budget']:.0f}",
        f"Task: {obs_dict['task_brief']}",
    ]
    if obs_dict.get("active_disruption"):
        d = obs_dict["active_disruption"]
        lines.append(f"⚠ DISRUPTION: {d.get('message', d.get('disruption_type', 'unknown'))}")
    if obs_dict.get("active_bookings"):
        lines.append("Active bookings:")
        for bk in obs_dict["active_bookings"]:
            o = bk["option"]
            lines.append(
                f"  {bk['booking_id']} [{bk['status']}] {o['carrier']} "
                f"{o['origin']}→{o['destination']} dep {o['departure_time']} "
                f"arr {o['arrival_time']} ₹{o['price']:.0f}"
            )
    if obs_dict.get("last_search_results"):
        lines.append("Search results:")
        for o in obs_dict["last_search_results"]:
            lines.append(
                f"  {o['option_id']}: {o['carrier']} {o['mode']} "
                f"{o['origin']}→{o['destination']} dep {o['departure_time']} "
                f"arr {o['arrival_time']} ₹{o['price']:.0f}"
            )
    if obs_dict.get("metadata", {}).get("info"):
        lines.append(f"Info: {obs_dict['metadata']['info']}")
    return "\n".join(lines)


def _parse_llm_action(raw: str) -> TravelAction:
    """Parse LLM JSON output into a TravelAction, with fallback."""
    # strip markdown fences
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    # try to find JSON object
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]

    data = json.loads(text)

    # normalise allowed_modes
    if "allowed_modes" in data and data["allowed_modes"]:
        data["allowed_modes"] = [
            m if isinstance(m, TravelMode) else TravelMode(m)
            for m in data["allowed_modes"]
        ]

    return TravelAction(**data)


def _extract_route(task_brief: str) -> list[str]:
    """Extract ordered city list from a task brief string."""
    import re
    # Try "→" route pattern first: e.g. "Hyderabad → Delhi → Chandigarh"
    if "→" in task_brief:
        # Get the part containing arrows (before first period after the arrow chain)
        arrow_part = task_brief.split(".")[0] if "." in task_brief else task_brief
        # If there's a colon before arrows, take after it
        if ":" in arrow_part and arrow_part.index(":") < arrow_part.index("→"):
            arrow_part = arrow_part.split(":", 1)[1]
        cities = [c.strip() for c in arrow_part.split("→")]
        cities = [c for c in cities if c]
        if len(cities) >= 2:
            return cities
    # Try "from X to Y" pattern
    m = re.search(r"from\s+(\w[\w\s]*?)\s+to\s+(\w[\w\s]*?)[\s.,]", task_brief, re.IGNORECASE)
    if m:
        return [m.group(1).strip(), m.group(2).strip()]
    return []


def _safe_fallback_action(obs_dict: dict, scenario_id: str = "") -> TravelAction:
    """Smart deterministic fallback when LLM output is unparseable."""
    bookings = obs_dict.get("active_bookings", [])
    search_results = obs_dict.get("last_search_results", [])
    current_city = obs_dict.get("current_city", "")
    task_brief = obs_dict.get("task_brief", "")
    disruption = obs_dict.get("active_disruption")

    route = _extract_route(task_brief)
    final_dest = route[-1] if route else ""

    # confirmed bookings only
    confirmed = [b for b in bookings if b.get("status") == "confirmed"]

    # 1) If there are disrupted bookings, cancel them to free budget
    for b in bookings:
        if b.get("status") == "disrupted":
            return TravelAction(action_type=ActionType.CANCEL_BOOKING, booking_id=b["booking_id"])

    # 2) If at final destination → finalize
    if current_city and current_city == final_dest:
        return TravelAction(action_type=ActionType.FINALIZE_TRIP)

    # 3) Figure out what city we need to reach next along the route
    next_dest = final_dest
    for i, city in enumerate(route):
        if city == current_city and i + 1 < len(route):
            next_dest = route[i + 1]
            break

    if not next_dest:
        return TravelAction(action_type=ActionType.WAIT, wait_minutes=60)

    # 4) If no search results for current leg, search
    has_results_for_leg = any(
        r.get("origin") == current_city and r.get("destination") == next_dest
        for r in search_results
    )

    if not has_results_for_leg:
        return TravelAction(
            action_type=ActionType.SEARCH_OPTIONS,
            origin=current_city,
            destination=next_dest,
        )

    # 5) If we have results but no confirmed booking for this leg, book the best flight
    has_booking_for_leg = any(
        b.get("option", {}).get("origin") == current_city
        and b.get("option", {}).get("destination") == next_dest
        for b in confirmed
    )

    if not has_booking_for_leg and search_results:
        current_time = obs_dict.get("current_time", "00:00")
        # filter: departure must be in the future, then prefer flights, then cheapest
        candidates = [
            r for r in search_results
            if r.get("origin") == current_city and r.get("destination") == next_dest
            and r.get("departure_time", "00:00") >= current_time
        ]
        if candidates:
            # sort: flights first, then by price
            candidates.sort(key=lambda r: (0 if r.get("mode") == "flight" else 1, r.get("price", 999999)))
            return TravelAction(action_type=ActionType.BOOK_OPTION, option_id=candidates[0]["option_id"])

    # 6) We have a booking — wait to advance time (larger increments)
    return TravelAction(action_type=ActionType.WAIT, wait_minutes=120)


# ── main loop ───────────────────────────────────────────────────────────────

def run_task(env: TravelOpsEnvironment, scenario_id: str, task_idx: int) -> dict:
    """Run one task, return score dict."""
    obs = env.reset(scenario_id=scenario_id)
    obs_dict = obs.model_dump()

    print(f"[START] task_id={scenario_id} task_index={task_idx}")

    total_reward = 0.0
    for step in range(1, MAX_STEPS + 1):
        if obs_dict.get("done", False):
            break

        # get LLM action
        action = None
        llm_raw = ""
        try:
            if LLM_AVAILABLE and client is not None:
                user_msg = _build_user_message(obs_dict, step)
                resp = client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.0,
                    max_tokens=300,
                )
                llm_raw = resp.choices[0].message.content or ""
                action = _parse_llm_action(llm_raw)
            else:
                action = _safe_fallback_action(obs_dict)
        except Exception as e:
            print(f"  [WARN] LLM parse error step {step}: {e}", file=sys.stderr)
            action = _safe_fallback_action(obs_dict)

        # step
        obs = env.step(action)
        obs_dict = obs.model_dump()
        reward = obs_dict.get("reward", 0.0) or 0.0
        total_reward += reward

        print(
            f"[STEP] task_id={scenario_id} step={step} "
            f"action={action.action_type.value} "
            f"reward={reward:.4f} "
            f"done={obs_dict.get('done', False)} "
            f"info={obs_dict.get('metadata', {}).get('info', '')}"
        )

        if obs_dict.get("done", False):
            break

    # if not finalized and at destination, auto-finalize
    if not obs_dict.get("done", False):
        obs = env.step(TravelAction(action_type=ActionType.FINALIZE_TRIP))
        obs_dict = obs.model_dump()
        reward = obs_dict.get("reward", 0.0) or 0.0
        total_reward += reward
        print(
            f"[STEP] task_id={scenario_id} step=auto_finalize "
            f"action=finalize_trip reward={reward:.4f} "
            f"done={obs_dict.get('done', False)} "
            f"info={obs_dict.get('metadata', {}).get('info', '')}"
        )

    final_score = obs_dict.get("metadata", {}).get("final_score", total_reward)
    if final_score is None:
        final_score = total_reward

    print(
        f"[END] task_id={scenario_id} "
        f"total_reward={total_reward:.4f} "
        f"final_score={final_score:.4f}"
    )

    return {
        "task_id": scenario_id,
        "total_reward": round(total_reward, 4),
        "final_score": round(final_score, 4) if final_score else 0.0,
    }


def main():
    print("=" * 60)
    print("  TravelOps OpenEnv — Inference")
    print("=" * 60)
    print(f"  API_BASE_URL: {API_BASE_URL}")
    print(f"  MODEL_NAME:   {MODEL_NAME}")
    print(f"  LLM available: {LLM_AVAILABLE}")
    print(f"  Scenarios:    {SCENARIO_IDS}")
    print("=" * 60)

    env = TravelOpsEnvironment()
    results = []

    for idx, sid in enumerate(SCENARIO_IDS):
        try:
            r = run_task(env, sid, idx)
            results.append(r)
        except Exception as e:
            print(f"[ERROR] task {sid}: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            results.append({"task_id": sid, "total_reward": 0.0, "final_score": 0.0})

    print()
    print("=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    for r in results:
        print(f"  {r['task_id']}: score={r['final_score']:.4f}")
    avg = sum(r["final_score"] for r in results) / max(len(results), 1)
    print(f"  Average score: {avg:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
