"""Quick inference integration tester for Cloud SRE Ops"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.sre_ops_environment import SreOpsEnvironment  # type: ignore
from models import SreAction, ActionType, MetricType  # type: ignore

def test_t2_rollback():
    env = SreOpsEnvironment()
    obs = env.reset("T2_BAD_RELEASE")
    print(f"[{obs.current_time}] Alert: {obs.active_alerts[0].message if obs.active_alerts else 'None'}")
    
    print("\n--- Action: Read Logs ---")
    act = SreAction(action_type=ActionType.READ_LOGS, service_name="payment-service")
    obs = env.step(act)
    if obs.last_logs:
        for l in obs.last_logs:
            print(f"LOG: {l.level} - {l.message}")

    print("\n--- Action: Rollback Deployment ---")
    act2 = SreAction(action_type=ActionType.ROLLBACK_DEPLOYMENT, service_name="payment-service", version="v2.1")
    obs = env.step(act2)
    print("STATUS:", obs.last_action_result)

    print("\n--- Action: Resolve ---")
    act3 = SreAction(action_type=ActionType.RESOLVE_INCIDENT)
    obs = env.step(act3)
    print("Resolved. Final Score:", obs.metadata.get("final_score"))

if __name__ == "__main__":
    test_t2_rollback()
