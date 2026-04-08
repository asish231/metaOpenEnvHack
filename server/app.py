"""TravelOps OpenEnv — FastAPI server entry point."""

from openenv.core.env_server import create_app

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import TravelAction, TravelObservation
from server.travel_ops_environment import TravelOpsEnvironment

app = create_app(
    TravelOpsEnvironment,
    TravelAction,
    TravelObservation,
    env_name="travel_ops_env",
)

def main():
    import uvicorn
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000, reload=False)

if __name__ == "__main__":
    main()
