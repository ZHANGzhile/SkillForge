"""Frozen three-round readonly Skill Evolution study, including honest no-ops.

Research collection uses fixed main-v3 with no scripted model fallback. Formal
validation stays private to the release controller. No test feedback reaches
the learner. Historical development protocols/ledgers remain unchanged.
"""
import argparse
from contextlib import ExitStack
import json
import math
from pathlib import Path
import shutil
import time

from scripts.collect_skill_evolution_learn import collect_one, evaluate_static
from scripts.continue_skill_evolution_selection import publish
from scripts.plan_skill_evolution_reuse import build_draft
from scripts.run_skill_evolution import ROOT, ModelSession, digest_file
from scripts.run_skill_evolution_reuse import audit as audit_smoke, audit_incomplete, check_no_history
from scripts.skill_evolution_release import (AgentRelease, ADAPTER, ADAPTER_SHA, fixed_model,
    hashed, relative, source_index)
from skillforge.evolution_common.artifacts import SplitLedger, clone, record
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.agent_evidence import read, semantic, audit_trajectory, declare_evidence_protocol
from skillforge.skill_evolution.catalog import Catalog, revision
from skillforge.skill_evolution.compiler import compile_screen
from skillforge.skill_evolution.experience import mine_opportunities
from skillforge.skill_evolution.governance import governed_revision, deduplicate
from skillforge.skill_evolution.registry import VersionedRegistry, verified_publication
from skillforge.skill_evolution.runtime import runtime_sources
from skillforge.skill_evolution.validation import (checked_hash, declare_protocol, validate_program,
    program_admission, audit_program_admission)
from skillforge.skill_evolution.workflows import WorkflowCase


LEDGER = "results/skill-evolution/v1.2/source-ledger"
PHASES = "results/skill-evolution/v1.2/research-budget-ledger"


def cases_and_partitions(draft):
    values = []
    for item in draft["rounds"]:
        values.extend((case, "train") for case in item["learn_cases"])
        for probes in item["program_validation_probes"].values():
            values.extend((probe["case"], "stable_validation" if probe["stable"] else "validation") for probe in probes)
        values.extend((value["case"], "stable_validation" if value["stable"] else "validation") for value in item["agent_validation_cases"])
    values.extend((value["case"], "test") for value in draft["final_test_cases"])
    return values


def register(draft_root, smoke, output, *, preflight, phase_id, phase_tokens=2800000, phase_wall=7200):
    draft_root, smoke, output, preflight = map(lambda path: Path(path).resolve(), (draft_root, smoke, output, preflight))
    if output.exists() or not phase_id:
        raise ValueError("fresh research root and phase identity required")
    prior_audit = audit_smoke(smoke)
    if not prior_audit["run_completed"] or not prior_audit["costs_reconciled"]:
        raise ValueError("complete independently audited cost smoke required")
    previous, smoke_registration = read(smoke / "report.json"), read(smoke / "registration.json")
    draft = read(draft_root / "draft.json"); checked_hash(draft)
    if draft != build_draft(smoke_registration, previous):
        raise ValueError("three-round draft or cost basis changed")
    check = read(preflight / "preflight.json")
    if not check["passed"] or check["pytest"]["status"] != "passed":
        raise ValueError("full independent preflight required before formal freeze")
    if (type(phase_tokens) is not int or not 2755920 <= phase_tokens <= 7864320 or
            type(phase_wall) not in {int, float} or not math.isfinite(phase_wall) or not 6994 <= phase_wall <= 43200):
        raise ValueError("explicit bounded research phase must cover frozen cost estimate")
    if previous["shared_total_charged_tokens"]+phase_tokens > 20000000 or previous["shared_total_wall_seconds"]+phase_wall > 43200:
        raise ValueError("cumulative study must remain within 20M-token envelope")
    if list((ROOT / PHASES).glob("*.json")):
        raise ValueError("research phase already registered; resume/audit it instead of resetting costs")
    settings = read(smoke / "model-identity.json"); fixed_model(settings)
    sources = source_index()
    for name in (__file__, "scripts/plan_skill_evolution_reuse.py"):
        source = Path(name) if Path(name).is_absolute() else ROOT / name
        sources[relative(source)] = digest_file(source)
    # The preflight copies the exact code tested. Reject tests of another tree.
    copied = Path(check["pytest"]["source_copy"])
    if any(not (copied / name).exists() or digest_file(copied / name) != value for name, value in sources.items()):
        raise ValueError("formal controller/source tree differs from independently tested copy")
    ledger = SplitLedger(ROOT / LEDGER)
    all_keys = set()
    for case, partition in cases_and_partitions(draft):
        WorkflowCase.model_validate(case).public_task()
        keys = {case["task_id"], case["source_group"], case["parameters"]["order_id"], case["authenticated_customer_id"]}
        if all_keys & keys or any(key in ledger.owners for key in keys):
            raise ValueError("formal source/task/entity is reused from another round, split or prior run")
        all_keys.update(keys)
    output.mkdir(parents=True)
    for name, value in sources.items():
        target = output / "source-snapshot" / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        if digest_file(target) != value:
            raise ValueError("source changed while freezing research protocol")
    for case, partition in cases_and_partitions(draft):
        ledger.claim(case["source_group"], partition,
            related_groups=[case["task_id"], case["parameters"]["order_id"], case["authenticated_customer_id"]])
    config = smoke_registration["config"]
    registry_report = read(ROOT / config["registry_run"] / "report.json")
    parent_registry = VersionedRegistry(ROOT / config["registry_run"] / "r")
    parent_snapshot = registry_report["snapshots"]["retained_parent"]
    _, baseline = parent_registry.load(parent_snapshot)
    budget = {"phase_id": phase_id, "prior_tokens": previous["shared_total_charged_tokens"],
        "prior_wall": previous["shared_total_wall_seconds"], "phase_max_tokens": phase_tokens,
        "phase_max_wall": phase_wall, "max_tokens": previous["shared_total_charged_tokens"]+phase_tokens,
        "max_wall": previous["shared_total_wall_seconds"]+phase_wall,
        "scope": "new explicit research allowance; previous development charges retained, old ceilings unchanged; wall is not GPU hours"}
    body = {"schema": "p5-three-round-research-protocol-v1", "frozen": True, "folder": relative(output),
        "draft": draft, "draft_hash": draft["hash"], "phase_id": phase_id, "budget": budget,
        "prior_smoke": relative(smoke), "prior_smoke_report_sha256": digest_file(smoke / "report.json"),
        "preflight": relative(preflight), "preflight_sha256": digest_file(preflight / "preflight.json"),
        "sources": sources, "runtime_sources": runtime_sources(), "settings": settings,
        "model_config": {key: config[key] for key in ("training_config", "adapter", "adapter_sha256", "limits")},
        "baseline_entries": baseline.entries(), "parent_registry": relative(parent_registry.root), "parent_snapshot": parent_snapshot,
        "screen": {"min_sources": 3, "min_model_call_saving": 1},
        "candidate_selection": "at most one: smallest compiled pattern_id; selected before formal validation; no validation feedback",
        "failure_policy": "no automatic replay of started arms; preserve unknown reservation; stop study on unresolved collection",
        "test_policy": "once after three round decisions; final test cannot change programs, boundaries or decoding",
        "research_claim_rule": "report raw paired source-unit differences; no gain claim from identical B/C catalogs",
        "unsupported": draft["generalization"], "no_history": draft["no_history"], "deployed": False}
    protocol = hashed(body); publish(output / "protocol.json", protocol)
    publish(ROOT / PHASES / (fingerprint(phase_id)+".json"), hashed({"phase_id": phase_id,
        "folder": relative(output), "protocol_hash": protocol["hash"], "budget": budget}))
    return protocol


