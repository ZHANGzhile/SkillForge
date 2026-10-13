"""Frozen paired collection, formal Agent receipts and pinned isolated Runtime.

No production service or latest pointer is modified. Engineering fixtures may
exercise the functions in tests, but cannot pass the real collection identity.
"""
from contextlib import ExitStack
import math
from pathlib import Path
import shutil
import time

from scripts.collect_skill_evolution_learn import collect_one, evaluate_static
from scripts.continue_skill_evolution_selection import publish
from scripts.run_skill_evolution import ROOT, ModelSession, digest_file
from scripts.run_skill_evolution_reuse import audit_incomplete, check_no_history
from skillforge.environment import Environment
from skillforge.evolution_common.artifacts import clone
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.agent_evidence import (read, semantic, audit_trajectory, audited_pairs,
    declare_evidence_protocol, execution_identity)
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.runtime import run_agent, PROTOCOL, runtime_sources
from skillforge.skill_evolution.validation import checked_hash
from skillforge.skill_evolution.workflows import WorkflowCase


ADAPTER = "results/training/main-v3/sft/adapter"
ADAPTER_SHA = "f195fe00128aa86587b5b37b5a3940116276966162d8f72c5bb222baf445669b"
CONTROLLERS = (__file__, "scripts/collect_skill_evolution_learn.py", "scripts/evolution_budget.py",
    "scripts/run_skill_evolution.py", "scripts/run_skill_evolution_reuse.py",
    "scripts/evolution_forks.py", "scripts/continue_skill_evolution_selection.py",
    "scripts/execution_aware_gpu_lease.py")


def hashed(body):
    return {**body, "hash": fingerprint(body)}


def relative(path, root=ROOT):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root):
        raise ValueError("artifact must stay within declared root")
    return path.relative_to(root).as_posix()


def source_index():
    sources = {"skillforge/" + name: value for name, value in runtime_sources().items()}
    for name in CONTROLLERS:
        path = Path(name) if Path(name).is_absolute() else ROOT / name
        sources[relative(path)] = digest_file(path)
    return sources


def fixed_model(settings):
    if (settings.get("engineering_only") is not False or settings.get("adapter_sha256") != ADAPTER_SHA or
            settings.get("model") != "Qwen3-4B-NF4-SFT" or settings.get("do_sample") is not False or
            settings.get("catalog_serving_code_hash") != digest_file(ROOT / "skillforge/skill_evolution/model.py") or
            digest_file(ROOT / ADAPTER / "adapter_model.safetensors") != ADAPTER_SHA):
        raise ValueError("fixed real main-v3 adapter and collection identity required")


def release_binding(registry, parent, candidate, protocol, ledger):
    """Validate exact publication/parent and independent predeclared holdouts."""
    checked_hash(protocol)
    previous, baseline = registry.load(parent)
    selected, proposed = registry.load(candidate)
    if (selected["operation"] != "PROGRAM_REGISTERED" or selected["parent_snapshot"] != parent or
            proposed.hash == baseline.hash):
        raise ValueError("a new formally registered direct-child program snapshot is required")
    old = {entry["skill_id"]: entry for entry in baseline.entries()}
    new = {entry["skill_id"]: entry for entry in proposed.entries()}
    changes = [entry for key, entry in new.items() if old.get(key) != entry]
    if set(old) - set(new) or len(changes) != 1:
        raise ValueError("one frozen program candidate without unrelated catalog changes required")
    changed = changes[0]
    from skillforge.evolution_common.artifacts import load_record
    registration_id = selected["registrations"][changed["revision"]]
    registration = load_record(registry.root, "registrations", registration_id)
    if registration["kind"] != "formal_program":
        raise ValueError("legacy imports are not new formal program admission")
    registry._audit_registration(registration)
    if (protocol["baseline_entries"] != baseline.entries() or protocol["candidate_entries"] != proposed.entries()):
        raise ValueError("paired protocol must bind exact parent and published candidate catalogs")
    plan = protocol["paired_protocol"]
    expected = declare_evidence_protocol(protocol["cases"], baseline, proposed, protocol["settings"], protocol["sources"],
        protocol["limits"], ledger, budget=protocol["budget"],
        **{key: plan[key] for key in ("metric", "min_group_gain", "min_groups", "alpha")})
    if expected != protocol:
        raise ValueError("frozen release protocol differs from independent declaration")
    stable = {item["source_group"] for item in plan["cases"] if item["split"] == "stable_validation"}
    primary = {item["source_group"] for item in plan["cases"] if item["split"] == "validation"}
    if len(stable) < 2 or len(primary) < 6 or plan["metric"] != "model_calls" or plan["min_group_gain"] < 1:
        raise ValueError("formal release requires six primary and two stable source groups and fixed gain gate")
    fixed_model(protocol["settings"])
    return {"parent_snapshot": parent, "candidate_snapshot": candidate,
        "parent_catalog_hash": baseline.hash, "candidate_catalog_hash": proposed.hash,
        "registration_id": registration_id, "published_revision": changed["revision"],
        "program_admission_hash": registration["program_admission"]["hash"],
        "learn_provenance_hash": registration["provenance_hash"], "paired_protocol_hash": protocol["hash"]}


