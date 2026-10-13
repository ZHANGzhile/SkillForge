"""P5 same-backend A/B/C development cost smoke; no formal efficacy claim."""
import argparse
from contextlib import ExitStack
import json
import math
from pathlib import Path
import shutil
import time

from scripts.collect_skill_evolution_learn import collect_one
from scripts.continue_skill_evolution_selection import publish
from scripts.evolution_budget import CheckpointAdmission
from scripts.run_skill_evolution import ROOT, ModelSession, digest_file
from skillforge.evolution_common.artifacts import SplitLedger
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.agent_evidence import audit_trajectory, read
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.registry import VersionedRegistry
from skillforge.skill_evolution.runtime import runtime_sources, PROTOCOL
from skillforge.skill_evolution.workflows import make_case


METHODS = ("A", "B", "C")


def hashed(body): return {**body, "hash": fingerprint(body)}


def check_no_history(row):
    """No cross-task raw trajectories; current-task observations/history remain."""
    task_id = row["case"]["task_id"]
    forbidden = {"learn_trajectories", "experience_memory", "raw_trajectories", "revision_memory", "source_group", "split", "gold", "fixture"}
    for index, step in enumerate(row["agent"]["steps"]):
        context = step["context"]
        if context["task_id"] != task_id or forbidden & set(context):
            raise ValueError("cross-task/private evidence in execution context")
        expected = [{key: value for key, value in old.items() if key not in
                    {"context", "messages", "model_response", "selection_trace"}} for old in row["agent"]["steps"][max(0,index-8):index]]
        if context["history"] != expected:
            raise ValueError("execution history contains evidence other than current-task steps")
    return True


def prior_evidence(config):
    """Carry actual prior costs, never replenish an exhausted project budget."""
    from scripts.verify_skill_evolution_registry import audit as audit_registry
    registry_run = ROOT / config["registry_run"]
    audit_registry(registry_run)
    prior = read(ROOT / config["prior_run"] / "report.json")
    registration = read(ROOT / config["prior_run"] / "registration.json")
    if prior["status"] != "complete": raise ValueError("prior learn phase must be complete/audited")
    if (config["budget"]["project_max_tokens"] != registration["config"]["budget"]["project_max_tokens"] or
            config["budget"]["project_max_wall_seconds"] != registration["config"]["budget"]["project_max_wall_seconds"]):
        raise ValueError("development cost smoke must retain existing cumulative ceilings")
    history, prior_tokens, prior_wall = [], prior["shared_total_charged_tokens"], prior["shared_total_wall_seconds"]
    for path in sorted((ROOT / "results/skill-evolution/v1.2/reuse-budget-ledger").glob("*.json")):
        owner = read(path)
        if owner["phase_id"] == config["budget"]["phase_id"]: raise ValueError("phase already registered; audit its existing run")
        if not (ROOT / owner["output"] / "report.json").exists(): raise ValueError("prior reuse phase is open; reconcile before continuing")
        result = audit(ROOT / owner["output"])
        previous = read(ROOT / owner["output"] / "report.json")
        if not result["costs_reconciled"]: raise ValueError("prior reuse costs unresolved")
        prior_tokens += previous["charged_tokens_including_incomplete"]
        prior_wall += previous["wall_seconds"]
        history.append({"output":owner["output"],"report_sha256":digest_file(ROOT / owner["output"] / "report.json")})
    if (prior_tokens >= config["budget"]["project_max_tokens"] or prior_wall >= config["budget"]["project_max_wall_seconds"]):
        raise ValueError("existing development budget exhausted")
    return {"prior_tokens":prior_tokens,"prior_wall":prior_wall,"prior_reuse_runs":history,
            "prior_report_sha256":digest_file(ROOT / config["prior_run"] / "report.json")}


