"""Same-context/state action interventions with real-model continuation."""
import argparse
import copy
from pathlib import Path
import time

from scripts.coordinator_io import atomic_json
from scripts.evaluate_fresh_holdout import audit as audit_reference, inputs
from scripts.evaluate_reuse_ablation import create_client, read, validate_record
from skillforge.dataset import digest, task_hash
from skillforge.environment import Environment
from skillforge.evaluation_checkpoints import read_checkpoint, save_checkpoint
from skillforge.jobs import JobStore, Worker
from skillforge.policies import READS
from skillforge.runtime import Runtime
from skillforge.schemas import Action
from skillforge.training_data import file_hash

PRIMITIVES = {"modify_address": "update_shipping_address", "cancel_order": "cancel_order", "refund": "issue_refund"}


def fork_snapshot(env, context):
    return {"context": copy.deepcopy(context), "state": env.snapshot(),
            "database_sql": list(env.db.iterdump()), "remaining_faults": copy.deepcopy(env.faults), "prefix_tool_calls": len(env.audit)}


def select_cases(records, max_steps):
    cases, exclusions = [], []
    for record in sorted(records, key=lambda r: r["task_id"]):
        for step in record["steps"]:
            action = step.get("action") or {}
            if action.get("type") != "skill":
                continue
            index = step["step_id"]
            case = {"case_id": record["task_id"] + "-step-" + str(index), "task_id": record["task_id"],
                    "step_id": index, "family": record["task_family"], "skill_action": action}
            reason = None
            if record["task_family"] not in PRIMITIVES:
                reason = "unsupported_primitive_mapping"
            elif index >= max_steps - 1:
                reason = "no_continuation_budget"
            elif any((s.get("action") or {}).get("type") != "tool" or (s.get("action") or {}).get("name") not in READS for s in record["steps"][:index]):
                reason = "prefix_not_read_only"
            elif action["name"] not in {s["skill_id"] for s in step["context"]["executable_skills"]}:
                reason = "skill_not_offered_at_fork"
            if reason:
                exclusions.append({**case, "reason": reason})
            else:
                case["primitive_action"] = Action(type="tool", name=PRIMITIVES[record["task_family"]], arguments=action["arguments"]).model_dump()
                cases.append(case)
    return cases, exclusions


class ForkClient:
    def __init__(self, base, env, source, case, arm, expected_fork=None):
        self.base, self.env, self.source, self.case = base, env, source, case
        self.arm, self.expected_fork = arm, expected_fork
        self.model = base.model if base is not None else "scripted-engineering-only"
        self.settings = base.settings if base is not None else {}
        self.index, self.actual_calls = 0, 0
        self.actual_inputs, self.fork = [], None
        self.replay_error = None

    @property
    def tokens(self):
        return self.base.tokens if self.base is not None else 0

    @property
    def fatal_error(self):
        return self.replay_error or (self.base.fatal_error if self.base is not None else None)

    def decide(self, context):
        index = self.index
        self.index += 1
        if index <= self.case["step_id"]:
            if context != self.source["steps"][index]["context"]:
                self.replay_error = "replayed source context differs"
                raise ValueError(self.replay_error)
            if index < self.case["step_id"]:
                return Action.model_validate(self.source["steps"][index]["action"])
            self.fork = fork_snapshot(self.env, context)
            if self.expected_fork is not None and self.fork != self.expected_fork:
                self.replay_error = "fork database/context/fault state differs"
                raise ValueError(self.replay_error)
            if self.arm == "capture":
                return Action(type="stop")  # discarded CPU preflight, never a scored model run
            return Action.model_validate(self.case[self.arm + "_action"])
        self.actual_calls += 1
        self.actual_inputs.append(copy.deepcopy(context))
        return self.base.decide(context)


def capture(task, source, case, skills):
    env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
    try:
        model = ForkClient(None, env, source, case, "capture")
        Runtime(model, skills=skills).run(task, env)
        if model.fatal_error or model.fork is None:
            raise ValueError(model.fatal_error or "fork was not reached")
        return model.fork
    finally:
        env.close()


