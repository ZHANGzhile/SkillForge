"""Synthetic RPC/token fixtures only; never real-model experiment evidence."""
import copy
import json
import queue
import shutil
import subprocess
import sys
import threading
import time

import pytest

from scripts.collect_skill_evolution_learn import collect_one, audit
from skillforge.environment import ToolError
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint
from skillforge.schemas import Action
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.compiler import compile_screen
from skillforge.skill_evolution.experience import normalize_calls, normalize_trajectory, mine_opportunities
from skillforge.skill_evolution.runtime import run_agent, runtime_sources, PROTOCOL, SYSTEM_PROMPT, public_policy_for, PUBLIC_POLICY
from skillforge.skill_evolution.workflows import GOALS, make_case


class SimulatedSession:
    """Emulates the token-reporting interface to test accounting, without LLM."""
    settings = {"model": "unit-test-simulated-token-interface", "engineering_only": False, "system_prompt": SYSTEM_PROMPT}
    def __init__(self, extra_search=False, ordered_reads=None):
        self.events, self.replies = queue.Queue(), queue.Queue()
        self.thread = None
        self.decisions, self.extra_search = 0, extra_search
        self.ordered_reads = ordered_reads

    def send(self, packet):
        if packet["type"] != "run":
            self.replies.put(packet); return
        def work():
            session = self
            actions = [Action(type="tool", name=name, arguments=packet["task"]["parameters"])
                       for name in (session.ordered_reads or GOALS[packet["task"]["family"]].required_evidence)]
            if self.extra_search:
                actions.insert(0, Action(type="tool", name="search_skills", arguments={"query": "shipment"}))
            actions.append(Action(type="stop"))
            iterator = iter(actions)
            class Model:
                settings = session.settings
                tokens = 0
                def decide(self, context):
                    assert not {"fixture", "expected", "verification", "split"} & set(context)
                    self.tokens += 100; session.decisions += 1
                    action = next(iterator)
                    self.last_messages = [{"role": "system", "content": SYSTEM_PROMPT},
                                          {"role": "user", "content": json.dumps(context)}]
                    self.last_response = action.model_dump_json()
                    return action
            def persist(value):
                self.events.put({"type": "checkpoint", "value": value})
                if self.replies.get(timeout=5)["type"] != "checkpoint_saved": raise RuntimeError("fixture cancelled")
            def tool(name, args, key, source):
                self.events.put({"type": "tool", "name": name, "arguments": args, "key": key, "source": source})
                response = self.replies.get(timeout=5)
                if response.get("error"): raise ToolError(response["error"])
                return response["result"]
            try:
                result = run_agent(Model(), packet["task"], Catalog(packet["catalog"]), tool, persist=persist, **packet["limits"])
                self.events.put({"type": "completed", "result": result})
            except RuntimeError:
                pass  # Test-only cancellation while blocked before inference.
        self.thread = threading.Thread(target=work); self.thread.start()

    def receive(self, timeout=5): return self.events.get(timeout=timeout)
    def close(self):
        if self.thread and self.thread.is_alive():
            self.replies.put({"type": "cancel"}); self.thread.join(timeout=5)
        assert not self.thread or not self.thread.is_alive()


CONFIG = {"limits": {"max_steps": 12, "max_search": 3, "max_load": 3, "max_tokens": 65536},
          "budget": {"project_max_tokens": 20000, "project_max_wall_seconds": 200}}


def fixture_row(tmp_path, seed=34123, extra_search=False, ordered_reads=None):
    case, session = make_case("logistics_investigation", seed, "train"), SimulatedSession(extra_search, ordered_reads)
    try:
        row, status = collect_one(session, case, Catalog([]), tmp_path / case.task_id, CONFIG, 0, 0, time.perf_counter())
        assert status["completed"] and row["verification"]["task_success"]
        assert status["charged_tokens"] == session.decisions * 100
        return row, status
    finally: session.close()


def test_real_rpc_controller_routes_workflow_eoc_and_reserves_per_request(tmp_path):
    row, status = fixture_row(tmp_path)
    assert row["agent"]["termination_source"] == "model" and len(row["tool_audit"]) == 3
    assert row["agent"]["interventions"]["runtime_intervention_count"] == 0
    assert status["charged_tokens"] == 400  # Simulated accounting units only.


def test_denied_budget_never_reaches_model_decide(tmp_path):
    session, case = SimulatedSession(), make_case("shipment_summary", 34123, "train")
    try:
        row, status = collect_one(session, case, Catalog([]), tmp_path / "denied", CONFIG, 19000, 0, time.perf_counter())
        assert row is None and status["denied_before_ack"] and status["charged_tokens"] == 0
        assert session.decisions == 0
    finally: session.close()


