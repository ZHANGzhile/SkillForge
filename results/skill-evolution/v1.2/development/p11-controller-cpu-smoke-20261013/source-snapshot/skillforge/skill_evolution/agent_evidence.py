"""CPU replay of recorded model responses, never new inference.

The replay checks action-to-tool causality and every durable checkpoint. It
does not certify that a model generated a response: collection provenance and
the frozen controller's budget ledger remain separate evidence requirements.
"""
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from unittest.mock import patch

from ..environment import Environment
from ..evolution_common.artifacts import clone
from ..evolution_schemas import fingerprint
from ..schemas import Action
from . import runtime
from .validation import checked_hash, database_hash
from .workflows import WorkflowCase, private_items, verify_workflow


ROOT = Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def semantic(value):
    """Only tool/search latency and top-level run duration are non-replayable."""
    if isinstance(value, list): return [semantic(item) for item in value]
    if isinstance(value, dict):
        return {key: semantic(item) for key, item in value.items() if key != "latency_ms"}
    return value


def execution_identity(settings, sources, limits, protocol):
    if settings.get("engineering_only") is not False or protocol != runtime.PROTOCOL:
        raise ValueError("supported real model protocol required")
    if (settings.get("prompt_sha256") != fingerprint(settings.get("system_prompt")) or
            settings.get("system_prompt") != runtime.SYSTEM_PROMPT or settings.get("decision_protocol") != protocol):
        raise ValueError("model prompt/protocol identity mismatch")
    if set(limits) != {"max_steps", "max_search", "max_load", "max_tokens"}:
        raise ValueError("complete execution limits required")
    if (any(type(value) is not int or value < 0 for value in limits.values()) or
            not 1 <= limits["max_steps"] <= 16):
        raise ValueError("invalid execution limits")
    return fingerprint({"settings": settings, "sources": sources, "limits": limits, "protocol": protocol})


def initial_identity(case):
    case = WorkflowCase.model_validate(case)
    env = Environment(fixture=case.fixture)
    try:
        return fingerprint({"database": database_hash(env), "facts": env.snapshot(), "items": private_items(env),
                            "faults": env.faults, "authenticated_customer_id": case.authenticated_customer_id})
    finally: env.close()


