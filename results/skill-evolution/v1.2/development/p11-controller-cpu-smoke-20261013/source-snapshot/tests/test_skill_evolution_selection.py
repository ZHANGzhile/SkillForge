import copy
import json
import random

import pytest

from scripts.evolution_forks import prepare_snapshot, fork_starts, check_pair
from scripts.evolution_opportunities import evaluate_opportunities, selection_funnel
from skillforge.environment import Environment
from skillforge.evolution_common.snapshot import restore_snapshot
from skillforge.evolution_schemas import fingerprint
from skillforge.schemas import Task, ExpectedOutcome, Action
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.runtime import run_agent
from skillforge.verifier import verify
from test_skill_evolution_catalog import entry
from test_skill_evolution_runtime import Model, actions, call, TASK


def private_task(**kwargs):
    return Task(**{**TASK, **kwargs}, split="train", template_id="selection-engineering", seed=42,
                expected=ExpectedOutcome(allowed_outcomes=["completed"], expected_state={"order.status": "CANCELLED"}))


def staged(tmp_path, catalog, fixture=None, faults=None):
    env = Environment(fixture=fixture, faults=faults)
    observations = {}
    for tool in ("get_order", "get_customer", "get_shipment"):
        observations.update(env.call(tool, {"order_id": "O1"}, "C1"))
    initial = env.snapshot()
    snap = tmp_path / "snapshot"
    ident = prepare_snapshot(snap, env, TASK, catalog, observations, random.Random(42))
    return env, initial, snap, ident


def test_rank_audit_is_full_library_deterministic_and_private(tmp_path):
    first = entry()
    other = copy.deepcopy(first)
    other["skill_id"] = other["contract"]["skill_id"] = "zzz"
    other["revision"] = fingerprint({k: v for k, v in other.items() if k != "revision"})
    c = Catalog([other, first])
    found, audit = c.search_audited("cancel order", top_k=1)
    again, second = c.search_audited("cancel order", top_k=1)
    assert found == again and audit["ranking"] == second["ranking"]
    assert len(audit["ranking"]) == 2 and len(audit["truncated_candidates"]) == 1
    assert audit["catalog_hash"] == c.hash and audit["latency_ms"] >= 0
    assert "required_tools" in found[0] and "required_observations" in found[0]
    assert "components" not in str(found) and "private-" not in json.dumps(found)
    # v1 search remains reproducible, without newly introduced public fields.
    assert "required_tools" not in c.search("cancel")[0]


def test_independent_opportunity_uses_goal_execution_not_family_or_names(tmp_path):
    e = entry(); e["contract"]["family"] = "misleading_public_tag"
    e["name"] = "Pineapple"; e["description"] = "No task keyword"
    e["revision"] = fingerprint({k: v for k, v in e.items() if k != "revision"})
    c = Catalog([e]); env, initial, snap, identity = staged(tmp_path, c)
    result = evaluate_opportunities(private_task(), c, snap, tmp_path / "opportunities", identity["runtime_identity"])
    assert result["eligible_count"] == 1
    assert result["opportunities"][0]["verification"]["task_success"]
    assert env.snapshot() == initial  # Counterfactual writes never reach the source.
    env.close()


def test_same_name_family_and_postcondition_do_not_prove_opportunity(tmp_path):
    e = entry(); e["contract"]["procedure"] = [{"kind": "finish", "tool": "", "arguments": {}, "condition": None}]
    e["revision"] = fingerprint({k: v for k, v in e.items() if k != "revision"})
    c = Catalog([e]); env, _, snap, identity = staged(tmp_path, c)
    result = evaluate_opportunities(private_task(), c, snap, tmp_path / "opportunities", identity["runtime_identity"])
    assert result["eligible_count"] == 0 and result["opportunities"][0]["status"] == "EXECUTION_OR_GOAL_FAILED"
    env.close()


@pytest.mark.parametrize("fixture,faults,status", [({"risk": "HIGH"}, None, "GATE_INAPPLICABLE"),
                                                  (None, {"cancel_order": ["timeout"]}, "INCONCLUSIVE_EXECUTION")])
def test_blocked_and_fault_unknown_are_distinct_opportunity_results(tmp_path, fixture, faults, status):
    c = Catalog([entry()]); env, _, snap, ident = staged(tmp_path, c, fixture, faults)
    result = evaluate_opportunities(private_task(), c, snap, tmp_path / "opportunities", ident["runtime_identity"])
    assert result["opportunities"][0]["status"] == status and result["eligible_count"] == 0
    env.close()


def test_selection_funnel_counts_organic_chain_and_keeps_auditor_out_of_context(tmp_path):
    e = entry(); c = Catalog([e]); env, initial, snap, ident = staged(tmp_path, c)
    opportunities = evaluate_opportunities(private_task(), c, snap, tmp_path / "opp", ident["runtime_identity"])
    result = run_agent(Model(actions(e)), TASK, c, call(env))
    verdict = verify(private_task(), initial, env.snapshot(), env.audit, result["outcome"])
    funnel = selection_funnel(result, opportunities, verdict)
    assert all(v == 1 for v in funnel["organic_funnel"].values())
    assert funnel["recall_at_k"] == funnel["conditional_selection_rate"] == 1
    for step in result["steps"]:
        t = step["selection_trace"]
        assert t["model_visible_context_hash"] == fingerprint(step["context"])
        assert "selection_trace" not in json.dumps(step["context"])
        assert "opportunities" not in json.dumps(step["context"])
    assert result["search_events"][0]["audit"]["ranking"]
    assert result["steps"][2]["selection_trace"]["new_verification_receipts"]
    env.close()


