"""Private preparation and checks for initial-decision availability interventions."""
import json
from pathlib import Path

from skillforge.evolution_common.artifacts import clone
from skillforge.evolution_common.snapshot import save_snapshot
from skillforge.evolution_schemas import fingerprint
from skillforge.execution_aware.contracts import ExecutionContract
from skillforge.policies import MUTATIONS
from skillforge.skill_evolution.catalog import LoadedSkills
from skillforge.skill_evolution.runtime import run_agent


class StagingOnly:
    settings = {"model": "snapshot-preparation-no-inference", "engineering_only": True}
    tokens = 0
    def decide(self, context):
        raise AssertionError("staging must never request model inference")


def prepare_snapshot(root, env, task, catalog, observations, rng):
    """Create a pristine runtime snapshot; preparation reads are explicit cost."""
    saved = []
    run_agent(StagingOnly(), task, catalog, lambda *_: None, cancelled=lambda: True,
              public_start={"observations": observations, "loaded_refs": {}}, persist=saved.append)
    digest = save_snapshot(root, env, saved[-1], rng)
    return {"snapshot_hash": digest, "runtime_identity": saved[-1]["identity"]}


def fork_starts(snapshot, catalog, offered_refs):
    item = json.loads((Path(snapshot) / "snapshot.json").read_text(encoding="utf-8"))
    body, saved = item["body"], item["body"]["runtime"]
    if fingerprint(body) != item["hash"]:
        raise ValueError("snapshot tampered")
    if (saved["steps"] or saved["model_requests"] or any(saved["budget"]["used"].values()) or
            ExecutionContract.restore(saved["execution_contract"], saved["execution_contract"]["body"]["task_id"]).pending()):
        raise ValueError("availability fork requires a pristine decision checkpoint")
    if any(e["tool_name"] in MUTATIONS for e in body["audit"]):
        raise ValueError("preparation must contain reads only")
    observed = {}
    for event in body["audit"]:
        if not event["error"]:
            observed.update({k: v for k, v in (event["result"] or {}).items() if "." in k})
    if observed != saved["state"]:
        raise ValueError("start observations must exactly match actual public read results")
    checked = LoadedSkills(catalog, offered_refs)
    return {"provided": {"observations": clone(observed), "loaded_refs": clone(checked.refs)},
            "withheld": {"observations": clone(observed), "loaded_refs": {}}}


def check_pair(provided, withheld):
    """Exactly one context intervention; future trajectories may diverge normally."""
    left, right = clone(provided["steps"][0]["context"]), clone(withheld["steps"][0]["context"])
    offered = left["catalog"].pop("loaded_skills")
    hidden = right["catalog"].pop("loaded_skills")
    if not offered or hidden or left != right:
        raise ValueError("fork contexts differ beyond declared Skill availability")
    return {"passed": True, "common_context_hash": fingerprint(left),
            "provided_context_hash": fingerprint(provided["steps"][0]["context"]),
            "withheld_context_hash": fingerprint(withheld["steps"][0]["context"]),
            "offered_refs": [{"skill_id": e["skill_id"], "revision": e["revision"]} for e in offered],
            "scope": "initial decision availability intervention; search/load disabled equally; later execution may differ"}
