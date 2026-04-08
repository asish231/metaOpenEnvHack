# TravelOps — Business-Travel Execution & Disruption Recovery

> An OpenEnv benchmark where an AI agent must search, book, and recover multi-modal itineraries across India's intercity network under budget, policy, and time constraints.

---

## Overview

TravelOps simulates a realistic **business-travel operations** scenario. A corporate traveller needs to reach their destination on time and within budget. The agent must:

- **Search** for travel options (flights, trains, buses)
- **Book** compliant itineraries respecting company policy
- **Handle disruptions** (cancellations, delays, missed connections)
- **Recover** by rebooking alternative routes
- **Finalize** the trip upon reaching the destination

The environment uses a fixed, deterministic India intercity network with realistic carriers (IndiGo, Air India, Vistara, IRCTC, etc.).

---

## Action Space

| Action | Required Fields | Description |
|--------|----------------|-------------|
| `search_options` | `origin`, `destination` | Search available travel options. Optional: `earliest_departure`, `latest_arrival`, `allowed_modes` |
| `book_option` | `option_id` | Book a travel option from search results |
| `cancel_booking` | `booking_id` | Cancel an existing booking (with refund) |
| `wait` | `wait_minutes` | Advance simulated clock (1–480 min) |
| `finalize_trip` | — | Declare trip complete (must be at destination) |

### Action JSON Examples

```json
{"action_type": "search_options", "origin": "Bangalore", "destination": "Mumbai"}
{"action_type": "book_option", "option_id": "T1_OPT1"}
{"action_type": "cancel_booking", "booking_id": "BK001"}
{"action_type": "wait", "wait_minutes": 60}
{"action_type": "finalize_trip"}
```

---

## Observation Space

Each observation contains:

| Field | Type | Description |
|-------|------|-------------|
| `current_city` | string | Traveller's current location |
| `current_time` | string | Simulated time (HH:MM) |
| `deadline` | string | Must arrive by (HH:MM) |
| `remaining_budget` | float | Budget left in INR |
| `active_bookings` | list | Current bookings with status |
| `last_search_results` | list | Results from last search |
| `active_disruption` | object/null | Active disruption event |
| `trip_status` | enum | not_started / in_progress / completed / failed |
| `task_brief` | string | Human-readable task description |
| `metadata` | dict | Step info, cumulative reward, final score |

---

## Benchmark Tasks

### T1: Direct On-Time (Easy)
- **Route**: Bangalore → Mumbai
- **Challenge**: Simple direct booking
- **Disruptions**: None
- **Tests**: Search, compliant booking, finalization

### T2: Pre-departure Cancellation (Medium)
- **Route**: Delhi → Chennai
- **Challenge**: Booked flight gets cancelled before departure
- **Disruptions**: Vistara cancellation at 06:30
- **Tests**: Recovery and rebooking

### T3: Delay & Missed Connection (Hard)
- **Route**: Hyderabad → Delhi → Chandigarh (two legs)
- **Challenge**: First leg delayed 90 min, causing missed connection
- **Disruptions**: IndiGo HYD→DEL delayed at 05:45
- **Tests**: Multimodal rerouting under time pressure

---

## Reward Design

Additive milestone rewards capped at 1.0:

| Milestone | Reward | Condition |
|-----------|--------|-----------|
| Discovery | +0.20 | Agent finds at least one feasible option |
| Compliant Itinerary | +0.30 | Books a budget/policy-compliant route |
| Recovery | +0.20 | After disruption, restores a valid itinerary |
| Completion | +0.30 | Reaches destination on time and finalizes |

Invalid/redundant actions yield 0.0 reward. Policy violations block milestones.

### Grader Score (0.0–1.0)

Final score factors: discovery (0.15), compliance (0.25), recovery (0.25), completion (0.20), cost efficiency (0.10), action efficiency (0.05).

---

## Setup & Usage

### Prerequisites
- Python 3.10+
- Docker (for deployment)

### Install
```bash
pip install openenv-core
pip install -e .
```

### Run Server Locally
```bash
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

### Run Inference
```bash
export API_BASE_URL="https://api.openai.com/v1"
export MODEL_NAME="gpt-4o-mini"
export OPENAI_API_KEY="sk-..."
python inference.py
```

### Docker
```bash
docker build -f server/Dockerfile -t travel-ops-env .
docker run -p 8000:8000 travel-ops-env
```

### Deploy to Hugging Face
```bash
openenv push --repo-id your-username/travel-ops-env
```

---

## Baseline Scores

| Task | Expected Score |
|------|---------------|
| T1_DIRECT_ON_TIME | 0.85–1.00 |
| T2_PREDEPARTURE_CANCELLATION | 0.70–0.95 |
| T3_DELAY_MISSED_CONNECTION | 0.55–0.85 |
| **Average** | **0.70–0.93** |

---

## Project Structure

```
.
├── __init__.py              # Package exports
├── models.py                # Pydantic Action/Observation/State models
├── client.py                # Typed EnvClient (WebSocket)
├── openenv.yaml             # OpenEnv manifest
├── pyproject.toml            # Python dependencies
├── inference.py             # Hackathon inference script
├── README.md                # This file
└── server/
    ├── __init__.py
    ├── travel_ops_environment.py  # Core environment logic
    ├── app.py                     # FastAPI server
    ├── Dockerfile                 # Container definition
    └── requirements.txt           # Server dependencies
```

---

## License

MIT