def audit_trajectory(folder, catalog, settings, sources, limits, *, charge_context):
    """Fail closed on incomplete/interrupted/unsupported recorded runs.

    sources use the runtime's skillforge-relative names. Existing registered
    code must match; newly added auditor modules need not have existed when
    the model ran. Archived sources are checked by the collection controller.
    charge_context comes from that controller, not from a counted pair row.
    """
    from scripts.evolution_budget import CheckpointAdmission

    folder = Path(folder)
    row = read(folder / "result.json")
    case = WorkflowCase.model_validate(row["case"])
    case.public_task()
    identity = execution_identity(settings, sources, limits, row["agent"]["protocol"])
    required = {"skill_evolution/runtime.py", "skill_evolution/catalog.py", "skill_evolution/trace.py",
                "skill_evolution/workflows.py", "evolution_common/artifacts.py", "environment.py", "skills.py",
                "execution_aware/contracts.py", "policies.py", "schemas.py", "tool_schemas.py", "prompts.py",
                "evolution_schemas.py"}
    if not required <= set(sources) or any(digest(ROOT / "skillforge" / name) != sources[name] for name in required):
        raise ValueError("replay requires registered execution/verifier source versions")
    if row["model_identity_hash"] != fingerprint(settings) or row["agent"]["catalog_hash"] != catalog.hash:
        raise ValueError("trajectory model/catalog mismatch")
    status = read(folder / "collection-status.json")
    if status["task_id"] != case.task_id or not status["completed"] or status["failure"] or status["denied_before_ack"]:
        raise ValueError("only complete settled collection evidence supported")
    paths = sorted((folder / "checkpoints").glob("*/snapshot.json"), key=lambda path: int(path.parent.name))
    if [int(path.parent.name) for path in paths] != list(range(len(paths))):
        raise ValueError("non-contiguous checkpoint sequence")
    manifests = {}
    def snapshot(path):
        value = read(path)
        if (fingerprint(value["body"]) != value["hash"] or
                digest(path.parent / "environment.sqlite") != value["body"]["database_sha256"]):
            raise ValueError("trajectory snapshot/SQLite integrity mismatch")
        manifests[str(path.relative_to(folder)).replace("\\", "/")] = digest(path)
        manifests[str((path.parent / "environment.sqlite").relative_to(folder)).replace("\\", "/")] = value["body"]["database_sha256"]
        return value
    initial = snapshot(folder / "initial-snapshot/snapshot.json")
    if initial["hash"] != row["snapshot_hash"] or initial["body"]["audit"] or initial["body"]["faults"]:
        raise ValueError("fresh fault-free readonly initial snapshot required")
    saved = [snapshot(path) for path in paths]
    if any(value["body"]["random_state"] != initial["body"]["random_state"] or
           value["body"]["order_id"] != case.parameters["order_id"] for value in [initial, *saved]):
        raise ValueError("readonly snapshot RNG/object identity mismatch")
    admission = CheckpointAdmission(**charge_context)
    seen = set()
    elapsed = 0
    for index, value in enumerate(saved):
        checkpoint = value["body"]["runtime"]
        pending = [i for i, request in enumerate(checkpoint["model_requests"])
                   if request["status"] == "pending" and i not in admission.approved]
        if pending:
            name = str(pending[0]) + ".json"
            receipt = read(folder / "admissions" / name)
            if receipt["elapsed_seconds"] < elapsed:
                raise ValueError("admission elapsed time regressed")
            elapsed = receipt["elapsed_seconds"]
            expected = admission.inspect(checkpoint, elapsed)
            if receipt != {**expected, "checkpoint_index": index} or not receipt["approved"]:
                raise ValueError("inference approval/budget mismatch")
            admission.record_approval(receipt)
            seen.add(name)
            manifests["admissions/" + name] = digest(folder / "admissions" / name)
        else: admission.inspect(checkpoint, elapsed)
    if seen != {path.name for path in (folder / "admissions").glob("*.json")}:
        raise ValueError("orphan inference approval")

    class RecordedModel:
        def __init__(self):
            self.settings, self.tokens, self.index = clone(settings), 0, 0
            self.last_response, self.last_messages = None, []
        def decide(self, context):
            step = row["agent"]["steps"][self.index]
            request = row["agent"]["model_requests"][self.index]
            if (context != step["context"] or len(step["messages"]) != 2 or
                    step["messages"][0] != {"role": "system", "content": settings["system_prompt"]} or
                    step["messages"][1]["role"] != "user" or json.loads(step["messages"][1]["content"]) != context):
                raise ValueError("recorded model context/messages differ from replay")
            if request["status"] != "completed" or request.get("usage_known") is not True or not 0 < request["charged_tokens"] <= 16384:
                raise ValueError("complete known model usage required")
            self.last_messages, self.last_response = clone(step["messages"]), step["model_response"]
            action = Action.model_validate_json(self.last_response)
            if action.model_dump() != step["action"]:
                raise ValueError("raw model response/action mismatch")
            self.tokens += request["charged_tokens"]
            self.index += 1
            return action

    env = Environment(fixture=case.fixture)
    model, cursor = RecordedModel(), 0
    def compare_database(path):
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            if fingerprint(list(db.iterdump())) != database_hash(env):
                raise ValueError("checkpoint database differs from independent action replay")
        finally: db.close()
    def persist(value):
        nonlocal cursor
        if cursor >= len(saved) or semantic(value) != semantic(saved[cursor]["body"]["runtime"]):
            raise ValueError("durable runtime checkpoint differs from replay")
        if (semantic(saved[cursor]["body"]["audit"]) != semantic(env.audit) or
                saved[cursor]["body"]["faults"] != env.faults):
            raise ValueError("durable tool evidence differs from replay")
        compare_database(paths[cursor].parent / "environment.sqlite")
        cursor += 1
    def call(name, args, key, source):
        from ..policies import READS
        if name not in READS:
            raise ValueError("readonly Agent evidence replay cannot execute writes")
        before = len(env.audit)
        try: return env.call(name, args, case.authenticated_customer_id, key)
        finally:
            for event in env.audit[before:]: event["decision_origin"] = source
    try:
        compare_database(folder / "initial-snapshot/environment.sqlite")
        if row["initial_state"] != env.snapshot() or row["initial_items"] != private_items(env):
            raise ValueError("initial private facts differ from fixture")
        # Override only the source index used to reconstruct a historical ID.
        # Executed source files were checked above; no model/network is loaded.
        with patch.object(runtime, "runtime_sources", return_value=clone(sources)):
            replay = runtime.run_agent(model, case.public_task(), catalog, call, **limits, persist=persist, auto_terminate=False)
        expected, observed = clone(row["agent"]), clone(replay)
        expected["metrics"].pop("seconds", None); observed["metrics"].pop("seconds", None)
        if semantic(expected) != semantic(observed) or cursor != len(saved) or model.index != len(row["agent"]["steps"]):
            raise ValueError("recorded Agent result differs from full action replay")
        if semantic(row["tool_audit"]) != semantic(env.audit) or row["final_state"] != env.snapshot() or row["final_items"] != private_items(env):
            raise ValueError("final tool/database evidence differs from replay")
        verdict = verify_workflow(case, row["initial_state"], env.snapshot(), env.audit, replay["outcome"], row["initial_items"], private_items(env))
        if (verdict != row["verification"] or admission.charged_tokens() != replay["metrics"]["tokens"] or
                status["charged_tokens"] != replay["metrics"]["tokens"] or status["last_budget"] != replay["budget"]):
            raise ValueError("independent workflow EOC/settled charges mismatch")
        manifests.update({name: digest(folder / name) for name in ("result.json", "collection-status.json")})
        intervention = replay["interventions"]["runtime_intervention_count"] > 0
        body = {"schema": "readonly-agent-evidence-v1", "task_id": case.task_id, "source_group": case.source_group,
                "split": case.split, "task_hash": fingerprint(case.public_task()), "initial_state_hash": initial_identity(case),
                "execution_identity": identity, "catalog_hash": catalog.hash, "evidence_files": manifests,
                "eoc": verdict["task_success"], "autonomous_eoc": verdict["task_success"] and not intervention,
                "runtime_assisted_eoc": verdict["task_success"] and intervention, "interventions": replay["interventions"],
                "attempted_violations": int(verdict["attempted_policy_violation"]),
                "actual_violations": int(verdict["actual_policy_violation"]),
                "workflow_violations": int(verdict["attempted_workflow_violation"] or verdict["actual_workflow_violation"]),
                "model_calls": replay["metrics"]["llm_calls"], "tokens": replay["metrics"]["tokens"], "cost_settled": True,
                "replay_tool_calls": len(env.audit), "new_model_calls": 0, "new_tokens": 0,
                "agent_admitted": False, "isolated_activated": False, "deployed": False,
                "scope": "recorded-response replay and controller approvals; not independent proof of inference generation"}
        return {**body, "hash": fingerprint(body)}
    finally: env.close()