def load_protocol(root):
    root = Path(root).resolve(); value = read(root / "protocol.json"); checked_hash(value)
    if value["schema"] != "p5-three-round-research-protocol-v1" or value["frozen"] is not True or value["folder"] != relative(root):
        raise ValueError("formal protocol/root identity mismatch")
    owner = read(ROOT / PHASES / (fingerprint(value["phase_id"])+".json"))
    if owner != hashed({"phase_id": value["phase_id"], "folder": relative(root), "protocol_hash": value["hash"], "budget": value["budget"]}):
        raise ValueError("research budget phase binding mismatch")
    for name, expected in value["sources"].items():
        if digest_file(ROOT / name) != expected or digest_file(root / "source-snapshot" / name) != expected:
            raise ValueError("frozen research source changed; use archived controller")
    expected_sources = source_index()
    for name in (__file__, "scripts/plan_skill_evolution_reuse.py"):
        path = Path(name) if Path(name).is_absolute() else ROOT / name
        expected_sources[relative(path)] = digest_file(path)
    if expected_sources != value["sources"] or runtime_sources() != value["runtime_sources"]:
        raise ValueError("complete frozen execution/controller identity required")
    if digest_file(ROOT / value["prior_smoke"] / "report.json") != value["prior_smoke_report_sha256"]:
        raise ValueError("inherited development costs changed")
    fixed_model(value["settings"])
    ledger = SplitLedger(ROOT / LEDGER)
    for case, partition in cases_and_partitions(value["draft"]):
        if any(ledger.owners.get(key) != partition for key in
                (case["task_id"], case["source_group"], case["parameters"]["order_id"], case["authenticated_customer_id"])):
            raise ValueError("formal source/entity ownership differs")
    return value


def import_registry(root, protocol):
    registry = ResearchRegistry(Path(root) / "r")
    if not registry.root.exists():
        shutil.copytree(ROOT / protocol["parent_registry"], registry.root)
    _, catalog = registry.load(protocol["parent_snapshot"])
    if catalog.entries() != protocol["baseline_entries"]:
        raise ValueError("exact audited development parent required")
    return registry