def test_real_same_state_fork_validates_primitive_as_successful_alternative(tmp_path):
    e = entry(); c = Catalog([e]); source, initial, snap, ident = staged(tmp_path, c)
    opportunities = evaluate_opportunities(private_task(), c, snap, tmp_path / "opp", ident["runtime_identity"])
    refs = {e["skill_id"]: {"revision": e["revision"], "content_hash": e["revision"]}}
    starts = fork_starts(snap, c, refs)
    arms = {}
    for arm in ("provided", "withheld"):
        env, _, _ = restore_snapshot(snap, tmp_path / (arm + ".sqlite"), ident["runtime_identity"])
        sequence = ([Action(type="skill", name=e["skill_id"], arguments=TASK["parameters"]), Action(type="stop")]
                    if arm == "provided" else [Action(type="tool", name="cancel_order", arguments=TASK["parameters"])])
        result = run_agent(Model(sequence), TASK, c, call(env), public_start=starts[arm], max_search=0, max_load=0)
        verdict = verify(private_task(), initial, env.snapshot(), env.audit, result["outcome"])
        assert verdict["task_success"]
        arms[arm] = result
        funnel = selection_funnel(result, opportunities, verdict)
        if arm == "withheld":
            assert funnel["raw_counts"]["legal_primitive_alternative"] == 1
            assert funnel["opportunity_rows"][0]["primary_cause"] == "SUCCESSFUL_PRIMITIVE_ALTERNATIVE"
        else:
            assert funnel["raw_counts"]["verified"] == 1 and funnel["organic_funnel"]["searched"] == 0
        env.close()
    assert check_pair(arms["provided"], arms["withheld"])["passed"]
    assert source.snapshot() == initial
    corrupted = copy.deepcopy(arms["withheld"])
    corrupted["steps"][0]["context"]["observations"]["customer.risk_level"] = "HIGH"
    with pytest.raises(ValueError, match="differ beyond"): check_pair(arms["provided"], corrupted)
    source.close()


def test_opportunity_failure_classification_is_not_business_failure(tmp_path):
    e = entry(); c = Catalog([e]); env, initial, snap, ident = staged(tmp_path, c)
    opportunities = evaluate_opportunities(private_task(), c, snap, tmp_path / "opp", ident["runtime_identity"])
    sequence = [Action(type="tool", name="search_skills", arguments={"query": "pineapple"}),
                Action(type="tool", name="cancel_order", arguments=TASK["parameters"])]
    result = run_agent(Model(sequence), TASK, c, call(env))
    verdict = verify(private_task(), initial, env.snapshot(), env.audit, result["outcome"])
    funnel = selection_funnel(result, opportunities, verdict)
    row = funnel["opportunity_rows"][0]
    assert row["primary_cause"] == "SUCCESSFUL_PRIMITIVE_ALTERNATIVE"
    assert "RETRIEVAL_MISS" in row["error_labels"] and funnel["all_task_eoc"]
    env.close()


