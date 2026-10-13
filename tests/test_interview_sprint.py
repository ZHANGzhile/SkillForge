"""CPU contract checks only; these are not learned-Agent evidence."""
import copy
import pytest

from skillforge.environment import Environment, ToolError
from skillforge.schemas import SkillContract, SkillStep, Action
from skillforge.interview_sprint.workflows import GOAL, make_case, verify_workflow, private_items
from skillforge.interview_sprint import adapters as api
from skillforge.skill_evolution.catalog import Catalog


def receipts(case):
    env = Environment(fixture=case.fixture)
    before, items = env.snapshot(), private_items(env)
    for name in GOAL.required_evidence:
        env.call(name, case.parameters, case.authenticated_customer_id)
    result = (before, env.snapshot(), copy.deepcopy(env.audit), items, private_items(env))
    env.close()
    return result


def evaluate(case, data):
    initial, final, audit, before_items, after_items = data
    return verify_workflow(case, initial, final, audit, "completed", before_items, after_items)


def test_eoc_requires_complete_customer_and_payment_values():
    case = make_case(135001, "dev")
    data = receipts(case)
    assert evaluate(case, data)["task_success"]
    for name in ("get_customer", "get_payment"):
        damaged = copy.deepcopy(data)
        event = next(e for e in damaged[2] if e["tool_name"] == name)
        event["result"].pop(next(iter(event["result"])))
        assert not evaluate(case, damaged)["task_success"]
        damaged = copy.deepcopy(data)
        event = next(e for e in damaged[2] if e["tool_name"] == name)
        key = next(iter(event["result"])); event["result"][key] = "forged"
        assert not evaluate(case, damaged)["task_success"]


def test_boundary_reads_and_independent_denial():
    case = make_case(135002, "dev", "boundary")
    assert evaluate(case, receipts(case))["task_success"]
    for variant in ("unauthorized", "missing"):
        case = make_case(135003, "dev", variant); env = Environment(fixture=case.fixture)
        initial, items = env.snapshot(), private_items(env)
        with pytest.raises(ToolError): env.call("get_customer", case.parameters, case.authenticated_customer_id)
        verdict = verify_workflow(case, initial, env.snapshot(), env.audit, "refused", items, private_items(env))
        assert verdict["task_success"] and verdict["expected_denial_observed"]
        env.close()


def test_existing_dsl_can_execute_five_reads_but_validator_rejects_missing_reads():
    case = make_case(135004, "dev")
    skill = SkillContract(skill_id="cpu_only_contract", family=GOAL.workflow_id, inputs=["order_id"],
        preconditions=[], forbidden_conditions=[], procedure=[SkillStep(kind="call", tool=name,
        arguments={"order_id": "$input.order_id"}) for name in GOAL.required_evidence] + [SkillStep(kind="finish")],
        postconditions={"order.order_id": "$input.order_id", "payment.order_id": "$input.order_id", "shipment.order_id": "$input.order_id"},
        source_trajectory_ids=[], policy_version="v1.1", status="CANDIDATE")
    functions = api.validation_functions()
    assert functions["static_check"](skill.model_dump(), GOAL.identity)["passed"]
    result = functions["run_case"](skill.model_dump(), {"case": case.model_dump(), "category": "positive"})
    assert result["behavior_conformant"]
    broken = skill.model_dump(); broken["procedure"] = [n for n in broken["procedure"] if n.get("tool") != "get_payment"]
    assert not functions["static_check"](broken, GOAL.identity)["passed"]


def test_runtime_keeps_original_weights_prompt_and_rejects_writes():
    class Scripted:
        settings = {"engineering_only": True}
        tokens = 0
        def __init__(self): self.contexts = []; self.actions = iter([
            Action(type="tool", name="cancel_order", arguments={"order_id": "IS13-O-135005"}), Action(type="stop")])
        def decide(self, context): self.contexts.append(context); return next(self.actions)
    case = make_case(135005, "dev"); model = Scripted(); env = Environment(fixture=case.fixture)
    def tool(name, args, key, source): return env.call(name, args, case.authenticated_customer_id, key)
    result = api.run_agent(model, case.public_task(), Catalog([]), tool)
    assert result["steps"][0]["error"] == "invalid_tool" and not env.audit
    tools = {t["name"] for t in model.contexts[0]["available_tools"]}
    assert not tools.intersection({"cancel_order", "issue_refund", "create_ticket", "escalate_to_human"})
    assert "fixture" not in model.contexts[0]
    env.close()


def test_versioned_rpc_miner_compiler_validation_and_replay_contract(tmp_path):
    """Synthetic token/RPC fixture only, NOT an autonomous-learning result."""
    import importlib.util
    import time
    from pathlib import Path
    from scripts.run_interview_sprint import collect_one, audit_arm
    from skillforge.interview_sprint.workflows import GOALS
    from skillforge.skill_evolution.catalog import revision
    from skillforge.evolution_common.artifacts import SplitLedger
    spec = importlib.util.spec_from_file_location("sprint_cpu_fixture", Path(__file__).with_name("test_skill_evolution_learn.py"))
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    class Session(fixture.SimulatedSession):
        send = api.bind(fixture.SimulatedSession.send, {"GOALS": GOALS, "run_agent": api.run_agent})
    session, rows = Session(), []
    config = copy.deepcopy(fixture.CONFIG)
    try:
        for i in range(3):
            case = make_case(135100+i, "train"); folder = tmp_path / case.task_id
            row, status = collect_one(session, case, Catalog([]), folder, config, 0, 0, time.perf_counter())
            assert status["completed"] and row["verification"]["task_success"]
            receipt = audit_arm(folder, case, Catalog([]), session.settings, config["limits"], (0,20000,0,200))
            assert receipt["passed"] and receipt["replay_tool_calls"] == 5
            rows.append(row)
        screen = api.mine_opportunities(rows, session.settings)
        compiled = api.compile_screen(screen)
        assert compiled["n_candidates"] == 1
        candidate = compiled["results"][0]["candidate"]
        assert len(candidate["skill"]["procedure"]) == 6 and candidate["expected_model_call_saving"] == 2
        entry = revision(candidate["skill"], name="CPU fixture only", description="not model learning evidence", support_domain={})
        ledger = SplitLedger(tmp_path / "ledger")
        for row in rows: ledger.claim(row["case"]["source_group"], "train")
        cases = []
        for i, category in enumerate(["positive","positive","boundary","boundary","negative","negative","fault","fault"]):
            case = make_case(135200+i,"validation","boundary" if category == "boundary" else "instance")
            item = {"case":case.model_dump(),"category":category,"stable":i==1}
            if category == "negative": item.update(authenticated_customer_id="OTHER",expected_error="permission_denied")
            if category == "fault": item.update(faults={"get_payment":["timeout"]},expected_error="timeout")
            cases.append(item)
        functions = api.validation_functions()
        protocol = functions["declare_protocol"](entry,GOAL.identity,cases,ledger,mode="formal",learn_candidate=candidate)
        report = functions["validate_program"](entry,protocol)
        assert report["decision"] == "ADMITTED"
        assert functions["program_admission"](report)["audit"]["passed"]
    finally: session.close()
