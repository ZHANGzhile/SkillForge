"""Explicit deterministic teacher supervision and executed counterfactual evidence.

Teacher rows are never counted as LLM trajectories. Skills remain bound to the
real train-success/train-failure/policy corpus in the original frozen bundle.
"""
import copy
import json
from pathlib import Path

from .dataset import digest, load_dataset, task_hash
from .environment import Environment, ToolError
from .experiment import load_bundle
from .learning import build_sft, make_preference
from .model import ScriptedPolicy
from .prompts import PROMPTS
from .provenance import audit_sources
from .runtime import POLICY_TEXT, Runtime
from .schemas import Action
from .skills import execute
from .tool_schemas import tool_definitions
from .verifier import verify


def write_jsonl(path, rows):
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode()
    Path(path).write_bytes(content)
    import hashlib
    return hashlib.sha256(content).hexdigest()


def messages(context, action=None):
    result = [{"role": "system", "content": PROMPTS["v2"]},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)}]
    if action is not None:
        result.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
    return result


def branch(task, skill, source_env, observations, context, action, snapshot_id):
    env = Environment()
    source_env.db.backup(env.db)
    env.order_id = source_env.order_id
    env.audit = copy.deepcopy(source_env.audit)
    state = copy.deepcopy(observations)
    initial = source_env.snapshot()
    if digest(list(env.db.iterdump())) != snapshot_id:
        env.close()
        raise ValueError("counterfactual database snapshot mismatch")
    event, error = None, None
    try:
        def call(name, args, key):
            return env.call(name, args, task.customer_id, key)
        if action.type == "skill":
            event = execute(skill, action.arguments, state, call, "counterfactual:" + snapshot_id)
            outcome = "completed" if event["success"] else "error"
        elif action.type == "escalate":
            call("escalate_to_human", {"order_id": task.parameters["order_id"], **action.arguments}, "counterfactual:escalation:" + snapshot_id)
            outcome = "escalated"
        elif action.type == "refuse":
            outcome = "refused"
        else:
            raise ValueError("unsupported counterfactual action")
    except ToolError as exc:
        error, outcome = exc.code, "error"
    try:
        final = env.snapshot()
        verdict = verify(task, initial, final, env.audit, outcome)
        evidence = {"task_id": task.task_id, "task_hash": task_hash(task), "split": "train",
            "snapshot_id": snapshot_id, "prompt": copy.deepcopy(context), "action": action.model_dump(),
            "initial_state": initial, "final_state": final, "tool_audit": copy.deepcopy(env.audit),
            "skill_event": event, "outcome": outcome, "verification": verdict, "error": error,
            "verified_correct": verdict["task_success"] and not verdict["attempted_policy_violation"] and not verdict["actual_policy_violation"],
            "supervision_origin": "executed_contract_counterfactual", "llm_calls": 0}
        evidence["evidence_id"] = digest(evidence)
        return evidence
    finally:
        env.close()


def counterfactuals(task, skill):
    if task.split != "train":
        raise ValueError("counterfactual learning accepts train only")
    if task.fixture.get("faults"):
        return [], "fault_sequence_requires_runtime_supervision"
    env = Environment(fixture=task.fixture)
    observations = {}
    try:
        reads = ["get_order", "get_payment" if task.family == "refund" else "get_shipment", "get_customer"]
        if task.family == "modify_address":
            reads.append("validate_address")
        for name in reads:
            args = {"order_id": task.parameters["order_id"]}
            if name == "validate_address":
                args["new_address"] = task.parameters["new_address"]
            observations.update(env.call(name, args, task.customer_id))
        context = {"request": task.request, "family": task.family, "parameters": task.parameters,
            "observations": observations, "history": [], "policy": POLICY_TEXT, "workflow": task.workflow,
            "available_tools": tool_definitions(), "executable_skills": [skill.model_dump(exclude={"statistics", "source_trajectory_ids"})],
            "retrieved_memory": [],
            "evaluation_instruction": "This is a fixed-candidate decision probe. Choose the listed skill, refuse, or escalate. Candidate presence does not imply eligibility."}
        snapshot_id = digest(list(env.db.iterdump()))
        actions = [Action(type="skill", name=skill.skill_id, arguments=task.parameters),
            Action(type="refuse"), Action(type="escalate", arguments={"reason": "policy boundary"})]
        return [branch(task, skill, env, observations, context, action, snapshot_id) for action in actions], None
    except ToolError as exc:
        return [], exc.code
    finally:
        env.close()


