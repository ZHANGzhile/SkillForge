"""CPU P4 engineering acceptance; scripted fixtures never teach or activate."""
import argparse
from pathlib import Path
import shutil
import time

from scripts.collect_skill_evolution_learn import audit, read
from scripts.continue_skill_evolution_selection import publish
from scripts.run_skill_evolution import ROOT, digest_file
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.evolution_schemas import fingerprint
from skillforge.schemas import SkillContract, SkillStep
from skillforge.skill_evolution.catalog import Catalog, revision
from skillforge.skill_evolution.compiler import compile_screen
from skillforge.skill_evolution.governance import deduplicate, governed_revision, Lifecycle, RevisionMemory
from skillforge.skill_evolution.validation import declare_protocol, validate_program, program_admission, audit_program_admission, ValidationCase
from skillforge.skill_evolution.runtime import runtime_sources
from skillforge.skill_evolution.admission import declare_paired_protocol, paired_gate
from skillforge.skill_evolution.workflows import GOALS, make_case


def engineering_cases():
    """Declared goals/probes, fresh dev sources; not formal holdout or learning."""
    rows = []
    categories = ["positive", "boundary", "boundary", "negative", "negative", "fault", "fault", "positive"]
    for index, category in enumerate(categories):
        case = make_case("logistics_investigation", 2026101400 + index, "dev")
        case.fixture.update(risk="LOW", order="CONFIRMED", shipment="NOT_STARTED")
        extra = {}
        if index == 1: case.fixture.update(risk="HIGH", shipment="SHIPPED")
        if index == 2: case.fixture.update(order="CANCELLED", shipment="DELIVERED")
        if index == 3: extra.update(authenticated_customer_id="unauthorized-p4-probe", expected_error="permission_denied")
        if index == 4: extra.update(parameters={"order_id": "missing-p4-probe"}, expected_error="not_found")
        if index == 5: extra.update(faults={"get_shipment": ["timeout"]}, expected_error="timeout")
        if index == 6: extra.update(faults={"get_order_items": ["response_lost"]}, expected_error="timeout")
        rows.append({"case": case.model_dump(), "category": category, "stable": index == 7, **extra})
    return rows


def engineering_entry(order=None):
    goal = GOALS["logistics_investigation"]
    contract = SkillContract(skill_id="p4_scripted_engineering_fixture", family=goal.workflow_id, inputs=["order_id"],
        preconditions=[], forbidden_conditions=[],
        procedure=[SkillStep(kind="call", tool=name, arguments={"order_id": "$input.order_id"})
                   for name in (order or ["get_order", "get_shipment", "get_order_items"])] + [SkillStep(kind="finish")],
        postconditions={"order.order_id": "$input.order_id", "shipment.order_id": "$input.order_id"},
        source_trajectory_ids=[], policy_version="v1.1", status="CANDIDATE")
    return revision(contract.model_dump(), name="SCRIPTED ENGINEERING FIXTURE", description="Not a learned Skill",
                    support_domain={"goal_hash": goal.identity, "scope": "scripted engineering only"})


def synthetic_pairs(groups=6, tasks_per_group=1):
    """Arithmetic fixtures, no model calls; never real Agent evidence."""
    plans, pairs = [], []
    for group in range(groups + 1):
        for task in range(tasks_per_group if group < groups else 1):
            task_id = f"engineering-pair-{group}-{task}"
            plan = {"task_id": task_id, "source_group": f"engineering-source-{group}",
                    "task_hash": fingerprint(task_id), "initial_state_hash": fingerprint([group, task]),
                    "split": "validation" if group < groups else "stable_validation"}
            plans.append(plan)
            common = {"eoc": True, "attempted_violations": 0, "actual_violations": 0, "workflow_violations": 0,
                      "cost_settled": True, "execution_identity": "engineering-same-backend",
                      "evidence_hash": fingerprint(["synthetic-not-Agent-evidence", task_id])}
            pairs.append({key: plan[key] for key in ("task_id", "source_group", "task_hash", "initial_state_hash")} | {
                "baseline": common | {"catalog_hash": "engineering-old-catalog", "model_calls": 5, "tokens": 1000},
                "candidate": common | {"catalog_hash": "engineering-new-catalog", "model_calls": 4, "tokens": 900}})
    protocol = declare_paired_protocol(plans, baseline_catalog_hash="engineering-old-catalog",
        candidate_catalog_hash="engineering-new-catalog", execution_identity="engineering-same-backend")
    return protocol, pairs


