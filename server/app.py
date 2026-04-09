"""TravelOps OpenEnv — FastAPI server entry point."""

from openenv.core.env_server import create_app

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import TravelAction, TravelObservation  # type: ignore
from server.travel_ops_environment import TravelOpsEnvironment  # type: ignore

app = create_app(
    TravelOpsEnvironment,
    TravelAction,
    TravelObservation,
    env_name="travel_ops_env",
)

@app.get("/")
def read_root():
    return {
        "status": "success",
        "message": "Welcome to the TravelOps OpenEnv Benchmark space!",
        "endpoints": {
            "websocket": "/ws"
        }
    }

def main():
    import uvicorn
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000, reload=False)

if __name__ == "__main__":
    main()
