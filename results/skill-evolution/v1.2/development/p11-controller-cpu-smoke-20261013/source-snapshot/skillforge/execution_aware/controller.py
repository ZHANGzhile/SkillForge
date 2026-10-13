"""Four-method boundary controller; only public evidence/candidate capabilities enter."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import random

from ..active_learning import rank_candidates, stopping_reason
from ..belief import BeliefState
from ..evolution_config import LearningOptions
from ..evolution_journal import BeliefJournal
from ..evolution_registry import EvolutionRegistry, boundary_admission, immutable_json
from ..evolution_schemas import EvidenceView, fingerprint
from ..gap_detection import detect_gaps


from .challenge import ChallengeOptions, challenge_gate
from .acquisition import AcquisitionOptions, augment_ranking


class ChallengeEvolutionController:
    def __init__(self, root, identity, hypotheses, seed_evidence, candidates, probe, validate, registry,
                 learning=None, passive_order=None, challenge=None, acquisition=None):
        self.root = Path(root)
        self.identity = identity
        self.hypotheses = hypotheses
        self.seed_evidence = seed_evidence
        self.candidates = candidates
        self.probe = probe
        self.validate = validate
        self.registry = EvolutionRegistry(registry)
        self.options = LearningOptions.model_validate(learning or {})
        self.challenge_options = ChallengeOptions(**(challenge or {}))
        self.acquisition_options = AcquisitionOptions(**(acquisition or {}))
        self.passive_order = list(passive_order) if passive_order is not None else [c.candidate_id for c in candidates]
        if len(set(self.passive_order)) != len(self.passive_order) or set(self.passive_order) != {c.candidate_id for c in candidates}:
            raise ValueError("passive stream must contain each public candidate once")
        if len({c.candidate_id for c in candidates}) != len(candidates):
            raise ValueError("duplicate candidates")
        if any(e.split != "seed" for e in seed_evidence):
            raise ValueError("initial evidence must be seed only")
        self.signature = {**identity, "controller_protocol": "challenge-boundary-controller-v1.1-dev",
            "challenge_options": asdict(self.challenge_options),
            "acquisition_options": asdict(self.acquisition_options),
            "hypotheses_hash": fingerprint([h.model_dump(mode="json") for h in hypotheses]),
            "seed_hash": fingerprint([e.model_dump() for e in seed_evidence]),
            "pool_hash": fingerprint([c.model_dump() for c in candidates]),
            "passive_order_hash": fingerprint(self.passive_order)}

    def run(self, method="active", max_queries=None, random_seed=101, defer_validation=False):
        if method not in {"active", "active_v2", "random", "passive", "no_adapt"}:
            raise ValueError("unknown method")
        options = self.options if max_queries is None else LearningOptions.model_validate(
            {**self.options.model_dump(), "max_queries": max_queries})
        signature = {**self.signature, "method": method, "learning": options.model_dump(), "random_seed": random_seed,
                     "defer_validation": defer_validation}
        immutable_json(self.root / "identity.json", signature)
        journal = BeliefJournal(self.root / "belief.sqlite", signature)
        stored = journal.restore()
        belief = BeliefState(self.hypotheses, self.identity["policy_epoch"], options.accuracy,
                             options.other_prior, options.complexity_lambda)
        journal.append(belief)
        for evidence in self.seed_evidence:
            if belief.update(evidence):
                journal.append(belief)
        gaps = detect_gaps(self.seed_evidence)
        immutable_json(self.root / "gap.json", gaps)
        queries, used = [], set()
        by_id = {c.candidate_id: c for c in self.candidates}
        random_order = sorted(by_id)
        random.Random(random_seed).shuffle(random_order)
        query_root = self.root / "queries"
        paths = sorted(query_root.glob("*.json")) if query_root.exists() else []

        gate_options = replace(self.challenge_options, max_queries=options.max_queries)

        def current_gate():
            if method != "active_v2":
                return None
            raw = belief.convergence(self.candidates, **options.convergence_args())
            if not raw.get("converged"):
                return None
            hypothesis = next(h for h in self.hypotheses if h.hypothesis_id == raw["hypothesis_id"])
            if hypothesis.kind != "no_change":
                return None
            return challenge_gate(belief, self.candidates,
                {q["candidate_id"]: q["evidence"] for q in queries}, gate_options)

        def stop():
            if method == "no_adapt":
                return "no_adaptation"
            gate = current_gate()
            if gate and not gate["passed"]:
                return None if gate["status"] == "challenge_required" else gate["status"]
            return stopping_reason(belief, self.candidates, len(queries), options.max_queries,
                [q["max_available_eig"] for q in queries], options.patience, options.min_information_gain,
                **options.convergence_args())

        def selection():
            ranked = rank_candidates(belief, self.candidates, used, options.cost_lambda, options.risk_lambda)
            if method == 'active_v2':
                ranked = augment_ranking(belief, self.candidates, used, ranked, self.acquisition_options,
                                         options.cost_lambda, options.risk_lambda)
            if not ranked:
                return None, []
            if method in {"active", "active_v2"}:
                gate = current_gate()
                challenged = [r for r in ranked if gate and r["candidate_id"] in gate["remaining_candidates"]]
                selected = challenged[0] if gate and not gate["passed"] and challenged else ranked[0]
            else:
                order = random_order if method == "random" else self.passive_order
                key = next(key for key in order if key not in used)
                selected = next(row for row in ranked if row["candidate_id"] == key)
            return selected, ranked

        def consume(row):
            candidate = by_id[row["candidate_id"]]
            ev = EvidenceView.model_validate(row["evidence"])
            if ev.split != "explore" or ev.policy_epoch != belief.policy_epoch:
                raise ValueError("probe evidence split/epoch mismatch")
            if candidate.member_hash and candidate.member_hash != ev.member_hash:
                raise ValueError("probe response belongs to another task")
            if ev.baseline_prediction != candidate.baseline_prediction or ev.guard_prediction != candidate.guard_prediction:
                raise ValueError("probe response prediction identity mismatch")
            # Controlled factors must agree with actual observations, not silently
            # let predicted candidate x differ from the state that was probed.
            if any(key in ev.observations and ev.observations[key] != value for key, value in candidate.observations.items()):
                raise ValueError("controlled factors disagree with tool observations")
            learned = method != "passive" or ev.label == "not_executable"
            if row["learned"] != learned:
                raise ValueError("passive evidence policy changed")
            if learned and belief.update(ev):
                journal.append(belief)
            queries.append(row)
            used.add(candidate.candidate_id)

        for index, path in enumerate(paths):
            row = json.loads(path.read_text(encoding="utf-8"))
            if stop() is not None:
                raise ValueError("persisted query appears after stopping")
            selected, ranked = selection()
            if (row.get("row_hash") != fingerprint({k: v for k, v in row.items() if k != "row_hash"})
                or row["index"] != index or path.name != f"query_{index:03d}.json"
                or row["identity_hash"] != fingerprint(signature)
                or fingerprint(row.get("h0_challenge_before")) != fingerprint(current_gate())
                or fingerprint(row["evidence"]) != row["evidence_hash"]
                or selected is None or row["candidate_id"] != selected["candidate_id"]
                or fingerprint(row["ranked"]) != fingerprint(ranked)):
                raise ValueError("query checkpoint corrupted or acquisition replay differs")
            consume(row)
        if stored and len(stored.history) > len(belief.history):
            raise ValueError("belief contains missing query records")
        while True:
            reason = stop()
            if reason:
                break
            selected, ranked = selection()
            if selected is None:
                reason = "pool_exhausted"
                break
            evidence = EvidenceView.model_validate(self.probe(selected["candidate_id"]))
            row = {"index": len(queries), "identity_hash": fingerprint(signature),
                "h0_challenge_before": current_gate(),
                "candidate_id": selected["candidate_id"], "ranked": ranked,
                "selected_eig": selected["eig"], "max_available_eig": max(r["eig"] for r in ranked),
                "evidence": evidence.model_dump(), "evidence_hash": fingerprint(evidence.model_dump()),
                "learned": method != "passive" or evidence.label == "not_executable"}
            row["row_hash"] = fingerprint(row)
            immutable_json(query_root / f"query_{len(queries):03d}.json", row)
            consume(row)
        journal.export(self.root / "belief")
        convergence = belief.convergence(self.candidates, **options.convergence_args())
        raw_converged = convergence["converged"]
        gate = current_gate()
        if gate and not gate["passed"]:
            convergence = {**convergence, "converged": False}
        result = {"raw_belief_converged": raw_converged, "belief_converged": convergence["converged"],
            "h0_challenge": gate, "boundary_validation_passed": None, "boundary_admitted": False,
            "agent_admitted": None, "activated": False, "nontrivial": False, "stop_reason": reason, "queries": len(queries), "convergence": convergence,
            "queries_to_convergence": len(queries) if convergence["converged"] and method != "no_adapt" else None,
            "learned_exploration_samples": sum(q["learned"] for q in queries),
            "exploration_tool_calls": sum(q["evidence"]["tool_calls"] for q in queries),
            "status": "INCONCLUSIVE", "method": method,
            "scope": "boundary-only evolution; model-level admission and final test are separate"}
        if convergence["converged"] or method == "no_adapt":
            hypothesis = next(h for h in self.hypotheses if
                (h.kind == "no_change" if method == "no_adapt" else h.hypothesis_id == convergence["hypothesis_id"]))
            result["nontrivial"] = any(c.baseline_prediction is not None and
                hypothesis.predict(c.observations, c.baseline_prediction, c.guard_prediction) is not None and
                hypothesis.predict(c.observations, c.baseline_prediction, c.guard_prediction) != c.baseline_prediction
                for c in self.candidates)
            candidate = {"parent_hash": self.identity["parent_hash"], "policy_epoch": self.identity["policy_epoch"],
                "hypothesis": hypothesis.model_dump(mode="json"), "belief_hash": fingerprint(belief.snapshot()),
                "training_evidence": [h["evidence"]["evidence_id"] for h in belief.history],
                "admission_identity": self.identity.get("admission_identity"),
                "parent_identity": self.identity.get("parent_identity")}
            immutable_json(self.root / "candidate.json", candidate)
            if defer_validation:
                result["status"] = "UNCHANGED" if method == "no_adapt" else "CANDIDATE_FROZEN"
                immutable_json(self.root / "summary.json", result)
                return result
            validation_path = self.root / "validation.json"
            report = json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else self.validate(candidate)
            immutable_json(validation_path, report)
            passed = boundary_admission(candidate, report) and report["stable_regressions"] == 0
            result["boundary_validation_passed"] = passed
            if method == "no_adapt" or not result["nontrivial"]:
                result["status"] = "UNCHANGED"
            elif passed:
                version = self.registry.publish(candidate, report)
                self.registry.load(version)
                result.update(status="VERIFIED", registry_version=version, boundary_admitted=True)
            else:
                result["status"] = "REJECTED"
        immutable_json(self.root / "summary.json", result)
        return result