def register(config, output):
    prior = prior_evidence(config)
    registry_report = read(ROOT / config["registry_run"] / "report.json")
    registry = VersionedRegistry(ROOT / config["registry_run"] / "r")
    selected, evolved = registry.load(registry_report["snapshots"]["retained_parent"])
    static = Catalog.load(ROOT / config["prior_run"] / "catalog.json")
    if selected["operation"] != "RETAIN_PARENT" or evolved.hash != static.hash:
        raise ValueError("this first smoke requires the actual audited zero-update catalog")
    catalogs = {"A":Catalog([]),"B":static,"C":evolved}
    cases = [make_case(name,seed,"dev") for name,seed in config["cases"]]
    if len(cases) != 2 or len({case.source_group for case in cases}) != len(cases):
        raise ValueError("two fresh independent dev cases required for this smoke")
    ledger = SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger")
    for case in cases:
        ledger.claim(case.source_group,"dev",related_groups=[case.task_id,case.parameters["order_id"],case.authenticated_customer_id])
    schedule = []
    for index,case in enumerate(cases):
        for method in METHODS[index:] + METHODS[:index]:
            schedule.append({"task_id":case.task_id,"method":method,"folder":f"c{index}/{method.lower()}"})
    sources = {"skillforge/" + name:value for name,value in runtime_sources().items()}
    for name in ("scripts/run_skill_evolution_reuse.py","scripts/collect_skill_evolution_learn.py","scripts/evolution_budget.py",
                 "scripts/evolution_forks.py","scripts/run_skill_evolution.py","scripts/execution_aware_gpu_lease.py"):
        sources[name] = digest_file(ROOT / name)
    for name,expected in sources.items():
        target = output / "source-snapshot" / name
        target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(ROOT / name,target)
        if digest_file(target) != expected: raise ValueError("source changed during registration")
    for method,catalog in catalogs.items(): catalog.save(output / (method + "-catalog.json"))
    publish(output / "private-dev-cases.json",[case.model_dump() for case in cases])
    body = {"schema":"p5-reuse-cost-smoke-protocol-v1","config":config,"protocol":PROTOCOL,"sources":sources,
            **prior,"cases_hash":fingerprint([case.model_dump() for case in cases]),
            "catalogs":{method:catalog.hash for method,catalog in catalogs.items()},"schedule":schedule,
            "parent_snapshot":registry_report["snapshots"]["retained_parent"],
            "no_history":"no cross-task raw trajectories in any arm; current-task steps retained; structural invariant, not a fourth independent treatment",
            "scope":"development cost smoke only; same model/runtime/retrieval/limits, catalog is the experimental factor"}
    reg = {**body,"protocol_hash":fingerprint(body)}
    publish(output / "registration.json",reg)
    owner = {"phase_id":config["budget"]["phase_id"],"output":output.relative_to(ROOT).as_posix(),
             "protocol_hash":reg["protocol_hash"],"ceilings":config["budget"],**prior}
    publish(ROOT / "results/skill-evolution/v1.2/reuse-budget-ledger" / (fingerprint(owner["phase_id"]) + ".json"),owner)
    return reg,cases,catalogs


def summarize(reg, rows, statuses, failure, wall):
    by_method = {}
    for method in METHODS:
        arm = [row for _,name,row in rows if name == method]
        by_method[method] = {"n":len(arm),"eoc":sum(row["verification"]["task_success"] for row in arm),
            "autonomous_eoc":sum(row["verification"]["task_success"] and not row["agent"]["interventions"]["runtime_intervention_count"] for row in arm),
            "runtime_assisted_eoc":sum(row["verification"]["task_success"] and bool(row["agent"]["interventions"]["runtime_intervention_count"]) for row in arm),
            **{key:sum(row["agent"]["metrics"][key] for row in arm) for key in ("llm_calls","tokens","tool_calls","search_calls","load_calls")},
            **{key:sum(row["verification"][key] for row in arm) for key in ("attempted_policy_violation","actual_policy_violation","attempted_workflow_violation","actual_workflow_violation")}}
    charged = sum(status["charged_tokens"] for status in statuses)
    comparison = []
    for task_id in dict.fromkeys(item["task_id"] for item in reg["schedule"]):
        arms = {method:row for identity,method,row in rows if identity == task_id}
        if len(arms) != 3: continue
        b,c = arms["B"],arms["C"]
        comparison.append({"task_id":task_id,"B_eoc":b["verification"]["task_success"],"C_eoc":c["verification"]["task_success"],
            "C_minus_B_eoc":int(c["verification"]["task_success"])-int(b["verification"]["task_success"]),
            "B_minus_C_model_calls":b["agent"]["metrics"]["llm_calls"]-c["agent"]["metrics"]["llm_calls"],
            "B_minus_C_tokens":b["agent"]["metrics"]["tokens"]-c["agent"]["metrics"]["tokens"]})
    return {"schema":"p5-reuse-cost-smoke-report-v1","protocol_hash":reg["protocol_hash"],
        "status":"complete" if len(rows) == len(reg["schedule"]) and not failure else "blocked_or_incomplete",
        "failure":failure,"planned_arms":len(reg["schedule"]),"completed_arms":len(rows),"methods":by_method,"paired_C_B":comparison,
        "charged_tokens_including_incomplete":charged,"wall_seconds":wall,
        "shared_total_charged_tokens":reg["prior_tokens"]+charged,"shared_total_wall_seconds":reg["prior_wall"]+wall,
        "case_statuses":statuses,"no_history_checked_arms":sum(check_no_history(row) for _,_,row in rows),
        "scripted_static_coverage_tool_calls":sum(status["static_evaluation_tool_calls"] for status in statuses),
        "real_candidates":0,"program_admitted":False,"agent_admitted":False,"isolated_activated":False,"deployed":False,"research_claim_passed":None,
        "scope":"two dev source groups, no significance/generalization claim; no-op B/C catalog identity explicitly retained"}


