"""Scripted CPU admission/activation mechanics. Never model capability evidence.

Positive-path tests explicitly replace real learn/publication and fixed-model
checks with unit stubs. The raw trajectory, checkpoints, fees and EOC are still
independently executed/replayed. Production entry rejects these identities.
"""
import copy
import json
import random

import pytest

from scripts import skill_evolution_release as release
from scripts.evolution_budget import CheckpointAdmission
from scripts.evolution_forks import prepare_snapshot
from scripts.verify_skill_evolution_p4 import engineering_entry
from skillforge.environment import Environment
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.evolution_common.snapshot import save_snapshot
from skillforge.schemas import Action
from skillforge.skill_evolution.agent_evidence import declare_evidence_protocol
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.registry import VersionedRegistry, verified_publication
from skillforge.skill_evolution.runtime import SYSTEM_PROMPT, PROTOCOL, runtime_sources, run_agent
from skillforge.skill_evolution.workflows import GOALS, make_case, private_items, verify_workflow


LIMITS = {"max_steps": 12, "max_search": 3, "max_load": 3, "max_tokens": 65536}
SETTINGS = {"model": "SCRIPTED-UNIT-ONLY", "engineering_only": False, "system_prompt": SYSTEM_PROMPT,
    "prompt_sha256": release.fingerprint(SYSTEM_PROMPT), "decision_protocol": PROTOCOL}
BUDGET = {"prior_tokens": 1234, "max_tokens": 1000000, "prior_wall": 20, "max_wall": 2000}


def scripted_arm(folder, case, catalog, *, prior, use_skill, no_gain=False, fail=False):
    folder.mkdir(parents=True)
    env, rng = Environment(fixture=case.fixture), random.Random(case.seed)
    initial, items = env.snapshot(), private_items(env)
    coverage = release.evaluate_static(case, catalog)
    release.publish(folder / "static-coverage.json", coverage)
    staged = prepare_snapshot(folder / "initial-snapshot", env, case.public_task(), catalog, {}, rng)
    if fail:
        actions = [Action(type="stop")]
    elif use_skill and not no_gain:
        entry = catalog.entries()[0]
        actions = [Action(type="tool", name="search_skills", arguments={"query": "investigation"}),
            Action(type="tool", name="load_skill", arguments={"skill_id": entry["skill_id"], "revision": entry["revision"]}),
            Action(type="skill", name=entry["skill_id"], arguments=case.parameters), Action(type="stop")]
    else:
        actions = [Action(type="tool", name=name, arguments=case.parameters) for name in GOALS[case.workflow_id].required_evidence]
        if not no_gain:
            actions.insert(0, Action(type="tool", name="search_skills", arguments={"query": "unit arithmetic extra action"}))
        actions.append(Action(type="stop"))
    class Model:
        settings, tokens = SETTINGS, 0
        def decide(self, context):
            action = actions.pop(0); self.tokens += 100
            self.last_messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": json.dumps(context)}]
            self.last_response = action.model_dump_json()
            return action
    admission = CheckpointAdmission(**{**BUDGET, "prior_tokens": prior})
    index = 0
    def persist(value):
        nonlocal index
        save_snapshot(folder / "checkpoints" / str(index), env, value, rng)
        receipt = admission.inspect(value, 1)
        if receipt is not None:
            release.publish(folder / "admissions" / (str(receipt["request_index"]) + ".json"), {**receipt, "checkpoint_index": index})
            admission.record_approval(receipt)
        index += 1
    def call(name, args, key, source):
        before = len(env.audit)
        try: return env.call(name, args, case.authenticated_customer_id, key)
        finally:
            for event in env.audit[before:]: event["decision_origin"] = source
    try:
        agent = run_agent(Model(), case.public_task(), catalog, call, **LIMITS, persist=persist, auto_terminate=False)
        status = {"task_id": case.task_id, "completed": True, "failure": None, "denied_before_ack": None,
            "charged_tokens": agent["metrics"]["tokens"], "last_budget": agent["budget"]}
        status["static_evaluation_tool_calls"] = sum(len(item["tool_audit"]) for item in coverage)
        row = {"schema": "workflow-learn-trajectory-v1", "case": case.model_dump(),
            "model_identity_hash": release.fingerprint(SETTINGS), "snapshot_hash": staged["snapshot_hash"],
            "initial_state": initial, "initial_items": items, "final_state": env.snapshot(), "final_items": private_items(env),
            "agent": agent, "tool_audit": env.audit, "static_coverage": coverage,
            "verification": verify_workflow(case, initial, env.snapshot(), env.audit, agent["outcome"], items, private_items(env))}
        release.publish(folder / "result.json", row); release.publish(folder / "collection-status.json", status)
        return status
    finally: env.close()


