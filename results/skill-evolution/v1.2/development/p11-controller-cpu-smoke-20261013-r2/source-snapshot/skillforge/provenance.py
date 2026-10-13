"""Bind source trajectories to immutable dataset tasks before compilation."""
from .dataset import task_hash
from .environment import Environment
from .policies import POLICY_VERSION
from .verifier import verify


def audit_sources(trajectories, tasks, allow_engineering=False):
    known = {t.task_id: t for t in tasks}
    seen = set()
    for record in trajectories:
        task = known.get(record.get("task_id"))
        if task is None or task.split != "train" or record.get("split") != "train":
            raise ValueError("source trajectory must belong to manifest train split")
        if record.get("task_hash") != task_hash(task) or record.get("dataset_id") != task.dataset_id:
            raise ValueError("source task fingerprint mismatch")
        if record.get("parameters") != task.parameters or record.get("user_request") != task.request:
            raise ValueError("source task content mismatch")
        if record.get("policy_version") != POLICY_VERSION:
            raise ValueError("source policy version mismatch")
        if record["trajectory_id"] in seen:
            raise ValueError("duplicate source trajectory ID")
        seen.add(record["trajectory_id"])
        if not allow_engineering and record.get("model") == "scripted-engineering-only":
            raise ValueError("scripted source requires explicit engineering mode")
        env = Environment(fixture=task.fixture)
        try:
            if env.snapshot() != record["initial_state"]:
                raise ValueError("source initial state mismatch")
        finally:
            env.close()
        actual = verify(task, record["initial_state"], record["final_state"], record["tool_audit"], record["outcome"])
        for key in ["task_success", "actual_policy_violation", "attempted_policy_violation"]:
            if actual[key] != record["verification"][key]:
                raise ValueError("source verification mismatch")
    if not trajectories:
        raise ValueError("empty source corpus")
    return {"trajectories": len(trajectories), "tasks": len({r["task_id"] for r in trajectories}),
        "engineering_sources": any(r["model"] == "scripted-engineering-only" for r in trajectories),
        "scope": "manifest binding and deterministic verdict consistency; not cryptographic attestation of model origin"}
