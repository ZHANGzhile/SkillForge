"""Audited paired B0/B3 ablation through the existing, identity-pinned Student.

No new GPU process and no model changes. HTTP uses the same HF client/settings
as the archived direct-HF reference. Latency includes transport overhead.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import time

import httpx

from scripts.coordinator_io import atomic_json
from scripts.evaluate_fresh_holdout import audit as audit_reference, inputs
from skillforge.benchmark import summarize
from skillforge.dataset import digest, task_hash
from skillforge.environment import Environment
from skillforge.evaluation_checkpoints import read_checkpoint, save_checkpoint
from skillforge.jobs import JobStore, Worker
from skillforge.model import ModelClient
from skillforge.runtime import Runtime
from skillforge.training_data import file_hash
from skillforge.verifier import verify


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class PinnedClient(ModelClient):
    fatal_error = None

    def decide(self, context):
        try:
            return super().decide(context)
        except httpx.HTTPError as exc:
            # A generated invalid Action is a model failure; resource/transport
            # failures stop the experiment instead of polluting its denominator.
            generated_invalid_action = False
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 502:
                try:
                    generated_invalid_action = exc.response.json().get("detail", {}).get("error") == "ValidationError"
                except (ValueError, AttributeError):
                    pass
            if not generated_invalid_action:
                self.fatal_error = type(exc).__name__ + ": " + str(exc)[:500]
            raise
        except ValueError as exc:
            if "private Student changed" in str(exc):
                self.fatal_error = str(exc)
            raise


def create_client(profile_path, expected):
    profile = read(profile_path)
    if not profile.get("require_server_identity") or profile.get("adapter") != "openai":
        raise ValueError("ablation requires the identity-pinned HF service")
    old = os.environ.get("SKILLFORGE_MODEL_CONFIG")
    os.environ["SKILLFORGE_MODEL_CONFIG"] = str(profile_path)
    try:
        model = PinnedClient(url=profile["url"], model=profile["model"])
    finally:
        if old is None:
            os.environ.pop("SKILLFORGE_MODEL_CONFIG", None)
        else:
            os.environ["SKILLFORGE_MODEL_CONFIG"] = old
    model.pin_identity()
    if model.settings["server_identity"] != expected or model.system_prompt != expected["system_prompt"]:
        raise ValueError("served model/settings differ from frozen B3 reference")
    return model


def prepared(plan_path):
    plan = read(plan_path)
    reference = audit_reference(plan["reference"], plan["training_config"], plan["dataset"])
    _, _, _, tasks, _, _ = inputs(plan["training_config"], plan["dataset"])
    parent = read(Path(plan["reference"]) / "identity.json")
    identity = {"variant": "B0", "plan_sha256": file_hash(plan_path), "reference_identity_hash": digest(parent),
        "reference_report_sha256": file_hash(Path(plan["reference"]) / "evaluation.json"),
        "model_settings": reference["model_settings"], "runtime_config": reference["runtime_config"],
        "profile_sha256": file_hash(plan["client_profile"]), "evaluator_sha256": file_hash(__file__),
        "task_hashes": {t.task_id: task_hash(t) for t in tasks}, "scope": plan["scope"]}
    rows = {t.task_id: read_checkpoint(Path(plan["reference"]) / "tasks" / (t.task_id + ".json"), parent, t.task_id, task_hash(t)) for t in tasks}
    return plan, identity, tasks, rows


def validate_record(record, task, settings, b0=False):
    env = Environment(fixture=task.fixture)
    try:
        state = env.snapshot(task.parameters["order_id"])
    finally:
        env.close()
    if record["task_hash"] != task_hash(task) or record["initial_state"] != state:
        raise ValueError("ablation task/initial state mismatch")
    for event in record["tool_audit"]:
        after = event["after_state"]
        delta = {k: {"before": state.get(k), "after": v} for k, v in after.items() if state.get(k) != v}
        if event["before_state"] != state or event["state_diff"] != delta:
            raise ValueError("ablation tool audit state chain mismatch")
        state = after
    if state != record["final_state"] or verify(task, record["initial_state"], state, record["tool_audit"], record["outcome"]) != record["verification"]:
        raise ValueError("ablation verdict/final state mismatch")
    actual_settings = record["model_settings"].get("server_identity") if b0 else record["model_settings"]
    if actual_settings != settings or record["metrics"]["llm_calls"] <= 0:
        raise ValueError("ablation did not use the frozen real model")
    if b0 and (record["skill_events"] or record["metrics"]["gate_tool_calls"]
               or any(s.get("context", {}).get("executable_skills") or s.get("context", {}).get("retrieved_memory") for s in record["steps"])):
        raise ValueError("B0 contains Skill/Gate/memory evidence")


def failure_kind(record):
    if record["verification"]["task_success"]:
        return None
    if record["outcome"] == "refused":
        if record["task_family"] == "composite":
            return "terminal_refusal_in_fallback_workflow"
        if record["initial_state"].get("customer.risk_level") == "HIGH":
            return "refusal_under_high_risk_policy"
    if record["outcome"] == "max_steps_exceeded":
        reads = [e for e in record["tool_audit"] if e["tool_name"].startswith("get_")]
        if reads and not any(e["state_diff"] for e in record["tool_audit"]):
            return "read_loop_without_state_change"
    return "other_contract_failure"


def paired_summary(b0, b3):
    if not b0 or set(b0) != set(b3):
        raise ValueError("paired ablation requires identical complete task coverage")
    cases = []
    for tid in sorted(b0):
        left, right = b0[tid], b3[tid]
        if left["task_hash"] != right["task_hash"] or left["initial_state"] != right["initial_state"]:
            raise ValueError("paired task/state mismatch")
        passed0, passed3 = left["verification"]["task_success"], right["verification"]["task_success"]
        cases.append({"task_id": tid, "family": right["task_family"], "b0_passed": passed0, "b3_passed": passed3,
            "b3_helped": not passed0 and passed3, "b3_harmed": passed0 and not passed3,
            "b3_skill_attempts": right["metrics"]["skill_calls"], "b0_failure_kind": failure_kind(left), "b3_failure_kind": failure_kind(right)})
    n = len(cases)
    harmed = sum(c["b3_harmed"] for c in cases)
    passed0 = sum(c["b0_passed"] for c in cases)
    return {"tasks": n, "B0": summarize(list(b0.values())), "B3": summarize(list(b3.values())),
        "paired_improvements": sum(c["b3_helped"] for c in cases), "paired_regressions": harmed,
        "skill_enabled_system_regression_rate": harmed / n,
        "regression_given_b0_success": harmed / passed0 if passed0 else None,
        "regressions_with_observed_skill_attempt": sum(c["b3_harmed"] and c["b3_skill_attempts"] > 0 for c in cases),
        "same_context_causal_ntr": None,
        "interpretation": "Whole-system Skill availability intervention also removes Gate hydration and changes later contexts. Paired regressions are not proof a particular Skill caused failure; direct-HF reference vs HTTP transport also precludes strict latency attribution.",
        "b3_failure_counts": dict(Counter(c["b3_failure_kind"] for c in cases if c["b3_failure_kind"])), "cases": cases}


def audit(plan_path):
    plan, identity, tasks, b3 = prepared(plan_path)
    root = Path(plan["output"])
    if read(root / "identity.json") != identity:
        raise ValueError("ablation identity changed")
    if {p.stem for p in (root / "tasks").glob("*.json")} != set(identity["task_hashes"]):
        raise ValueError("ablation task coverage mismatch")
    b0 = {}
    for task in tasks:
        b0[task.task_id] = read_checkpoint(root / "tasks" / (task.task_id + ".json"), identity, task.task_id, task_hash(task))
        validate_record(b0[task.task_id], task, identity["model_settings"], b0=True)
        validate_record(b3[task.task_id], task, identity["model_settings"])
    result = {"identity": identity, "full_system": paired_summary(b0, b3)["B0"], "paired": paired_summary(b0, b3)}
    if read(root / "evaluation.json") != result:
        raise ValueError("ablation summary differs from audited checkpoints")
    return result


def evaluate(plan_path, resume=False):
    plan, identity, tasks, b3 = prepared(plan_path)
    root = Path(plan["output"])
    if root.exists() and not resume:
        raise ValueError("ablation output exists; explicit --resume required")
    root.mkdir(parents=True, exist_ok=True)
    if (root / "identity.json").exists() and read(root / "identity.json") != identity:
        raise ValueError("ablation identity changed")
    atomic_json(root / "identity.json", identity)
    (root / "tasks").mkdir(exist_ok=True)
    b0 = {}
    for task in tasks:
        validate_record(b3[task.task_id], task, identity["model_settings"])
        path = root / "tasks" / (task.task_id + ".json")
        if path.exists():
            b0[task.task_id] = read_checkpoint(path, identity, task.task_id, task_hash(task))
            validate_record(b0[task.task_id], task, identity["model_settings"], b0=True)
    model = None
    for task in tasks:
        if task.task_id not in b0:
            if model is None:
                model = create_client(plan["client_profile"], identity["model_settings"])
            env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
            try:
                row = Runtime(model, skills=[], memory=[]).run(task, env)
            finally:
                env.close()
            if model.fatal_error:
                atomic_json(root / "infrastructure_failure.json", {"error": model.fatal_error, "partial": row})
                raise RuntimeError("ablation infrastructure failed; partial is not a scored task")
            validate_record(row, task, identity["model_settings"], b0=True)
            b0[task.task_id] = save_checkpoint(root / "tasks" / (task.task_id + ".json"), row, identity)
        update_progress(root, {"stage": "running", "completed": len(b0), "total": len(tasks), "at": time.time()})
    paired = paired_summary(b0, b3)
    atomic_json(root / "evaluation.json", {"identity": identity, "full_system": paired["B0"], "paired": paired})
    result = audit(plan_path)
    update_progress(root, {"stage": "completed", "completed": len(tasks), "total": len(tasks), "at": time.time()})
    return result


def update_progress(root, value):
    atomic_json(root / "progress.json", value)
    Path("docs").mkdir(exist_ok=True)
    Path("docs/REUSE_ABLATION_LIVE.md").write_bytes((
        "# main-v3 无Skill对照实时进度\n\n" + time.strftime("%Y-%m-%d %H:%M:%S")
        + "\n\n只做固定模型的事后系统消融；不进行训练或重新选择部署模型。完整报告生成前不以部分结果宣称总体收益。\n\n```json\n"
        + json.dumps(value, ensure_ascii=False, indent=2) + "\n```\n").encode("utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="configs/reuse-ablation.json")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    if args.audit_only:
        report = audit(args.plan)
    else:
        lock = Worker(JobStore(".runtime/reuse-ablation-lock"), lambda *_: None)
        lock.start()
        try:
            report = evaluate(args.plan, args.resume)
        except Exception as exc:
            update_progress(Path(read(args.plan)["output"]), {"stage": "failed", "error": type(exc).__name__, "message": str(exc), "at": time.time()})
            raise
        finally:
            lock.close()
    print(json.dumps({k: v for k, v in report["paired"].items() if k != "cases"}, ensure_ascii=True, indent=2))
