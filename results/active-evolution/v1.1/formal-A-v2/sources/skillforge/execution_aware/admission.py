"""Separate evidence at each evolution stage; H0 is never a learned update."""
from dataclasses import dataclass


@dataclass(frozen=True)
class AdmissionEvidence:
    run_id: str
    method: str
    complete: bool
    nontrivial: bool
    belief_converged: bool
    boundary_validation_passed: bool | None = None
    agent_evaluation_planned: bool = False
    agent_validation_passed: bool | None = None
    activated: bool = False
    deployed: bool = False

    @property
    def boundary_admitted(self):
        return self.complete and self.method != "no_adapt" and self.nontrivial and self.boundary_validation_passed is True

    @property
    def agent_admitted(self):
        return self.boundary_admitted and self.agent_evaluation_planned and self.agent_validation_passed is True

    def validate(self):
        if not self.complete and (self.activated or self.deployed):
            raise ValueError("incomplete run cannot activate")
        if self.agent_validation_passed is not None and not self.agent_evaluation_planned:
            raise ValueError("unplanned Agent evaluation")
        if self.activated and not self.agent_admitted:
            raise ValueError("activation requires nontrivial Agent admission")
        if self.deployed and not self.activated:
            raise ValueError("deployment requires activation")


def admission_funnel(rows):
    """Input is the complete predeclared cohort, including unevaluated entries."""
    if not rows or len({r.run_id for r in rows}) != len(rows):
        raise ValueError("unique nonempty predeclared cohort required")
    for row in rows:
        row.validate()
    complete = [r for r in rows if r.complete]
    eligible = [r for r in rows if r.boundary_admitted and r.agent_evaluation_planned]
    counts = {"planned": len(rows), "complete": len(complete),
              "belief_converged": sum(r.complete and r.belief_converged for r in rows),
              "boundary_admitted": sum(r.boundary_admitted for r in rows),
              "agent_admitted": sum(r.agent_admitted for r in rows),
              "activated": sum(r.activated for r in rows), "deployed": sum(r.deployed for r in rows)}
    branches = {"incomplete": len(rows)-len(complete),
                "h0_or_unchanged": sum(r.complete and not r.nontrivial for r in rows),
                "h0_validation_failed": sum(r.complete and not r.nontrivial and r.boundary_validation_passed is False for r in rows),
                "agent_not_scheduled": sum(r.boundary_admitted and not r.agent_evaluation_planned for r in rows),
                "agent_pending": sum(r.agent_validation_passed is None for r in eligible),
                "agent_rejected": sum(r.agent_validation_passed is False for r in eligible)}
    adaptation = [r for r in rows if r.method != "no_adapt"]
    return {"counts": counts, "branches": branches,
            "fixed_cohort_rates": {k: v/len(rows) for k, v in counts.items() if k not in {"planned", "complete"}},
            "conditional_rates": {
                "belief_convergence_rate": counts["belief_converged"]/len(complete) if complete else None,
                "boundary_admission_rate": counts["boundary_admitted"]/len(adaptation) if adaptation else None,
                "agent_admission_rate": counts["agent_admitted"]/len(eligible) if eligible else None,
                "end_to_end_activation_rate": counts["activated"]/len(adaptation) if adaptation else None},
            "denominators": {"complete_runs": len(complete), "adaptation_runs": len(adaptation), "scheduled_admitted_boundary_proposals": len(eligible)},
            "nested": all(not r.boundary_admitted or r.belief_converged for r in rows),
            "activation_scope": "isolated evaluation; deployment reported separately"}