def synthetic_release(tmp_path, monkeypatch, *, outcome="pass"):
    ledger = SplitLedger(tmp_path / "sources")
    baseline = Catalog([]); candidate = Catalog([verified_publication(engineering_entry())])
    cases = []
    for index in range(8):
        case = make_case("logistics_investigation", 78800+index, "validation")
        stable = index >= 6
        ledger.claim(case.source_group, "stable_validation" if stable else "validation",
            related_groups=[case.task_id, case.parameters["order_id"], case.authenticated_customer_id])
        cases.append({"case": case.model_dump(), "stable": stable})
    protocol = declare_evidence_protocol(cases, baseline, candidate, SETTINGS, runtime_sources(), LIMITS, ledger, budget=BUDGET)
    class UnitRegistry:
        def load(self, identity): return ({}, baseline if identity == "unit-parent" else candidate)
    binding = {"parent_snapshot": "unit-parent", "candidate_snapshot": "unit-candidate",
        "parent_catalog_hash": baseline.hash, "candidate_catalog_hash": candidate.hash,
        "published_revision": candidate.entries()[0]["revision"], "unit_stub": True}
    # ONLY the publication/model trust boundary is stubbed for this CPU test.
    monkeypatch.setattr(release, "release_binding", lambda *args: copy.deepcopy(binding))
    monkeypatch.setattr(release, "fixed_model", lambda settings: None)
    controller = release.AgentRelease(UnitRegistry(), ledger, artifact_root=tmp_path)
    folder = tmp_path / "run"
    declaration = controller.declare(folder, parent="unit-parent", candidate="unit-candidate", protocol=protocol,
        config={"adapter": release.ADAPTER, "adapter_sha256": release.ADAPTER_SHA, "limits": LIMITS}, phase_id="SCRIPTED-UNIT-ONLY")
    release.publish(folder / "model-identity.json", SETTINGS)
    statuses, prior = [], BUDGET["prior_tokens"]
    for index, item in enumerate(cases):
        for arm in ("baseline", "candidate"):
            status = scripted_arm(folder / str(index) / arm, make_case("logistics_investigation", 78800+index, "validation"),
                baseline if arm == "baseline" else candidate, prior=prior, use_skill=arm == "candidate",
                no_gain=outcome == "tie", fail=outcome == "regression" and arm == "candidate" and index == 7)
            statuses.append({"index": index, "arm": arm, "status": status}); prior += status["charged_tokens"]
    report = release.hashed({"schema": "formal-agent-release-cost-report-v1", "declaration_hash": declaration["hash"],
        "statuses": statuses, "failure": None, "wall_seconds": 10, "charged_tokens": prior-BUDGET["prior_tokens"], "complete": True})
    release.publish(folder / "collection-report.json", report)
    return controller, folder