def smoke(config, output):
    from scripts.execution_aware_gpu_lease import GPUServiceLease
    output = Path(output).resolve(); output.mkdir(parents=True,exist_ok=False)
    started = time.perf_counter()
    reg,cases,catalogs = register(config,output)
    case_map = {case.task_id:case for case in cases}
    rows,statuses,failure = [],[],None
    try:
        with GPUServiceLease(),ExitStack() as cleanup:
            remaining = config["budget"]["project_max_wall_seconds"]-reg["prior_wall"]-(time.perf_counter()-started)-10
            if remaining <= 0: raise TimeoutError("shared wall budget exhausted before model initialization")
            session = ModelSession(config,output,init_timeout=min(remaining,120))
            cleanup.callback(session.close)
            if session.settings.get("engineering_only") is not False or session.settings.get("adapter_sha256") != config["adapter_sha256"]:
                raise ValueError("registered fixed real-model weights required")
            publish(output / "model-identity.json",session.settings)
            for item in reg["schedule"]:
                row,status = collect_one(session,case_map[item["task_id"]],catalogs[item["method"]],output / item["folder"],config,
                    reg["prior_tokens"]+sum(previous["charged_tokens"] for previous in statuses),reg["prior_wall"],started)
                statuses.append({**item,**status})
                if row: rows.append((item["task_id"],item["method"],row))
                print(json.dumps({"method":item["method"],"task_id":item["task_id"],"completed":status["completed"],
                    "eoc":row["verification"]["task_success"] if row else None,"tokens":status["charged_tokens"],"failure":status["failure"]}),flush=True)
                if not status["completed"]:
                    failure = status["failure"]; break
    except Exception as exc: failure = type(exc).__name__ + ": " + str(exc)
    report = summarize(reg,rows,statuses,failure,time.perf_counter()-started)
    publish(output / "report.json",report)
    return report


def audit_incomplete(folder, context):
    """Conservatively retain approved unknown costs; never restart an arm."""
    folder = Path(folder); status = read(folder / "collection-status.json")
    admission, seen, denied = CheckpointAdmission(**context),set(),False
    paths = sorted((folder / "checkpoints").glob("*/snapshot.json"),key=lambda path:int(path.parent.name))
    if [int(path.parent.name) for path in paths] != list(range(len(paths))): raise ValueError("non-contiguous incomplete checkpoint sequence")
    elapsed = 0
    for path in paths:
        if denied: raise ValueError("checkpoint follows denied inference")
        snapshot = read(path)
        if fingerprint(snapshot["body"]) != snapshot["hash"] or digest_file(path.parent / "environment.sqlite") != snapshot["body"]["database_sha256"]:
            raise ValueError("incomplete checkpoint integrity mismatch")
        value = snapshot["body"]["runtime"]
        pending = [i for i,r in enumerate(value["model_requests"]) if r["status"] == "pending" and i not in admission.approved]
        if pending:
            name = str(pending[0]) + ".json"; receipt = read(folder / "admissions" / name)
            if receipt["elapsed_seconds"] < elapsed: raise ValueError("incomplete elapsed time regressed")
            elapsed = receipt["elapsed_seconds"]
            expected = admission.inspect(value,elapsed)
            if receipt != {**expected,"checkpoint_index":int(path.parent.name)}: raise ValueError("incomplete inference admission mismatch")
            seen.add(name)
            if receipt["approved"]: admission.record_approval(receipt)
            else:
                denied = True
                if receipt != status["denied_before_ack"]: raise ValueError("denied request not reconciled")
        else: admission.inspect(value,elapsed)
    if seen != {path.name for path in (folder / "admissions").glob("*.json")} or admission.charged_tokens() != status["charged_tokens"]:
        raise ValueError("incomplete/orphan inference charge mismatch")
    if status["last_budget"] != (admission.last["budget"] if admission.last else None): raise ValueError("incomplete final budget mismatch")
    return status["charged_tokens"]


