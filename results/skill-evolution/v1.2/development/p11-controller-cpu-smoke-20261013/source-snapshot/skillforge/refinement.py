"""At most two deterministic repairs to the existing finite domain contract."""
import json
from pathlib import Path

from .dataset import digest
from .learning import validate_skill
from .skills import compile_skill


def validate_and_refine(candidate, training, validation_tasks, max_refinements=2, output_dir=None):
    if type(max_refinements) is not int or not 0 <= max_refinements <= 2:
        raise ValueError("max_refinements must be an integer from 0 to 2")
    if not validation_tasks or any(t.split != "validation" for t in validation_tasks):
        raise ValueError("refinement accepts validation feedback only")
    if not training or any(t.get("split") != "train" for t in training):
        raise ValueError("refinement compilation evidence must be train only")
    original_id = candidate.skill_id
    current = candidate.model_copy(deep=True)
    current.statistics.pop("validation", None)
    history, repairs, stop_reason = [], [], "verified"
    canonical = None
    root = Path(output_dir) if output_dir is not None else None
    if root:
        if root.exists() and any(root.iterdir()):
            raise ValueError("refinement output must be a new/empty directory")
        root.mkdir(parents=True, exist_ok=True)
    for attempt in range(max_refinements + 1):
        current.status = "VALIDATING"
        input_hash = digest(current.model_dump())
        report = validate_skill(current, validation_tasks)
        record = {"attempt": attempt, "version": current.version, "input_hash": input_hash,
            "contract": current.model_dump(), "validation": report, "changes": list(repairs),
            "source_hash": digest(training), "feedback_task_ids": [r["task_id"] for r in report["cases"] if not r["correct"]]}
        history.append(record)
        if root:
            (root / f"attempt-{attempt}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        if current.status == "VERIFIED":
            break
        if attempt == max_refinements:
            stop_reason = "refinement_budget_exhausted"
            break
        if canonical is None:
            canonical = compile_skill(training, candidate.family)
        # Validation determines the failing section; only train+policy defines repair.
        boundary_failure = any(not r["correct"] and (not r["positive"] or r["gate_status"] != "APPLICABLE") for r in report["cases"])
        sections = ["preconditions", "forbidden_conditions"] if boundary_failure else ["inputs", "procedure", "postconditions"]
        repairs = [field for field in sections if getattr(current, field) != getattr(canonical, field)]
        if not repairs:
            stop_reason = "no_supported_repair"
            break
        current = current.model_copy(deep=True)
        for field in repairs:
            setattr(current, field, getattr(canonical.model_copy(deep=True), field))
        current.source_trajectory_ids = list(canonical.source_trajectory_ids)
        current.version += 1
        current.status = "CANDIDATE"
        current.statistics.pop("validation", None)
    if current.status != "VERIFIED":
        current.status = "REJECTED"
    assert current.skill_id == original_id
    result = {"skill_id": original_id, "status": current.status, "stop_reason": stop_reason,
        "refinements": len(history) - 1, "validation_runs": len(history), "history": history,
        "final_contract": current.model_dump(),
        "scope": "finite-domain canonical repair using train evidence; validation selects repair section, test never participates"}
    if root:
        (root / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return current, result
