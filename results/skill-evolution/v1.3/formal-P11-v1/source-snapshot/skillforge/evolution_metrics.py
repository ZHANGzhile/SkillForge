"""Paired boundary retention and read-only sensitivity; no oracle access."""
from .active_learning import rank_candidates
from .belief import BeliefState
from .evolution_schemas import EvidenceView


def retention(cases):
    if not cases or len({r["task_id"] for r in cases})!=len(cases):
        raise ValueError("nonempty unique paired cases required")
    if any(r["split"] not in {"stable_validation","stable_test","model_stable_validation","model_stable_test"} for r in cases):
        raise ValueError("retention requires a stable partition")
    before=after=preserved=regressions=0
    for row in cases:
        if any(type(row.get(k)) is not bool for k in ("truth","baseline_prediction","prediction")):
            raise ValueError("unknown labels cannot silently score as failures")
        a=row["baseline_prediction"]==row["truth"]
        b=row["prediction"]==row["truth"]
        before+=a
        after+=b
        preserved+=a and b
        regressions+=a and not b
    n=len(cases)
    return {"cases":n,"before_correct":before,"after_correct":after,"regression_count":regressions,
        "regression_rate":regressions/n,"retention_rate":preserved/before if before else None,
        "conditional_regression_rate":regressions/before if before else None,
        "forgetting":(before-after)/n,"scope":"paired boundary correctness, not autonomous model EOC"}


def sensitivity(hypotheses, epoch, seeds, queries, candidates, options, accuracies=(.9,.95,.99)):
    reports=[]
    for accuracy in accuracies:
        belief=BeliefState(hypotheses,epoch,accuracy,options.other_prior,options.complexity_lambda)
        for item in seeds:
            belief.update(item)
        rows=[]
        used=set()
        for query in queries:
            ranked=rank_candidates(belief,candidates,used,options.cost_lambda,options.risk_lambda)
            actual=query["candidate_id"]
            if actual not in {c.candidate_id for c in candidates} or actual in used:
                raise ValueError("query history differs from frozen public pool")
            rows.append({"query_index":len(rows),"actual_candidate_id":actual,
                "counterfactual_top":ranked[0]["candidate_id"],
                "actual_rank":next(i+1 for i,row in enumerate(ranked) if row["candidate_id"]==actual),
                "same_top":ranked[0]["candidate_id"]==actual,
                "convergence_before":belief.convergence(candidates,**options.convergence_args())})
            if query.get("learned",True):
                belief.update(EvidenceView.model_validate(query["evidence"]))
            used.add(actual)
        reports.append({"accuracy":accuracy,"steps":rows,
            "final":belief.convergence(candidates,**options.convergence_args())})
    return {"scope":"fixed evidence path reweighting only; no extra queries, tuning or alternate-path performance claim",
            "runs":reports}
