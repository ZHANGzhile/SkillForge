"""Finite schema-only enumeration. No environment, evaluator or policy imports."""
import itertools

from .evolution_schemas import DOMAINS, Hypothesis, Predicate, fingerprint


def generate_hypotheses(observed_fields, thresholds=(1000, 3000, 5000, 10000), max_predicates=2):
    if max_predicates not in (1, 2) or not set(observed_fields) <= set(DOMAINS):
        raise ValueError("unsupported hypothesis domain")
    predicates = []
    for field in sorted(set(observed_fields)):
        domain = DOMAINS[field]
        if domain is None:
            predicates += [Predicate(field=field, op=op, value=v) for v in thresholds for op in ("lt", "lte", "gt", "gte")]
        else:
            predicates += [Predicate(field=field, op=op, value=v) for v in domain for op in ("eq", "neq")]
            for size in range(2, len(domain)):
                predicates += [Predicate(field=field, op=op, value=list(v)) for v in itertools.combinations(domain, size) for op in ("in", "not_in")]
    result = [Hypothesis(hypothesis_id="H0", kind="no_change")]
    for size in range(1, max_predicates + 1):
        for group in itertools.combinations(predicates, size):
            if len({p.field for p in group}) != size:
                continue
            for kind in ("restrict", "relax"):
                ident = fingerprint([kind, [p.model_dump() for p in group]])
                result.append(Hypothesis(hypothesis_id=ident, kind=kind, predicates=group))
    result.append(Hypothesis(hypothesis_id="H_other", kind="other"))
    return result
