"""P4 engineering tests only; no learning evidence or deployed library edits."""
import copy
import json

import pytest

from scripts.verify_skill_evolution_p4 import engineering_cases, engineering_entry, synthetic_pairs
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.catalog import revision, Catalog
from skillforge.skill_evolution.governance import identities, deduplicate, governed_revision, RevisionMemory, Lifecycle
from skillforge.skill_evolution.validation import declare_protocol, validate_program, audit_validation, program_admission, static_check
from skillforge.skill_evolution.admission import paired_gate
from skillforge.skill_evolution.workflows import GOALS


GOAL = GOALS["logistics_investigation"].identity


def revise(parent, *, kind="metadata", boundary=False):
    contract = copy.deepcopy(parent["contract"]); contract["version"] += 1
    if kind == "program": contract["procedure"][:3] = list(reversed(contract["procedure"][:3]))
    if boundary: contract["forbidden_conditions"] = [{"field": "order.status", "op": "eq", "value": "CANCELLED", "evidence": ["unit-only"]}]
    return revision(contract, name="Edited description", description="Metadata test", support_domain=parent["support_domain"], parent_revision=parent["revision"])


def validation_fixture(tmp_path):
    entry = engineering_entry()
    protocol = declare_protocol(entry, GOAL, engineering_cases(), SplitLedger(tmp_path / "sources"))
    return entry, protocol, validate_program(entry, protocol)


def test_semantic_identity_ignores_names_versions_and_input_aliases():
    entry = engineering_entry(); contract = copy.deepcopy(entry["contract"])
    contract.update(skill_id="other_name", version=9, inputs=["entity"])
    for node in contract["procedure"]:
        if node["kind"] == "call": node["arguments"]["order_id"] = "$input.entity"
    contract["postconditions"] = {key: "$input.entity" for key in contract["postconditions"]}
    assert identities(entry["contract"], GOAL)["semantic_fingerprint"] == identities(contract, GOAL)["semantic_fingerprint"]
    assert deduplicate(contract, GOAL, [entry])["status"] == "EXACT_DUPLICATE"


def test_reordered_calls_are_only_potential_duplicates():
    original = engineering_entry(); reordered = engineering_entry(["get_order_items", "get_order", "get_shipment"])
    result = deduplicate(reordered["contract"], GOAL, [original])
    assert result["status"] == "POTENTIAL_DUPLICATE" and not result["exact"]
    assert identities(original["contract"], GOAL)["program_fingerprint"] != result["program_fingerprint"]


def test_governance_enforces_revision_kind_boundary_lane_and_exact_parent():
    parent = engineering_entry(); metadata = revise(parent)
    sidecar = governed_revision(metadata, goal_hash=GOAL, parent=parent, revision_kind="metadata_revision")
    assert sidecar["supersedes"] == parent["revision"]
    program = revise(parent, kind="program")
    assert governed_revision(program, goal_hash=GOAL, parent=parent)["revision_kind"] == "program_revision"
    with pytest.raises(ValueError, match="metadata"): governed_revision(program, goal_hash=GOAL, parent=parent, revision_kind="metadata_revision")
    boundary = revise(parent, boundary=True)
    with pytest.raises(ValueError, match="boundary"): governed_revision(boundary, goal_hash=GOAL, parent=parent)
    assert governed_revision(boundary, goal_hash=GOAL, parent=parent, revision_kind="boundary_revision", lane="boundary")["lane"] == "boundary"
    bad = copy.deepcopy(program); bad["parent_revision"] = "wrong"; bad["revision"] = fingerprint({k:v for k,v in bad.items() if k != "revision"})
    with pytest.raises(ValueError, match="parent"): governed_revision(bad, goal_hash=GOAL, parent=parent)
    rejected = copy.deepcopy(parent); rejected["contract"]["status"] = "REJECTED"
    rejected["revision"] = fingerprint({k:v for k,v in rejected.items() if k != "revision"})
    with pytest.raises(ValueError, match="inactive"): governed_revision(revise(rejected, kind="program"), goal_hash=GOAL, parent=rejected)


