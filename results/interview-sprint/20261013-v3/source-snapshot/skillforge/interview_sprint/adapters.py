"""Bind frozen algorithms to an explicit new workflow/evaluator version.

Function code objects are reused; globals are copied, never patched in historical
modules. All base and extension source bytes enter the sprint source identity.
"""
import hashlib
from pathlib import Path
from types import FunctionType

from skillforge.evolution_common.artifacts import clone
from skillforge.skill_evolution import experience, compiler, validation, runtime
from .workflows import GOALS, GOAL, WorkflowCase, verify_workflow


def bind(fn, replacements):
    result = FunctionType(fn.__code__, {**fn.__globals__, **replacements}, fn.__name__, fn.__defaults__, fn.__closure__)
    result.__kwdefaults__ = fn.__kwdefaults__
    return result


def sources():
    root = Path(__file__).resolve().parents[2]
    result = {"skillforge/" + key: value for key, value in runtime.runtime_sources().items()}
    for path in [*Path(__file__).parent.glob("*.py"), root / "scripts/run_interview_sprint.py"]:
        if path.exists(): result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


normalize_trajectory = bind(experience.normalize_trajectory, {"WorkflowCase": WorkflowCase, "GOALS": GOALS})
mine_opportunities = bind(experience.mine_opportunities, {"normalize_trajectory": normalize_trajectory, "GOALS": GOALS})
compile_opportunity = bind(compiler.compile_opportunity, {"GOALS": GOALS})
compile_screen = bind(compiler.compile_screen, {"compile_opportunity": compile_opportunity})


def public_policy_for(task):
    policy = clone(runtime.PUBLIC_POLICY)
    if task["family"] in GOALS:
        goal = GOALS[task["family"]]
        policy.update(workflow_goal=goal.model_dump(), workflow_goal_hash=goal.identity,
            terminal_rules_in_priority_order=["permission_denied or not_found: refuse; do not retry access",
                "Read all evidence required by the public read-only goal, then stop",
                "HIGH risk or any business status does not prohibit authorized reads",
                "Never write, escalate or create tickets for a read-only goal"],
            scope="predeclared read-only dossier goal; no evaluator or candidate-provided correctness")
    return policy


def readonly_tools():
    return [item for item in runtime.tool_definitions() if item["name"] in GOAL.required_evidence]


run_agent = bind(runtime.run_agent, {"public_policy_for": public_policy_for, "PROTOCOL": "interview-dossier-runtime-v1",
                                  "runtime_sources": sources, "TOOLS": set(GOAL.required_evidence),
                                  "tool_definitions": readonly_tools})
ValidationCase = None


def validation_functions():
    # Pydantic's frozen legacy Literal intentionally cannot accept a new task;
    # the versioned case schema changes only that field's type.
    from typing import Literal
    from pydantic import Field, create_model
    VCase = create_model("DossierValidationCase", __base__=validation.ValidationCase, case=(WorkflowCase, ...))
    replacements = {"GOALS": GOALS, "WorkflowCase": WorkflowCase, "ValidationCase": VCase,
                    "verify_workflow": verify_workflow, "validator_sources": sources}
    for name in ("static_check", "run_case", "declare_protocol", "validate_program", "audit_validation", "program_admission", "audit_program_admission"):
        replacements[name] = bind(getattr(validation, name), replacements)
    # Rebind after all functions exist so every dependency uses this evaluator.
    for name in ("static_check", "run_case", "declare_protocol", "validate_program", "audit_validation", "program_admission", "audit_program_admission"):
        replacements[name].__globals__.update(replacements)
    return replacements
