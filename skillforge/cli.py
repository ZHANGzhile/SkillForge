import argparse
import json
import sys
from pathlib import Path

from .benchmark import run_benchmark
from .model import ModelClient, ScriptedPolicy
from .pipeline import engineering_pipeline
from .schemas import Action


def main():
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="SkillForge local research sandbox")
    parser.add_argument("command", choices=["demo", "benchmark", "model-smoke", "dataset", "collect", "prepare", "compare", "refine"])
    parser.add_argument("--scripted", action="store_true", help="Engineering fixture only; never an LLM result")
    parser.add_argument("--output", default="results")
    parser.add_argument("--dataset", help="Directory containing manifest.json and split files")
    parser.add_argument("--source", help="Collected training trajectories JSONL")
    parser.add_argument("--bundle", help="Immutable frozen.json for comparison")
    parser.add_argument("--candidate", help="Candidate SkillContract JSON for bounded repair")
    parser.add_argument("--families", nargs="+", choices=["modify_address", "cancel_order", "refund"], default=["modify_address", "cancel_order", "refund"])
    parser.add_argument("--max-refinements", type=int, choices=[0, 1, 2], default=2)
    parser.add_argument("--split", choices=["train", "validation", "test"], default="test")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--instances", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--ablation", action="store_true")
    parser.add_argument("--failure-fixtures", action="store_true", help="Explicitly collect intentionally wrong scripted actions for engineering only")
    args = parser.parse_args()
    if args.command in {"collect", "prepare", "compare", "refine"} and not args.dataset:
        parser.error("--dataset is required")
    if args.command in {"prepare", "refine"} and not args.source:
        parser.error("--source is required")
    if args.command == "compare" and not args.bundle:
        parser.error("--bundle is required")
    if args.command == "refine" and not args.candidate:
        parser.error("--candidate is required")
    if args.failure_fixtures and (not args.scripted or args.command != "collect"):
        parser.error("--failure-fixtures requires collect --scripted")
    if args.command == "dataset":
        from .dataset import write_dataset
        print(json.dumps(write_dataset(args.output, seed=args.seed, instances=args.instances), indent=2))
    elif args.command == "collect":
        from .experiment import collect
        print(json.dumps(collect(args.dataset, ScriptedPolicy if args.scripted else ModelClient,
            args.output, engineering=args.scripted, failure_fixtures=args.failure_fixtures), indent=2))
    elif args.command == "refine":
        from .dataset import load_dataset
        from .experiment import read_sources
        from .provenance import audit_sources
        from .refinement import validate_and_refine
        from .schemas import SkillContract
        _, tasks = load_dataset(args.dataset)
        records = read_sources(args.source)
        audit_sources(records, tasks, allow_engineering=args.scripted)
        candidate = SkillContract.model_validate_json(Path(args.candidate).read_text(encoding="utf-8"))
        skill, report = validate_and_refine(candidate, records, [t for t in tasks if t.split == "validation"],
            max_refinements=args.max_refinements, output_dir=args.output)
        print(json.dumps({"status": skill.status, "refinements": report["refinements"], "stop_reason": report["stop_reason"],
            "summary": str(Path(args.output).resolve() / "summary.json")}, indent=2))
        if skill.status != "VERIFIED":
            sys.exit(1)
    elif args.command == "prepare":
        from .experiment import prepare
        bundle = prepare(args.dataset, args.source, args.output, engineering=args.scripted, families=args.families, max_refinements=args.max_refinements)
        print(json.dumps({"bundle": str(Path(args.output).resolve() / "frozen.json"), "bundle_hash": bundle["bundle_hash"],
            "verified_skills": len(bundle["skills"]), "engineering_only": bundle["engineering_only"]}, indent=2))
    elif args.command == "compare":
        from .experiment import compare
        report = compare(args.dataset, args.bundle, ScriptedPolicy if args.scripted else ModelClient,
            args.output, repeats=args.repeats, engineering=args.scripted, ablation=args.ablation)
        print(json.dumps({"artifact_dir": report["artifact_dir"], "engineering_only": report["config"]["engineering_only"], "summary": report["summary"]}, indent=2))
    elif args.command == "demo":
        report = engineering_pipeline(Path(args.output) / "engineering")
        print(json.dumps({"engineering_only": True, "summary": str(Path(report["artifact_dir"]) / "pipeline_summary.json"),
            "validation": {k: v for k, v in report["validation"].items() if k != "cases"}, "runs": len(report["comparison"])}, indent=2))
    elif args.command == "benchmark":
        model = ScriptedPolicy() if args.scripted else ModelClient()
        tasks = None
        if args.dataset:
            from .dataset import load_dataset
            _, all_tasks = load_dataset(args.dataset)
            tasks = [t for t in all_tasks if t.split == args.split]
        summary, _ = run_benchmark(model, tasks=tasks, output_root=args.output)
        print(json.dumps(summary, indent=2))
        if all(s is None for s in [summary["task_success_rate"]]) or summary["task_success_rate"] == 0:
            sys.exit(1)
    else:
        model = ModelClient()
        try:
            action = model.decide({"request": "Return a stop action for this interface smoke test; no tools required."})
            Action.model_validate(action.model_dump())
            report = {"compatible": True, "model": model.model, "action": action.model_dump(), "tokens": model.tokens,
                "model_settings": model.settings,
                "scope": "Configured adapter JSON action only; business outcomes and GPU training require separate evaluation"}
        except Exception as exc:
            report = {"compatible": False, "model": model.model, "error_type": type(exc).__name__, "reason": str(exc)[:500]}
        path = Path(args.output)
        path.mkdir(parents=True, exist_ok=True)
        (path / "model_smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        if not report["compatible"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
