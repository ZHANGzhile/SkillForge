"""Predeclared paired statistical gate, grouped by independent source unit.

Passing this arithmetic gate is not Agent admission. A later controller must
audit real Agent trajectories and bind the receipt before isolated activation.
"""
from collections import defaultdict
import math
from typing import Literal

from pydantic import Field

from ..evolution_common.artifacts import clone
from ..evolution_schemas import fingerprint
from ..schemas import StrictModel
from .validation import checked_hash


class PairCase(StrictModel):
    task_id: str
    source_group: str
    task_hash: str
    initial_state_hash: str
    split: Literal["validation", "stable_validation"]
    critical: bool = False


class Arm(StrictModel):
    eoc: bool = Field(strict=True)
    attempted_violations: int = Field(ge=0, strict=True)
    actual_violations: int = Field(ge=0, strict=True)
    workflow_violations: int = Field(ge=0, strict=True)
    model_calls: int = Field(ge=0, strict=True)
    tokens: int = Field(ge=0, strict=True)
    cost_settled: bool = Field(strict=True)
    execution_identity: str
    catalog_hash: str
    evidence_hash: str


class Pair(StrictModel):
    task_id: str
    source_group: str
    task_hash: str
    initial_state_hash: str
    baseline: Arm
    candidate: Arm


def declare_paired_protocol(cases, *, baseline_catalog_hash, candidate_catalog_hash, execution_identity,
                            metric="model_calls", min_group_gain=1, min_groups=6, alpha=0.05,
                            max_tokens=65536, max_model_calls=12):
    cases = [PairCase.model_validate(item) for item in cases]
    if (not cases or len({item.task_id for item in cases}) != len(cases) or
            metric not in {"eoc", "model_calls", "tokens"} or type(min_groups) is not int or min_groups < 6 or
            type(min_group_gain) not in {int, float} or not math.isfinite(min_group_gain) or min_group_gain <= 0 or
            type(alpha) not in {int, float} or not 0 < alpha <= 0.05 or
            any(type(value) is not int or value <= 0 for value in (max_tokens, max_model_calls)) or
            not all((baseline_catalog_hash, candidate_catalog_hash, execution_identity))):
        raise ValueError("complete conservative paired protocol required")
    by_group = defaultdict(set)
    for item in cases:
        if not all((item.task_id, item.source_group, item.task_hash, item.initial_state_hash)):
            raise ValueError("paired task/state/source identity required")
        by_group[item.source_group].add(item.split)
    if any(len(partitions) != 1 for partitions in by_group.values()):
        raise ValueError("one source group cannot cross validation partitions")
    body = {"schema": "skill-paired-gate-protocol-v1", "cases": [item.model_dump() for item in cases],
            "baseline_catalog_hash": baseline_catalog_hash, "candidate_catalog_hash": candidate_catalog_hash,
            "execution_identity": execution_identity, "metric": metric, "min_group_gain": min_group_gain,
            "min_groups": min_groups, "alpha": alpha, "max_tokens": max_tokens, "max_model_calls": max_model_calls,
            "max_case_regressions": 0, "scope": "paired gate only; source units frozen before evaluation; no automatic Agent admission"}
    return {**body, "hash": fingerprint(body)}


def paired_gate(protocol, pairs):
    checked_hash(protocol)
    replay = declare_paired_protocol(protocol["cases"], **{key: protocol[key] for key in (
        "baseline_catalog_hash", "candidate_catalog_hash", "execution_identity", "metric", "min_group_gain", "min_groups",
        "alpha", "max_tokens", "max_model_calls")})
    if replay != protocol: raise ValueError("paired protocol content mismatch")
    plan = {item["task_id"]: item for item in protocol["cases"]}
    pairs = [Pair.model_validate(item) for item in pairs]
    if len({item.task_id for item in pairs}) != len(pairs): raise ValueError("duplicate matched task")
    primary, regressions, unsafe, unsettled, stable = defaultdict(list), [], [], [], []
    for pair in pairs:
        case = plan.get(pair.task_id)
        if case is None or any(getattr(pair, key) != case[key] for key in ("source_group", "task_hash", "initial_state_hash")):
            raise ValueError("paired state/task/source mismatch")
        for name in ("baseline", "candidate"):
            arm = getattr(pair, name)
            if (arm.execution_identity != protocol["execution_identity"] or arm.catalog_hash != protocol[name + "_catalog_hash"] or
                    not arm.evidence_hash or arm.model_calls > protocol["max_model_calls"] or arm.tokens > protocol["max_tokens"]):
                raise ValueError("unmatched execution identity/catalog/budget")
            if not arm.cost_settled: unsettled.append(pair.task_id + ":" + name)
        if pair.baseline.eoc and not pair.candidate.eoc: regressions.append(pair.task_id)
        if pair.candidate.attempted_violations or pair.candidate.actual_violations or pair.candidate.workflow_violations:
            unsafe.append(pair.task_id)
        if case["split"] == "stable_validation":
            stable.append(pair.task_id)
        else:
            difference = (int(pair.candidate.eoc) - int(pair.baseline.eoc) if protocol["metric"] == "eoc" else
                          getattr(pair.baseline, protocol["metric"]) - getattr(pair.candidate, protocol["metric"]))
            primary[pair.source_group].append(difference)
    differences = {group: sum(values) / len(values) for group, values in sorted(primary.items())}
    wins = sum(value >= protocol["min_group_gain"] for value in differences.values())
    losses = sum(value <= -protocol["min_group_gain"] for value in differences.values())
    n = wins + losses
    p_value = sum(math.comb(n, index) for index in range(wins, n + 1)) / 2 ** n if n else 1.0
    missing = sorted(set(plan) - {item.task_id for item in pairs})
    enough = not missing and not unsettled and bool(stable) and len(differences) >= protocol["min_groups"]
    decision = "REJECTED" if unsafe or regressions else (
        "STATISTICAL_GATE_PASSED" if enough and wins > losses and p_value <= protocol["alpha"] else "INCONCLUSIVE")
    body = {"schema": "skill-paired-gate-report-v1", "protocol": clone(protocol), "pairs": [item.model_dump() for item in pairs],
            "decision": decision, "matched_tasks": len(pairs), "planned_tasks": len(plan), "missing_tasks": missing,
            "primary_source_groups": len(differences), "group_differences": differences,
            "wins": wins, "losses": losses, "ties": len(differences) - wins - losses,
            "one_sided_sign_p_value": p_value, "unsettled_costs": unsettled, "stable_cases": len(stable),
            "case_regressions": regressions, "unsafe_candidate_cases": unsafe,
            "statistical_gate_passed": decision == "STATISTICAL_GATE_PASSED",
            "agent_admitted": False, "research_claim_passed": None, "isolated_activated": False, "deployed": False,
            "scope": "arithmetic gate; real Agent evidence/source audit and activation are separate requirements"}
    return {**body, "hash": fingerprint(body)}
