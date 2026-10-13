"""Read-only P7 diagnosis of every frozen v1.1 active/active_v2 pair.

Replays public Bayes evidence and convergence/challenge states without probing,
changing hypotheses, running a model or feeding held-out results to a learner.
Original EIG values are checked for internal order and exact paired equality;
this does not claim a fresh independent recomputation of every archived EIG.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import shutil
import time

from scripts.continue_skill_evolution_selection import publish
from scripts.run_skill_evolution import ROOT, digest_file
from skillforge.active_learning import stopping_reason
from skillforge.belief import BeliefState, entropy
from skillforge.evolution_config import LearningOptions
from skillforge.evolution_schemas import Candidate, EvidenceView, Hypothesis, fingerprint
from skillforge.execution_aware.challenge import ChallengeOptions, challenge_gate


def read(path): return json.loads(Path(path).read_text(encoding="utf-8"))
def hashed(value): return {**value, "hash": fingerprint(value)}


def state_diagnostic(belief, candidates, evidence, options, challenge):
    convergence = belief.convergence(candidates, **options.convergence_args())
    kinds = {item.hypothesis_id: item.kind for item in belief.hypotheses}
    top = convergence["hypothesis_id"]
    eligible = convergence["converged"] and kinds[top] == "no_change"
    gate = challenge_gate(belief, candidates, evidence, challenge)
    h0 = next(index for index, hypothesis in enumerate(belief.hypotheses) if hypothesis.kind == "no_change")
    return {"query_count": len(evidence), "ordinary_convergence": convergence,
        "top_kind": kinds[top], "h0_posterior": belief.posterior[h0], "h0_gate_entry_eligible": eligible,
        "actual_gate": gate if eligible else None,
        "counterfactual_H0_challenge": {key: gate[key] for key in ("status", "passed", "required", "configured_k",
            "distinct_challenges", "completed", "queries_charged", "coverage_shortfall")},
        "counterfactual_remaining_candidates": gate["remaining_candidates"],
        "counterfactual_alternative_count": len(gate["alternative_ids"]),
        "counterfactual_alternative_ids_hash": fingerprint(gate["alternative_ids"]),
        "remaining_budget": options.max_queries-len(evidence),
        "unknown_query_count": sum(item["label"] == "unknown" for item in evidence.values()),
        "scope": "counterfactual gate diagnostic is not ordinary convergence or a new probe"}


def check_rank(row, candidates, used, options, gate):
    ranked = row["ranked"]
    pool = {candidate.candidate_id: candidate for candidate in candidates}
    if {item["candidate_id"] for item in ranked} != set(pool)-used or len(ranked) != len(pool)-len(used):
        raise ValueError("ranking must include every unused public candidate exactly once")
    for item in ranked:
        candidate = pool[item["candidate_id"]]
        if (item["cost"] != candidate.cost or item["mutation_probability"] != candidate.mutation_probability or
                not math.isfinite(item["eig"]) or item["eig"] < 0 or
                abs(item["score"]-(item["eig"]-options.cost_lambda*candidate.cost-options.risk_lambda*candidate.mutation_probability)) > 1e-12):
            raise ValueError("archived public EIG/cost/risk score is inconsistent")
    if ranked != sorted(ranked, key=lambda item: (-item["score"], item["candidate_id"])):
        raise ValueError("archived ranking order is inconsistent")
    challenged = [item for item in ranked if gate and item["candidate_id"] in gate["remaining_candidates"]]
    chosen = challenged[0] if gate and not gate["passed"] and challenged else ranked[0]
    if (row["candidate_id"] != chosen["candidate_id"] or row["selected_eig"] != chosen["eig"] or
            row["max_available_eig"] != max(item["eig"] for item in ranked)):
        raise ValueError("selected query differs from archived ranking and actual gate")


def replay_pair(active, enhanced):
    packet, other = read(enhanced / "learner-packet.json"), read(active / "learner-packet.json")
    for key in ("candidates", "hypotheses", "seed_evidence", "learning", "passive_order", "random_seed", "challenge", "acquisition"):
        if packet[key] != other[key]: raise ValueError("paired public learning inputs differ: "+key)
    if packet["acquisition"] or other["acquisition"]:
        raise ValueError("this audit covers the frozen selected gate-only acquisition, not weighted development variants")
    identity = read(enhanced / "learner/identity.json")
    if any(value != 0 for value in identity["acquisition_options"].values()):
        raise ValueError("formal gate-only acquisition weights changed")
    candidates = [Candidate.model_validate(item) for item in packet["candidates"]]
    hypotheses = [Hypothesis.model_validate(item) for item in packet["hypotheses"]]
    options = LearningOptions.model_validate(packet["learning"])
    challenge = ChallengeOptions(**{**packet["challenge"], "max_queries": options.max_queries})
    if (identity["pool_hash"] != fingerprint([item.model_dump() for item in candidates]) or
            identity["hypotheses_hash"] != fingerprint([item.model_dump(mode="json") for item in hypotheses]) or
            identity["seed_hash"] != fingerprint(packet["seed_evidence"])):
        raise ValueError("public packet differs from frozen identity")
    belief = BeliefState(hypotheses, identity["policy_epoch"], options.accuracy, options.other_prior, options.complexity_lambda)
    belief_files = sorted((enhanced / "learner/belief").glob("belief_step_*.json"))
    if read(belief_files[0])["snapshot"] != belief.snapshot():
        raise ValueError("initial belief differs from frozen prior")
    step_index = 1
    def update(raw):
        nonlocal step_index
        if not belief.update(raw): raise ValueError("duplicate evidence in archived belief")
        saved = read(belief_files[step_index]); step_index += 1
        if (saved["evidence"] != raw or saved["posterior_hash"] != fingerprint(belief.posterior) or
                abs(saved["entropy"]-entropy(belief.posterior)) > 1e-10):
            raise ValueError("independent Bayes posterior differs from archived checkpoint")
    for evidence in packet["seed_evidence"]:
        if evidence["split"] != "seed": raise ValueError("only public seed evidence may initialize belief")
        update(evidence)
    paths, peer_paths = sorted((enhanced / "learner/queries").glob("*.json")), sorted((active / "learner/queries").glob("*.json"))
    if len(paths) != len(peer_paths): raise ValueError("formal paired query counts differ")
    diagnostics, evidence, used, gains = [], {}, set(), []
    for index, (path, peer_path) in enumerate(zip(paths, peer_paths)):
        row, peer = read(path), read(peer_path)
        for item in (row, peer):
            if item["row_hash"] != fingerprint({key: value for key, value in item.items() if key != "row_hash"}):
                raise ValueError("archived query row hash mismatch")
        if row["index"] != index or path.name != f"query_{index:03d}.json" or row["identity_hash"] != fingerprint(identity):
            raise ValueError("query order/identity mismatch")
        for key in ("candidate_id", "evidence", "ranked", "selected_eig", "max_available_eig", "learned"):
            if row[key] != peer[key]: raise ValueError("active/active_v2 actual query or ranking differs: "+key)
        state = state_diagnostic(belief, candidates, evidence, options, challenge)
        if (row["h0_challenge_before"] != state["actual_gate"] or
                stopping_reason(belief, candidates, len(evidence), options.max_queries, gains,
                    options.patience, options.min_information_gain, **options.convergence_args()) is not None):
            raise ValueError("archived query follows stopping or incorrect H0 gate")
        check_rank(row, candidates, used, options, state["actual_gate"])
        raw = EvidenceView.model_validate(row["evidence"]).model_dump()
        candidate = next(item for item in candidates if item.candidate_id == row["candidate_id"])
        if (raw["split"] != "explore" or raw["policy_epoch"] != belief.policy_epoch or not row["learned"] or
                raw["member_hash"] != candidate.member_hash or fingerprint(raw) != row["evidence_hash"] or
                raw["baseline_prediction"] != candidate.baseline_prediction or raw["guard_prediction"] != candidate.guard_prediction or
                any(raw["observations"].get(key) != value for key, value in candidate.observations.items())):
            raise ValueError("query feedback differs from actual public member observations")
        state.update(selected_candidate_id=row["candidate_id"], max_available_eig=row["max_available_eig"],
            active_and_v2_rankings_equal=True, enhanced_weights={"disagreement": 0, "coverage": 0})
        diagnostics.append(state); evidence[row["candidate_id"]] = raw; used.add(row["candidate_id"])
        gains.append(row["max_available_eig"]); update(raw)
    final = state_diagnostic(belief, candidates, evidence, options, challenge)
    diagnostics.append({**final, "terminal": True})
    summary = read(enhanced / "learner/summary.json")
    reason = stopping_reason(belief, candidates, len(evidence), options.max_queries, gains,
        options.patience, options.min_information_gain, **options.convergence_args())
    if (step_index != len(belief_files) or summary["convergence"] != final["ordinary_convergence"] or
            summary["h0_challenge"] != final["actual_gate"] or summary["queries"] != len(evidence) or summary["stop_reason"] != reason):
        raise ValueError("terminal belief/convergence/stop differs from independent replay")
    metrics = read(enhanced / "metrics.json"); effective = read(enhanced / "effective-version.json")
    fallback_errors = metrics["effective_test"]["errors"] if not metrics["boundary_admitted"] and effective["effective_hypothesis"]["kind"] == "no_change" else 0
    return {"queries": len(paths), "steps": diagnostics, "final": final, "stop_reason": reason,
        "h0_gate_entries": sum(item["h0_gate_entry_eligible"] for item in diagnostics),
        "boundary_admitted": metrics["boundary_admitted"], "certified_false_convergence": metrics["false_convergence"],
        "certified_h0_false_convergence": metrics["h0_false_convergence"], "effective_fallback_errors": fallback_errors,
        "top_diagnostic_errors": metrics["top_diagnostic"]["errors"],
        "effective_errors": metrics["effective_test"]["errors"], "effective_hypothesis": effective["effective_hypothesis"],
        "sources": {str(path.relative_to(enhanced)).replace("\\", "/"): digest_file(path) for path in
            [enhanced / "learner-packet.json", enhanced / "learner/identity.json", enhanced / "learner/summary.json", enhanced / "metrics.json", enhanced / "effective-version.json", *paths, *belief_files]}}


def audit(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists(): raise ValueError("fresh diagnosis output required")
    record = read(root / "protocol.json"); protocol = record["protocol"]
    if fingerprint(protocol) != record["protocol_hash"]: raise ValueError("historical protocol hash differs")
    if protocol["selected_variant"] != "gate": raise ValueError("expected frozen selected gate-only variant")
    for name, expected in protocol["sources"].items():
        if digest_file(ROOT / name) != expected: raise ValueError("historical frozen source changed: "+name)
    cpu = read(root / "cpu-report.json")
    if cpu["protocol_hash"] != record["protocol_hash"] or len(cpu["runs"]) != 150:
        raise ValueError("complete historical 150-run matrix required")
    output.mkdir(parents=True)
    started, rows = time.perf_counter(), []
    for world in protocol["config"]["worlds"]:
        for seed in protocol["config"]["paired_seeds"]:
            result = replay_pair(root / "cpu" / world / str(seed) / "active", root / "cpu" / world / str(seed) / "active_v2")
            row = hashed({"world": world, "seed": seed, **result})
            publish(output / world / (str(seed)+".json"), row)
            rows.append(row)
            print(json.dumps({"world": world, "seed": seed, "queries": row["queries"], "h0_entries": row["h0_gate_entries"], "stop": row["stop_reason"]}), flush=True)
    report = hashed({"schema": "p7-historical-counterfactual-selection-audit-v1", "historical_protocol_hash": record["protocol_hash"],
        "historical_cpu_report_sha256": digest_file(root / "cpu-report.json"), "historical_root": root.relative_to(ROOT).as_posix(),
        "audited_pairs": len(rows), "audited_v2_queries": sum(row["queries"] for row in rows),
        "h0_gate_entries": sum(row["h0_gate_entries"] for row in rows), "query_rank_or_selection_differences": 0,
        "stop_reasons": dict(Counter(row["stop_reason"] for row in rows)),
        "nonadmitted_fallback_error_runs": sum(row["effective_fallback_errors"] > 0 for row in rows),
        "effective_fallback_errors": sum(row["effective_fallback_errors"] for row in rows),
        "certified_false_convergence_runs": sum(row["certified_false_convergence"] for row in rows),
        "certified_h0_false_convergence_runs": sum(row["certified_h0_false_convergence"] for row in rows),
        "row_hashes": [row["hash"] for row in rows], "wall_seconds": time.perf_counter()-started,
        "audit_source_sha256": digest_file(__file__), "new_model_calls": 0, "new_tokens": 0, "new_probe_calls": 0,
        "scope": "all frozen pairs, public Bayes/convergence/H0 counterfactual replay; archived EIG order and paired equality, not independent EIG recalculation; heldout outcomes are diagnosis only, never optimizer feedback"})
    publish(output / "report.json", report); shutil.copyfile(__file__, output / "source-audit_boundary_evolution_history.py")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default="results/active-evolution/v1.1/formal-B-v1"); parser.add_argument("--output", required=True)
    args = parser.parse_args(); print(json.dumps(audit(args.run, args.output), ensure_ascii=False))