def audited_pairs(protocol, evidence_pairs, ledger):
    """Accept audited evidence packets only; the caller must re-audit their files.

    This joins real-evidence audit output to the arithmetic gate. It deliberately
    retains agent_admitted=false until frozen run/provenance audit is integrated.
    """
    from .admission import paired_gate
    pairs = []
    plan = {case["task_id"]: case for case in protocol["cases"]}
    for baseline, candidate in evidence_pairs:
        for evidence in (baseline, candidate):
            checked_hash(evidence)
            if evidence.get("schema") != "readonly-agent-evidence-v1" or not evidence.get("evidence_files"):
                raise ValueError("full independently audited Agent evidence required")
        task = plan.get(baseline["task_id"])
        if task is None:
            raise ValueError("unplanned Agent evidence")
        for evidence in (baseline, candidate):
            # WorkflowCase uses validation; the separately frozen plan and
            # ledger distinguish stable_validation without relabeling a case.
            if (evidence["split"] != "validation" or any(evidence[key] != task[key] for key in
                    ("task_id", "source_group", "task_hash", "initial_state_hash")) or
                    any(ledger.owners.get(key) != task["split"] for key in (task["task_id"], task["source_group"]))):
                raise ValueError("Agent evidence must belong to declared held-out source partition")
        fields = ("eoc", "attempted_violations", "actual_violations", "workflow_violations", "model_calls", "tokens",
                  "cost_settled", "execution_identity", "catalog_hash")
        pairs.append({**{key: task[key] for key in ("task_id", "source_group", "task_hash", "initial_state_hash")},
                      "baseline": {**{key: baseline[key] for key in fields}, "evidence_hash": baseline["hash"]},
                      "candidate": {**{key: candidate[key] for key in fields}, "evidence_hash": candidate["hash"]}})
    return paired_gate(protocol, pairs)


