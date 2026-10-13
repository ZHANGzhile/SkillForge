"""Isolated, time-bounded real Skill experiment; never edits historical formal data."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import queue
import random
import subprocess
import threading
import time

from skillforge.environment import Environment
from skillforge.evolution_common.artifacts import SplitLedger, clone, record
from skillforge.evolution_schemas import fingerprint
from skillforge.evolution_registry import immutable_json
from skillforge.skill_evolution.catalog import Catalog, revision
from skillforge.skill_evolution.registry import verified_publication
from skillforge.skill_evolution.admission import declare_paired_protocol, paired_gate
from skillforge.skill_evolution import runtime as legacy_runtime
from skillforge.interview_sprint import adapters as api
from skillforge.interview_sprint.workflows import GOAL, GOALS, WorkflowCase, make_case, verify_workflow, private_items
from scripts.run_skill_evolution import ModelSession, static_catalog, digest_file
from scripts import collect_skill_evolution_learn as old_collection
from scripts.evolution_forks import prepare_snapshot as original_prepare
from scripts.evolution_budget import CheckpointAdmission

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "results/interview-sprint/20261013-v1"


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def publish(path, value):
    immutable_json(Path(path), value)


prepare = api.bind(original_prepare, {"run_agent": api.run_agent})
coverage = api.bind(old_collection.evaluate_static, {"verify_workflow": verify_workflow})
collect_one = api.bind(old_collection.collect_one, {"verify_workflow": verify_workflow,
                        "evaluate_static": coverage, "prepare_snapshot": prepare})


class SprintSession(ModelSession):
    def __init__(self, config, output, *, init_timeout=240):
        self.log = (output / "agent.stderr.log").open("w", encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("SKILLFORGE_")}
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        python = ROOT / ".venv-train/Scripts/python.exe"
        self.process = subprocess.Popen([str(python), "-m", "skillforge.interview_sprint.worker"], cwd=ROOT,
            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log, text=True, encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.events = queue.Queue()
        def reader():
            for line in self.process.stdout: self.events.put(line)
            self.events.put(None)
        self.reader = threading.Thread(target=reader, daemon=True); self.reader.start()
        try:
            self.send({"config": str(ROOT / config["training_config"]), "adapter": str(ROOT / config["adapter"]),
                "adapter_sha256": config["adapter_sha256"], "output": str((output / "worker-public").resolve())})
            ready = self.receive(init_timeout)
            if ready["type"] != "ready": raise RuntimeError("real model initialization failed")
            self.settings = ready["settings"]
        except BaseException:
            self.close(); raise


def declare(root):
    root.mkdir(parents=True, exist_ok=False)
    now = datetime.now(timezone.utc)
    config = read(ROOT / "configs/skill-evolution-v1.2.learn-dev.json")
    config["limits"] = {"max_steps": 12, "max_search": 3, "max_load": 3, "max_tokens": 65536}
    config["budget"] = {"project_max_tokens": 4000000, "project_max_wall_seconds": 25200}
    train = [make_case(131001+i, "train") for i in range(6)]
    val = [make_case(132001+i, "validation", variant) for i, variant in enumerate(
        ["instance", "instance", "paraphrase", "paraphrase", "boundary", "partial_payment"])]
    stable_val = [make_case(132101+i, "validation", workflow_id=wf) for i, wf in enumerate(("shipment_summary", "logistics_investigation"))]
    test = [make_case(133001+i, "test", variant) for i, variant in enumerate(
        ["instance", "instance", "instance", "paraphrase", "paraphrase", "boundary", "partial_payment", "unauthorized", "missing"])]
    stable_test = [make_case(133101+i, "test", workflow_id=wf) for i, wf in enumerate(("shipment_summary", "logistics_investigation"))]
    program_cases = []
    for i, category in enumerate(["positive", "positive", "boundary", "boundary", "negative", "negative", "fault", "fault"]):
        case = make_case(134001+i, "validation", "boundary" if category == "boundary" else "instance")
        item = {"case": case.model_dump(), "category": category, "stable": i == 1}
        if category == "negative":
            item.update(expected_error="permission_denied" if i == 4 else "not_found")
            if i == 4: item["authenticated_customer_id"] = "IS13-OTHER"
            else: item["parameters"] = {"order_id": "IS13-MISSING"}
        if category == "fault": item.update(expected_error="timeout", faults={"get_payment" if i == 6 else "get_shipment": ["timeout"]})
        program_cases.append(item)
    ledger = SplitLedger(root / "source-ledger")
    for case in train + val + stable_val + test + stable_test + [WorkflowCase.model_validate(x["case"]) for x in program_cases]:
        partition = ("stable_validation" if case in stable_val or any(x["stable"] and x["case"]["task_id"] == case.task_id for x in program_cases)
                     else "stable_test" if case in stable_test else case.split)
        ledger.claim(case.source_group, partition, related_groups=[case.task_id, case.parameters["order_id"], case.fixture["customer_id"]])
    catalog = static_catalog(config)
    body = {"schema": "interview-sprint-protocol-v1", "created_utc": now.isoformat(),
        "sprint_started_utc": "2026-10-13T09:06:38+00:00", "candidate_deadline_utc": "2026-10-13T13:06:38+00:00",
        "deadline_utc": "2026-10-13T16:06:38+00:00", "max_implementation_experiment_hours": 7,
        "config": config, "goal": GOAL.model_dump(), "goal_hash": GOAL.identity,
        "sources": api.sources(), "static_catalog": catalog.entries(), "static_catalog_hash": catalog.hash,
        "train": [c.model_dump() for c in train], "validation": [c.model_dump() for c in val],
        "stable_validation": [c.model_dump() for c in stable_val], "test": [c.model_dump() for c in test],
        "stable_test": [c.model_dump() for c in stable_test], "program_cases": program_cases,
        "opportunity": {"min_sources": 3, "min_model_call_saving": 1, "discovery_execute_stop_decisions": 4},
        "agent_gate": {"metric": "model_calls", "min_groups": 6, "min_group_gain": 1, "alpha": .05, "max_case_regressions": 0},
        "methods": ["PrimitiveOnly", "StaticLibrary", "ExperienceEvolution"],
        "allowed_tools": sorted(GOAL.required_evidence), "canonicalization": "NONE; diagnose differing successful orders before a versioned change",
        "hypothesis": "Five-read experience may compile into a novel reusable program and save at least one model decision including discovery costs",
        "eoc_scope": "complete genuine five-category receipts, no generated narrative correctness claim",
        "study_scale": "EXPLORATORY; source-group paired units; no claim of statistical significance",
        "safety": "fixed main-v3, original ownership Guard, read-only tool capability shared by all arms; no post-training or production activation",
        "p11": "Existing frozen P11 is read-only; wait for its GPU lease to release, never terminate it"}
    protocol = {**body, "hash": fingerprint(body)}
    for name, expected in body["sources"].items():
        source = ROOT / name
        target = root / "source-snapshot" / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(source.read_bytes())
        if digest_file(target) != expected: raise ValueError("source copy mismatch")
    publish(root / "protocol.json", protocol)
    publish(root / "catalog.json", catalog.entries())
    return protocol


def check_sources(protocol):
    for name, expected in protocol["sources"].items():
        if digest_file(ROOT / name) != expected: raise ValueError("sprint frozen source changed: " + name)


def now():
    return datetime.now(timezone.utc)


def forbidden_attempts(row):
    """Count blocked action intent as well as executed business tool violations."""
    from skillforge.policies import MUTATIONS
    return sum(bool(step.get("action") and (
        step["action"]["type"] == "escalate" or
        step["action"]["type"] == "tool" and step["action"]["name"] in MUTATIONS or
        step["action"]["type"] == "skill" and any(
            event["skill_id"] == step["action"]["name"] and not event["success"] for event in row["agent"]["skill_events"])))
        for step in row["agent"]["steps"])


def summarize(root, report, rows):
    groups = {}
    for item in rows:
        key = (item["phase"], item["method"])
        data = groups.setdefault(key, {"n":0,"eoc":0,"autonomous_eoc":0,"calls":0,"tokens":0,"tool_calls":0,
            "search":0,"load":0,"skill_selected":0,"skill_success":0,"forbidden_attempts":0,"actual_violation":0})
        row = item["row"]; agent, verdict = row["agent"], row["verification"]
        data["n"] += 1; data["eoc"] += int(verdict["task_success"])
        data["autonomous_eoc"] += int(verdict["task_success"] and agent["termination_source"] == "model" and not agent["interventions"].get("runtime_intervention_count",0))
        for key2, metric in [("calls","llm_calls"),("tokens","tokens"),("tool_calls","tool_calls"),("search","search_calls"),("load","load_calls")]:
            data[key2] += agent["metrics"][metric]
        data["skill_selected"] += len(agent["skill_events"]); data["skill_success"] += sum(e["success"] for e in agent["skill_events"])
        data["forbidden_attempts"] += forbidden_attempts(row)
        data["actual_violation"] += int(verdict["actual_policy_violation"] or verdict["actual_workflow_violation"])
    comparisons = []
    for phase in ("agent-validation", "heldout"):
        by_task = {}
        for item in rows:
            if item["phase"] == phase: by_task.setdefault(item["row"]["case"]["task_id"], {})[item["method"]] = item["row"]
        for task, arms in by_task.items():
            for baseline in ("PrimitiveOnly", "StaticLibrary"):
                if baseline not in arms or "ExperienceEvolution" not in arms: continue
                a,b = arms[baseline], arms["ExperienceEvolution"]
                comparisons.append({"phase":phase,"task_id":task,"source_group":b["case"]["source_group"],
                    "variant": b["case"]["variant"], "baseline":baseline,"baseline_eoc":a["verification"]["task_success"],
                    "candidate_eoc":b["verification"]["task_success"], "eoc_delta":int(b["verification"]["task_success"])-int(a["verification"]["task_success"]),
                    "model_call_saving":a["agent"]["metrics"]["llm_calls"]-b["agent"]["metrics"]["llm_calls"],
                    "token_saving":a["agent"]["metrics"]["tokens"]-b["agent"]["metrics"]["tokens"],
                    "joint_success":a["verification"]["task_success"] and b["verification"]["task_success"],
                    "regression":a["verification"]["task_success"] and not b["verification"]["task_success"]})
    publish(root / "paired-effects.json", comparisons)
    publish(root / "method-metrics.json", [{"phase":k[0],"method":k[1],**v} for k,v in groups.items()])
    lines = ["# Interview Sprint — real new Skill closed-loop experiment", "",
        "Status: **"+report["status"]+"**. Exploratory fixed-domain evidence; no statistical significance claim.","",
        "The original Stage 1 had zero useful opportunities: short 3–4-decision tasks did not cover the frozen four-decision discovery/execution cost. "
        "This experiment tests whether independently declared five-category evidence collection yields a useful reusable program with fixed main-v3 weights.","",
        "EOC compares full customer/order/payment/shipment returns and the complete item list with initial SQLite facts, checks ownership and unchanged state. "
        "Negative tasks require an actual denial followed by refusal. Candidates cannot define correctness. This does not evaluate generated dossier prose.","",
        "The existing Opportunity Miner and TraceCompiler consume audited real learn trajectories; at least three independent source groups and at least one estimated saved model decision are required. "
        "No family-specific tool sequence, new model training, or test-driven threshold change is used.","",
        f"Candidates: {report['candidate_count']}; Program Admission: {report['program_admitted']}; Agent Admission: {report['agent_admitted']}; activation/deployment: false.","",
        "| Phase | Method | EOC | Autonomous EOC | Model calls | Tokens | Tools | Search/load | Skill successful/selected |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for (phase,method),v in groups.items():
        lines.append(f"| {phase} | {method} | {v['eoc']}/{v['n']} | {v['autonomous_eoc']}/{v['n']} | {v['calls']} | {v['tokens']} | {v['tool_calls']} | {v['search']}/{v['load']} | {v['skill_success']}/{v['skill_selected']} |")
    lines.extend(["", "Costs including unsuccessful or incomplete collection: `"+json.dumps(report["costs"])+"`.", "",
        "Raw paired effects (including failure costs, regressions and joint-success eligibility), per-variant results, exact model messages, "
        "tool receipts, source group ownership, candidate nodes and version identities are stored alongside this report. "
        "Source groups, not arms or tool events, are independent units. Confidence is limited by the small sample and shared task template.","",
        "Failures/limitations: "+str(report["failure"])+". Rejected programs and no-benefit outcomes retain the parent library. "
        "Scripted static coverage, program checks and recorded-response audits are CPU engineering evidence and are not additional autonomous learning samples.","",
        "Interview trade-offs: conservative discovery-inclusive utility, exact public-input parameter binding, provenance per node, fail-closed safety, "
        "program/Agent admission separation, held-out ownership, and preservation of negative outcomes. Scope is restricted procedural Skill learning and reuse."])
    (root / "REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def audit_arm(folder, case, catalog, settings, limits, charge):
    """Actual SQLite replay of exact saved model outputs, decisions and receipts."""
    from skillforge.schemas import Action
    from skillforge.skill_evolution.agent_evidence import semantic
    from scripts.audit_boundary_runtime_smoke import first_difference
    row, status = read(folder / "result.json"), read(folder / "collection-status.json")
    if not status["completed"] or row["model_identity_hash"] != fingerprint(settings): raise ValueError("incomplete/foreign arm")
    env = Environment(fixture=case.fixture)
    try:
        if env.snapshot() != row["initial_state"] or private_items(env) != row["initial_items"]: raise ValueError("initial DB mismatch")
        admission = CheckpointAdmission(*charge)
        checkpoints = sorted((folder / "checkpoints").glob("*/snapshot.json"), key=lambda p: int(p.parent.name))
        saved = []
        for p in checkpoints:
            snap = read(p)
            if fingerprint(snap["body"]) != snap["hash"] or digest_file(p.parent / "environment.sqlite") != snap["body"]["database_sha256"]:
                raise ValueError("checkpoint integrity mismatch")
            state = snap["body"]["runtime"]; saved.append(state)
            pending = [i for i, q in enumerate(state["model_requests"]) if q["status"] == "pending" and i not in admission.approved]
            if pending:
                receipt = read(folder / "admissions" / f"{pending[0]}.json")
                expected = admission.inspect(state, receipt["elapsed_seconds"])
                if receipt != {**expected, "checkpoint_index": int(p.parent.name)} or not receipt["approved"]: raise ValueError("request admission mismatch")
                admission.record_approval(receipt)
            else: admission.inspect(state, 0)
        if admission.charged_tokens() != status["charged_tokens"]: raise ValueError("charge mismatch")
        class Recorded:
            def __init__(self): self.settings, self.tokens, self.index = settings, 0, 0
            def decide(self, context):
                i = self.index; step, request = row["agent"]["steps"][i], row["agent"]["model_requests"][i]
                if context != step["context"] or json.loads(step["messages"][1]["content"]) != context or step["messages"][0]["content"] != settings["system_prompt"]:
                    raise ValueError("raw model messages do not match replay context")
                if not request["usage_known"]: raise ValueError("unknown usage cannot be audited as success")
                self.last_messages, self.last_response = step["messages"], step["model_response"]
                self.tokens += request["charged_tokens"]; self.index += 1
                return Action.model_validate_json(self.last_response)
        model, replays = Recorded(), []
        def tool(name, args, key, source):
            try: return env.call(name, args, case.authenticated_customer_id, key)
            finally:
                if env.audit: env.audit[-1]["decision_origin"] = source
        replay = api.run_agent(model, case.public_task(), catalog, tool, persist=replays.append, **limits)
        left, right = clone(replay), clone(row["agent"])
        left["metrics"].pop("seconds"); right["metrics"].pop("seconds")
        difference = first_difference(semantic(left), semantic(right), "agent") if semantic(left) != semantic(right) else None
        if difference: raise ValueError(difference)
        if len(replays) != len(saved): raise ValueError("checkpoint count differs")
        for i, (a, b) in enumerate(zip(replays, saved)):
            difference = first_difference(semantic(a), semantic(b), f"checkpoint[{i}]") if semantic(a) != semantic(b) else None
            if difference: raise ValueError(difference)
        if semantic(env.audit) != semantic(row["tool_audit"]): raise ValueError("actual tool audit differs")
        verdict = verify_workflow(case, row["initial_state"], env.snapshot(), env.audit, replay["outcome"], row["initial_items"], private_items(env))
        if verdict != row["verification"]: raise ValueError("independent EOC differs")
        if not model.index == len(row["agent"]["model_requests"]): raise ValueError("orphan model request")
        receipt = {"passed": True, "result_sha256": digest_file(folder / "result.json"), "checkpoints": len(saved),
                   "replay_tool_calls": len(env.audit),
                   "charged_tokens": status["charged_tokens"], "scope": "recorded real outputs replayed against actual SQLite and independent EOC; no new inference"}
        publish(folder / "independent-audit.json", receipt)
        return receipt
    finally: env.close()


def run(root):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    protocol = read(root / "protocol.json"); check_sources(protocol)
    if (root / "run-registration.json").exists(): raise ValueError("no implicit retry or budget refill; use a fresh versioned continuation")
    config, statuses, rows, audits = protocol["config"], [], [], []
    started = time.perf_counter(); failure = None; proposal = None; program = None; gate = None
    absolute_deadline = datetime.fromisoformat(protocol["deadline_utc"])
    candidate_deadline = datetime.fromisoformat(protocol["candidate_deadline_utc"])
    # Poll the existing lease WITHOUT attempting inference or disturbing P11.
    while (ROOT / ".runtime/active-evolution-gpu-lease.json").exists():
        if now() >= candidate_deadline:
            publish(root / "report.json", {"status": "NO_USEFUL_CANDIDATE", "reason": "GPU unavailable before four-hour deadline", "model_calls": 0})
            return
        time.sleep(15)
    config = clone(config)
    config["budget"]["project_max_wall_seconds"] = min(config["budget"]["project_max_wall_seconds"], (absolute_deadline-now()).total_seconds())
    publish(root / "run-registration.json", {"protocol_hash": protocol["hash"], "started_utc": now().isoformat(), "config": config})
    catalogs = {"PrimitiveOnly": Catalog([]), "StaticLibrary": Catalog(protocol["static_catalog"])}
    def collect(session, case, method, phase):
        check_sources(protocol)
        if now() >= absolute_deadline: raise TimeoutError("seven-hour sprint deadline")
        prior = sum(s["charged_tokens"] for s in statuses)
        folder = root / phase / case.task_id / method
        row, status = collect_one(session, case, catalogs[method], folder, config, prior, 0, started)
        statuses.append({**status, "method": method, "phase": phase, "folder": folder.relative_to(root).as_posix()})
        if not row: raise RuntimeError(status["failure"])
        receipt = audit_arm(folder, case, catalogs[method], session.settings, config["limits"],
                            (prior, config["budget"]["project_max_tokens"], 0, config["budget"]["project_max_wall_seconds"]))
        audits.append(receipt); rows.append({"phase": phase, "method": method, "row": row})
        print(json.dumps({"phase": phase, "task": case.task_id, "method": method, "eoc": row["verification"]["task_success"],
                          "model_calls": row["agent"]["metrics"]["llm_calls"], "tokens": status["charged_tokens"]}), flush=True)
        return row
    try:
        with GPUServiceLease(), ExitStack() as stack:
            session = SprintSession(config, root); stack.callback(session.close)
            if session.settings.get("adapter_sha256") != config["adapter_sha256"] or session.settings.get("engineering_only") is not False:
                raise ValueError("fixed real main-v3 required")
            publish(root / "model-identity.json", session.settings)
            for data in protocol["train"]:
                if now() >= candidate_deadline: raise TimeoutError("four-hour candidate deadline")
                collect(session, WorkflowCase.model_validate(data), "StaticLibrary", "learn")
            learn = [r["row"] for r in rows if r["phase"] == "learn"]
            screen = api.mine_opportunities(learn, session.settings)
            publish(root / "opportunity-screen.json", screen)
            proposal = api.compile_screen(screen); publish(root / "candidate-screen.json", proposal)
            if not proposal["n_candidates"]:
                print(json.dumps({"milestone": "NO_USEFUL_CANDIDATE", "reasons": [r["reasons"] for r in screen["records"]]}), flush=True)
            else:
                if proposal["n_candidates"] != 1: raise ValueError("multiple candidates need separately frozen selection; no test-based choice")
                candidate = next(r["candidate"] for r in proposal["results"] if r["candidate"])
                if now() >= candidate_deadline: raise TimeoutError("candidate arose after four-hour cutoff")
                entry = revision(candidate["skill"], name="Order investigation dossier",
                    description=GOAL.public_goal, support_domain={"goal_hash": GOAL.identity, "authorized_reads_only": True})
                publish(root / "candidate-entry.json", entry)
                functions = api.validation_functions(); ledger = SplitLedger(root / "source-ledger")
                vp = functions["declare_protocol"](entry, GOAL.identity, protocol["program_cases"], ledger,
                    mode="formal", learn_candidate=candidate)
                publish(root / "program-validation-protocol.json", vp)
                validation = functions["validate_program"](entry, vp); publish(root / "program-validation.json", validation)
                program = functions["program_admission"](validation); publish(root / "program-admission.json", program)
                if program["decision"] == "ADMITTED":
                    published = verified_publication(entry)
                    catalogs["ExperienceEvolution"] = Catalog([*catalogs["StaticLibrary"].entries(), published])
                    record(root / "registry", "registrations", {"kind": "interview_exploratory_program", "candidate": candidate,
                        "published_entry": published, "program_admission_hash": program["hash"], "learn_audits": audits,
                        "agent_admitted": False, "isolated_activated": False, "deployed": False})
                    publish(root / "candidate-catalog.json", catalogs["ExperienceEvolution"].entries())
                    plan = []
                    for data in protocol["validation"] + protocol["stable_validation"]:
                        case = WorkflowCase.model_validate(data); env = Environment(fixture=case.fixture)
                        try: initial_hash = fingerprint({"state": env.snapshot(), "items": private_items(env), "auth": case.authenticated_customer_id})
                        finally: env.close()
                        plan.append({"task_id": case.task_id, "source_group": case.source_group, "task_hash": fingerprint(case.model_dump()),
                            "initial_state_hash": initial_hash, "split": "stable_validation" if data in protocol["stable_validation"] else "validation"})
                    execution_identity = fingerprint({"model": session.settings, "sources": protocol["sources"], "limits": config["limits"]})
                    paired = declare_paired_protocol(plan, baseline_catalog_hash=catalogs["StaticLibrary"].hash,
                        candidate_catalog_hash=catalogs["ExperienceEvolution"].hash, execution_identity=execution_identity,
                        **{k:v for k,v in protocol["agent_gate"].items() if k != "max_case_regressions"})
                    publish(root / "paired-validation-protocol.json", paired)
                    pairs = []
                    for index, data in enumerate(protocol["validation"] + protocol["stable_validation"]):
                        case = WorkflowCase.model_validate(data); arms = {}
                        methods = protocol["methods"][index % 3:] + protocol["methods"][:index % 3]
                        for method in methods: arms[method] = collect(session, case, method, "agent-validation")
                        def arm(method):
                            row = arms[method]; verdict, metrics = row["verification"], row["agent"]["metrics"]
                            return {"eoc": verdict["task_success"], "attempted_violations": int(verdict["attempted_policy_violation"]) + forbidden_attempts(row),
                                "actual_violations": int(verdict["actual_policy_violation"]), "workflow_violations": int(verdict["actual_workflow_violation"]),
                                "model_calls": metrics["llm_calls"], "tokens": metrics["tokens"], "cost_settled": True,
                                "execution_identity": execution_identity, "catalog_hash": catalogs[method].hash, "evidence_hash": fingerprint(row)}
                        pairs.append({**{k:v for k,v in plan[index].items() if k != "split"},
                                      "baseline": arm("StaticLibrary"), "candidate": arm("ExperienceEvolution")})
                    gate = paired_gate(paired, pairs); publish(root / "agent-paired-gate.json", gate)
                    publish(root / "agent-admission.json", {"agent_admitted": gate["statistical_gate_passed"],
                        "gate_hash": gate["hash"], "all_raw_arms_independently_replayed": True,
                        "scope": "exploratory fixed-domain gate; not a research significance claim", "activated": False})
                    for index, data in enumerate(protocol["test"] + protocol["stable_test"]):
                        case = WorkflowCase.model_validate(data)
                        for method in protocol["methods"][index % 3:] + protocol["methods"][:index % 3]: collect(session, case, method, "heldout")
    except Exception as exc:
        failure = type(exc).__name__ + ": " + str(exc)
    report = {"schema": "interview-sprint-report-v1", "protocol_hash": protocol["hash"],
        "status": "FAILED_OR_INCOMPLETE" if failure else "NO_USEFUL_CANDIDATE" if not proposal or not proposal["n_candidates"] else "PROGRAM_REJECTED" if not program or program["decision"] != "ADMITTED" else "COMPLETE",
        "failure": failure, "candidate_count": proposal["n_candidates"] if proposal else 0,
        "program_admitted": bool(program and program["decision"] == "ADMITTED"),
        "agent_admitted": bool(gate and gate["statistical_gate_passed"]), "research_claim_passed": None,
        "activated": False, "deployed": False, "costs": {"charged_tokens": sum(s["charged_tokens"] for s in statuses),
            "model_calls": sum(r["row"]["agent"]["metrics"]["llm_calls"] for r in rows),
            "tool_calls": sum(len(r["row"]["tool_audit"]) for r in rows), "wall_seconds": time.perf_counter()-started,
            "gpu_utilization_hours": "UNMEASURED", "static_coverage_tool_calls": sum(s["static_evaluation_tool_calls"] for s in statuses),
            "recorded_response_audit_tool_calls": sum(a["replay_tool_calls"] for a in audits),
            "program_validation_tool_calls": program["report"]["tool_calls"] if program else 0,
            "program_admission_replay_tool_calls": program["audit"]["replay_tool_calls"] if program else 0},
        "arm_statuses": statuses, "audits": audits,
        "limitations": ["human-declared domain and goals", "fixed model, permissions and existing straight-line DSL",
            "exploratory sample; no statistical significance claim", "receipt completeness, not dossier prose quality", "no SFT/DPO/RL"]}
    publish(root / "report.json", report)
    summarize(root, report, rows)
    print(json.dumps({k:report[k] for k in ("status", "failure", "candidate_count", "program_admitted", "agent_admitted", "costs")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["declare", "run"]); parser.add_argument("--output", type=Path, default=DEFAULT)
    args = parser.parse_args()
    if args.command == "declare": print(json.dumps({"protocol_hash": declare(args.output)["hash"]}))
    else: run(args.output)