def run(output, compiler_run):
    started = time.perf_counter()
    output, compiler_run = Path(output).resolve(), Path(compiler_run).resolve()
    binding, proposal = read(compiler_run / "binding.json"), read(compiler_run / "report.json")
    if fingerprint({key: value for key, value in binding.items() if key != "hash"}) != binding["hash"]:
        raise ValueError("compiler binding integrity mismatch")
    for name, digest in binding["sources"].items():
        if digest_file(compiler_run / ("source-" + Path(name).name)) != digest:
            raise ValueError("saved compiler source mismatch")
        if digest_file(ROOT / name) != digest:
            raise ValueError("replay with the registered compiler source version")
    learn = ROOT / binding["learn_run"]
    collection_audit = audit(learn)
    if not collection_audit["run_completed"] or collection_audit["report_sha256"] != binding["learn_report_sha256"]:
        raise ValueError("compiler/learn report mismatch")
    screen = read(compiler_run / "opportunity-screen.json")
    if fingerprint(screen) != binding["opportunity_screen_hash"] or compile_screen(screen) != proposal:
        raise ValueError("compiler screen/report replay mismatch")
    # This entrypoint only exercises a no-candidate round. Actual candidates
    # must go through separately declared formal validation, not these fixtures.
    if proposal["n_candidates"]:
        raise ValueError("real candidates require a separate formal validation protocol")
    output.mkdir(parents=True, exist_ok=False)
    snapshot = {"skillforge/" + name: digest for name, digest in runtime_sources().items()}
    snapshot["skillforge/tool_schemas.py"] = digest_file(ROOT / "skillforge/tool_schemas.py")
    snapshot["scripts/verify_skill_evolution_p4.py"] = digest_file(__file__)
    for name, digest in snapshot.items():
        target = output / "source-snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        if digest_file(target) != digest: raise ValueError("P4 snapshot source changed")
    publish(output / "source-index.json", snapshot)
    cases = engineering_cases()
    sources = {}
    for name in ("skillforge/skill_evolution/governance.py", "skillforge/skill_evolution/validation.py",
                 "skillforge/skill_evolution/admission.py", "scripts/verify_skill_evolution_p4.py"):
        target = output / ("source-" + Path(name).name)
        shutil.copyfile(ROOT / name, target); sources[name] = digest_file(target)
        if sources[name] != digest_file(ROOT / name): raise ValueError("P4 source changed during registration")
    publish(output / "engineering-suite.json", {"cases": cases, "goal_hash": GOALS["logistics_investigation"].identity,
            "sources": sources, "mode": "engineering", "scope": "scripted fixtures; no learning or formal admission"})
    ledger = SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger")
    entry = engineering_entry()
    goal = GOALS["logistics_investigation"].identity
    protocol = declare_protocol(entry, goal, cases, ledger)
    publish(output / "protocol.json", protocol)
    validation = validate_program(entry, protocol)
    publish(output / "program-validation.json", validation)
    receipt = program_admission(validation)
    publish(output / "program-admission.json", receipt)
    alternate = engineering_entry(["get_order_items", "get_shipment", "get_order"])
    duplicate = deduplicate(alternate["contract"], goal, [entry])
    sidecar = governed_revision(entry, goal_hash=goal)
    publish(output / "governance-revision.json", sidecar)
    life = Lifecycle(output / "lifecycle", sidecar)
    life.transition("DISCOVERED", reason="scripted engineering fixture only")
    life.transition("CANDIDATE", reason="exercise lifecycle guards")
    life.transition("INCONCLUSIVE", reason="engineering evidence cannot admit a program", evidence={"receipt_hash": receipt["hash"]})
    memory = RevisionMemory(output / "revision-memory", ledger)
    memory.append(candidate_revision=entry["revision"], parent_revision="engineering-parent", trigger_gap="engineering-only",
                  changed_nodes=[0], support_domain="dev only", pairs=[{"source_group": cases[0]["case"]["source_group"],
                  "task_id": cases[0]["case"]["task_id"], "split": "dev", "outcome": "tie"}], accepted_in_dev=False,
                  reason="exercise retained-parent path", evidence_hashes=[validation["hash"]])
    pair_protocol, pairs = synthetic_pairs()
    pair_report = paired_gate(pair_protocol, pairs)
    small_protocol, small_pairs = synthetic_pairs(groups=1, tasks_per_group=30)
    small_report = paired_gate(small_protocol, small_pairs)
    publish(output / "synthetic-paired-gate.json", pair_report)
    publish(output / "synthetic-small-sample.json", small_report)
    passed = (validation["engineering_passed"] and receipt["decision"] == "INCONCLUSIVE" and
              duplicate["status"] == "POTENTIAL_DUPLICATE" and life.status == "INCONCLUSIVE" and
              pair_report["statistical_gate_passed"] and small_report["decision"] == "INCONCLUSIVE")
    report = {"schema": "p4-engineering-report-v1", "engineering_passed": bool(passed),
              "compiler_run": compiler_run.relative_to(ROOT).as_posix(), "source_snapshot_hash": fingerprint(snapshot),
              "real_learn_report_sha256": binding["learn_report_sha256"], "compiler_binding_hash": binding["hash"],
              "real_candidates": 0, "no_update_reason": "NO_USEFUL_CANDIDATE", "retained_catalog_hash": Catalog.load(learn / "catalog.json").hash,
              "engineering_program_cases": len(validation["cases"]), "category_counts": validation["category_counts"],
              "engineering_tool_calls": validation["tool_calls"] + receipt["audit"]["replay_tool_calls"],
              "validation_tool_calls": validation["tool_calls"], "audit_replay_tool_calls": receipt["audit"]["replay_tool_calls"],
              "program_admission_decision": receipt["decision"],
              "coarse_duplicate_status": duplicate["status"], "synthetic_gate_passed": pair_report["statistical_gate_passed"],
              "small_sample_gate": small_report["decision"], "model_calls": 0, "tokens": 0,
              "cpu_engineering_wall_seconds": time.perf_counter() - started,
              "program_admitted": False, "agent_admitted": False, "research_claim_passed": None,
              "isolated_activated": False, "deployed": False, "sources": sources,
              "scope": "CPU engineering only; scripted fixtures excluded from learn; real parent retained; no Skill registration"}
    publish(output / "report.json", report)
    return report


