"""Replay admission counters from exact per-case validation evidence."""
from .evolution_schemas import fingerprint

COUNTERS = ("positive_cases", "negative_cases", "actual_violations", "false_allow", "false_block",
            "baseline_false_block", "normal_failures", "baseline_normal_failures", "stable_cases", "stable_regressions")


def counters(cases):
    totals = {key: 0 for key in COUNTERS}
    ids = set()
    for row in cases:
        if row["task_id"] in ids:
            raise ValueError("duplicate validation case")
        ids.add(row["task_id"])
        if row["split"] not in {"validation", "stable_validation"}:
            raise ValueError("nonvalidation case in admission")
        for key in ("truth", "prediction", "baseline_prediction", "procedure_success"):
            if type(row.get(key)) is not bool:
                raise ValueError("unknown/missing validation evidence")
        if type(row["actual_violations"]) is not int or row["actual_violations"] < 0:
            raise ValueError("invalid actual violation counter")
        truth, predicted, baseline = row["truth"], row["prediction"], row["baseline_prediction"]
        totals["actual_violations"] += row["actual_violations"]
        if row["split"] == "validation":
            totals["positive_cases" if truth else "negative_cases"] += 1
            totals["false_allow"] += int(predicted and not truth)
            totals["false_block"] += int(truth and not predicted)
            totals["baseline_false_block"] += int(truth and not baseline)
            totals["normal_failures"] += int(truth and (not predicted or not row["procedure_success"]))
            totals["baseline_normal_failures"] += int(truth and (not baseline or not row["procedure_success"]))
        else:
            totals["stable_cases"] += 1
            totals["stable_regressions"] += int(baseline == truth and predicted != truth)
    return totals


def audit_admission(candidate, report):
    identity = candidate.get("admission_identity")
    if not identity:
        return  # Legacy development-only receipt; formal runner requires identity.
    if report.get("admission_identity") != identity:
        raise ValueError("validation dataset/evaluator identity mismatch")
    parent = candidate.get("parent_identity")
    if not parent or parent.get("contract_hash") != candidate["parent_hash"]:
        raise ValueError("unbound parent contract")
    cases = report.get("cases", [])
    members = identity["validation_members"]
    if {r["task_id"] for r in cases} != set(members):
        raise ValueError("validation case coverage mismatch")
    for row in cases:
        if {"hash": row["task_hash"], "split": row["split"]} != members[row["task_id"]]:
            raise ValueError("validation case member mismatch")
        if len(row.get("probe_hash", "")) != 64:
            raise ValueError("missing probe binding")
    if fingerprint(cases) != report.get("cases_hash"):
        raise ValueError("validation evidence hash mismatch")
    expected = counters(cases)
    if any(report.get(k) != value for k, value in expected.items()):
        raise ValueError("validation aggregate contradicts per-case evidence")