@pytest.mark.parametrize("outcome,expected", [("pass", "ADMITTED"), ("tie", "INCONCLUSIVE"), ("regression", "REJECTED")])
def test_scripted_receipt_gate_then_pinned_isolated_runtime(tmp_path, monkeypatch, outcome, expected):
    controller, folder = synthetic_release(tmp_path, monkeypatch, outcome=outcome)
    receipt = controller.admit(folder)
    assert receipt["decision"] == expected and receipt["agent_admitted"] == (expected == "ADMITTED")
    assert receipt["statistical_gate"]["primary_source_groups"] == 6 and receipt["statistical_gate"]["stable_cases"] == 2
    assert receipt["new_model_calls"] == receipt["new_tokens"] == 0 and not receipt["deployed"]
    assert controller.audit_receipt(folder) == receipt
    if expected != "ADMITTED":
        with pytest.raises(ValueError, match="formal Agent admission"): controller.activate(folder, tmp_path / "isolated")
        return
    activated = controller.activate(folder, tmp_path / "isolated")
    assert activated["isolated_activated"] and not activated["deployed"]
    instance = controller.open_isolated(tmp_path / "isolated")
    assert instance.catalog.hash == receipt["binding"]["candidate_catalog_hash"]
    # Frozen instance can execute an independent new readonly task.
    case = make_case("logistics_investigation", 78999, "test")
    actions = [Action(type="tool", name=name, arguments=case.parameters) for name in GOALS[case.workflow_id].required_evidence] + [Action(type="stop")]
    class UnitModel:
        settings, tokens = SETTINGS, 0
        def decide(self, context): self.tokens += 100; return actions.pop(0)
    assert instance.execute(UnitModel(), case)["outcome"] == "completed"
    with pytest.raises(ValueError, match="model/source"):
        instance.execute(type("Wrong", (), {"settings": {}})(), case)


@pytest.mark.parametrize("change", ["cost", "order", "elapsed", "receipt", "source", "phase", "catalog", "activation"])
def test_rehashed_tampering_cannot_bypass_raw_audit_or_activation_pin(tmp_path, monkeypatch, change):
    controller, folder = synthetic_release(tmp_path, monkeypatch)
    controller.admit(folder)
    if change in {"catalog", "activation"}:
        controller.activate(folder, tmp_path / "isolated")
        path = tmp_path / "isolated" / ("catalog.json" if change == "catalog" else "activation.json")
        if change == "catalog":
            value = {"schema": "skill-catalog-v1", "hash": Catalog([]).hash, "entries": []}
        else:
            value = release.read(path); value["deployed"] = True; value = release.hashed({k:v for k,v in value.items() if k != "hash"})
        path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(ValueError): controller.open_isolated(tmp_path / "isolated")
        return
    if change == "receipt":
        path = folder / "agent-admission.json"; value = release.read(path); value["charged_tokens"] -= 100
    elif change == "source":
        path = folder / "source-snapshot/scripts/skill_evolution_release.py"; path.write_text("forged", encoding="utf-8")
        with pytest.raises(ValueError, match="sources changed"): controller.audit_receipt(folder)
        return
    elif change == "phase":
        path = next((tmp_path / "results/skill-evolution/v1.2/agent-release-ledger").glob("*.json"))
        value = release.read(path); value["declaration_hash"] = "forged"
    else:
        path = folder / "collection-report.json"; value = release.read(path)
        if change == "cost": value["charged_tokens"] -= 100
        elif change == "order": value["statuses"].reverse()
        else: value["wall_seconds"] = 0
    path.write_text(json.dumps(release.hashed({k:v for k,v in value.items() if k != "hash"})), encoding="utf-8")
    with pytest.raises(ValueError): controller.audit_receipt(folder)


def test_actual_formal_entry_rejects_legacy_zero_update_and_scripted_model(tmp_path):
    registry = VersionedRegistry(tmp_path / "registry"); catalog = Catalog([])
    parent = registry.bootstrap(catalog, reason="unit-only", evidence=release.hashed({"catalog_hash": catalog.hash}))
    retained = registry.retain(parent, reason="unit-only zero update", evidence=release.hashed({"unit": True}))
    with pytest.raises(ValueError, match="formally registered"):
        release.release_binding(registry, parent, retained, release.hashed({"unit": True}), SplitLedger(tmp_path / "sources"))
    with pytest.raises(ValueError, match="fixed real"):
        release.fixed_model(SETTINGS)


def test_duplicate_formal_submission_refuses_second_phase(tmp_path, monkeypatch):
    controller, folder = synthetic_release(tmp_path, monkeypatch)
    declaration = release.read(folder / "declaration.json")
    with pytest.raises(ValueError, match="already submitted"):
        controller.declare(tmp_path / "rerun", parent="unit-parent", candidate="unit-candidate",
            protocol=declaration["protocol"], config=declaration["config"], phase_id="another-unit-phase")
    assert not (tmp_path / "rerun").exists()