def collect_stage(root, folder, protocol, cases, catalogs, prior_tokens, prior_wall):
    """One model load; independently sandbox each scheduled arm. Stop on failure."""
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    folder = Path(folder)
    if folder.exists():
        raise ValueError("stage already started; audit existing evidence instead of replay")
    folder.mkdir(parents=True)
    plan = hashed({"schema": "p5-registered-collection-stage-v1", "protocol_hash": protocol["hash"],
        "cases": clone(cases), "catalogs": {name: catalog.entries() for name, catalog in catalogs.items()},
        "prior_tokens": prior_tokens, "prior_wall": prior_wall,
        "order": [{"case_index": index, "method": method} for index, item in enumerate(cases) for method in item["methods"]]})
    publish(folder / "plan.json", plan)
    statuses, failure, started = [], None, time.perf_counter()
    config = {**protocol["model_config"], "budget": {"project_max_tokens": protocol["budget"]["max_tokens"],
        "project_max_wall_seconds": protocol["budget"]["max_wall"]}}
    try:
        with GPUServiceLease(), ExitStack() as cleanup:
            timeout = protocol["budget"]["max_wall"]-prior_wall-10
            if timeout <= 0: raise TimeoutError("registered cumulative wall budget exhausted")
            session = ModelSession(config, folder, init_timeout=timeout); cleanup.callback(session.close)
            if session.settings != protocol["settings"]:
                raise ValueError("fixed real backend identity differs from formal freeze")
            publish(folder / "model-identity.json", session.settings)
            for scheduled in plan["order"]:
                index, method = scheduled["case_index"], scheduled["method"]
                case = WorkflowCase.model_validate(cases[index]["case"])
                _, status = collect_one(session, case, catalogs[method], folder / str(index) / method, config,
                    prior_tokens+sum(row["status"]["charged_tokens"] for row in statuses), prior_wall, started)
                statuses.append({**scheduled, "status": status})
                print(json.dumps({"stage": relative(folder, root), "case": case.task_id, "method": method,
                    "tokens": status["charged_tokens"], "completed": status["completed"]}), flush=True)
                if not status["completed"]: raise RuntimeError(status["failure"])
    except Exception as exc:
        failure = type(exc).__name__+": "+str(exc)
    report = hashed({"schema": "p5-collection-stage-cost-v1", "plan_hash": plan["hash"], "statuses": statuses,
        "failure": failure, "wall_seconds": time.perf_counter()-started,
        "charged_tokens": sum(item["status"]["charged_tokens"] for item in statuses),
        "complete": len(statuses) == len(plan["order"]) and failure is None})
    publish(folder / "report.json", report)
    return report


def audit_stage(folder, protocol, *, cases, catalogs, prior_tokens, prior_wall):
    folder = Path(folder); plan, report = read(folder / "plan.json"), read(folder / "report.json")
    checked_hash(plan); checked_hash(report)
    expected = hashed({"schema": "p5-registered-collection-stage-v1", "protocol_hash": protocol["hash"],
        "cases": clone(cases), "catalogs": {name: catalog.entries() for name, catalog in catalogs.items()},
        "prior_tokens": prior_tokens, "prior_wall": prior_wall,
        "order": [{"case_index": index, "method": method} for index, item in enumerate(cases) for method in item["methods"]]})
    if plan != expected or report["plan_hash"] != plan["hash"]:
        raise ValueError("stage differs from frozen cases/catalog/order/budget")
    if (type(report["wall_seconds"]) not in {int, float} or not math.isfinite(report["wall_seconds"]) or report["wall_seconds"] < 0 or
            [{key: item[key] for key in ("case_index", "method")} for item in report["statuses"]] != plan["order"][:len(report["statuses"])]):
        raise ValueError("stage elapsed time/order invalid")
    if report["statuses"] and read(folder / "model-identity.json") != protocol["settings"]:
        raise ValueError("actual model differs from protocol")
    if {relative(path, folder) for path in folder.glob("*/*/collection-status.json")} != {
            str(item["case_index"])+"/"+item["method"]+"/collection-status.json" for item in report["statuses"]}:
        raise ValueError("orphan raw stage costs cannot be omitted")
    packets, rows, charged, incomplete, max_elapsed = [], [], 0, False, 0
    for item in report["statuses"]:
        if incomplete: raise ValueError("collection continued after incomplete arm")
        index, method, status = item["case_index"], item["method"], item["status"]
        path = folder / str(index) / method
        if read(path / "collection-status.json") != status:
            raise ValueError("stage raw status/cost mismatch")
        context = {"prior_tokens": prior_tokens+charged, "max_tokens": protocol["budget"]["max_tokens"],
            "prior_wall": prior_wall, "max_wall": protocol["budget"]["max_wall"]}
        if status["completed"]:
            row = read(path / "result.json")
            if row["case"] != cases[index]["case"] or row["schema"] != "workflow-learn-trajectory-v1":
                raise ValueError("stage raw case/collector differs")
            check_no_history(row)
            coverage = read(path / "static-coverage.json")
            if (row["static_coverage"] != coverage or semantic(coverage) !=
                    semantic(evaluate_static(WorkflowCase.model_validate(row["case"]), catalogs[method])) or
                    status["static_evaluation_tool_calls"] != sum(len(value["tool_audit"]) for value in coverage)):
                raise ValueError("static coverage/cost differs from independent sandbox execution")
            packet = audit_trajectory(path, catalogs[method], protocol["settings"], protocol["runtime_sources"],
                protocol["model_config"]["limits"], charge_context=context)
            packets.append({"case_index": index, "method": method, "evidence": packet}); rows.append(row)
        else:
            audit_incomplete(path, context); incomplete = True
        charged += status["charged_tokens"]
        for receipt in (path / "admissions").glob("*.json"):
            max_elapsed = max(max_elapsed, read(receipt)["elapsed_seconds"])
    complete = len(report["statuses"]) == len(plan["order"]) and not incomplete and report["failure"] is None
    if (charged != report["charged_tokens"] or report["complete"] != complete or
            report["wall_seconds"]+1e-6 < max_elapsed or prior_tokens+charged > protocol["budget"]["max_tokens"]):
        raise ValueError("stage accounting/completion cannot be independently reconciled")
    return {"report": report, "packets": packets, "rows": rows, "complete": complete}