def prepared(plan_path):
    plan = read(plan_path)
    reference = audit_reference(plan["reference"], plan["training_config"], plan["dataset"])
    _, _, _, tasks, _, skills = inputs(plan["training_config"], plan["dataset"])
    source_identity = read(Path(plan["reference"]) / "identity.json")
    sources = {t.task_id: read_checkpoint(Path(plan["reference"]) / "tasks" / (t.task_id + ".json"), source_identity, t.task_id, task_hash(t)) for t in tasks}
    for task in tasks:
        validate_record(sources[task.task_id], task, reference["model_settings"])
    cases, exclusions = select_cases(list(sources.values()), reference["runtime_config"]["max_steps"])
    identity = {"plan_sha256": file_hash(plan_path), "evaluator_sha256": file_hash(__file__),
        "client_auditor_sha256": file_hash(Path(__file__).with_name("evaluate_reuse_ablation.py")),
        "reference_identity": source_identity, "reference_sha256": file_hash(Path(plan["reference"]) / "evaluation.json"),
        "profile_sha256": file_hash(plan["client_profile"]), "model_settings": reference["model_settings"],
        "cases": cases, "exclusions": exclusions, "scope": plan["scope"]}
    return plan, identity, {t.task_id: t for t in tasks}, skills, sources


def validate_branch(row, task, case, arm, identity, source, expected_fork):
    if row["model_settings"].get("server_identity") != identity["model_settings"]:
        raise ValueError("counterfactual model identity mismatch")
    validate_record({**row, "model_settings": identity["model_settings"]}, task, identity["model_settings"])
    cf = row["counterfactual"]
    if cf["case_id"] != case["case_id"] or cf["arm"] != arm or cf["fork"] != expected_fork:
        raise ValueError("counterfactual fork evidence mismatch")
    index = case["step_id"]
    if len(row["steps"]) <= index + 1:
        raise ValueError("no real-model continuation")
    for i in range(index + 1):
        if row["steps"][i]["context"] != source["steps"][i]["context"]:
            raise ValueError("source prefix context mismatch")
        expected = source["steps"][i]["action"] if i < index else case[arm + "_action"]
        if row["steps"][i]["action"] != expected:
            raise ValueError("forced or replayed action mismatch")
    sent = [s["context"] for s in row["steps"][index + 1:]]
    if cf["actual_model_inputs"] != sent or row["metrics"]["llm_calls"] != len(sent):
        raise ValueError("real continuation input/call accounting mismatch")
    if cf["replayed_decisions"] != index or cf["forced_decisions"] != 1 or row["metrics"]["decision_calls"] != len(row["steps"]):
        raise ValueError("replay/forced decision accounting mismatch")


def summarize_pairs(pairs):
    cases = []
    for pair in pairs:
        skill, primitive = pair["skill"], pair["primitive"]
        if skill["counterfactual"]["fork"] != primitive["counterfactual"]["fork"]:
            raise ValueError("paired contexts/database/fault queues differ")
        passed_s = skill["verification"]["task_success"]
        passed_p = primitive["verification"]["task_success"]
        cases.append({"case_id": skill["counterfactual"]["case_id"], "family": skill["task_family"],
            "skill_passed": passed_s, "primitive_passed": passed_p,
            "skill_helped": passed_s and not passed_p, "skill_harmed": passed_p and not passed_s,
            "skill_continuation_llm_calls": skill["metrics"]["llm_calls"], "primitive_continuation_llm_calls": primitive["metrics"]["llm_calls"]})
    n, denominator = len(cases), sum(c["primitive_passed"] for c in cases)
    harm = sum(c["skill_harmed"] for c in cases)
    return {"contexts": n, "skill_successes": sum(c["skill_passed"] for c in cases), "primitive_successes": denominator,
        "helped": sum(c["skill_helped"] for c in cases), "harmed": harm,
        "harm_rate_over_observed_contexts": harm / n if n else None,
        "observed_reuse_counterfactual_ntr": harm / denominator if denominator else None,
        "ntr_denominator": "primitive-success contexts among eligible observed Skill uses",
        "population_causal_ntr": None, "cases": cases}