def retain_no_candidate(registry, parent, compiler_run, *, round_id):
    """Audited zero-update exit; never convert legacy import into admission."""
    from skillforge.skill_evolution.provenance import audit_compiler_run
    if not round_id:
        raise ValueError("explicit round identity required")
    proposal = audit_compiler_run(compiler_run)
    if proposal["proposal"]["n_candidates"] != 0 or proposal["proposal"]["status"] != "NO_USEFUL_CANDIDATE":
        raise ValueError("zero-update branch requires audited absence of a useful candidate")
    _, catalog = registry.load(parent)
    if catalog.hash != proposal["catalog_hash"]:
        raise ValueError("learn catalog differs from selected parent")
    evidence = hashed({"schema": "no-candidate-round-exit-v1", "round_id": round_id,
        "compiler_provenance_hash": proposal["hash"], "parent_snapshot": parent, "catalog_hash": catalog.hash,
        "program_validation": "SKIPPED_NO_CANDIDATE", "agent_validation": "SKIPPED_NO_CANDIDATE",
        "program_admitted": False, "agent_admitted": False, "isolated_activated": False, "deployed": False})
    return registry.retain(parent, reason="NO_USEFUL_CANDIDATE", evidence=evidence)


class AgentRelease:
    def __init__(self, registry, ledger, *, artifact_root=ROOT):
        self.registry, self.ledger = registry, ledger
        self.artifact_root = Path(artifact_root).resolve()

    def declare(self, folder, *, parent, candidate, protocol, config, phase_id):
        folder = Path(folder).resolve()
        rel = relative(folder, self.artifact_root)
        if not phase_id or folder.exists():
            raise ValueError("fresh collection directory and phase identity required")
        binding = release_binding(self.registry, parent, candidate, protocol, self.ledger)
        if protocol["sources"] != runtime_sources():
            raise ValueError("formal collection requires the complete current Runtime source identity")
        if (config["adapter"] != ADAPTER or config["adapter_sha256"] != ADAPTER_SHA or
                config["limits"] != protocol["limits"]):
            raise ValueError("collector model/limits must match frozen paired protocol")
        owners = self.artifact_root / "results/skill-evolution/v1.2/agent-release-ledger"
        for path in owners.glob("*.json"):
            prior = read(path); checked_hash(prior)
            if prior["phase_id"] == phase_id or prior["candidate_snapshot"] == candidate:
                raise ValueError("phase/candidate already submitted; formal holdout cannot be retuned")
        sources = source_index()
        body = {"schema": "formal-agent-release-collection-v1", "phase_id": phase_id, "folder": rel,
            "binding": binding, "protocol": clone(protocol), "config": clone(config), "sources": sources,
            "ownership": {key: self.ledger.owners[key] for item in protocol["cases"] for key in
                (item["case"]["task_id"], item["case"]["source_group"], item["case"]["parameters"]["order_id"],
                 item["case"]["authenticated_customer_id"])},
            "collection_order": "declared task order, baseline then candidate",
            "scope": "formal validation only; one frozen submission; no optimizer feedback"}
        declaration = hashed(body)
        folder.mkdir(parents=True)
        for name, expected in sources.items():
            target = folder / "source-snapshot" / name
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(ROOT / name, target)
            if digest_file(target) != expected:
                raise ValueError("source changed before collection registration")
        publish(folder / "declaration.json", declaration)
        publish(owners / (fingerprint(phase_id) + ".json"), hashed({"phase_id": phase_id, "folder": rel,
            "candidate_snapshot": candidate, "declaration_hash": declaration["hash"]}))
        return declaration

    def _declaration(self, folder):
        folder = Path(folder).resolve()
        value = read(folder / "declaration.json"); checked_hash(value)
        if value["schema"] != "formal-agent-release-collection-v1" or value["folder"] != relative(folder, self.artifact_root):
            raise ValueError("collection declaration/root mismatch")
        owner = read(self.artifact_root / "results/skill-evolution/v1.2/agent-release-ledger" /
            (fingerprint(value["phase_id"]) + ".json"))
        if owner != hashed({"phase_id": value["phase_id"], "folder": value["folder"],
                "candidate_snapshot": value["binding"]["candidate_snapshot"], "declaration_hash": value["hash"]}):
            raise ValueError("collection phase ledger binding mismatch")
        for name, expected in value["sources"].items():
            if digest_file(ROOT / name) != expected or digest_file(folder / "source-snapshot" / name) != expected:
                raise ValueError("registered collection/auditor sources changed")
        if value["sources"] != source_index():
            raise ValueError("complete registered controller source index required")
        binding = release_binding(self.registry, value["binding"]["parent_snapshot"],
            value["binding"]["candidate_snapshot"], value["protocol"], self.ledger)
        if binding != value["binding"] or any(self.ledger.owners.get(key) != partition for key, partition in value["ownership"].items()):
            raise ValueError("release provenance or source ownership changed")
        return value

    def collect(self, folder):
        """Only this collector creates formal raw evidence; no inference fallback."""
        from scripts.execution_aware_gpu_lease import GPUServiceLease
        folder = Path(folder).resolve(); declaration = self._declaration(folder)
        if (folder / "model-identity.json").exists() or (folder / "collection-report.json").exists():
            raise ValueError("formal collection already started; audit, do not replay writes or inference")
        protocol = declaration["protocol"]; budget = protocol["budget"]
        config = {**declaration["config"], "budget": {"project_max_tokens": budget["max_tokens"],
            "project_max_wall_seconds": budget["max_wall"]}}
        catalogs = {arm: Catalog(protocol[arm + "_entries"]) for arm in ("baseline", "candidate")}
        statuses, failure, started = [], None, time.perf_counter()
        try:
            with GPUServiceLease(), ExitStack() as cleanup:
                session = ModelSession(config, folder, init_timeout=budget["max_wall"]-budget["prior_wall"]-10)
                cleanup.callback(session.close)
                if session.settings != protocol["settings"]:
                    raise ValueError("live model differs from predeclared backend")
                fixed_model(session.settings); publish(folder / "model-identity.json", session.settings)
                for index, item in enumerate(protocol["cases"]):
                    case = WorkflowCase.model_validate(item["case"])
                    for arm in ("baseline", "candidate"):
                        _, status = collect_one(session, case, catalogs[arm], folder / str(index) / arm, config,
                            budget["prior_tokens"] + sum(row["status"]["charged_tokens"] for row in statuses), budget["prior_wall"], started)
                        statuses.append({"index": index, "arm": arm, "status": status})
                        if not status["completed"]:
                            raise RuntimeError(status["failure"])
        except Exception as exc:
            failure = type(exc).__name__ + ": " + str(exc)
        report = hashed({"schema": "formal-agent-release-cost-report-v1", "declaration_hash": declaration["hash"],
            "statuses": statuses, "failure": failure, "wall_seconds": time.perf_counter()-started,
            "charged_tokens": sum(row["status"]["charged_tokens"] for row in statuses),
            "complete": len(statuses) == 2*len(protocol["cases"]) and all(row["status"]["completed"] for row in statuses) and failure is None})
        publish(folder / "collection-report.json", report)
        return report

    def evaluate(self, folder):
        """Recompute raw evidence, cost settlement and gate; never trust row counts."""
        folder = Path(folder).resolve(); declaration = self._declaration(folder)
        protocol = declaration["protocol"]; budget = protocol["budget"]
        report = read(folder / "collection-report.json"); checked_hash(report)
        if (report["declaration_hash"] != declaration["hash"] or type(report["wall_seconds"]) not in {int, float} or
                not math.isfinite(report["wall_seconds"]) or report["wall_seconds"] < 0):
            raise ValueError("finite registered collection cost report required")
        settings = read(folder / "model-identity.json") if report["statuses"] else protocol["settings"]
        if settings != protocol["settings"]:
            raise ValueError("registered inference model mismatch")
        fixed_model(settings)
        schedule = [(index, arm) for index in range(len(protocol["cases"])) for arm in ("baseline", "candidate")]
        if [(item["index"], item["arm"]) for item in report["statuses"]] != schedule[:len(report["statuses"])]:
            raise ValueError("raw collection order differs from predeclared schedule")
        if {relative(path, folder) for path in folder.glob("*/*/collection-status.json")} != {
                str(item["index"])+"/"+item["arm"]+"/collection-status.json" for item in report["statuses"]}:
            raise ValueError("orphan collection arm costs cannot be dropped")
        catalogs = {arm: Catalog(protocol[arm + "_entries"]) for arm in ("baseline", "candidate")}
        prior, packets, pairs, calls, max_elapsed, use_count = budget["prior_tokens"], [], [], 0, 0, 0
        incomplete = False
        for item in report["statuses"]:
            if incomplete:
                raise ValueError("collection cannot continue after an unsettled arm")
            index, arm, status = item["index"], item["arm"], item["status"]
            path = folder / str(index) / arm
            if read(path / "collection-status.json") != status:
                raise ValueError("raw collection status/cost report mismatch")
            context = {**budget, "prior_tokens": prior}
            if status["completed"]:
                raw = read(path / "result.json")
                if raw["case"] != protocol["cases"][index]["case"] or raw["schema"] != "workflow-learn-trajectory-v1":
                    raise ValueError("formal raw case or collector schema mismatch")
                check_no_history(raw)
                if (raw.get("static_coverage") != read(path / "static-coverage.json") or
                        semantic(raw["static_coverage"]) != semantic(evaluate_static(WorkflowCase.model_validate(raw["case"]), catalogs[arm]))):
                    raise ValueError("static coverage differs from independent sandbox replay")
                packet = audit_trajectory(path, catalogs[arm], settings, protocol["sources"], protocol["limits"], charge_context=context)
                packets.append(packet); calls += packet["model_calls"]
                if arm == "candidate":
                    pairs.append(packets[-2:])
                    revision = declaration["binding"]["published_revision"]
                    skill_id = next(entry["skill_id"] for entry in catalogs[arm].entries() if entry["revision"] == revision)
                    use_count += sum(packet["eoc"] and event.get("success") is True and event.get("skill_id") == skill_id and
                        event.get("revision") == revision for event in raw["agent"]["skill_events"])
            else:
                incomplete = True; audit_incomplete(path, context)
            prior += status["charged_tokens"]
            for receipt in (path / "admissions").glob("*.json"):
                max_elapsed = max(max_elapsed, read(receipt)["elapsed_seconds"])
        complete = len(report["statuses"]) == len(schedule) and not incomplete and report["failure"] is None
        if (report["charged_tokens"] != prior-budget["prior_tokens"] or report["complete"] != complete or
                report["wall_seconds"]+1e-6 < max_elapsed or prior > budget["max_tokens"]):
            raise ValueError("collection charges, elapsed time or completion do not reconcile")
        gate = audited_pairs(protocol["paired_protocol"], pairs, self.ledger)
        # Business EOC never requires Skill use. A claim that the Agent can use
        # this newly published program separately requires observed success.
        decision = ("REJECTED" if gate["decision"] == "REJECTED" else
            "ADMITTED" if complete and gate["statistical_gate_passed"] and use_count > 0 else "INCONCLUSIVE")
        body = {"schema": "formal-agent-admission-receipt-v1", "declaration_hash": declaration["hash"],
            "binding": clone(declaration["binding"]), "collection_report_hash": report["hash"],
            "statistical_gate": gate, "audited_evidence": packets, "complete": complete,
            "successful_candidate_skill_events": use_count, "decision": decision,
            "program_admitted": True, "agent_admitted": decision == "ADMITTED", "research_claim_passed": None,
            "isolated_activated": False, "deployed": False,
            "charged_tokens": report["charged_tokens"], "model_calls": calls, "wall_seconds": report["wall_seconds"],
            "replay_tool_calls": sum(packet["replay_tool_calls"] for packet in packets), "new_model_calls": 0, "new_tokens": 0,
            "scope": "formal validation admission only; research/generalization and activation require separate evidence"}
        return hashed(body)

    def admit(self, folder):
        receipt = self.evaluate(folder)
        publish(Path(folder) / "agent-admission.json", receipt)
        return receipt

    def audit_receipt(self, folder):
        receipt = read(Path(folder) / "agent-admission.json"); checked_hash(receipt)
        if self.evaluate(folder) != receipt:
            raise ValueError("Agent admission differs from independently replayed collection")
        return receipt

    def activate(self, folder, output):
        """Instantiate a local pinned Runtime; neither service deploy nor latest."""
        receipt = self.audit_receipt(folder)
        if receipt["decision"] != "ADMITTED" or not receipt["agent_admitted"]:
            raise ValueError("formal Agent admission required for isolated activation")
        output = Path(output).resolve(); relative(output, self.artifact_root)
        if output.exists():
            raise ValueError("fresh isolated instance directory required")
        declaration = self._declaration(folder)
        _, catalog = self.registry.load(receipt["binding"]["candidate_snapshot"])
        output.mkdir(parents=True)
        catalog.save(output / "catalog.json")
        # Instantiate and check the very same pinned catalog/settings/limits
        # used by execute(), before marking this local instance ready.
        instance = IsolatedRuntime(Catalog.load(output / "catalog.json"), declaration["protocol"]["settings"],
            declaration["protocol"]["sources"], declaration["protocol"]["limits"])
        body = {"schema": "isolated-agent-runtime-activation-v1", "state": "ISOLATED_ACTIVE",
            "collection_folder": relative(folder, self.artifact_root), "instance_folder": relative(output, self.artifact_root),
            "agent_admission_hash": receipt["hash"], "snapshot": receipt["binding"]["candidate_snapshot"],
            "catalog_hash": instance.catalog.hash, "execution_identity": instance.execution_identity,
            "program_admitted": True, "agent_admitted": True, "isolated_activated": True, "deployed": False,
            "scope": "local readonly Runtime instance only; no running web service, production mutation or global latest pointer"}
        activation = hashed(body); publish(output / "activation.json", activation)
        return activation

    def open_isolated(self, output):
        output = Path(output).resolve(); relative(output, self.artifact_root)
        saved = read(output / "activation.json"); checked_hash(saved)
        folder = self.artifact_root / saved["collection_folder"]
        relative(folder, self.artifact_root)
        receipt = self.audit_receipt(folder)
        declaration = self._declaration(folder)
        _, selected = self.registry.load(saved["snapshot"])
        catalog = Catalog.load(output / "catalog.json")
        instance = IsolatedRuntime(catalog, declaration["protocol"]["settings"], declaration["protocol"]["sources"], declaration["protocol"]["limits"])
        if (saved["instance_folder"] != relative(output, self.artifact_root) or saved["agent_admission_hash"] != receipt["hash"] or
                not receipt["agent_admitted"] or saved["snapshot"] != receipt["binding"]["candidate_snapshot"] or
                catalog.hash != selected.hash or saved["catalog_hash"] != catalog.hash or
                saved["execution_identity"] != instance.execution_identity or saved["state"] != "ISOLATED_ACTIVE" or
                saved["program_admitted"] is not True or saved["agent_admitted"] is not True or
                saved["isolated_activated"] is not True or saved["deployed"] is not False):
            raise ValueError("isolated runtime pin/receipt disposition mismatch")
        return instance