def audit_proposal(round_root):
    round_root = Path(round_root).resolve(); root = round_root.parent
    protocol = load_protocol(root)
    start = read(round_root / "start.json"); checked_hash(start)
    number = start["round"]
    if start["protocol_hash"] != protocol["hash"] or not 1 <= number <= 3:
        raise ValueError("round start/protocol mismatch")
    if round_root.name != "r"+str(number):
        raise ValueError("round path/number mismatch")
    expected_parent, tokens, wall = protocol["parent_snapshot"], protocol["budget"]["prior_tokens"], protocol["budget"]["prior_wall"]
    lineage_registry = ResearchRegistry(root / "r")
    for previous_number in range(1, number):
        prior = audit_round(root, protocol, lineage_registry, previous_number, parent=expected_parent, prior_tokens=tokens, prior_wall=wall)
        expected_parent = prior["selected_snapshot"]; tokens += prior["charged_tokens"]; wall += prior["wall_seconds"]
    if start != hashed({"round": number, "protocol_hash": protocol["hash"], "parent_snapshot": expected_parent,
            "prior_tokens": tokens, "prior_wall": wall}):
        raise ValueError("proposal must inherit the complete audited round lineage and costs")
    planned = protocol["draft"]["rounds"][number-1]
    registry = ResearchRegistry(root / "r"); _, catalog = registry.load(start["parent_snapshot"])
    cases = [{"case": case, "methods": ["C"]} for case in planned["learn_cases"]]
    audit = audit_stage(round_root / "learn", protocol, cases=cases, catalogs={"C": catalog},
        prior_tokens=start["prior_tokens"], prior_wall=start["prior_wall"])
    if not audit["complete"]:
        raise ValueError("incomplete real learn cannot produce formal proposal")
    rows = sorted(audit["rows"], key=lambda item: item["case"]["task_id"])
    screen = mine_opportunities(rows, protocol["settings"], **protocol["screen"])
    proposal = compile_screen(screen)
    if read(round_root / "screen.json") != screen or read(round_root / "proposal.json") != proposal:
        raise ValueError("learn-only proposal differs from raw evidence replay")
    return hashed({"schema": "p5-audited-round-proposal-v1", "round_root": relative(round_root),
        "round_start_hash": start["hash"], "protocol_hash": protocol["hash"], "catalog_hash": catalog.hash,
        "collection_report_hash": audit["report"]["hash"], "agent_evidence": audit["packets"], "proposal": proposal,
        "new_model_calls": 0, "new_tokens": 0})


class ResearchRegistry(VersionedRegistry):
    """VersionedRegistry extension for this frozen study's learn provenance."""
    @staticmethod
    def _audit_registration(value):
        if value.get("provenance_schema") != "p5-audited-round-proposal-v1":
            return VersionedRegistry._audit_registration(value)
        receipt = value["program_admission"]; audit_program_admission(receipt)
        proposal = value["proposal_entry"]
        if (receipt["decision"] != "ADMITTED" or receipt["catalog_revision"] != proposal["revision"] or
                receipt["report"]["entry"] != proposal or verified_publication(proposal) != value["published_entry"]):
            raise ValueError("formal round program validation/publication mismatch")
        provenance = audit_proposal(ROOT / value["compiler_run"])
        candidates = [item["candidate"] for item in provenance["proposal"]["results"] if item["candidate"] is not None]
        candidate = receipt["report"]["protocol"]["learn_candidate"]
        if provenance["hash"] != value["provenance_hash"] or candidate not in candidates or candidate["skill"] != proposal["contract"]:
            raise ValueError("formal round candidate lacks real learn provenance")
        if value["governance"] != governed_revision(proposal, goal_hash=candidate["goal_hash"], parent=value["parent_entry"]):
            raise ValueError("formal round governance/parent changed")
        return provenance

    def register_program(self, parent_snapshot, entry, *, program_admission, compiler_run, reason):
        provenance = audit_proposal(compiler_run)
        previous, catalog = self.load(parent_snapshot)
        if provenance["catalog_hash"] != catalog.hash:
            raise ValueError("proposal parent catalog mismatch")
        parent = next((item for item in catalog.entries() if item["skill_id"] == entry["skill_id"]), None)
        goal = entry["support_domain"]["goal_hash"]
        duplicate = deduplicate(entry["contract"], goal, [item for item in catalog.entries() if item != parent])
        if duplicate["status"] != "NOVEL":
            raise ValueError("duplicate candidate cannot publish without controlled comparison")
        value = {"kind": "formal_program", "provenance_schema": provenance["schema"], "proposal_entry": clone(entry),
            "published_entry": verified_publication(entry), "parent_entry": parent, "program_admission": clone(program_admission),
            "governance": governed_revision(entry, goal_hash=goal, parent=parent), "compiler_run": relative(compiler_run),
            "provenance_hash": provenance["hash"], "deduplication": duplicate, "agent_admitted_by_this_run": False}
        self._audit_registration(value)
        registration_id = record(self.root, "registrations", value); published = value["published_entry"]
        return self._snapshot([item for item in catalog.entries() if item != parent]+[published], parent=parent_snapshot,
            operation="PROGRAM_REGISTERED", reason=reason, evidence={"registration_id": registration_id},
            registrations={**previous["registrations"], published["revision"]: registration_id})


