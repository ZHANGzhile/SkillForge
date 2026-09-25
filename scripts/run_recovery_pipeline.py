"""Isolated main-v3 candidate: train-only curriculum, then full validation.

Uses the existing GPU ownership lock and checkpoint audits. main-v2 plan,
weights, evaluations and execution source are kept immutable.
"""
import json
from pathlib import Path
import time

from scripts import run_training_pipeline as pipeline
from scripts.audit_validation import audit
from scripts.coordinator_io import atomic_json
from skillforge.jobs import JobStore, Worker


def main():
    plan_path = Path("configs/recovery-runs.json")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    pipeline.PLAN = plan
    pipeline.TRAIN = Path(plan["root"])
    pipeline.EVAL = Path(plan["evaluation_root"])
    marker = Path(".runtime/recovery-pipeline.json")
    guard = Worker(JobStore(".runtime/training-pipeline-lock"), lambda *_: None)
    guard.start()
    try:
        atomic_json(marker, {"stage": "training_and_validation", "at": time.time(), "plan": str(plan_path)})
        pipeline.training("sft", smoke=True)
        pipeline.training("sft")
        pipeline.evaluation("SFT", "validation")
        report = audit(pipeline.EVAL / "SFT-validation", plan["config"], plan["validation_loss_data"])
        reference = audit(Path(plan["reference_evaluation"]), plan["reference_config"], plan["validation_loss_data"])
        eligible = (report["full_system"]["actual_policy_violation_rate"] == 0
            and report["full_system"]["task_success_rate"] >= reference["full_system"]["task_success_rate"])
        result = {"stage": "validation_completed", "at": time.time(), "plan": str(plan_path),
            "eligible_for_product_acceptance": eligible, "candidate": report["full_system"],
            "reference": reference["full_system"], "rule": "Zero actual violations and validation EOC at least the deployed main-v2 DPO; never select by test.",
            "next": "Fresh-instance frozen evaluation and unchanged real HTTP acceptance; not yet deployed."}
        atomic_json(marker, result)
        pipeline.status("completed", training_root=str(pipeline.TRAIN), evaluation_root=str(pipeline.EVAL),
            recovery_candidate=True, deployment_pending=True)
    except BaseException as exc:
        atomic_json(marker, {"stage": "failed", "at": time.time(), "error": type(exc).__name__, "message": str(exc)})
        pipeline.status("failed", error=type(exc).__name__, message=str(exc))
        raise
    finally:
        guard.close()


if __name__ == "__main__":
    main()
