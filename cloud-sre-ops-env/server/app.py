"""FastAPI server for the Cloud SRE Ops Environment."""

from fastapi import FastAPI
from openenv.core.env_server.server import EnvServer

from .sre_ops_environment import SreOpsEnvironment
from models import SreAction, SreObservation

app = FastAPI(title="Cloud SRE Ops OpenEnv")

# Mount the OpenEnv websocket routes
env_server = EnvServer(
    env_class=SreOpsEnvironment,
    action_model=SreAction,
    observation_model=SreObservation,
)
app.include_router(env_server.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000, reload=True)