def run_round(root, protocol, registry, planned, parent, prior_tokens, prior_wall):
    root = Path(root); number = planned["round"]; folder = root / ("r"+str(number))
    if folder.exists(): raise ValueError("round already started; audit existing evidence")
    folder.mkdir()
    started = time.perf_counter()
    start = hashed({"round": number, "protocol_hash": protocol["hash"], "parent_snapshot": parent,
        "prior_tokens": prior_tokens, "prior_wall": prior_wall})
    publish(folder / "start.json", start)
    _, catalog = registry.load(parent)
    learn = collect_stage(root, folder / "learn", protocol,
        [{"case": case, "methods": ["C"]} for case in planned["learn_cases"]], {"C": catalog}, prior_tokens, prior_wall)
    if not learn["complete"]:
        raise RuntimeError("formal learn incomplete; preserve evidence and reconcile, no automatic replay")
    rows = [read(folder / "learn" / str(index) / "C/result.json") for index in range(len(planned["learn_cases"]))]
    rows.sort(key=lambda item: item["case"]["task_id"])
    screen = mine_opportunities(rows, protocol["settings"], **protocol["screen"])
    proposal = compile_screen(screen)
    publish(folder / "screen.json", screen); publish(folder / "proposal.json", proposal)
    provenance = audit_proposal(folder); publish(folder / "proposal-audit.json", provenance)
    candidates = sorted((item for item in proposal["results"] if item["candidate"] is not None), key=lambda item: item["pattern_id"])
    selected, program_decision, agent_decision, activation = parent, "SKIPPED_NO_CANDIDATE", "SKIPPED_NO_CANDIDATE", None
    agent_cost, candidate_snapshot = {"charged_tokens": 0, "wall_seconds": 0}, None
    if candidates:
        candidate = candidates[0]["candidate"]
        entry = revision(candidate["skill"], name=candidate["purpose"], description=candidate["purpose"],
            support_domain={"goal_hash": candidate["goal_hash"], "scope": candidate["support_domain"]})
        ledger = SplitLedger(ROOT / LEDGER)
        validation = declare_protocol(entry, candidate["goal_hash"], planned["program_validation_probes"][candidate["skill"]["family"]],
            ledger, mode="formal", learn_candidate=candidate)
        publish(folder / "program-validation-protocol.json", validation)
        receipt = program_admission(validate_program(entry, validation)); publish(folder / "program-admission.json", receipt)
        program_decision = receipt["decision"]; agent_decision = "SKIPPED_PROGRAM_NOT_ADMITTED"
        if program_decision == "ADMITTED":
            candidate_snapshot = registry.register_program(parent, entry, program_admission=receipt, compiler_run=folder, reason="formal readonly candidate")
            _, proposed = registry.load(candidate_snapshot)
            paired = declare_evidence_protocol(planned["agent_validation_cases"], catalog, proposed, protocol["settings"],
                protocol["runtime_sources"], protocol["model_config"]["limits"], ledger,
                budget={"prior_tokens": prior_tokens+learn["charged_tokens"], "max_tokens": protocol["budget"]["max_tokens"],
                    "prior_wall": prior_wall+learn["wall_seconds"], "max_wall": protocol["budget"]["max_wall"]})
            release = AgentRelease(registry, ledger)
            release.declare(folder / "agent", parent=parent, candidate=candidate_snapshot, protocol=paired,
                config=protocol["model_config"], phase_id=protocol["phase_id"]+"-r"+str(number))
            agent_cost = release.collect(folder / "agent")
            agent = release.admit(folder / "agent"); agent_decision = agent["decision"]
            if agent_decision == "ADMITTED":
                activation = release.activate(folder / "agent", folder / "isolated")
                release.open_isolated(folder / "isolated"); selected = candidate_snapshot
    if selected == parent:
        evidence = hashed({"round": number, "proposal_hash": provenance["hash"], "program_decision": program_decision,
            "agent_decision": agent_decision, "candidate_snapshot": candidate_snapshot,
            "program_admitted": program_decision == "ADMITTED", "agent_admitted": False, "isolated_activated": False, "deployed": False})
        selected = registry.retain(parent, reason="NO_USEFUL_CANDIDATE" if not candidates else "CANDIDATE_NOT_AGENT_ADMITTED", evidence=evidence)
    _, kept = registry.load(selected)
    result = hashed({"schema": "p5-complete-round-v1", "round": number, "start_hash": start["hash"],
        "parent_snapshot": parent, "selected_snapshot": selected, "candidate_snapshot": candidate_snapshot,
        "parent_catalog_hash": catalog.hash, "selected_catalog_hash": kept.hash,
        "proposal_audit_hash": provenance["hash"], "n_candidates": proposal["n_candidates"],
        "program_decision": program_decision, "agent_decision": agent_decision,
        "program_admitted": program_decision == "ADMITTED", "agent_admitted": agent_decision == "ADMITTED",
        "isolated_activated": activation is not None, "activation_hash": activation["hash"] if activation else None,
        "deployed": False, "charged_tokens": learn["charged_tokens"]+agent_cost["charged_tokens"],
        "learn_model_calls": sum(row["agent"]["metrics"]["llm_calls"] for row in rows),
        "learn_static_coverage_tool_calls": sum(item["status"]["static_evaluation_tool_calls"] for item in learn["statuses"]),
        "program_validation_tool_calls": read(folder / "program-admission.json")["report"]["tool_calls"] if candidates else 0,
        "wall_seconds": learn["wall_seconds"]+agent_cost["wall_seconds"],
        "cycle_wall_seconds_including_cpu_audits": time.perf_counter()-started,
        "validation_feedback_to_optimizer": False, "complete": True})
    publish(folder / "result.json", result)
    return result