class IsolatedRuntime:
    """Local execution object; catalog/weights/limits pinned, readonly sandbox."""
    def __init__(self, catalog, settings, sources, limits):
        self.catalog, self.settings = Catalog(catalog.entries()), clone(settings)
        self.sources, self.limits = clone(sources), clone(limits)
        self.execution_identity = execution_identity(settings, sources, limits, PROTOCOL)

    def execute(self, model, case):
        from skillforge.policies import READS
        from unittest.mock import patch
        if model.settings != self.settings or any(digest_file(ROOT / "skillforge" / name) != value for name, value in self.sources.items()):
            raise ValueError("isolated Runtime model/source identity changed")
        case = WorkflowCase.model_validate(case)
        env = Environment(fixture=case.fixture)
        def call(name, arguments, key, origin):
            if name not in READS:
                raise ValueError("isolated readonly Runtime cannot perform writes")
            before = len(env.audit)
            try: return env.call(name, arguments, case.authenticated_customer_id, key)
            finally:
                for event in env.audit[before:]: event["decision_origin"] = origin
        try:
            with patch("skillforge.skill_evolution.runtime.runtime_sources", return_value=clone(self.sources)):
                return run_agent(model, case.public_task(), self.catalog, call, **self.limits, auto_terminate=False)
        finally: env.close()
