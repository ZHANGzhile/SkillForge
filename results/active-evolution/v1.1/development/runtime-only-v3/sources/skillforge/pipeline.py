import json
from pathlib import Path

from .benchmark import generate_tasks, run_benchmark
from .learning import build_sft, validate_skill
from .model import ScriptedPolicy
from .schemas import Action
from .skills import SkillRegistry, compile_address
from .decision_eval import evaluate_decisions


class UnsafeFixturePolicy(ScriptedPolicy):
    """Intentionally incorrect behavior for verifier regression and negative evidence."""
    def decide(self, context):
        if not context["history"]:
            return Action(type="tool", name="update_shipping_address", arguments=context["parameters"])
        return Action(type="stop")


def engineering_pipeline(root="results/engineering"):
    root = Path(root)
    # New artifact directory each time preserves immutable skill evidence versions.
    import uuid
    root = root / str(uuid.uuid4())
    root.mkdir(parents=True, exist_ok=True)
    _, positives = run_benchmark(ScriptedPolicy(), generate_tasks("train", repeats=3), output_root=root, label="source-positive-fixtures")
    negatives_tasks = [t for t in generate_tasks("train") if t.family == "modify_address" and t.fixture.get("shipment") in {"SHIPPED", "PROCESSING"}]
    _, negatives = run_benchmark(UnsafeFixturePolicy(), negatives_tasks, output_root=root, label="source-negative-fixtures")
    skill = compile_address(positives + negatives)
    naive = skill.model_copy(deep=True)
    report = validate_skill(skill, generate_tasks("validation", repeats=2))
    registry = SkillRegistry(root / "skills")
    registry.save(skill)
    results = []
    # Same scripted policy: these runs validate wiring, not research hypotheses.
    for label, skills, verified, memory in [
        ("B0", [], True, []),
        ("B1", [], True, positives),
        ("B2", [naive], False, []), ("B3", [skill], True, []),
    ]:
        summary, _ = run_benchmark(ScriptedPolicy(), skills=skills, verified=verified, memory=memory, output_root=root, label=label)
        results.append(summary)
    sft = build_sft(positives + negatives)
    (root / "sft_engineering_fixtures.jsonl").write_text("\n".join(json.dumps(s) for s in sft), encoding="utf-8")
    output = {"engineering_only": True, "not_model_benchmark": True, "validation": report,
        "artifact_dir": str(root.resolve()), "decision_evaluation": evaluate_decisions(ScriptedPolicy(), skill, generate_tasks()),
        "comparison": results, "sft_fixture_actions": len(sft), "limitations": ["scripted policy", "address compiler only", "shared smoke templates across splits", "no trained model"]}
    (root / "pipeline_summary.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    return output
