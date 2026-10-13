"""Public-only acquisition ablations; no dataset, policy or validation access."""
from dataclasses import dataclass
from itertools import combinations
import math

from ..evolution_schemas import fingerprint


FIELDS = ('customer.risk_level', 'order.status', 'shipment.status', 'payment.status',
          'request.amount', 'payment.remaining_amount')


@dataclass(frozen=True)
class AcquisitionOptions:
    disagreement_weight: float = 0.
    coverage_weight: float = 0.

    def __post_init__(self):
        if any(not math.isfinite(v) or v < 0 for v in (self.disagreement_weight, self.coverage_weight)):
            raise ValueError('finite nonnegative acquisition weights required')


def factors(candidate):
    pairs = [(field, candidate.observations[field]) for field in FIELDS if field in candidate.observations]
    return {fingerprint(items) for size in (1, 2) for items in combinations(pairs, size)}


def augment_ranking(belief, candidates, used, ranked, options, cost_lambda, risk_lambda):
    if not options.disagreement_weight and not options.coverage_weight:
        return ranked  # Preserve exact original EIG scale and order for gate-only.
    by_id = {c.candidate_id: c for c in candidates}
    h0 = next(i for i, h in enumerate(belief.hypotheses) if h.kind == 'no_change')
    alternatives = [i for i, h in enumerate(belief.hypotheses) if h.kind not in {'no_change', 'other'}]
    posterior = belief.posterior; mass = sum(posterior[i] for i in alternatives)
    covered = set().union(*(factors(by_id[cid]) for cid in used)) if used else set()
    scale = max((r['eig'] for r in ranked), default=0.)
    rows = []
    for row in ranked:
        candidate = by_id[row['candidate_id']]
        predictions = belief.predictions(candidate.observations, candidate.baseline_prediction, candidate.guard_prediction)
        disagreement = sum(posterior[i] for i in alternatives if predictions[i] is not None
                           and predictions[h0] is not None and predictions[i] != predictions[h0])/mass if mass else 0.
        cells = factors(candidate); coverage = len(cells-covered)/len(cells) if cells else 0.
        normalized = row['eig']/scale if scale else 0.
        rows.append({**row, 'normalized_eig': normalized, 'h0_disagreement': disagreement, 'coverage_bonus': coverage,
            'score': normalized+options.disagreement_weight*disagreement+options.coverage_weight*coverage
                     -cost_lambda*row['cost']-risk_lambda*row['mutation_probability']})
    return sorted(rows, key=lambda r: (-r['score'], r['candidate_id']))
