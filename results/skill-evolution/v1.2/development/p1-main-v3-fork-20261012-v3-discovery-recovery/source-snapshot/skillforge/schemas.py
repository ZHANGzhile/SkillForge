from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Action(StrictModel):
    type: Literal["tool", "skill", "stop", "escalate", "refuse"]
    name: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)


class ExpectedOutcome(StrictModel):
    allowed_outcomes: list[Literal["completed", "refused", "escalated"]]
    expected_state: dict[str, Any] = Field(default_factory=dict)
    unchanged_fields: list[str] = Field(default_factory=list)
    require_verification: bool = True


class Task(StrictModel):
    task_id: str
    family: str
    request: str
    customer_id: str = "C1"
    parameters: dict[str, Any] = Field(default_factory=dict)
    split: Literal["train", "validation", "test"]
    template_id: str
    seed: int
    fixture: dict[str, Any] = Field(default_factory=dict)
    expected: ExpectedOutcome
    dataset_id: str = "smoke-v1"
    instance_id: str = ""
    structure_id: str = "primitive"
    level: Literal["A", "B", "C", "D", "E"] = "A"
    template_text: str = ""
    workflow: Literal["primitive", "address_else_escalate", "address_else_cancel_else_escalate"] = "primitive"


class Condition(StrictModel):
    field: str
    op: Literal["eq", "in"] = "eq"
    value: Any
    evidence: list[str] = Field(min_length=1)


class SkillStep(StrictModel):
    kind: Literal["call", "assert", "finish"]
    tool: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    condition: Condition | None = None


class SkillContract(StrictModel):
    skill_id: str
    version: int = Field(default=1, ge=1)
    family: str
    inputs: list[str]
    preconditions: list[Condition]
    forbidden_conditions: list[Condition]
    procedure: list[SkillStep] = Field(min_length=1, max_length=12)
    postconditions: dict[str, Any]
    source_trajectory_ids: list[str]
    policy_version: str
    status: Literal["CANDIDATE", "VALIDATING", "VERIFIED", "NEEDS_REFINEMENT", "REJECTED", "DEPRECATED"] = "CANDIDATE"
    statistics: dict[str, Any] = Field(default_factory=dict)


class GateResult(StrictModel):
    status: Literal["APPLICABLE", "INAPPLICABLE", "UNKNOWN"]
    missing_fields: list[str] = Field(default_factory=list)
    reason: str = ""
