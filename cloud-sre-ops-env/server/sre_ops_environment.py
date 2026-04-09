"""Cloud SRE Ops OpenEnv — Core Environment Logic.

Simulates Kubernetes-like microservices cluster incident response:
  T1_MEMORY_LEAK        — scale or rollback auth-service memory leak
  T2_BAD_RELEASE        — rollback a faulty payment-service deployment
  T3_CASCADING_FAILURE  — rate-limit API Gateway + scale database
"""

from __future__ import annotations

import copy
import uuid
import random
from typing import Any, Dict, List, Optional

from openenv.core.env_server.interfaces import Environment

# Relative import when running behind FastAPI (server package)
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import (  # type: ignore
    ActionType,
    Alert,
    ClusterStatus,
    IncidentState,
    LogEntry,
    MetricDataPoint,
    MetricType,
    ServiceState,
    ServiceStatus,
    SreAction,
    SreObservation,
)


def _hhmm_to_minutes(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def _minutes_to_hhmm(m: int) -> str:
    m = max(0, m)
    return f"{(m // 60) % 24:02d}:{m % 60:02d}"


def _make_scenarios() -> Dict[str, Dict[str, Any]]:
    return {
        "T1_MEMORY_LEAK": {
            "description": "PagerDuty Alert: `auth-service` latency high. Memory utilization is growing. Find the cause and remediate (scale, restart, or rollback).",
            "start_time": "10:00",
            "deadline": "11:00",
            "sla_budget_hours": 1.0,
            "initial_services": {
                "auth-service": {"replicas": 2, "version": "v1.2.4", "status": ServiceStatus.WARNING},
                "api-gateway": {"replicas": 3, "version": "v3.0.0", "status": ServiceStatus.HEALTHY},
                "payment-service": {"replicas": 2, "version": "v2.1.0", "status": ServiceStatus.HEALTHY},
                "database-cluster": {"replicas": 3, "version": "v14.5", "status": ServiceStatus.HEALTHY},
            },
            "faults": ["auth_memory_leak"],
        },
        "T2_BAD_RELEASE": {
            "description": "PagerDuty Alert: `payment-service` HTTP 500 error rate spiked after a recent release. Identify the bad release from logs and roll it back.",
            "start_time": "14:00",
            "deadline": "15:00",
            "sla_budget_hours": 1.0,
            "initial_services": {
                "auth-service": {"replicas": 2, "version": "v1.2.3", "status": ServiceStatus.HEALTHY},
                "api-gateway": {"replicas": 3, "version": "v3.0.0", "status": ServiceStatus.HEALTHY},
                "payment-service": {"replicas": 2, "version": "v2.2.0-rc1", "status": ServiceStatus.CRITICAL},
                "database-cluster": {"replicas": 3, "version": "v14.5", "status": ServiceStatus.HEALTHY},
            },
            "faults": ["payment_bad_release"],
        },
        "T3_CASCADING_FAILURE": {
            "description": "Major Outage: DB latency > 5000ms. `api-gateway` traffic spiked, locking `database-cluster`. Rate-limit the gateway and scale the DB.",
            "start_time": "02:00",
            "deadline": "03:00",
            "sla_budget_hours": 1.0,
            "initial_services": {
                "auth-service": {"replicas": 5, "version": "v1.2.3", "status": ServiceStatus.WARNING},
                "api-gateway": {"replicas": 10, "version": "v3.0.0", "status": ServiceStatus.CRITICAL},
                "payment-service": {"replicas": 3, "version": "v2.1.0", "status": ServiceStatus.WARNING},
                "database-cluster": {"replicas": 3, "version": "v14.5", "status": ServiceStatus.CRITICAL},
            },
            "faults": ["db_thundering_herd"],
        },
    }

SCENARIOS = _make_scenarios()
SCENARIO_IDS = list(SCENARIOS.keys())

class SreOpsEnvironment(Environment):
    def __init__(self) -> None:
        self._scenario_idx: int = 0
        self._state: IncidentState = IncidentState(episode_id="", step_count=0)
        self._scenario: Dict[str, Any] = {}
        self._sim_minutes: int = 0
        self._done: bool = False
        self._cumulative_reward: float = 0.0
        self._services: Dict[str, Dict[str, Any]] = {}
        self._configs: Dict[str, Dict[str, str]] = {}
        self._last_result_msg: str = ""
        self._last_metrics: Optional[List[MetricDataPoint]] = None
        self._last_logs: Optional[List[LogEntry]] = None
        self._sla_used: float = 0.0

    def reset(self, scenario_id: Optional[str] = None) -> SreObservation:
        if scenario_id and scenario_id in SCENARIOS:
            self._scenario_idx = SCENARIO_IDS.index(scenario_id)
        sid = SCENARIO_IDS[self._scenario_idx % len(SCENARIO_IDS)]
        self._scenario = copy.deepcopy(SCENARIOS[sid])

        self._state = IncidentState(
            episode_id=str(uuid.uuid4())[:12],
            step_count=0,
            scenario_id=sid,
        )
        self._state.milestones_awarded = {
            "diagnosis": False,
            "mitigation": False,
            "resolution": False,
        }
        self._state.active_faults = copy.deepcopy(self._scenario.get("faults", []))

        self._sim_minutes = _hhmm_to_minutes(self._scenario["start_time"])
        self._sla_used = 0.0
        self._done = False
        self._cumulative_reward = 0.0
        
        self._services = copy.deepcopy(self._scenario["initial_services"])
        self._configs = {
            "api-gateway": {"rate_limit": "10000", "timeout": "30s"},
            "auth-service": {"token_expiry": "1h"},
        }
        
        self._last_result_msg = "Incident declared. Review alerts and run diagnostics."
        self._last_metrics = None
        self._last_logs = None

        self._scenario_idx += 1
        return self._build_observation(reward=0.0)

    def step(self, action: SreAction) -> SreObservation:
        if self._done:
            self._last_result_msg = "Incident already resolved or SLA breached."
            return self._build_observation(0.0)

        self._state.step_count += 1
        self._state.action_history.append(action.model_dump())
        self._last_metrics = None
        self._last_logs = None
        
        handler = {
            ActionType.QUERY_METRICS: self._handle_query_metrics,
            ActionType.READ_LOGS: self._handle_read_logs,
            ActionType.SCALE_SERVICE: self._handle_scale,
            ActionType.ROLLBACK_DEPLOYMENT: self._handle_rollback,
            ActionType.RESTART_SERVICE: self._handle_restart,
            ActionType.PATCH_CONFIG: self._handle_patch,
            ActionType.WAIT: self._handle_wait,
            ActionType.RESOLVE_INCIDENT: self._handle_resolve,
        }.get(action.action_type)

        if not handler:
            self._last_result_msg = f"Unknown action: {action.action_type}"
            return self._build_observation(0.0)

        return handler(action)

    @property
    def state(self) -> IncidentState:
        return self._state

    # ── Actions ────────────────────────────────────────────────────────
    
    def _handle_query_metrics(self, action: SreAction) -> SreObservation:
        svc = action.service_name
        if not svc or svc not in self._services:
            self._last_result_msg = f"Service not found: {svc}"
            return self._build_observation(0.0)
            
        points = []
        val = 0.0
        unit = ""
        m = action.metric_type
        
        if m == MetricType.CPU: val, unit = 45.0, "%"
        elif m == MetricType.MEMORY: val, unit = 60.0, "%"
        elif m == MetricType.LATENCY: val, unit = 50.0, "ms"
        elif m == MetricType.ERROR_RATE: val, unit = 1.0, "%"

        # Apply fault effects
        if "auth_memory_leak" in self._state.active_faults and svc == "auth-service":
            if m == MetricType.MEMORY: val = 95.0 + (self._state.step_count * 0.5)
            if m == MetricType.LATENCY: val = 800.0
        if "payment_bad_release" in self._state.active_faults and svc == "payment-service":
            if m == MetricType.ERROR_RATE: val = 85.0
        if "db_thundering_herd" in self._state.active_faults and svc == "database-cluster":
            if m == MetricType.CPU: val = 100.0
            if m == MetricType.LATENCY: val = 5000.0

        for i in range(action.time_window_minutes or 5):
            t = _minutes_to_hhmm(self._sim_minutes - i)
            points.append(MetricDataPoint(timestamp=t, value=val + random.uniform(-2, 2), unit=unit))

        self._last_metrics = points
        self._last_result_msg = f"Fetched {m.value} for {svc}."
        
        self._award_milestone("diagnosis", 0.20)
        return self._build_observation(0.0)

    def _handle_read_logs(self, action: SreAction) -> SreObservation:
        svc = action.service_name
        if not svc or svc not in self._services:
            self._last_result_msg = f"Service not found: {svc}"
            return self._build_observation(0.0)
            
        logs = []
        if "payment_bad_release" in self._state.active_faults and svc == "payment-service":
            logs.append(LogEntry(timestamp=_minutes_to_hhmm(self._sim_minutes), level="ERROR", message="Exception: module 'stripe' has no attribute 'Charge' (v2.2.0-rc1)"))
        elif "db_thundering_herd" in self._state.active_faults and svc == "database-cluster":
            logs.append(LogEntry(timestamp=_minutes_to_hhmm(self._sim_minutes), level="WARN", message="Too many connections. Active locks: 5042"))
        elif "auth_memory_leak" in self._state.active_faults and svc == "auth-service":
            logs.append(LogEntry(timestamp=_minutes_to_hhmm(self._sim_minutes), level="ERROR", message="java.lang.OutOfMemoryError: Java heap space"))
        else:
            logs.append(LogEntry(timestamp=_minutes_to_hhmm(self._sim_minutes), level="INFO", message=f"{svc} responding normally."))

        self._last_logs = logs
        self._last_result_msg = f"Fetched logs for {svc}."
        self._award_milestone("diagnosis", 0.20)
        return self._build_observation(0.0)

    def _handle_scale(self, action: SreAction) -> SreObservation:
        svc = action.service_name
        if not svc or svc not in self._services:
            self._last_result_msg = "Invalid service."
            return self._build_observation(0.0)
        
        reps = action.replicas or 1
        self._services[svc]["replicas"] = reps
        self._last_result_msg = f"Scaled {svc} to {reps} replicas."
        
        # Checking fault logic
        if "auth_memory_leak" in self._state.active_faults and svc == "auth-service" and reps > 4:
            self._state.active_faults.remove("auth_memory_leak")
            self._services[svc]["status"] = ServiceStatus.HEALTHY
            self._award_milestone("resolution", 0.30)
            
        if "db_thundering_herd" in self._state.active_faults and svc == "database-cluster" and reps >= 5:
            self._award_milestone("mitigation", 0.30)

        # Advance time by 3 mins for scaling
        self._advance_time(3)
        return self._build_observation(0.0)

    def _handle_rollback(self, action: SreAction) -> SreObservation:
        svc = action.service_name
        if not svc or svc not in self._services:
            self._last_result_msg = "Invalid service."
            return self._build_observation(0.0)
            
        ver = action.version or "previous"
        self._services[svc]["version"] = ver
        self._last_result_msg = f"Rolled back {svc} to {ver}."
        
        if "payment_bad_release" in self._state.active_faults and svc == "payment-service" and "v2.1" in ver:
            self._state.active_faults.remove("payment_bad_release")
            self._services[svc]["status"] = ServiceStatus.HEALTHY
            self._award_milestone("resolution", 0.30)
            
        if "auth_memory_leak" in self._state.active_faults and svc == "auth-service" and "v1.2.3" in ver:
            self._state.active_faults.remove("auth_memory_leak")
            self._services[svc]["status"] = ServiceStatus.HEALTHY
            self._award_milestone("resolution", 0.30)

        self._advance_time(5)
        return self._build_observation(0.0)

    def _handle_restart(self, action: SreAction) -> SreObservation:
        svc = action.service_name
        if not svc or svc not in self._services:
            self._last_result_msg = "Invalid service."
            return self._build_observation(0.0)
            
        self._last_result_msg = f"Restarted pods for {svc}."
        if "auth_memory_leak" in self._state.active_faults and svc == "auth-service":
            self._award_milestone("mitigation", 0.30)
            # Doesn't fix root cause

        self._advance_time(2)
        return self._build_observation(0.0)

    def _handle_patch(self, action: SreAction) -> SreObservation:
        svc = action.service_name
        if not svc or svc not in self._services:
            self._last_result_msg = "Invalid service."
            return self._build_observation(0.0)
            
        self._configs.setdefault(svc, {})[action.config_key] = action.config_value
        self._last_result_msg = f"Patched config '{action.config_key}'='{action.config_value}' for {svc}."
        
        if "db_thundering_herd" in self._state.active_faults and svc == "api-gateway":
            if action.config_key == "rate_limit" and int(action.config_value) < 1000:
                self._state.active_faults.remove("db_thundering_herd")
                self._services["api-gateway"]["status"] = ServiceStatus.HEALTHY
                self._services["database-cluster"]["status"] = ServiceStatus.HEALTHY
                self._award_milestone("resolution", 0.30)

        self._advance_time(1)
        return self._build_observation(0.0)

    def _handle_wait(self, action: SreAction) -> SreObservation:
        m = action.wait_minutes or 5
        self._advance_time(m)
        self._last_result_msg = f"Waited {m} minutes."
        return self._build_observation(0.0)

    def _handle_resolve(self, action: SreAction) -> SreObservation:
        self._done = True
        if not self._state.active_faults:
            self._state.done_reason = "resolved_successfully"
            self._last_result_msg = "Incident declared resolved correctly!"
        else:
            self._state.done_reason = "false_resolution"
            self._last_result_msg = "Incident declared resolved, but outages persist!"
        return self._build_observation(0.0)

    # ── Helpers ────────────────────────────────────────────────────────

    def _advance_time(self, minutes: int):
        self._sim_minutes += minutes
        
        # If there are active faults, SLA burns proportional to severity
        if self._state.active_faults:
            self._sla_used += (minutes / 60.0)

        dl = _hhmm_to_minutes(self._scenario["deadline"])
        if self._sim_minutes >= dl:
            self._done = True
            self._state.done_reason = "deadline_breached"
            self._last_result_msg = "Deadline breached - SLA violation!"
            
    def _award_milestone(self, name: str, amount: float):
        if not self._state.milestones_awarded.get(name):
            self._state.milestones_awarded[name] = True
            self._cumulative_reward += amount

    def _compute_score(self) -> float:
        score = sum([
            0.20 if self._state.milestones_awarded.get("diagnosis") else 0.0,
            0.30 if self._state.milestones_awarded.get("mitigation") else 0.0,
            0.30 if self._state.milestones_awarded.get("resolution") else 0.0,
        ])
        if self._state.done_reason == "resolved_successfully":
            # Efficiency bonus 
            if self._sla_used < self._scenario["sla_budget_hours"]:
                score += 0.20
        return min(max(score, 0.0), 1.0)

    def _build_observation(self, reward: float) -> SreObservation:
        # Build active alerts
        alerts = []
        for f in self._state.active_faults:
            if f == "auth_memory_leak":
                alerts.append(Alert(alert_id="ALT-101", service_name="auth-service", severity="HIGH", message="Memory utilization >90%", timestamp=_minutes_to_hhmm(self._sim_minutes)))
            elif f == "payment_bad_release":
                alerts.append(Alert(alert_id="ALT-202", service_name="payment-service", severity="CRITICAL", message="HTTP 5xx Error rate spiked", timestamp=_minutes_to_hhmm(self._sim_minutes)))
            elif f == "db_thundering_herd":
                alerts.append(Alert(alert_id="ALT-303", service_name="database-cluster", severity="CRITICAL", message="DB Connections Exhausted, Queue Depth >5000", timestamp=_minutes_to_hhmm(self._sim_minutes)))

        # Build services list
        svcs = []
        for k, v in self._services.items():
            svcs.append(ServiceState(service_name=k, replicas=v["replicas"], version=v["version"], status=v["status"]))

        cluster_stat = ClusterStatus.UP
        if len(self._state.active_faults) > 0:
            cluster_stat = ClusterStatus.DEGRADED

        score = self._compute_score() if self._done else None
        
        # Calculate reward deltas if needed (handled additively in cumulative)
        # For simplicity, returning 0.0 immediate reward, rely on cumulative in real impl.

        return SreObservation(
            current_time=_minutes_to_hhmm(self._sim_minutes),
            deadline=self._scenario["deadline"],
            cluster_status=cluster_stat,
            services=svcs,
            active_alerts=alerts,
            sla_budget_remaining=max(0.0, self._scenario["sla_budget_hours"] - self._sla_used),
            task_brief=self._scenario["description"],
            last_action_result=self._last_result_msg,
            last_metrics=self._last_metrics,
            last_logs=self._last_logs,
            metadata={
                "cumulative_reward": round(self._cumulative_reward, 2),
                **({"final_score": score} if score is not None else {}),
            }
        )