def update_progress(root, **value):
    value["at"] = time.time()
    atomic_json(root / "progress.json", value)
    import json
    Path("docs/ACTION_COUNTERFACTUAL_LIVE.md").write_text("# 动作级反事实实时进度\n\n" + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")


def run(plan_path, resume=False, audit_only=False):
    plan, identity, tasks, skills, sources = prepared(plan_path)
    root = Path(plan["output"])
    if root.exists() and not (resume or audit_only):
        raise ValueError("output exists; explicit resume required")
    if audit_only and (not (root / "evaluation.json").exists() or not (root / "identity.json").exists()):
        raise ValueError("completed evaluation required for audit")
    root.mkdir(parents=True, exist_ok=True)
    if (root / "identity.json").exists() and read(root / "identity.json") != identity:
        raise ValueError("counterfactual identity changed")
    if not audit_only:
        atomic_json(root / "identity.json", identity)
    expected_names = {c["case_id"] + "-" + a for c in identity["cases"] for a in ("skill", "primitive")}
    (root / "branches").mkdir(exist_ok=True)
    existing = {p.stem for p in (root / "branches").glob("*.json")}
    if existing - expected_names or (audit_only and existing != expected_names):
        raise ValueError("counterfactual branch coverage mismatch")
    rows, forks = {}, {}
    # All reference contexts and reusable evidence are audited before any GPU call.
    for case in identity["cases"]:
        tid, cid = case["task_id"], case["case_id"]
        forks[cid] = capture(tasks[tid], sources[tid], case, skills)
        for arm in ("skill", "primitive"):
            name = cid + "-" + arm
            if name in existing:
                row = read_checkpoint(root / "branches" / (name + ".json"), {**identity, "case_id": cid, "arm": arm}, tid, task_hash(tasks[tid]))
                validate_branch(row, tasks[tid], case, arm, identity, sources[tid], forks[cid])
                rows[name] = row
    base = None
    pairs = []
    for i, case in enumerate(identity["cases"]):
        tid, cid = case["task_id"], case["case_id"]
        # Alternate arm order to avoid a constant first-arm serving order.
        for arm in (("skill", "primitive") if i % 2 == 0 else ("primitive", "skill")):
            name = cid + "-" + arm
            if name not in rows:
                if audit_only:
                    raise ValueError("missing audited branch")
                if base is None:
                    base = create_client(plan["client_profile"], identity["model_settings"])
                task = tasks[tid]
                env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
                model = ForkClient(base, env, sources[tid], case, arm, forks[cid])
                try:
                    row = Runtime(model, skills=skills).run(task, env)
                finally:
                    env.close()
                if model.fatal_error or model.fork is None:
                    atomic_json(root / "infrastructure_failure.json", {"error": model.fatal_error, "partial": row})
                    raise RuntimeError("counterfactual replay or infrastructure failure; partial unscored")
                row["metrics"]["llm_calls"] = model.actual_calls
                row["counterfactual"] = {"case_id": cid, "arm": arm, "fork": model.fork,
                    "replayed_decisions": case["step_id"], "forced_decisions": 1, "actual_model_inputs": model.actual_inputs}
                validate_branch(row, task, case, arm, identity, sources[tid], forks[cid])
                rows[name] = save_checkpoint(root / "branches" / (name + ".json"), row, {**identity, "case_id": cid, "arm": arm})
            if not audit_only:
                update_progress(root, stage="running", completed=len(rows), total=len(expected_names))
        pairs.append({arm: rows[cid + "-" + arm] for arm in ("skill", "primitive")})
    report = {"identity": identity, "paired": summarize_pairs(pairs)}
    if (root / "evaluation.json").exists() and read(root / "evaluation.json") != report:
        raise ValueError("counterfactual summary differs from checkpoints")
    if not audit_only:
        atomic_json(root / "evaluation.json", report)
        update_progress(root, stage="completed", completed=len(rows), total=len(expected_names))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="configs/action-counterfactual.json")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    if args.audit_only:
        result = run(args.plan, audit_only=True)
    else:
        lock = Worker(JobStore(".runtime/action-counterfactual-lock"), lambda *_: None)
        lock.start()
        try:
            result = run(args.plan, args.resume)
        except Exception as exc:
            update_progress(Path(read(args.plan)["output"]), stage="failed", error=type(exc).__name__, message=str(exc))
            raise
        finally:
            lock.close()
    print({k: v for k, v in result["paired"].items() if k != "cases"})