def declare_evidence_protocol(cases, baseline_catalog, candidate_catalog, settings, sources, limits, ledger, *, budget,
                              metric="model_calls", min_group_gain=1, min_groups=6, alpha=0.05):
    """Freeze full case/backend/catalog identity before collecting paired arms.

    cases are {case: WorkflowCase, stable: bool}. All are validation cases;
    stable is a source-ledger partition, not an extra independent primary unit.
    Arms execute baseline then candidate in declared task order, with one
    cumulative inference budget; the collector must preserve that order.
    """
    from .admission import declare_paired_protocol
    from .catalog import Catalog
    execution = execution_identity(settings, sources, limits, runtime.PROTOCOL)
    if (set(budget) != {"prior_tokens", "max_tokens", "prior_wall", "max_wall"} or
            any(type(budget[key]) is not int or budget[key] < 0 for key in ("prior_tokens", "max_tokens")) or
            budget["max_tokens"] <= budget["prior_tokens"] or
            any(type(budget[key]) not in {float, int} or not math.isfinite(budget[key]) or budget[key] < 0
                for key in ("prior_wall", "max_wall")) or budget["max_wall"] <= budget["prior_wall"]):
        raise ValueError("explicit cumulative inference budget required")
    for catalog in (baseline_catalog, candidate_catalog):
        Catalog(catalog.entries())
        if any(entry["contract"]["status"] != "VERIFIED" for entry in catalog.entries()):
            raise ValueError("paired Agent catalog must contain VERIFIED publications")
    plan, normalized = [], []
    for item in cases:
        if set(item) != {"case", "stable"} or type(item["stable"]) is not bool:
            raise ValueError("explicit validation/stable case declaration required")
        case = WorkflowCase.model_validate(item["case"])
        if case.split != "validation": raise ValueError("learn/dev/test cannot enter Agent admission validation")
        partition = "stable_validation" if item["stable"] else "validation"
        keys = [case.task_id, case.source_group, case.parameters["order_id"], case.authenticated_customer_id]
        if any(ledger.owners.get(key) != partition for key in keys):
            raise ValueError("preclaimed independent validation source/entity ownership required")
        plan.append({"task_id": case.task_id, "source_group": case.source_group, "task_hash": fingerprint(case.public_task()),
                     "initial_state_hash": initial_identity(case), "split": partition, "critical": item["stable"]})
        normalized.append({"case": case.model_dump(), "stable": item["stable"]})
    paired = declare_paired_protocol(plan, baseline_catalog_hash=baseline_catalog.hash, candidate_catalog_hash=candidate_catalog.hash,
                execution_identity=execution, metric=metric, min_group_gain=min_group_gain, min_groups=min_groups, alpha=alpha,
                max_tokens=limits["max_tokens"], max_model_calls=limits["max_steps"])
    body = {"schema": "readonly-agent-paired-evidence-protocol-v1", "paired_protocol": paired,
            "cases": normalized, "settings": clone(settings), "sources": clone(sources), "limits": clone(limits),
            "budget": clone(budget), "baseline_entries": baseline_catalog.entries(), "candidate_entries": candidate_catalog.entries(),
            "auditor_sha256": digest(__file__), "statistics_sha256": digest(Path(__file__).with_name("admission.py")),
            "collection_order": "declared task order, baseline then candidate",
            "scope": "paired evidence/statistical gate; frozen collection provenance still required for Agent admission"}
    return {**body, "hash": fingerprint(body)}