def audit(root):
    root = Path(root).resolve(); reg,report = read(root / "registration.json"),read(root / "report.json")
    if fingerprint({key:value for key,value in reg.items() if key != "protocol_hash"}) != reg["protocol_hash"]:
        raise ValueError("reuse registration hash mismatch")
    for name,expected in reg["sources"].items():
        if digest_file(root / "source-snapshot" / name) != expected: raise ValueError("reuse archived source mismatch")
    for name in ("scripts/run_skill_evolution_reuse.py","scripts/evolution_budget.py","scripts/collect_skill_evolution_learn.py"):
        if digest_file(ROOT / name) != reg["sources"][name]: raise ValueError("audit with registered controller version")
    config = reg["config"]
    prior = read(ROOT / config["prior_run"] / "report.json")
    if digest_file(ROOT / config["prior_run"] / "report.json") != reg["prior_report_sha256"]:
        raise ValueError("prior shared cost evidence changed")
    prior_tokens,prior_wall = prior["shared_total_charged_tokens"],prior["shared_total_wall_seconds"]
    for item in reg["prior_reuse_runs"]:
        if digest_file(ROOT / item["output"] / "report.json") != item["report_sha256"]: raise ValueError("prior reuse report changed")
        previous = read(ROOT / item["output"] / "report.json")
        prior_tokens += previous["charged_tokens_including_incomplete"]; prior_wall += previous["wall_seconds"]
    if reg["prior_tokens"] != prior_tokens or reg["prior_wall"] != prior_wall: raise ValueError("reuse cumulative cost reset")
    budget = config["budget"]
    owner = read(ROOT / "results/skill-evolution/v1.2/reuse-budget-ledger" / (fingerprint(budget["phase_id"]) + ".json"))
    expected_owner = {"phase_id":budget["phase_id"],"output":root.relative_to(ROOT).as_posix(),
        "protocol_hash":reg["protocol_hash"],"ceilings":budget,
        **{key:reg[key] for key in ("prior_tokens","prior_wall","prior_reuse_runs","prior_report_sha256")}}
    if owner != expected_owner: raise ValueError("registered reuse phase/budget ledger mismatch")
    if type(report["wall_seconds"]) not in {int,float} or not math.isfinite(report["wall_seconds"]) or report["wall_seconds"] < 0:
        raise ValueError("invalid collection wall time")
    catalogs = {method:Catalog.load(root / (method + "-catalog.json")) for method in METHODS}
    cases = read(root / "private-dev-cases.json")
    if fingerprint(cases) != reg["cases_hash"] or any(case["split"] != "dev" for case in cases): raise ValueError("reuse dev cases mismatch")
    ledger = SplitLedger(ROOT / "results/skill-evolution/v1.2/source-ledger")
    for case in cases:
        if any(ledger.owners.get(key) != "dev" for key in (case["task_id"],case["source_group"],case["parameters"]["order_id"],case["authenticated_customer_id"])):
            raise ValueError("reuse dev source/entity ownership mismatch")
    if catalogs["A"].entries() or any(catalogs[method].hash != reg["catalogs"][method] for method in METHODS): raise ValueError("reuse method/catalog mismatch")
    selected,c = VersionedRegistry(ROOT / config["registry_run"] / "r").load(reg["parent_snapshot"])
    if c.hash != catalogs["C"].hash or catalogs["B"].hash != Catalog.load(ROOT / config["prior_run"] / "catalog.json").hash:
        raise ValueError("reuse static/evolution catalog provenance mismatch")
    if c.hash != catalogs["B"].hash or selected["operation"] != "RETAIN_PARENT": raise ValueError("smoke zero-update baseline changed")
    expected_schedule = []
    for index,case in enumerate(cases):
        for method in METHODS[index:] + METHODS[:index]: expected_schedule.append({"task_id":case["task_id"],"method":method,"folder":f"c{index}/{method.lower()}"})
    if expected_schedule != reg["schedule"]: raise ValueError("reuse method order changed")
    completed, statuses, evidence, charged = [],[],[],0
    settings = read(root / "model-identity.json") if (root / "model-identity.json").exists() else None
    if settings is not None and settings.get("adapter_sha256") != config["adapter_sha256"]: raise ValueError("reuse model adapter mismatch")
    sources = {name.removeprefix("skillforge/"):value for name,value in reg["sources"].items() if name.startswith("skillforge/")}
    case_map = {case["task_id"]:case for case in cases}
    incomplete = False
    for item in reg["schedule"]:
        folder = root / item["folder"]
        if not (folder / "collection-status.json").exists():
            if any(folder.rglob("snapshot.json")): raise ValueError("unreconciled arm without final status")
            incomplete = True; continue
        if incomplete: raise ValueError("arm follows a missing/incomplete predecessor")
        status = read(folder / "collection-status.json"); statuses.append({**item,**status})
        context = {"prior_tokens":reg["prior_tokens"]+charged,"max_tokens":config["budget"]["project_max_tokens"],
                   "prior_wall":reg["prior_wall"],"max_wall":config["budget"]["project_max_wall_seconds"]}
        if status["completed"]:
            row = read(folder / "result.json")
            if row["case"] != case_map[item["task_id"]]: raise ValueError("raw reuse case changed")
            packet = audit_trajectory(folder,catalogs[item["method"]],settings,sources,config["limits"],charge_context=context)
            check_no_history(row); evidence.append({**item,"audit":packet}); charged += packet["tokens"]
            completed.append((item["task_id"],item["method"],row))
        else:
            charged += audit_incomplete(folder,context); incomplete = True
    expected = summarize(reg,completed,statuses,report["failure"],report["wall_seconds"])
    last_admission_elapsed = max((read(path)["elapsed_seconds"] for item in reg["schedule"]
        for path in (root / item["folder"] / "admissions").glob("*.json")),default=0)
    if report["wall_seconds"] < last_admission_elapsed:
        raise ValueError("reported wall time precedes completed inference approvals")
    for task_id in case_map:
        arms = [item["audit"] for item in evidence if item["task_id"] == task_id]
        if any(len({item[key] for item in arms}) > 1 for key in ("task_hash","initial_state_hash","execution_identity")):
            raise ValueError("A/B/C task, independent initial state or execution backend mismatch")
    if report != expected or charged != report["charged_tokens_including_incomplete"]:
        raise ValueError("reuse report differs from independent raw-evidence/cost audit")
    result = {"passed":True,"run_completed":report["status"] == "complete","costs_reconciled":True,
        "protocol_hash":reg["protocol_hash"],"report_sha256":digest_file(root / "report.json"),"generator_sha256":digest_file(__file__),
        "audited_arms":len(evidence),"charged_tokens":charged,"replay_tool_calls":sum(item["audit"]["replay_tool_calls"] for item in evidence),
        "no_history_checked_arms":len(evidence),"new_model_calls":0,"new_tokens":0,"scope":"recorded response replay, exact A/B/C catalogs, cumulative approvals and No-History context invariant"}
    publish(root / "evidence-audits" / (digest_file(__file__) + ".json"),result)
    publish(root / "agent-evidence" / (digest_file(__file__) + ".json"),hashed({"arms":evidence,"scope":"development, not formal admission"}))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["smoke","audit"]); parser.add_argument("--config",default="configs/skill-evolution-v1.2.reuse-dev.json")
    parser.add_argument("--output"); parser.add_argument("--run")
    args = parser.parse_args()
    if args.command == "smoke" and not args.output or args.command == "audit" and not args.run: parser.error("smoke requires --output; audit requires --run")
    result = smoke(read(args.config),args.output) if args.command == "smoke" else audit(args.run)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    raise SystemExit(0 if result.get("passed",result.get("status") == "complete") else 1)