def audit_round(root, protocol, registry, number, *, parent, prior_tokens, prior_wall):
    folder = Path(root) / ("r"+str(number)); result, start = read(folder / "result.json"), read(folder / "start.json")
    checked_hash(result); checked_hash(start)
    if start != hashed({"round": number, "protocol_hash": protocol["hash"], "parent_snapshot": parent,
            "prior_tokens": prior_tokens, "prior_wall": prior_wall}) or result["start_hash"] != start["hash"]:
        raise ValueError("round lineage or inherited budget mismatch")
    proposal = audit_proposal(folder)
    if read(folder / "proposal-audit.json") != proposal or result["proposal_audit_hash"] != proposal["hash"]:
        raise ValueError("round proposal audit binding mismatch")
    learn = read(folder / "learn/report.json")
    agent_cost = {"charged_tokens": 0, "wall_seconds": 0}
    decision = "SKIPPED_NO_CANDIDATE" if not proposal["proposal"]["n_candidates"] else None
    if decision:
        if result["candidate_snapshot"] is not None or result["program_decision"] != decision or result["agent_decision"] != decision:
            raise ValueError("zero candidate cannot fabricate admission")
    else:
        program = read(folder / "program-admission.json"); audit_program_admission(program)
        chosen = sorted((item for item in proposal["proposal"]["results"] if item["candidate"] is not None), key=lambda item: item["pattern_id"])[0]["candidate"]
        entry = revision(chosen["skill"], name=chosen["purpose"], description=chosen["purpose"],
            support_domain={"goal_hash": chosen["goal_hash"], "scope": chosen["support_domain"]})
        planned = protocol["draft"]["rounds"][number-1]
        expected_validation = declare_protocol(entry, chosen["goal_hash"], planned["program_validation_probes"][chosen["skill"]["family"]],
            SplitLedger(ROOT / LEDGER), mode="formal", learn_candidate=chosen)
        if program["report"]["entry"] != entry or program["report"]["protocol"] != expected_validation:
            raise ValueError("candidate selection or formal program probes differ from predeclaration")
        if result["program_decision"] != program["decision"]:
            raise ValueError("program receipt disposition changed")
        if program["decision"] != "ADMITTED" and (result["agent_decision"] != "SKIPPED_PROGRAM_NOT_ADMITTED" or result["candidate_snapshot"] is not None):
            raise ValueError("program rejection/inconclusive cannot admit or register an Agent candidate")
        if program["decision"] == "ADMITTED":
            release = AgentRelease(registry, SplitLedger(ROOT / LEDGER))
            agent = release.audit_receipt(folder / "agent"); agent_cost = read(folder / "agent/collection-report.json")
            _, proposed = registry.load(result["candidate_snapshot"])
            expected_paired = declare_evidence_protocol(planned["agent_validation_cases"], registry.load(parent)[1], proposed,
                protocol["settings"], protocol["runtime_sources"], protocol["model_config"]["limits"], SplitLedger(ROOT / LEDGER),
                budget={"prior_tokens": prior_tokens+learn["charged_tokens"], "max_tokens": protocol["budget"]["max_tokens"],
                    "prior_wall": prior_wall+learn["wall_seconds"], "max_wall": protocol["budget"]["max_wall"]})
            declaration = read(folder / "agent/declaration.json")
            if declaration["protocol"] != expected_paired or agent["binding"]["parent_snapshot"] != parent or agent["binding"]["candidate_snapshot"] != result["candidate_snapshot"]:
                raise ValueError("formal Agent holdouts/backend/budget or candidate binding changed")
            if result["agent_decision"] != agent["decision"]:
                raise ValueError("Agent receipt disposition changed")
            if agent["agent_admitted"]:
                release.open_isolated(folder / "isolated")
                activation = read(folder / "isolated/activation.json")
                if result["selected_snapshot"] != agent["binding"]["candidate_snapshot"] or result["activation_hash"] != activation["hash"]:
                    raise ValueError("selected admitted snapshot/activation mismatch")
            elif result["activation_hash"] is not None:
                raise ValueError("Agent rejection/inconclusive cannot carry activation evidence")
    selected, catalog = registry.load(result["selected_snapshot"])
    _, previous = registry.load(parent)
    if not result["agent_admitted"]:
        if selected["operation"] != "RETAIN_PARENT" or selected["parent_snapshot"] != parent or catalog.hash != previous.hash:
            raise ValueError("rejection/no-update must retain exact parent")
        evidence = hashed({"round": number, "proposal_hash": proposal["hash"], "program_decision": result["program_decision"],
            "agent_decision": result["agent_decision"], "candidate_snapshot": result["candidate_snapshot"],
            "program_admitted": result["program_decision"] == "ADMITTED", "agent_admitted": False,
            "isolated_activated": False, "deployed": False})
        if selected["evidence"] != evidence or result["activation_hash"] is not None:
            raise ValueError("retained snapshot must bind exact audited round disposition")
    if (result["parent_snapshot"] != parent or result["parent_catalog_hash"] != previous.hash or result["selected_catalog_hash"] != catalog.hash or
            result["n_candidates"] != proposal["proposal"]["n_candidates"] or result["program_admitted"] != (result["program_decision"] == "ADMITTED") or
            result["agent_admitted"] != (result["agent_decision"] == "ADMITTED") or result["isolated_activated"] != result["agent_admitted"] or
            result["charged_tokens"] != learn["charged_tokens"]+agent_cost["charged_tokens"] or
            result["wall_seconds"] != learn["wall_seconds"]+agent_cost["wall_seconds"] or not result["complete"] or result["deployed"] or
            result["validation_feedback_to_optimizer"] is not False):
        raise ValueError("round disposition/cost/parent invariant mismatch")
    if (result["learn_model_calls"] != sum(item["evidence"]["model_calls"] for item in proposal["agent_evidence"]) or
            result["learn_static_coverage_tool_calls"] != sum(item["status"]["static_evaluation_tool_calls"] for item in learn["statuses"]) or
            result["program_validation_tool_calls"] != (read(folder / "program-admission.json")["report"]["tool_calls"] if not decision else 0)):
        raise ValueError("round model/scripted validation cost counters differ")
    return result