def audit_paired_files(protocol, references, ledger, *, artifact_root=ROOT):
    """Build gate inputs from raw evidence directories, ignoring counted rows."""
    from .catalog import Catalog
    checked_hash(protocol)
    catalogs = {name: Catalog(protocol[name + "_entries"]) for name in ("baseline", "candidate")}
    expected = declare_evidence_protocol(protocol["cases"], catalogs["baseline"], catalogs["candidate"], protocol["settings"],
                protocol["sources"], protocol["limits"], ledger, budget=protocol["budget"],
                **{key: protocol["paired_protocol"][key] for key in ("metric", "min_group_gain", "min_groups", "alpha")})
    if expected != protocol: raise ValueError("paired evidence protocol identity differs")
    plan = {item["case"]["task_id"]: item["case"] for item in protocol["cases"]}
    if (len({item["task_id"] for item in references}) != len(references) or
            any(set(item) != {"task_id", "baseline", "candidate"} or item["task_id"] not in plan for item in references)):
        raise ValueError("unique planned raw evidence references required")
    refs = {item["task_id"]: item for item in references}
    budget, packets, seen = clone(protocol["budget"]), [], set()
    artifact_root = Path(artifact_root).resolve()
    for task_id, case in plan.items():
        if task_id not in refs: continue
        arms = []
        for name in ("baseline", "candidate"):
            folder = (artifact_root / refs[task_id][name]).resolve()
            if not folder.is_relative_to(artifact_root) or folder in seen:
                raise ValueError("each raw arm must be a distinct directory within the artifact root")
            seen.add(folder)
            if read(folder / "result.json")["case"] != case:
                raise ValueError("raw paired case differs from frozen declaration")
            packet = audit_trajectory(folder, catalogs[name], protocol["settings"], protocol["sources"], protocol["limits"], charge_context=budget)
            budget["prior_tokens"] += packet["tokens"]
            arms.append(packet)
        packets.append(arms)
    gate = audited_pairs(protocol["paired_protocol"], packets, ledger)
    body = {"schema": "readonly-agent-paired-evidence-report-v1", "protocol": clone(protocol),
            "references": clone(references), "audited_evidence": packets, "statistical_gate": gate,
            "replay_tool_calls": sum(arm["replay_tool_calls"] for arms in packets for arm in arms),
            "new_model_calls": 0, "new_tokens": 0, "agent_admitted": False, "isolated_activated": False, "deployed": False,
            "scope": "raw files independently replayed; statistical passage alone cannot activate or claim Agent admission"}
    return {**body, "hash": fingerprint(body)}


def audit_paired_report(report, ledger, *, artifact_root=ROOT):
    checked_hash(report)
    replay = audit_paired_files(report["protocol"], report["references"], ledger, artifact_root=artifact_root)
    if replay != report: raise ValueError("paired Agent evidence report differs from independent raw-file audit")
    return {"passed": True, "report_hash": report["hash"], "replay_tool_calls": replay["replay_tool_calls"],
            "new_model_calls": 0, "new_tokens": 0, "agent_admitted": False}
