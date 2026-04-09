"""Cloud SRE Ops OpenEnv — Typed Pydantic Models.

Defines Action, Observation, State, and supporting nested records for the
cloud infrastructure incident response benchmark.
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from openenv.core.env_server.types import Action, Observation, State

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    QUERY_METRICS = "query_metrics"
    READ_LOGS = "read_logs"
    SCALE_SERVICE = "scale_service"
    ROLLBACK_DEPLOYMENT = "rollback_deployment"
    RESTART_SERVICE = "restart_service"
    PATCH_CONFIG = "patch_config"
    WAIT = "wait"
    RESOLVE_INCIDENT = "resolve_incident"


class MetricType(str, Enum):
    CPU = "cpu"
    MEMORY = "memory"
    LATENCY = "latency"
    ERROR_RATE = "error_rate"


class ClusterStatus(str, Enum):
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"


class ServiceStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    DOWN = "down"


# ---------------------------------------------------------------------------
# Nested value objects
# ---------------------------------------------------------------------------

class Alert(BaseModel):
    """An active PagerDuty style alert."""
    alert_id: str
    service_name: str
    severity: str
    message: str
    timestamp: str  # "HH:MM"


class ServiceState(BaseModel):
    """Current state of a deployment/service."""
    service_name: str
    replicas: int
    version: str
    status: ServiceStatus


class MetricDataPoint(BaseModel):
    """A data point for a metric at a given time."""
    timestamp: str
    value: float
    unit: str


class LogEntry(BaseModel):
    """A single log entry returned in queries."""
    timestamp: str
    level: str
    message: str


# ---------------------------------------------------------------------------
# Action
# ---------------------------------------------------------------------------

class SreAction(Action):
    """Agent action sent to the environment each step."""
    action_type: ActionType = Field(..., description="Which action to perform")

    # target service
    service_name: Optional[str] = Field(None, description="Service to target (e.g. 'auth-service')")

    # query_metrics
    metric_type: Optional[MetricType] = Field(None, description="Metric to retrieve")
    time_window_minutes: Optional[int] = Field(5, description="Minutes to look back")

    # read_logs
    lines: Optional[int] = Field(10, description="Number of logs to tail")

    # scale_service
    replicas: Optional[int] = Field(None, description="Target number of replicas")

    # rollback_deployment
    version: Optional[str] = Field(None, description="Version tag to rollback to")

    # patch_config
    config_key: Optional[str] = Field(None, description="Configuration key")
    config_value: Optional[str] = Field(None, description="Configuration value")

    # wait
    wait_minutes: Optional[int] = Field(None, description="Minutes to wait/observe")


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

class SreObservation(Observation):
    """Observation returned by reset() and step()."""
    current_time: str = Field(..., description="Simulated time HH:MM")
    deadline: str = Field(..., description="Must resolve by HH:MM")
    cluster_status: ClusterStatus = Field(default=ClusterStatus.UP)
    services: List[ServiceState] = Field(default_factory=list)
    active_alerts: List[Alert] = Field(default_factory=list)
    sla_budget_remaining: float = Field(..., description="SLA budget left (hours)")
    task_brief: str = Field("", description="Human-readable incident description")
    
    # Recent action results
    last_action_result: str = Field("", description="Summary or text return of the last action")
    last_metrics: Optional[List[MetricDataPoint]] = Field(None)
    last_logs: Optional[List[LogEntry]] = Field(None)
    
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class IncidentState(State):
    """Full episode state."""
    scenario_id: str = ""
    milestones_awarded: Dict[str, bool] = Field(default_factory=dict)
    action_history: List[Dict[str, Any]] = Field(default_factory=list)
    done_reason: str = ""
    
    # Hidden system states
    internal_service_health: Dict[str, ServiceStatus] = Field(default_factory=dict)
    active_faults: List[str] = Field(default_factory=list)
    metrics_cache: Dict[str, Any] = Field(default_factory=dict)
