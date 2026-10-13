"""Schema-bounded refinement. Receives examples, never a changed-policy oracle."""
import itertools

from scripts.boundary_learning import condition_accepts
from skillforge.dataset import digest
from skillforge.schemas import Condition
from skillforge.skills import gate


def adapt(base, examples, domains, limit=2):
    if not examples or any(e["split"] != "train" for e in examples):
        raise ValueError("only current-version train examples are permitted")
    if len({e["policy_version"] for e in examples}) != 1:
        raise ValueError("mixed policy versions")
    positive = [e for e in examples if e["label"] == "positive"]
    negative = [e for e in examples if e["label"] == "negative"]
    if not positive or not negative:
        raise ValueError("success and business-failure evidence required")
    pool = []
    for field, values in domains.items():
        for value in values:
            for forbidden in (False, True):
                pool.append(dict(field=field, op="eq", value=value, forbidden=forbidden))
        for count in range(2, len(values)):
            for subset in itertools.combinations(values, count):
                pool.append(dict(field=field, op="in", value=list(subset), forbidden=False))
    pool.sort(key=lambda c: (c["op"] != "eq", digest(c)))
    pool = [c for c in pool if all(condition_accepts(c, e["state"]) for e in positive)]
    learned = base.model_copy(deep=True)
    remaining = [e for e in negative if gate(learned, e["state"], e["parameters"]).status == "APPLICABLE"]
    steps = []
    for _ in range(limit):
        scores = [(sum(not condition_accepts(c, e["state"]) for e in remaining), index, c) for index, c in enumerate(pool)]
        if not scores or max(s[0] for s in scores) == 0:
            break
        _, _, chosen = min(scores, key=lambda s: (-s[0], s[1]))
        excluded = [e for e in remaining if not condition_accepts(chosen, e["state"])]
        evidence = ["success:" + e["id"] for e in positive] + ["failure:" + e["id"] for e in excluded]
        condition = Condition(**{k: chosen[k] for k in ("field", "op", "value")}, evidence=evidence)
        getattr(learned, "forbidden_conditions" if chosen["forbidden"] else "preconditions").append(condition)
        steps.append({"condition": chosen, "excluded": [e["id"] for e in excluded], "preserved_positives": len(positive)})
        remaining = [e for e in remaining if e not in excluded]
    return learned, {"steps": steps, "unresolved": [e["id"] for e in remaining], "candidate_count": len(pool)}
