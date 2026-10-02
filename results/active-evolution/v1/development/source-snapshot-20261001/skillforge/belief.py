"""Posterior under a declared finite observation model; not calibrated confidence."""
import math

from .evolution_schemas import EvidenceView, Hypothesis, fingerprint


def normalize(log_weights):
    pivot = max(log_weights)
    values = [math.exp(v - pivot) for v in log_weights]
    total = sum(values)
    return [v / total for v in values]


def entropy(probabilities):
    return -sum(p * math.log(p) for p in probabilities if p > 0)


class BeliefState:
    def __init__(self, hypotheses, policy_epoch, accuracy=.99, other_prior=.1, complexity_lambda=1.):
        if not .5 < accuracy < 1 or not 0 < other_prior < 1 or not math.isfinite(complexity_lambda) or complexity_lambda < 0:
            raise ValueError("invalid declared observation model")
        if len({h.hypothesis_id for h in hypotheses}) != len(hypotheses) or sum(h.kind == "other" for h in hypotheses) != 1 or len(hypotheses) < 2:
            raise ValueError("unique hypotheses and one OTHER required")
        self.hypotheses = list(hypotheses)
        self.policy_epoch, self.accuracy = policy_epoch, accuracy
        self.other_prior, self.complexity_lambda = other_prior, complexity_lambda
        raw = [-complexity_lambda * len(h.predicates) for h in hypotheses if h.kind != "other"]
        probs = iter(normalize(raw))
        self.log_weights = [math.log(other_prior if h.kind == "other" else (1-other_prior)*next(probs)) for h in hypotheses]
        self.history, self.seen = [], {}

    @property
    def posterior(self):
        return normalize(self.log_weights)

    def predictions(self, facts, baseline):
        return [h.predict(facts, baseline) for h in self.hypotheses]

    def likelihood(self, predicted, observed):
        return .5 if predicted is None else self.accuracy if predicted == observed else 1-self.accuracy

    def update(self, evidence):
        evidence = EvidenceView.model_validate(evidence)
        if evidence.policy_epoch != self.policy_epoch:
            raise ValueError("mixed policy epochs")
        payload = evidence.model_dump()
        signature = fingerprint(payload)
        # One source trajectory may not be relabelled with a new evidence ID.
        source = evidence.trajectory_id
        if source in self.seen:
            if self.seen[source] != signature:
                raise ValueError("conflicting duplicate evidence")
            return False
        before = self.posterior
        if evidence.label != "unknown":
            observed = evidence.label == "executable"
            predictions = self.predictions(evidence.observations, evidence.baseline_prediction)
            self.log_weights = [w + math.log(self.likelihood(p, observed)) for w, p in zip(self.log_weights, predictions)]
        self.seen[source] = signature
        self.history.append({"evidence": payload, "before": before, "after": self.posterior,
            "entropy_delta": entropy(before)-entropy(self.posterior)})
        return True

    def snapshot(self):
        return {"policy_epoch": self.policy_epoch, "accuracy": self.accuracy,
            "other_prior": self.other_prior, "complexity_lambda": self.complexity_lambda,
            "hypotheses": [h.model_dump(mode="json") for h in self.hypotheses], "history": self.history,
            "posterior": self.posterior, "entropy": entropy(self.posterior),
            "scope": "posterior under the declared finite observation model"}

    @classmethod
    def restore(cls, snapshot):
        result = cls([Hypothesis.model_validate(h) for h in snapshot["hypotheses"]], snapshot["policy_epoch"],
            snapshot["accuracy"], snapshot["other_prior"], snapshot["complexity_lambda"])
        for entry in snapshot["history"]:
            result.update(entry["evidence"])
        if fingerprint(result.snapshot()) != fingerprint(snapshot):
            raise ValueError("belief replay mismatch")
        return result

    def convergence(self, candidates, threshold=.95, entropy_threshold=.15, other_threshold=.05):
        # Equivalence is explicitly restricted to the frozen public candidate support.
        if not candidates:
            return {"converged": False, "reason": "empty_support"}
        groups = {}
        for index, hypothesis in enumerate(self.hypotheses):
            key = ("OTHER",) if hypothesis.kind == "other" else tuple(hypothesis.predict(c.observations, c.baseline_prediction) for c in candidates)
            groups.setdefault(key, []).append(index)
        posterior = self.posterior
        masses = {key: sum(posterior[i] for i in indices) for key, indices in groups.items()}
        structured = [k for k in groups if k != ("OTHER",)]
        best = max(structured, key=lambda key: masses[key])
        index = min(groups[best], key=lambda i: (len(self.hypotheses[i].predicates), self.hypotheses[i].hypothesis_id))
        hypothesis = self.hypotheses[index]
        valid = [e["evidence"] for e in self.history if e["evidence"]["label"] != "unknown"]
        fits = bool(valid) and all(hypothesis.predict(e["observations"], e["baseline_prediction"]) == (e["label"] == "executable") for e in valid)
        converged = fits and None not in best and masses[best] >= threshold and entropy(masses.values()) <= entropy_threshold and masses[("OTHER",)] <= other_threshold
        return {"converged": converged, "hypothesis_id": hypothesis.hypothesis_id,
            "class_posterior": masses[best], "other_posterior": masses[("OTHER",)],
            "class_entropy": entropy(masses.values()), "fits_observed_evidence": fits,
            "scope": "equivalence on declared candidate support, not global semantic identity"}