def memory_attempt(ledger, index=1, split="dev"):
    ledger.claim("group", split, related_groups=["task"])
    return dict(candidate_revision=f"candidate-{index}", parent_revision="parent", trigger_gap="repeat failure",
        changed_nodes=[0], support_domain="unit dev", pairs=[{"source_group":"group", "task_id":"task", "split":split, "outcome":"tie"}],
        accepted_in_dev=False, reason="no gain", evidence_hashes=[fingerprint(index)])


def test_revision_memory_keeps_rejections_caps_attempts_and_replays_lineage(tmp_path):
    ledger = SplitLedger(tmp_path / "sources"); memory = RevisionMemory(tmp_path / "memory", ledger)
    first = memory.append(**memory_attempt(ledger, 1)); memory.append(**memory_attempt(ledger, 2))
    assert len(RevisionMemory(tmp_path / "memory", ledger).entries) == 2 and not first["attempt"]["accepted_in_dev"]
    with pytest.raises(ValueError, match="budget"): memory.append(**memory_attempt(ledger, 3))
    path = tmp_path / "memory/000001.json"; value = json.loads(path.read_text()); value["previous_hash"] = "other"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="integrity"): RevisionMemory(tmp_path / "memory", ledger)


@pytest.mark.parametrize("split", ["validation", "test", "stable_validation"])
def test_revision_memory_cannot_receive_formal_feedback(tmp_path, split):
    ledger = SplitLedger(tmp_path / "sources"); attempt = memory_attempt(ledger, split=split)
    with pytest.raises(ValueError, match="learn/dev"): RevisionMemory(tmp_path / "memory", ledger).append(**attempt)


def test_revision_memory_rejects_relabelled_heldout_source(tmp_path):
    ledger = SplitLedger(tmp_path / "sources"); attempt = memory_attempt(ledger, split="validation")
    attempt["pairs"][0]["split"] = "dev"
    with pytest.raises(ValueError, match="owned"): RevisionMemory(tmp_path / "memory", ledger).append(**attempt)


def test_engineering_validation_separates_completion_denial_and_fault_exit(tmp_path):
    _, _, report = validation_fixture(tmp_path)
    assert report["engineering_passed"] and report["decision"] == "INCONCLUSIVE" and not report["program_admitted"]
    assert report["category_counts"] == dict(positive=2, boundary=2, negative=2, fault=2)
    assert sum(row["eoc"]["task_success"] for row in report["cases"]) == 4
    assert all(row["behavior_conformant"] and row["database_unchanged"] and not row["pending_obligations"] for row in report["cases"])
    assert sum(row["raw_attempted_policy_violations"] for row in report["cases"]) == 1
    assert all(not row["unexpected_attempted_violations"] for row in report["cases"])
    assert audit_validation(report)["passed"]


@pytest.mark.parametrize("mutation", ["write", "instance", "state", "finish", "missing_read", "assert_order"])
def test_static_gate_rejects_unsafe_or_unbound_programs_before_dispatch(mutation):
    contract = engineering_entry()["contract"]
    if mutation == "write": contract["procedure"][0].update(tool="issue_refund", arguments={"order_id":"$input.order_id", "amount":1})
    elif mutation == "instance": contract["procedure"][0]["arguments"]["order_id"] = "training-order"
    elif mutation == "state": contract["procedure"][0]["arguments"]["order_id"] = "$state.order.order_id"
    elif mutation == "finish": contract["procedure"].insert(0, {"kind":"finish"})
    elif mutation == "missing_read": contract["procedure"].pop(2)
    else: contract["procedure"].insert(0,{"kind":"assert", "condition":{"field":"order.status", "value":"CONFIRMED", "evidence":["unit"]}})
    assert not static_check(contract, GOAL)["passed"]


def test_validation_replay_rejects_forged_eoc_even_with_recomputed_artifact_hash(tmp_path):
    _, _, report = validation_fixture(tmp_path)
    report["cases"][0]["eoc"]["task_success"] = False
    report["hash"] = fingerprint({k:v for k,v in report.items() if k != "hash"})
    with pytest.raises(ValueError, match="replay mismatch"): audit_validation(report)


