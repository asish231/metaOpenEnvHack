---
title: Cloud SRE Ops Benchmark
emoji: 🌩️
colorFrom: red
colorTo: orange
sdk: docker
app_port: 8000
---
# Cloud SRE Ops — Site Reliability Engineering Benchmark

> An OpenEnv benchmark where an AI agent acts as a Site Reliability Engineer (SRE), responding to PagerDuty-style alerts in a Kubernetes-like microservice cluster. The agent must query metrics, read streaming logs, and execute remediation actions (scaling, rollbacks, configuration patches) to mitigate and resolve complex infrastructure outages.

---

## Overview

Cloud SRE Ops simulates realistic, highly complex **production incidents** that require deep reasoning about distributed systems. The AI agent must diagnose and resolve the fault before the SLA budget is breached.

The environment simulates a 4-tier microservice architecture:
- `api-gateway`
- `auth-service`
- `payment-service`
- `database-cluster`

---

## Action Space

| Action | Required Fields | Description |
|--------|----------------|-------------|
| `query_metrics` | `service_name`, `metric_type` | Fetch CPU, Memory, Latency, or Error Rate time-series metrics. |
| `read_logs`     | `service_name` | Pull recent application/container logs. |
| `scale_service` | `service_name`, `replicas` | Adjust horizontal scaling for a service. |
| `rollback_deployment` | `service_name`, `version` | Rollback a deployment to a specified version. |
| `restart_service`     | `service_name` | Restart the pods of a given service. |
| `patch_config`  | `service_name`, `config_key`, `config_value`| Hot-patch service configuration (e.g., rate limits). |
| `wait`          | `wait_minutes` | Advance time to observe system delta. |
| `resolve_incident`    | — | Declare the incident mitigated and complete. |

---

## Benchmark Scenarios

### T1: Memory Leak (Medium)
- **Target**: `auth-service`
- **Challenge**: The auth service memory utilization grows over time, leading to OOMs and latency.
- **Resolution**: Agent must identify the memory leak and gracefully `restart` to clear cache, then permanently fix via `scale_service` or `rollback_deployment`.

### T2: Bad Release (Hard)
- **Target**: `payment-service`
- **Challenge**: A recent deployment introduced a dependency bug, spiking HTTP 500 errors.
- **Resolution**: Agent must read logs to find the exception and version constraint, then `rollback_deployment` to the previous stable release.

### T3: Cascading Failure (Expert)
- **Target**: `api-gateway` & `database-cluster`
- **Challenge**: A massive traffic spike overwhelms the database, creating thousands of active locks.
- **Resolution**: Agent must `patch_config` the API gateway to enforce rate limiting and concurrently `scale` the database cluster to clear the backlog.

---

## Reward Milestones

- **Diagnosis (+0.20)**: Correctly queries metrics or logs revealing the root cause.
- **Mitigation (+0.30)**: Applies temporary fix (e.g., restarting a leaking pod).
- **Resolution (+0.30)**: Permanently fixes the root cause safely.
- **Efficiency Bonus (+0.20)**: Finalized successfully within reasonable time/budget limits.

---

## Setup & Usage

### Local Docker
```bash
docker build -f server/Dockerfile -t sre-ops-env .
docker run -p 8000:8000 sre-ops-env
```
