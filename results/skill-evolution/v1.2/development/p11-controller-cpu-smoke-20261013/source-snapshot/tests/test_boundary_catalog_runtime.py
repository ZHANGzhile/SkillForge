"""Stage 2 interface dev contracts; real SQLite, scripted model, no research."""
import copy

import pytest

from scripts.run_skill_evolution import static_catalog
from skillforge.environment import Environment
from skillforge.schemas import Action
from skillforge.evolution_boundary import parent_identity
from skillforge.boundary_runtime.catalog import BoundaryCatalog, h0_bindings
from skillforge.boundary_runtime.runtime import run_agent, SYSTEM_PROMPT
from skillforge.skill_evolution.runtime import SYSTEM_PROMPT as STAGE1_PROMPT
from test_skill_evolution_runtime import Model, call


def prepared(family, patch=None):
    base = static_catalog({"static_bundle": "results/real-v2-frozen/frozen.json"})
    bindings = h0_bindings(base)
    entry = next(row for row in base.entries() if row["contract"]["family"] == family)
    if patch: bindings[entry["skill_id"]]["patch"] = patch
    catalog = BoundaryCatalog(base.entries(), bindings)
    params = {"order_id": "O1"}
    if family == "refund": params["amount"] = 100
    if family == "modify_address": params["new_address"] = "Delivery lane 204"
    task = {"task_id": "stage2-dev", "family": family, "request": "Please perform the requested operation.", "parameters": params}
    actions = [Action(type="tool", name="search_skills", arguments={"query": family, "top_k": 5}),
        Action(type="tool", name="load_skill", arguments={"skill_id": entry["skill_id"], "revision": entry["revision"]}),
        Action(type="skill", name=entry["skill_id"], arguments=params), Action(type="stop")]
    return base, catalog, entry, task, actions


def test_h0_preserves_program_and_discovery_with_autonomous_verified_stop():
    base, catalog, entry, task, actions = prepared("refund")
    env = Environment()
    try: result = run_agent(Model(actions), task, catalog, call(env))
    finally: env.close()
    assert catalog.hash == base.hash and catalog.entries() == base.entries()
    assert SYSTEM_PROMPT == STAGE1_PROMPT
    assert result["skill_events"][0]["success"] and result["termination_source"] == "model"
    assert result["verification_receipts"][0]["status"] == "VERIFIED"
    assert result["interventions"]["runtime_intervention_count"] == 0
    assert result["boundary_bundle_hash"] == catalog.bundle_hash
    old, _ = base.search_audited("refund")
    new, _ = catalog.search_audited("refund")
    assert [(r["skill_id"], r["revision"]) for r in old] == [(r["skill_id"], r["revision"]) for r in new]


def test_restriction_blocks_old_eligible_program_before_mutation():
    _, catalog, entry, task, actions = prepared("refund", {"hypothesis_id": "restriction", "kind": "restrict",
        "predicates": [{"field": "shipment.status", "op": "eq", "value": "PROCESSING"}]})
    env = Environment(fixture={"shipment": "PROCESSING"})
    try:
        result = run_agent(Model(actions), task, catalog, call(env))
        assert result["steps"][2]["error"] == "skill_boundary_inapplicable"
        assert not any(event["tool_name"] == "issue_refund" for event in env.audit)
    finally: env.close()


def test_relaxation_replaces_parent_business_veto_but_not_environment_guard(monkeypatch):
    from skillforge import environment
    from scripts.active_evolution_worlds import policy
    monkeypatch.setattr(environment, "eligibility", lambda name, state, args: policy("W6", name, state, args))
    base, catalog, entry, task, actions = prepared("modify_address", {"hypothesis_id": "relaxation", "kind": "relax",
        "predicates": [{"field": "shipment.status", "op": "eq", "value": "PROCESSING"}]})
    env = Environment(fixture={"shipment": "PROCESSING"})
    try:
        result = run_agent(Model(actions), task, catalog, call(env))
        assert result["skill_events"][0]["success"]
        assert env.snapshot()["order.shipping_address"] == task["parameters"]["new_address"]
        assert catalog.entries() == base.entries()
        assert parent_identity(entry["contract"])["procedure_hash"] == catalog.boundaries()[entry["skill_id"]]["program_hash"]
    finally: env.close()
    env = Environment(fixture={"shipment": "PROCESSING", "risk": "HIGH"})
    try:
        result = run_agent(Model(actions), task, catalog, call(env))
        assert result["steps"][2]["error"] == "skill_boundary_inapplicable"
        assert not any(e["tool_name"] == "update_shipping_address" for e in env.audit)
    finally: env.close()


def test_primitive_assistance_and_checkpoint_bind_boundary_bundle():
    base, catalog, entry, task, _ = prepared("refund")
    env, snapshots = Environment(), []
    try:
        result = run_agent(Model([Action(type="tool", name="get_payment", arguments={"order_id": "O1"}),
            Action(type="tool", name="get_customer", arguments={"order_id": "O1"}),
            Action(type="tool", name="issue_refund", arguments=task["parameters"])]),
            task, catalog, call(env), persist=lambda state: snapshots.append(copy.deepcopy(state)))
        assert result["termination_source"] == "runtime"
        assert result["interventions"]["forced_readback_count"] == 1
        assert result["interventions"]["auto_termination_count"] == 1
        changed = catalog.boundaries(); changed[entry["skill_id"]]["patch"] = {
            "hypothesis_id": "new", "kind": "restrict", "predicates": [{"field": "request.amount", "op": "gt", "value": 3000}]}
        with pytest.raises(ValueError, match="identity"):
            run_agent(Model([]), task, BoundaryCatalog(base.entries(), changed), call(env), checkpoint=snapshots[0])
    finally: env.close()


def test_other_or_program_rebinding_cannot_enter_runtime():
    base, _, entry, _, _ = prepared("refund")
    binding = h0_bindings(base); binding[entry["skill_id"]]["program_hash"] = "forged"
    with pytest.raises(ValueError, match="frozen program"):
        BoundaryCatalog(base.entries(), binding)
    binding = h0_bindings(base); binding[entry["skill_id"]]["patch"] = {"hypothesis_id": "OTHER", "kind": "other", "predicates": []}
    with pytest.raises(ValueError, match="OTHER"):
        BoundaryCatalog(base.entries(), binding)