def test_fork_rejects_fabricated_public_observations(tmp_path):
    e = entry(); c = Catalog([e]); source, _, snap, _ = staged(tmp_path, c)
    path = snap / "snapshot.json"; item = json.loads(path.read_text())
    item["body"]["runtime"]["state"]["customer.risk_level"] = "HIGH"
    item["hash"] = fingerprint(item["body"])
    path.write_text(json.dumps(item), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly match"): fork_starts(snap, c, {})
    source.close()


def test_offered_not_selected_is_explicit_and_successful_primitive_is_preserved(tmp_path):
    e = entry(); c = Catalog([e]); env, initial, snap, ident = staged(tmp_path, c)
    opportunities = evaluate_opportunities(private_task(), c, snap, tmp_path / "opp", ident["runtime_identity"])
    sequence = actions(e)[:2] + [Action(type="tool", name="get_order", arguments=TASK["parameters"]),
                               Action(type="tool", name="get_customer", arguments=TASK["parameters"]),
                               Action(type="tool", name="cancel_order", arguments=TASK["parameters"])]
    result = run_agent(Model(sequence), TASK, c, call(env))
    verdict = verify(private_task(), initial, env.snapshot(), env.audit, result["outcome"])
    row = selection_funnel(result, opportunities, verdict)["opportunity_rows"][0]
    assert row["offered"] and row["gate_applicable"] and not row["selected"]
    assert "OFFERED_NOT_SELECTED" in row["error_labels"] and row["legal_primitive_alternative"]
    env.close()


def test_load_error_and_binding_error_are_audited_without_writes():
    e = entry(); c = Catalog([e]); env = Environment()
    sequence = [Action(type="tool", name="load_skill", arguments={"skill_id": e["skill_id"], "revision": "wrong"})]
    sequence += actions(e)[:2]
    sequence += [Action(type="skill", name=e["skill_id"], arguments={"order_id": "O2"}), Action(type="refuse")]
    result = run_agent(Model(sequence), TASK, c, call(env))
    assert result["steps"][0]["selection_trace"]["primary_cause"] == "NOT_LOADED"
    assert result["steps"][3]["selection_trace"]["primary_cause"] == "BINDING_ERROR"
    assert env.audit == []
    env.close()


def test_pre_model_failure_stays_in_cost_ledger_and_pending_work_blocks_retry(tmp_path, monkeypatch):
    import scripts.run_skill_evolution as runner
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    failed = tmp_path / "failed"; failed.mkdir()
    report = {"status": "blocked_or_incomplete", "n": 0, "charged_tokens_including_incomplete": 0,
              "wall_seconds": 1.25, "unfinished_task_budget": None,
              "failure": "ModuleNotFoundError: No module named 'psutil'"}
    (failed / "report.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="not explicitly reconciled"):
        runner.prior_cost({"shared_budget_roots": ["failed"]})
    assert runner.prior_cost({"closed_pre_model_failures": ["failed"]})[0]["wall_seconds"] == 1.25
    report["unfinished_task_budget"] = {"used": {"tokens": 16384}}
    (failed / "report.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="pending"):
        runner.prior_cost({"closed_pre_model_failures": ["failed"]})


def test_hard_negative_same_description_is_retrieved_but_not_an_opportunity(tmp_path):
    positive = entry(); negative = copy.deepcopy(positive)
    negative["skill_id"] = negative["contract"]["skill_id"] = "cancel_hard_negative"
    negative["contract"]["forbidden_conditions"][0]["value"] = "LOW"
    negative["revision"] = fingerprint({k: v for k, v in negative.items() if k != "revision"})
    c = Catalog([positive, negative])
    found, _ = c.search_audited("cancel order", top_k=2)
    assert {v["skill_id"] for v in found} == {positive["skill_id"], negative["skill_id"]}
    env, _, snap, identity = staged(tmp_path, c)
    result = evaluate_opportunities(private_task(), c, snap, tmp_path / "opp", identity["runtime_identity"])
    eligible = [r["skill_id"] for r in result["opportunities"] if r["eligible"]]
    assert eligible == [positive["skill_id"]]
    env.close()


def test_unresolvable_unknown_is_audited_without_permission_or_write():
    e = entry()
    e["contract"]["preconditions"].append({"field": "invoice.reviewed", "op": "eq", "value": True, "evidence": ["engineering-only"]})
    e["revision"] = fingerprint({k: v for k, v in e.items() if k != "revision"})
    env = Environment()
    result = run_agent(Model(actions(e)), TASK, Catalog([e]), call(env))
    trace = result["steps"][2]["selection_trace"]
    assert trace["primary_cause"] == "GATE_UNKNOWN" and not trace["executed_skill"]["success"]
    assert env.snapshot()["order.status"] == "CONFIRMED"
    assert not any(a["tool_name"] == "cancel_order" for a in env.audit)
    env.close()


def test_zero_catalog_budget_removes_virtual_tools_in_both_availability_arms():
    e = entry(); c = Catalog([e]); env = Environment()
    model = Model([Action(type="tool", name="cancel_order", arguments=TASK["parameters"])])
    run_agent(model, TASK, c, call(env), max_search=0, max_load=0)
    names = {t["name"] for t in model.contexts[0]["available_tools"]}
    assert "cancel_order" in names and not {"search_skills", "load_skill"} & names
    env.close()


def test_same_state_control_can_recover_via_search_load_with_equal_nonzero_budgets(tmp_path):
    e = entry(); c = Catalog([e]); source, _, snap, ident = staged(tmp_path, c)
    refs = {e["skill_id"]: {"revision": e["revision"], "content_hash": e["revision"]}}
    starts = fork_starts(snap, c, refs); results = {}
    for arm in ("provided", "withheld"):
        env, _, _ = restore_snapshot(snap, tmp_path / (arm + ".sqlite"), ident["runtime_identity"])
        sequence = ([Action(type="skill", name=e["skill_id"], arguments=TASK["parameters"]), Action(type="stop")]
                    if arm == "provided" else
                    [Action(type="skill", name="cancel_order", arguments=TASK["parameters"])] + actions(e))
        result = run_agent(Model(sequence), TASK, c, call(env), public_start=starts[arm])
        assert result["outcome"] == "completed" and result["skill_events"][0]["success"]
        if arm == "withheld":
            assert result["steps"][0]["error"] == "skill_not_loaded"
            assert result["metrics"]["search_calls"] == result["metrics"]["load_calls"] == 1
        results[arm] = result; env.close()
    pair = check_pair(results["provided"], results["withheld"])
    assert pair["passed"] and "equal discovery budgets" in pair["scope"]
    source.close()
