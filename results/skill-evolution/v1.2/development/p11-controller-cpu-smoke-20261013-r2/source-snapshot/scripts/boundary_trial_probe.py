"""Spawn-only private actual DSL probes, including original-policy restoration."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from scripts.boundary_trial_worlds import selected_policy, policy
from skillforge.environment import Environment, ToolError
from skillforge.evolution_execution import execute_frozen
from skillforge.evolution_schemas import fingerprint


def child(spec, world, contract):
    with selected_policy(world):
        env = Environment(fixture=spec["fixture"])
        initial, execution, success = env.snapshot(), None, False
        try:
            def call(name, args, key): return env.call(name, args, spec["fixture"]["customer_id"], key)
            try:
                execution = execute_frozen(contract, spec["parameters"], call, spec["task_id"], force_probe=True)
                success = execution["success"]
            except ToolError: pass
            return {"trajectory_id": fingerprint([spec["task_id"], spec["policy_epoch"], contract]),
                "task_id": spec["task_id"], "policy_epoch": spec["policy_epoch"], "origin": "controlled_procedure",
                "procedure_success": success, "initial_state": initial, "final_state": env.snapshot(),
                "tool_audit": env.audit, "execution": execution,
                "actual_violations": sum(bool(e["state_diff"]) and e["committed"] and e["tool_name"] in
                    {"issue_refund", "update_shipping_address", "cancel_order"} and
                    policy(world, e["tool_name"], e["before_state"], e["arguments"]) != "allow" for e in env.audit)}
        finally: env.close()


def probe(spec, world, contract):
    with tempfile.TemporaryDirectory(prefix="boundary-trial-probe-") as folder:
        source, target = Path(folder) / "request.json", Path(folder) / "response.json"
        source.write_text(json.dumps({"spec": spec, "world": world, "contract": contract}), encoding="utf-8")
        subprocess.run([sys.executable, "-m", "scripts.boundary_trial_probe", str(source), str(target)],
            check=True, capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        return json.loads(target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path(sys.argv[2]).write_text(json.dumps(child(**request)), encoding="utf-8")