def prepare_supervision(dataset, bundle_path, output):
    manifest, tasks = load_dataset(dataset)
    bundle, skills = load_bundle(bundle_path, manifest["dataset_hash"])
    if bundle["engineering_only"]:
        raise ValueError("supervision requires contracts compiled from real model train evidence")
    audit_sources(bundle["memory"], tasks, allow_engineering=False)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    runtime_records, sft, preferences, evidence, skipped = [], [], [], [], []
    for task in [t for t in tasks if t.split == "train"]:
        env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
        try:
            result = Runtime(ScriptedPolicy(), skills=skills).run(task, env)
            result["supervision_origin"] = "deterministic_contract_teacher"
            runtime_records.append(result)
        finally:
            env.close()
        for row in build_sft([result]):
            sft.append({"messages": messages(row["prompt"], row["target"]), "split": "train",
                "action_type": row["target"]["type"], "source_trajectory_id": result["trajectory_id"],
                "source_step_id": row["source_step_id"], "task_id": task.task_id, "task_hash": task_hash(task),
                "supervision_origin": "deterministic_contract_teacher", "protocol": "free_action_runtime", "llm_calls": 0})
        skill = next((s for s in skills if s.family == task.family), None)
        if skill is None:
            continue
        branches, reason = counterfactuals(task, skill)
        evidence.extend(branches)
        positives = [b for b in branches if b["verified_correct"]]
        if len(positives) != 1:
            skipped.append({"task_id": task.task_id, "reason": reason or "not_exactly_one_verified_positive"})
            continue
        chosen = positives[0]
        sft.append({"messages": messages(chosen["prompt"], chosen["action"]), "split": "train",
            "action_type": chosen["action"]["type"], "task_id": task.task_id, "task_hash": task_hash(task),
            "evidence_id": chosen["evidence_id"], "supervision_origin": "executed_contract_counterfactual",
            "protocol": "free_action_fixed_candidate", "llm_calls": 0})
        for rejected in [b for b in branches if not b["verified_correct"]]:
            pair = make_preference(chosen, rejected)
            pair.update({"task_id": task.task_id, "task_hash": task_hash(task),
                "messages": messages(pair["prompt"]), "supervision_origin": "executed_contract_counterfactual",
                "protocol": "free_action_fixed_candidate", "llm_calls": 0})
            preferences.append(pair)
    from collections import Counter
    report = {"format": "skillforge-supervision-v1", "dataset_hash": manifest["dataset_hash"],
        "bundle_hash": bundle["bundle_hash"], "skill_source_audit": bundle["source_audit"],
        "teacher": "deterministic_contract_teacher", "teacher_llm_calls": 0,
        "runtime_trajectories": len(runtime_records), "runtime_passed": sum(r["verification"]["task_success"] for r in runtime_records),
        "sft_examples": len(sft), "sft_action_counts": dict(Counter(r["action_type"] for r in sft)),
        "dpo_pairs": len(preferences), "counterfactual_branches": len(evidence), "skipped": skipped,
        "files": {"runtime.jsonl": write_jsonl(root / "runtime.jsonl", runtime_records),
            "sft.jsonl": write_jsonl(root / "sft.jsonl", sft), "dpo.jsonl": write_jsonl(root / "dpo.jsonl", preferences),
            "counterfactuals.jsonl": write_jsonl(root / "counterfactuals.jsonl", evidence)},
        "scope": "explicit deterministic supervision for post-training, not real LLM baseline performance",
        "limitations": ["synthetic bounded domain", "candidate preferences cover immediate skill/refusal/escalation decisions", "faults excluded from counterfactual pairs but retained in runtime supervision"]}
    (root / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