def test_normalization_uses_public_bindings_and_keeps_node_provenance(tmp_path):
    row, _ = fixture_row(tmp_path)
    norm = normalize_trajectory(row, SimulatedSession.settings)
    assert norm["usable_success"] and norm["pattern"]["calls"][0]["arguments"] == {"order_id": "$input.order_id"}
    assert row["case"]["parameters"]["order_id"] not in json.dumps(norm["pattern"])
    assert not {"fixture", "initial_state", "final_state", "expected"} & set(norm)
    assert norm["events"][0]["source"]["audit_index"] == 0
    assert {event["origin"] for event in norm["events"]} == {"model"}


def test_three_sources_with_no_discovery_adjusted_saving_are_not_useful(tmp_path):
    rows = [fixture_row(tmp_path, seed)[0] for seed in (34123, 34124, 34125)]
    result = mine_opportunities(rows, SimulatedSession.settings)
    assert result["status"] == "NO_USEFUL_OPPORTUNITY"
    assert result["records"][0]["checks"]["independent_sources"]
    assert result["records"][0]["expected_model_call_saving"] == 0


def test_opportunity_requires_independent_sources_even_with_measured_overhead(tmp_path):
    rows = [fixture_row(tmp_path, seed, extra_search=True)[0] for seed in (34123, 34124, 34125)]
    result = mine_opportunities(rows, SimulatedSession.settings)
    assert result["status"] == "OPPORTUNITIES_FOUND" and len(result["records"][0]["nodes"][0]["sources"]) == 3
    duplicate = copy.deepcopy(rows[0])
    assert mine_opportunities([rows[0], duplicate, copy.deepcopy(duplicate)], SimulatedSession.settings)["status"] == "NO_USEFUL_OPPORTUNITY"


@pytest.mark.parametrize("kind", ["test", "scripted", "identity"])
def test_heldout_scripted_or_wrong_identity_cannot_be_learn_evidence(tmp_path, kind):
    row, _ = fixture_row(tmp_path)
    settings = copy.deepcopy(SimulatedSession.settings)
    if kind == "test": row["case"]["split"] = "test"
    elif kind == "scripted": settings["engineering_only"] = True
    else: row["model_identity_hash"] = "forged"
    with pytest.raises(ValueError): normalize_trajectory(row, settings)


def test_unbound_failed_write_is_preserved_but_cannot_create_readonly_pattern(tmp_path):
    row, _ = fixture_row(tmp_path)
    row["verification"]["task_success"] = False
    row["tool_audit"].append({"tool_name": "create_ticket", "arguments": {"reason": "instance-specific"},
                              "result": None, "error": "timeout", "decision_origin": "model"})
    norm = normalize_trajectory(row, SimulatedSession.settings)
    assert not norm["usable_success"] and norm["normalization_error"]


def test_workflow_public_rules_allow_reads_in_high_risk_and_shipped_states():
    case = make_case("logistics_investigation", 34123, "train")
    policy = public_policy_for(case.public_task())
    assert policy["workflow_goal_hash"] == case.goal_hash and not policy["workflow_goal"]["writes_allowed"]
    assert public_policy_for({"family": "refund"}) == PUBLIC_POLICY


def test_worker_scratch_scope_denies_private_experiment_files(tmp_path):
    secret = tmp_path / "private-fixture.json"; secret.write_text('{"fixture": "private"}')
    packet = {"guard_test": True, "output": str(tmp_path / "worker-public"), "path": str(secret)}
    process = subprocess.run([sys.executable, "-m", "skillforge.execution_aware.worker"], input=json.dumps(packet)+"\n",
                             capture_output=True, text=True, timeout=15)
    assert process.returncode == 0 and json.loads(process.stdout)["type"] == "denied"


def audit_fixture(tmp_path):
    row, status = fixture_row(tmp_path)
    root = tmp_path
    sources = {"skillforge/" + name: digest for name, digest in runtime_sources().items()}
    repo = __import__("pathlib").Path(__file__).resolve().parents[1]
    for name in sources:
        target = root / "source-snapshot" / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repo / name, target)
    cases = [row["case"]]; goals = {k: {"goal": v.model_dump(), "hash": v.identity} for k, v in GOALS.items()}
    reg = {"sources": sources, "cases_hash": fingerprint(cases), "goal_set_hash": fingerprint(goals),
           "catalog_hash": Catalog([]).hash, "config": CONFIG, "protocol": PROTOCOL, "prior_tokens": 0, "prior_wall_seconds": 0}
    reg["protocol_hash"] = fingerprint(reg)
    Catalog([]).save(root / "catalog.json")
    immutable_json(root / "registration.json", reg)
    immutable_json(root / "goals.json", goals)
    immutable_json(root / "private-learn-cases.json", cases)
    immutable_json(root / "model-identity.json", SimulatedSession.settings)
    immutable_json(root / "report.json", {"status": "complete", "protocol_hash": reg["protocol_hash"], "n": 1, "planned": 1,
                    "tokens": 400, "eoc": 1, "charged_tokens_including_incomplete": 400,
                    "case_statuses": [status], "attempted_policy_violations": 0,
                    "actual_policy_violations": 0, "actual_workflow_violations": 0,
                    "shared_total_charged_tokens": 400, "shared_total_wall_seconds": 1, "wall_seconds": 1})
    return root