def final_cases(protocol):
    methods = ("A", "B", "C")
    return [{"case": item["case"], "methods": list(methods[index % 3:]+methods[:index % 3])}
        for index, item in enumerate(protocol["draft"]["final_test_cases"])]


def summarize_final(protocol, audited):
    by_method, paired = {}, []
    for method in ("A", "B", "C"):
        packets = [item["evidence"] for item in audited["packets"] if item["method"] == method]
        rows = [row for item, row in zip(audited["packets"], audited["rows"]) if item["method"] == method]
        by_method[method] = {"n": len(packets), **{key: sum(packet[key] for packet in packets) for key in
            ("eoc", "autonomous_eoc", "runtime_assisted_eoc", "model_calls", "tokens", "attempted_violations", "actual_violations", "workflow_violations")},
            "tool_calls": sum(row["agent"]["metrics"]["tool_calls"] for row in rows),
            "search_calls": sum(row["agent"]["metrics"]["search_calls"] for row in rows),
            "load_calls": sum(row["agent"]["metrics"]["load_calls"] for row in rows)}
    for index, item in enumerate(protocol["draft"]["final_test_cases"]):
        arms = {row["method"]: row["evidence"] for row in audited["packets"] if row["case_index"] == index}
        if set(arms) != {"A", "B", "C"}: continue
        if any(len({arm[key] for arm in arms.values()}) != 1 for key in ("task_hash", "initial_state_hash", "execution_identity")):
            raise ValueError("final arms differ in task/state/backend")
        b, c = arms["B"], arms["C"]
        paired.append({"task_id": c["task_id"], "source_group": c["source_group"], "stratum": item["stratum"],
            "B_eoc": b["eoc"], "C_eoc": c["eoc"], "C_minus_B_eoc": int(c["eoc"])-int(b["eoc"]),
            "B_minus_C_model_calls_joint_success": b["model_calls"]-c["model_calls"] if b["eoc"] and c["eoc"] else 0,
            "B_minus_C_tokens_joint_success": b["tokens"]-c["tokens"] if b["eoc"] and c["eoc"] else 0,
            "case_regression": b["eoc"] and not c["eoc"]})
    return {"methods": by_method, "paired_C_B": paired,
        "scripted_static_coverage_tool_calls": sum(item["status"]["static_evaluation_tool_calls"] for item in audited["report"]["statuses"]),
        "source_groups": len({item["source_group"] for item in paired}), "negative_transfer_cases": sum(item["case_regression"] for item in paired),
        "G_learn": "NOT_ESTIMATED: learn collection is not an independent paired learn_eval",
        "no_history_checked_arms": len(audited["packets"]), "statistical_unit": "source_group",
        "scope": "predeclared readonly strata only; EOC does not require Skill use; no training or unsupported structural generalization"}