def audit_engineering(root):
    """Replay saved CPU evidence, without inference or new source claims."""
    root = Path(root).resolve()
    report, index = read(root / "report.json"), read(root / "source-index.json")
    if fingerprint(index) != report["source_snapshot_hash"]:
        raise ValueError("P4 snapshot index mismatch")
    for name, digest in index.items():
        if digest_file(root / "source-snapshot" / name) != digest:
            raise ValueError("P4 archived source mismatch")
    for name, digest in report["sources"].items():
        if index[name] != digest or digest_file(root / ("source-" + Path(name).name)) != digest:
            raise ValueError("P4 engineering source mismatch")
    validation, receipt = read(root / "program-validation.json"), read(root / "program-admission.json")
    protocol = read(root / "protocol.json")
    suite = read(root / "engineering-suite.json")
    if (validation["protocol"] != protocol or receipt["report"] != validation or
            protocol["mode"] != "engineering" or suite["mode"] != "engineering" or
            [ValidationCase.model_validate(item).model_dump() for item in suite["cases"]] != protocol["cases"]):
        raise ValueError("P4 suite/protocol/report mismatch")
    replay = audit_program_admission(receipt)
    sidecar = read(root / "governance-revision.json")
    if sidecar != governed_revision(validation["entry"], goal_hash=protocol["goal_hash"]):
        raise ValueError("P4 governance revision mismatch")
    life = Lifecycle(root / "lifecycle", sidecar)
    memory = RevisionMemory(root / "revision-memory", SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger"))
    if life.status != "INCONCLUSIVE" or len(memory.entries) != 1 or memory.entries[0]["attempt"]["accepted_in_dev"]:
        raise ValueError("P4 engineering lifecycle/memory mismatch")
    gates = [read(root / name) for name in ("synthetic-paired-gate.json", "synthetic-small-sample.json")]
    for gate in gates:
        if paired_gate(gate["protocol"], gate["pairs"]) != gate:
            raise ValueError("P4 paired statistics mismatch")
    compiler = ROOT / report["compiler_run"]
    binding, proposal = read(compiler / "binding.json"), read(compiler / "report.json")
    if fingerprint({key: value for key, value in binding.items() if key != "hash"}) != binding["hash"]:
        raise ValueError("P4 compiler binding mismatch")
    learn = ROOT / binding["learn_run"]
    collection = audit(learn)
    screen = read(compiler / "opportunity-screen.json")
    if (not collection["run_completed"] or collection["report_sha256"] != binding["learn_report_sha256"] or
            fingerprint(screen) != binding["opportunity_screen_hash"] or compile_screen(screen) != proposal or proposal["n_candidates"]):
        raise ValueError("P4 retained-parent proof mismatch")
    expected = {"real_learn_report_sha256": binding["learn_report_sha256"], "compiler_binding_hash": binding["hash"],
                "real_candidates": 0, "no_update_reason": "NO_USEFUL_CANDIDATE", "retained_catalog_hash": Catalog.load(learn / "catalog.json").hash,
                "engineering_program_cases": len(validation["cases"]), "category_counts": validation["category_counts"],
                "validation_tool_calls": validation["tool_calls"], "audit_replay_tool_calls": receipt["audit"]["replay_tool_calls"],
                "engineering_tool_calls": validation["tool_calls"] + receipt["audit"]["replay_tool_calls"],
                "program_admission_decision": "INCONCLUSIVE", "synthetic_gate_passed": True, "small_sample_gate": "INCONCLUSIVE",
                "model_calls": 0, "tokens": 0, "program_admitted": False, "agent_admitted": False,
                "research_claim_passed": None, "isolated_activated": False, "deployed": False, "engineering_passed": True}
    if (not validation["engineering_passed"] or not gates[0]["statistical_gate_passed"] or gates[1]["decision"] != "INCONCLUSIVE" or
            any(fingerprint(report[key]) != fingerprint(value) for key, value in expected.items())):
        raise ValueError("P4 aggregate/disposition mismatch")
    result = {"passed": True, "generator_sha256": digest_file(__file__), "report_sha256": digest_file(root / "report.json"),
              "source_snapshot_hash": fingerprint(index), "real_candidates": 0, "retained_parent": True,
              "model_calls": 0, "tokens": 0, "audit_replay_tool_calls": replay["replay_tool_calls"],
              "scope": "archived sources, independent program replay, lifecycle/memory, grouped statistics and real no-update binding"}
    publish(root / "evidence-audits" / (result["generator_sha256"] + ".json"), result)
    return result


if __name__ == "__main__":
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output"); parser.add_argument("--compiler-run"); parser.add_argument("--run")
    args = parser.parse_args()
    if not args.run and not (args.output and args.compiler_run): parser.error("provide --run for audit or --compiler-run and --output for engineering")
    report = audit_engineering(args.run) if args.run else run(args.output, args.compiler_run)
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report.get("passed", report.get("engineering_passed")) else 1)