def test_engineering_cannot_be_relabelled_formal_and_formal_sources_cannot_be_reused(tmp_path):
    entry, protocol, _ = validation_fixture(tmp_path)
    protocol["mode"] = "formal"; protocol["hash"] = fingerprint({k:v for k,v in protocol.items() if k != "hash"})
    with pytest.raises(ValueError, match="bound learn candidate"): validate_program(entry, protocol)
    ledger = SplitLedger(tmp_path / "heldout")
    case = engineering_cases()[0]["case"]; ledger.claim(case["source_group"], "validation")
    with pytest.raises(ValueError, match="cross splits"): declare_protocol(entry, GOAL, engineering_cases(), ledger)


def test_lifecycle_rejects_engineering_verification_activation_and_rejected_parent_reuse(tmp_path):
    entry, _, report = validation_fixture(tmp_path)
    sidecar = governed_revision(entry, goal_hash=GOAL)
    life = Lifecycle(tmp_path / "life", sidecar)
    life.transition("DISCOVERED", reason="unit fixture")
    life.transition("CANDIDATE", reason="unit fixture")
    with pytest.raises(ValueError, match="formal program admission"): life.transition("VERIFIED", reason="attempt bypass", evidence=program_admission(report))
    with pytest.raises(ValueError, match="invalid lifecycle"): life.transition("ISOLATED_ACTIVE", reason="attempt activation")
    life.transition("REJECTED", reason="unit rejection")
    assert Lifecycle(tmp_path / "life", sidecar).status == "REJECTED"
    with pytest.raises(ValueError): life.transition("CANDIDATE", reason="reuse rejected version")
    assert Catalog([entry]).search("SCRIPTED") == []


def test_paired_sign_gate_counts_source_groups_and_keeps_agent_admission_separate():
    protocol, pairs = synthetic_pairs()
    report = paired_gate(protocol, pairs)
    assert report["statistical_gate_passed"] and report["primary_source_groups"] == 6
    assert report["one_sided_sign_p_value"] == 1/64 and not report["agent_admitted"]
    small_protocol, many_tasks = synthetic_pairs(groups=1, tasks_per_group=100)
    small = paired_gate(small_protocol, many_tasks)
    assert small["matched_tasks"] == 101 and small["primary_source_groups"] == 1 and small["decision"] == "INCONCLUSIVE"


def test_paired_cost_gate_cannot_reward_cheaper_joint_failures():
    protocol, pairs = synthetic_pairs()
    for pair in pairs[:-1]:
        pair["baseline"]["eoc"] = pair["candidate"]["eoc"] = False
    report = paired_gate(protocol, pairs)
    assert report["decision"] == "INCONCLUSIVE" and report["wins"] == 0
    assert report["primary_source_groups"] == 6 and all(value == 0 for value in report["group_differences"].values())


@pytest.mark.parametrize("kind", ["stable_regression", "attempt", "actual", "workflow"])
def test_paired_hard_safety_and_stable_regression_override_statistical_gain(kind):
    protocol, pairs = synthetic_pairs()
    target = pairs[-1]["candidate"]
    if kind == "stable_regression": target["eoc"] = False
    else: target[{"attempt":"attempted_violations", "actual":"actual_violations", "workflow":"workflow_violations"}[kind]] = 1
    assert paired_gate(protocol, pairs)["decision"] == "REJECTED"


@pytest.mark.parametrize("kind", ["missing", "unsettled", "state", "source", "backend", "cost"])
def test_paired_gate_preserves_missing_cost_and_identity_failures(kind):
    protocol, pairs = synthetic_pairs()
    if kind == "missing": pairs.pop(0)
    elif kind == "unsettled": pairs[0]["candidate"]["cost_settled"] = False
    elif kind == "state": pairs[0]["initial_state_hash"] = "changed"
    elif kind == "source": pairs[0]["source_group"] = "changed"
    elif kind == "backend": pairs[0]["candidate"]["execution_identity"] = "different-runtime"
    else: pairs[0]["candidate"]["tokens"] = -1
    if kind in {"missing", "unsettled"}: assert paired_gate(protocol, pairs)["decision"] == "INCONCLUSIVE"
    else:
        with pytest.raises(ValueError): paired_gate(protocol, pairs)
