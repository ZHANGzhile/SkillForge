"""Scripted engineering evidence only; never counted as real-model results."""
import copy
import json
import random

import pytest

from scripts.evolution_forks import prepare_snapshot, fork_starts, check_pair
from scripts.evolution_opportunities import evaluate_opportunities, selection_funnel
from scripts.run_skill_evolution import snapshot_sources
from scripts.run_skill_evolution_selection import audit
from skillforge.environment import Environment
from skillforge.evolution_common.snapshot import restore_snapshot, save_snapshot
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from skillforge.schemas import Action, Task, ExpectedOutcome
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.runtime import PROTOCOL, run_agent
from skillforge.verifier import verify
from test_skill_evolution_catalog import entry
from test_skill_evolution_runtime import Model, call, TASK


class MessagesModel(Model):
    def decide(self, context):
        self.last_messages = [{"role": "system", "content": "Scripted engineering fixture"},
                              {"role": "user", "content": json.dumps(context)}]
        return super().decide(context)


@pytest.fixture
def evidence(tmp_path, request):
    partial = getattr(request, "param", False)
    root = tmp_path / "forks"; root.mkdir()
    e = entry(); c = Catalog([e]); c.save(root / "catalog.json")
    task = Task(**TASK, split="train", template_id="engineering-fork", seed=42,
                expected=ExpectedOutcome(allowed_outcomes=["completed"], expected_state={"order.status": "CANCELLED"}))
    immutable_json(root / "private-dev-tasks.json", [task.model_dump()])
    sources = snapshot_sources(root)
    limits = {"max_steps": 6, "max_search": 0, "max_load": 0, "max_tokens": 32768}
    reg = {"config": {"limits": limits}, "catalog_hash": c.hash, "sources": sources, "protocol": PROTOCOL}
    immutable_json(root / "registration.json", {**reg, "protocol_hash": fingerprint(reg)})
    folder = root / task.task_id; folder.mkdir()
    source = Environment(str(folder / "source.sqlite"))
    observations = {}
    for name in ("get_order", "get_customer", "get_shipment"):
        observations.update(source.call(name, TASK["parameters"], task.customer_id))
    staged = prepare_snapshot(folder / "initial-snapshot", source, TASK, c, observations, random.Random(42))
    opportunities = evaluate_opportunities(task, c, folder / "initial-snapshot", folder / "opportunity-forks", staged["runtime_identity"])
    immutable_json(folder / "opportunities.json", opportunities)
    refs = {e["skill_id"]: {"revision": e["revision"], "content_hash": e["revision"]}}
    starts = fork_starts(folder / "initial-snapshot", c, refs)
    arms = {}
    for arm in (("provided",) if partial else ("provided", "withheld")):
        env, _, rng = restore_snapshot(folder / "initial-snapshot", folder / arm / "live.sqlite", staged["runtime_identity"])
        initial, prefix = env.snapshot(), len(env.audit)
        sequence = ([Action(type="skill", name=e["skill_id"], arguments=TASK["parameters"]), Action(type="stop")]
                    if arm == "provided" else [Action(type="tool", name="cancel_order", arguments=TASK["parameters"])])
        model = MessagesModel(sequence); saved = []
        agent = run_agent(model, TASK, c, call(env), public_start=starts[arm], persist=saved.append, **limits)
        save_snapshot(folder / arm / "checkpoints/0", env, saved[-1], rng)
        verdict = verify(task, initial, env.snapshot(), env.audit, agent["outcome"])
        row = {"task_id": task.task_id, "arm": arm, "public_start": starts[arm], "snapshot_hash": staged["snapshot_hash"],
               "initial_state_hash": fingerprint(initial), "task_hash": fingerprint(task.model_dump()),
               "prefix_audit_count": prefix, "agent": agent, "verification": verdict, "tool_audit": env.audit,
               "selection_funnel": selection_funnel(agent, opportunities, verdict)}
        immutable_json(folder / arm / "result.json", row)
        arms[arm] = agent; env.close()
    if not partial:
        immutable_json(folder / "pair-check.json", {"task_id": task.task_id, "order": ["provided", "withheld"], **check_pair(arms["provided"], arms["withheld"])})
    immutable_json(root / "model-identity.json", model.settings)
    immutable_json(root / "report.json", {"status": "blocked_or_incomplete" if partial else "complete",
                                         "n": len(arms), "planned": 2, "pairs": 0 if partial else 1,
                                         "tokens": 0, "eoc": len(arms), "actual_violations": 0, "attempted_violations": 0})
    source.close()
    return root


def test_independent_fork_audit_accepts_engineering_pair(evidence):
    result = audit(evidence)
    assert result["passed"] and result["pairs"] == 1 and result["charged_tokens"] == 0


def test_fork_audit_rejects_declared_shared_state_changed_before_inference(evidence):
    path = evidence / TASK["task_id"] / "provided/result.json"
    row = json.loads(path.read_text())
    row["public_start"]["observations"]["customer.risk_level"] = "HIGH"
    path.write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError, match="initial public state"): audit(evidence)


def test_fork_audit_rejects_forged_aggregate_tokens(evidence):
    path = evidence / "report.json"; report = json.loads(path.read_text()); report["tokens"] = 10
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="aggregate mismatch"): audit(evidence)


def test_fork_audit_rejects_loaded_program_tamper_even_when_context_hashes_match(evidence):
    path = evidence / TASK["task_id"] / "provided/result.json"; row = json.loads(path.read_text())
    step = row["agent"]["steps"][0]
    step["context"]["catalog"]["loaded_skills"][0]["program"][0]["tool"] = "issue_refund"
    step["messages"][1]["content"] = json.dumps(step["context"])
    step["selection_trace"]["model_visible_context_hash"] = fingerprint(step["context"])
    step["selection_trace"]["model_messages_hash"] = fingerprint(step["messages"])
    path.write_text(json.dumps(row), encoding="utf-8")
    pair_path = evidence / TASK["task_id"] / "pair-check.json"; pair = json.loads(pair_path.read_text())
    pair["provided_context_hash"] = fingerprint(step["context"])
    pair_path.write_text(json.dumps(pair), encoding="utf-8")
    with pytest.raises(ValueError, match="exact catalog revision"): audit(evidence)


@pytest.mark.parametrize("evidence", [True], indirect=True)
def test_partial_run_has_valid_evidence_but_is_not_a_complete_pair(evidence):
    result = audit(evidence)
    assert result["evidence_integrity_passed"] and not result["run_completed"]
    assert result["pairs"] == 0 and result["cases"] == 1
    assert result["missing_arms"] == [{"task_id": TASK["task_id"], "arm": "withheld"}]