def test_independent_collection_audit_recomputes_eoc_and_cost(tmp_path):
    root = audit_fixture(tmp_path)
    assert audit(root)["n"] == 1
    path = root / "report.json"; report = json.loads(path.read_text()); report["tokens"] = 0
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="aggregate accounting"): audit(root)


def test_collection_audit_rejects_forged_safety_aggregate(tmp_path):
    root = audit_fixture(tmp_path)
    path = root / "report.json"; report = json.loads(path.read_text())
    report["actual_workflow_violations"] = 1
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="aggregate safety"): audit(root)


def compiler_fixture(tmp_path, ordered_reads=None):
    rows = [fixture_row(tmp_path, seed, extra_search=True, ordered_reads=ordered_reads)[0]
            for seed in (34123, 34124, 34125)]
    screen = mine_opportunities(rows, SimulatedSession.settings)
    return rows, screen, compile_screen(screen)


def test_trace_compiler_parameterizes_actual_events_and_keeps_candidate_unadmitted(tmp_path):
    from skillforge.environment import Environment
    from skillforge.execution_aware.contracts import ExecutionContract
    from skillforge.schemas import SkillContract
    from skillforge.skills import execute
    from skillforge.skill_evolution.workflows import WorkflowCase, private_items, verify_workflow
    rows, _, report = compiler_fixture(tmp_path)
    assert report["status"] == "CANDIDATES_PROPOSED" and report["n_candidates"] == 1
    candidate = report["results"][0]["candidate"]
    assert fingerprint({k: v for k, v in candidate.items() if k != "hash"}) == candidate["hash"]
    skill = SkillContract.model_validate(candidate["skill"])
    assert skill.status == "CANDIDATE" and not candidate["program_admitted"]
    assert all(len(node["sources"]) == 3 for node in candidate["node_provenance"])
    assert rows[0]["case"]["parameters"]["order_id"] not in json.dumps(candidate["skill"]["procedure"])
    # A fresh environment checks semantics independently of the compile code.
    case = WorkflowCase.model_validate(rows[0]["case"])
    env = Environment(fixture=case.fixture)
    try:
        initial, items = env.snapshot(), private_items(env)
        tracker = ExecutionContract("compiler-engineering-test")
        def dispatch(name, args, key): return env.call(name, args, case.authenticated_customer_id, key)
        event = execute(skill, case.parameters, {}, lambda name, args, key: tracker.call(dispatch, name, args, key, source="skill"), "candidate")
        verdict = verify_workflow(case, initial, env.snapshot(), env.audit,
                                  "completed" if event["success"] else "error", items, private_items(env))
        assert event["success"] and verdict["task_success"] and not tracker.pending()
        assert [e["tool_name"] for e in env.audit] == [node.tool for node in skill.procedure if node.kind == "call"]
    finally: env.close()


def test_changed_valid_trace_order_changes_program_without_family_template(tmp_path):
    _, _, first = compiler_fixture(tmp_path / "first")
    reverse = ["get_order_items", "get_shipment", "get_order"]
    _, _, second = compiler_fixture(tmp_path / "second", ordered_reads=reverse)
    left, right = first["results"][0]["candidate"], second["results"][0]["candidate"]
    assert left["skill"]["family"] == right["skill"]["family"]
    assert left["program_structure_hash"] != right["program_structure_hash"]
    assert [node["tool"] for node in right["skill"]["procedure"] if node["kind"] == "call"] == reverse


@pytest.mark.parametrize("tamper", ["source", "split", "event", "utility"])
def test_trace_compiler_rejects_forged_provenance_or_support(tmp_path, tamper):
    _, screen, _ = compiler_fixture(tmp_path)
    if tamper == "source": screen["records"][0]["nodes"][0]["sources"][0]["audit_index"] = 99
    elif tamper == "split": screen["normalized"][0]["split"] = "test"
    elif tamper == "event": screen["normalized"][0]["events"][0]["tool"] = "issue_refund"
    else: screen["records"][0]["expected_model_call_saving"] = 10
    with pytest.raises(ValueError): compile_screen(screen)


def test_trace_compiler_preserves_no_useful_opportunity_as_no_candidate(tmp_path):
    rows = [fixture_row(tmp_path, seed)[0] for seed in (34123, 34124, 34125)]
    report = compile_screen(mine_opportunities(rows, SimulatedSession.settings))
    assert report["status"] == "NO_USEFUL_CANDIDATE" and report["n_candidates"] == 0
    assert all(row["candidate"] is None for row in report["results"])