def run(root):
    root = Path(root).resolve(); protocol = load_protocol(root); registry = import_registry(root, protocol)
    parent, prior_tokens, prior_wall = protocol["parent_snapshot"], protocol["budget"]["prior_tokens"], protocol["budget"]["prior_wall"]
    rounds = []
    for planned in protocol["draft"]["rounds"]:
        path = root / ("r"+str(planned["round"]))
        if not (path / "result.json").exists():
            run_round(root, protocol, registry, planned, parent, prior_tokens, prior_wall)
        result = audit_round(root, protocol, registry, planned["round"], parent=parent, prior_tokens=prior_tokens, prior_wall=prior_wall)
        rounds.append(result); parent = result["selected_snapshot"]
        prior_tokens += result["charged_tokens"]; prior_wall += result["wall_seconds"]
        print(json.dumps({"round_complete": planned["round"], "candidates": result["n_candidates"],
            "agent_decision": result["agent_decision"], "cumulative_tokens": prior_tokens}), flush=True)
    _, selected = registry.load(parent)
    catalogs = {"A": Catalog([]), "B": Catalog(protocol["baseline_entries"]), "C": selected}
    publish(root / "decisions-frozen.json", hashed({"protocol_hash": protocol["hash"], "round_hashes": [item["hash"] for item in rounds],
        "selected_snapshot": parent, "catalogs": {key: value.hash for key, value in catalogs.items()},
        "prior_tokens": prior_tokens, "prior_wall": prior_wall, "test_feedback_to_optimizer": False}))
    if not (root / "test/report.json").exists():
        collect_stage(root, root / "test", protocol, final_cases(protocol), catalogs, prior_tokens, prior_wall)
    audited = audit_stage(root / "test", protocol, cases=final_cases(protocol), catalogs=catalogs, prior_tokens=prior_tokens, prior_wall=prior_wall)
    if not audited["complete"]: raise RuntimeError("final test incomplete; audit pending charges before any continuation")
    result = research_report(protocol, rounds, audited, parent, prior_tokens, prior_wall)
    publish(root / "report.json", result)
    return result


def research_report(protocol, rounds, audited, parent, prior_tokens, prior_wall):
    body = {"schema": "p5-three-round-research-results-v1", "protocol_hash": protocol["hash"], "complete": True,
        "completed_real_rounds": len(rounds), "rounds": rounds, "final": summarize_final(protocol, audited),
        "final_test_report_hash": audited["report"]["hash"], "selected_snapshot": parent,
        "charged_tokens": prior_tokens-protocol["budget"]["prior_tokens"]+audited["report"]["charged_tokens"],
        "collection_wall_seconds": prior_wall-protocol["budget"]["prior_wall"]+audited["report"]["wall_seconds"],
        "shared_total_tokens": prior_tokens+audited["report"]["charged_tokens"],
        "shared_total_wall_seconds": prior_wall+audited["report"]["wall_seconds"],
        "program_admitted": any(item["program_admitted"] for item in rounds),
        "agent_admitted": any(item["agent_admitted"] for item in rounds),
        "isolated_activated": any(item["isolated_activated"] for item in rounds), "deployed": False,
        "research_claim_passed": None, "gpu_hours": "UNMEASURED", "new_training": False}
    return hashed(body)


def audit(root):
    """Read/replay only. Never start a missing model stage or repair a report."""
    root = Path(root).resolve(); protocol = load_protocol(root)
    registry = ResearchRegistry(root / "r")
    parent, tokens, wall = protocol["parent_snapshot"], protocol["budget"]["prior_tokens"], protocol["budget"]["prior_wall"]
    rounds = []
    for number in (1, 2, 3):
        result = audit_round(root, protocol, registry, number, parent=parent, prior_tokens=tokens, prior_wall=wall)
        rounds.append(result); parent = result["selected_snapshot"]; tokens += result["charged_tokens"]; wall += result["wall_seconds"]
    _, selected = registry.load(parent)
    catalogs = {"A": Catalog([]), "B": Catalog(protocol["baseline_entries"]), "C": selected}
    expected = hashed({"protocol_hash": protocol["hash"], "round_hashes": [item["hash"] for item in rounds],
        "selected_snapshot": parent, "catalogs": {key: value.hash for key, value in catalogs.items()},
        "prior_tokens": tokens, "prior_wall": wall, "test_feedback_to_optimizer": False})
    if read(root / "decisions-frozen.json") != expected:
        raise ValueError("test must bind three frozen round decisions and final catalogs")
    test = audit_stage(root / "test", protocol, cases=final_cases(protocol), catalogs=catalogs, prior_tokens=tokens, prior_wall=wall)
    if not test["complete"]: raise ValueError("incomplete final test cannot certify a completed study")
    result = research_report(protocol, rounds, test, parent, tokens, wall)
    if result != read(root / "report.json"):
        raise ValueError("research report differs from independently audited raw rounds and test")
    receipt = hashed({"schema": "p5-independent-study-audit-v1", "passed": True, "protocol_hash": protocol["hash"],
        "report_hash": result["hash"], "completed_real_rounds": 3, "test_arms": len(test["packets"]),
        "shared_total_tokens": result["shared_total_tokens"], "new_model_calls": 0, "new_tokens": 0})
    publish(root / "evidence-audits" / (digest_file(__file__)+".json"), receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    for name in ("draft", "smoke", "output", "preflight", "phase-id"):
        freeze.add_argument("--"+name, required=True)
    execute = sub.add_parser("run"); execute.add_argument("--run", required=True)
    verify = sub.add_parser("audit"); verify.add_argument("--run", required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        result = register(args.draft, args.smoke, args.output, preflight=args.preflight, phase_id=args.phase_id)
        print(json.dumps({"protocol_hash": result["hash"], "frozen": result["frozen"], "budget": result["budget"]}))
    elif args.command == "run":
        result = run(args.run)
        print(json.dumps({"complete": result["complete"], "rounds": result["completed_real_rounds"], "tokens": result["charged_tokens"]}))
    else:
        print(json.dumps(audit(args.run)))
