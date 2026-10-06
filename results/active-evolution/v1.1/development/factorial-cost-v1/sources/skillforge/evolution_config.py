"""Strict, identity-bearing options used by all four methods."""
from pydantic import Field

from .evolution_schemas import Record


class LearningOptions(Record):
    max_queries: int = Field(default=20, ge=0, le=1000)
    max_predicates: int = Field(default=2, ge=1, le=2)
    complexity_lambda: float = Field(default=1., ge=0, le=100, allow_inf_nan=False)
    other_prior: float = Field(default=.1, gt=0, lt=1)
    accuracy: float = Field(default=.99, gt=.5, lt=1)
    posterior_threshold: float = Field(default=.95, gt=.5, lt=1)
    entropy_threshold: float = Field(default=.15, ge=0, allow_inf_nan=False)
    other_threshold: float = Field(default=.05, ge=0, lt=1)
    min_information_gain: float = Field(default=.01, ge=0, allow_inf_nan=False)
    patience: int = Field(default=3, ge=1)
    cost_lambda: float = Field(default=.01, ge=0, allow_inf_nan=False)
    risk_lambda: float = Field(default=.01, ge=0, allow_inf_nan=False)

    def convergence_args(self):
        return {"threshold":self.posterior_threshold,"entropy_threshold":self.entropy_threshold,
                "other_threshold":self.other_threshold}
