"""Freeze train-derived skills before paired test-set evaluation."""
import csv
import json
import subprocess
import uuid
from pathlib import Path

from .benchmark import run_benchmark, summarize
from .dataset import digest, load_dataset
from .decision_eval import evaluate_decisions
from .learning import validate_skill
from .policies import POLICY_VERSION
from .provenance import audit_sources
from .schemas import SkillContract
from .skills import compile_skill, compile_naive_skill


def collect(dataset_dir, model_factory, output_dir, engineering=False, failure_fixtures=False):
    from .model import ScriptedPolicy
    from .schemas import Action
    if failure_fixtures and not engineering:
        raise ValueError("intentional failure fixtures require engineering mode")
    manifest, tasks = load_dataset(dataset_dir)
    model = model_factory()
    if model.model == "scripted-engineering-only" and not engineering:
        raise ValueError("scripted model requires engineering mode")
    if model.model != "scripted-engineering-only":
        model.decide({"request": "Return a stop action for interface compatibility only."})
    root = Path(output_dir) / str(uuid.uuid4())
    root.mkdir(parents=True)
    train = [t for t in tasks if t.split == "train"]
    _, records = run_benchmark(model, train, output_root=root, label="train-source")
    if failure_fixtures:
        class CounterexampleFixture(ScriptedPolicy):
            def decide(self, context):
                if not context["history"]:
                    name = {"modify_address": "update_shipping_address", "cancel_order": "cancel_order", "refund": "issue_refund"}[context["family"]]
                    return Action(type="tool", name=name, arguments=context["parameters"])
                return Action(type="stop")
        negative_tasks = [t for t in train if t.family in {"modify_address", "cancel_order", "refund"}
            and (t.fixture.get("shipment") in {"SHIPPED", "PROCESSING"} or t.fixture.get("risk") == "HIGH" or t.fixture.get("invalid_address")
                 or t.fixture.get("over") or t.fixture.get("payment") == "FAILED")]
        _, failed = run_benchmark(CounterexampleFixture(), negative_tasks, output_root=root, label="explicit-counterexample-fixtures")
        records += failed
    source_path = root / "source_trajectories.jsonl"
    source_path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    report = {"source_path": str(source_path.resolve()), "dataset_hash": manifest["dataset_hash"],
        "model": model.model, "engineering_only": engineering, "intentional_failure_fixtures": failure_fixtures,
        **audit_sources(records, tasks, allow_engineering=engineering)}
    (root / "collection.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def read_sources(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def prepare(dataset_dir, source_path, output_dir, engineering=False, families=("modify_address", "cancel_order"), max_refinements=2):
    from .refinement import validate_and_refine
    if not families or len(set(families)) != len(families) or not set(families) <= {"modify_address", "cancel_order", "refund"}:
        raise ValueError("invalid or duplicate compiler families")
    manifest, tasks = load_dataset(dataset_dir)
    records = read_sources(source_path)
    source_report = audit_sources(records, tasks, allow_engineering=engineering)
    skills, candidates, naive_skills, validation, refinement = [], [], [], {}, {}
    for family in families:
        skill = compile_skill(records, family)
        candidates.append(skill.model_dump())
        naive_skills.append(compile_naive_skill(records, family).model_dump())
        skill, refinement[family] = validate_and_refine(skill, records, [t for t in tasks if t.split == "validation"], max_refinements=max_refinements)
        validation[family] = refinement[family]["history"][-1]["validation"]
        if skill.status == "VERIFIED":
            skills.append(skill.model_dump())
    # Freeze complete train corpus for B1. Artifact hashes bind exactly what is reused.
    bundle = {"format": "skillforge-frozen-v1", "dataset_hash": manifest["dataset_hash"], "policy_version": POLICY_VERSION,
        "engineering_only": source_report["engineering_sources"], "source_audit": source_report,
        "source_hash": digest(records), "memory": records, "skills": skills, "candidates": candidates,
        "naive_skills": naive_skills, "validation": validation, "refinement": refinement}
    bundle["bundle_hash"] = digest(bundle)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / "frozen.json"
    if target.exists() and json.loads(target.read_text(encoding="utf-8")) != bundle:
        raise ValueError("frozen bundle is immutable; choose a new output directory")
    target.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return bundle


def load_bundle(path, dataset_hash):
    bundle = json.loads(Path(path).read_text(encoding="utf-8"))
    if bundle["bundle_hash"] != digest({k: v for k, v in bundle.items() if k != "bundle_hash"}):
        raise ValueError("frozen bundle hash mismatch")
    if bundle["dataset_hash"] != dataset_hash or bundle["policy_version"] != POLICY_VERSION:
        raise ValueError("frozen bundle dataset/policy mismatch")
    if digest(bundle["memory"]) != bundle["source_hash"]:
        raise ValueError("frozen source corpus mismatch")
    skills = [SkillContract.model_validate(s) for s in bundle["skills"]]
    if any(s.status != "VERIFIED" for s in skills):
        raise ValueError("bundle must contain verified skills")
    return bundle, skills


def compare(dataset_dir, bundle_path, model_factory, output_dir="results/comparisons", repeats=1, engineering=False, ablation=False):
    if repeats < 1:
        raise ValueError("repeats must be positive")
    manifest, tasks = load_dataset(dataset_dir)
    bundle, skills = load_bundle(bundle_path, manifest["dataset_hash"])
    if bundle["engineering_only"] and not engineering:
        raise ValueError("scripted source corpus cannot be reported as a research comparison")
    audit_sources(bundle["memory"], tasks, allow_engineering=engineering)
    probe = model_factory()
    if probe.model == "scripted-engineering-only" and not engineering:
        raise ValueError("scripted model requires engineering mode")
    # Fail once before launching hundreds of requests against an unavailable endpoint.
    if probe.model != "scripted-engineering-only":
        probe.decide({"request": "Return a stop action for interface compatibility only."})
    root = Path(output_dir) / str(uuid.uuid4())
    root.mkdir(parents=True)
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        commit = None
    config = {"dataset_hash": manifest["dataset_hash"], "bundle_hash": bundle["bundle_hash"], "model": probe.model,
        "policy_version": POLICY_VERSION, "repeats": repeats, "engineering_only": engineering,
        "git_commit": commit, "ablation": ablation,
        "baseline_definition": "B2 uses success-only naive contracts frozen before validation. B3 uses success+failure+policy contracts admitted by validation. B3-no-gate isolates runtime gate with VERIFIED metadata retained.",
        "verified_skill_count": len(skills)}
    code_root = Path(__file__).parent
    config["source_code_hash"] = digest({p.name: p.read_text(encoding="utf-8") for p in sorted(code_root.glob("*.py"))})
    config["dataset_audit"] = manifest["audit"]
    (root / "experiment.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    testing = [t for t in tasks if t.split == "test"]
    naive = [SkillContract.model_validate(s) for s in bundle["naive_skills"]]
    variants = [("B0", [], [], True), ("B1", [], bundle["memory"], True),
        ("B2", naive, [], False), ("B3", skills, [], True)]
    if ablation:
        variants.append(("B3-no-gate", skills, [], False))
    summaries, per_variant = [], {}
    for label, contracts, memory, use_gate in variants:
        results = []
        for repeat in range(repeats):
            _, batch = run_benchmark(model_factory(), testing, skills=contracts, memory=memory, verified=use_gate, output_root=root / label, label=label)
            results.extend(batch)
        per_variant[label] = results
        row = {"label": label, **summarize(results)}
        row["pass_all_repeats"] = sum(all(r["verification"]["task_success"] for r in results if r["task_id"] == t.task_id) for t in testing) / len(testing)
        row["repeat_count"] = repeats
        summaries.append(row)
        (root / "progress.json").write_text(json.dumps({"completed_variants": [s["label"] for s in summaries]}), encoding="utf-8")
    by_level = {label: {level: summarize([r for r in results if r["level"] == level]) for level in "ABCDE"} for label, results in per_variant.items()}
    decisions = [evaluate_decisions(model_factory(), skill, testing) for skill in skills]
    report = {"config": config, "summary": summaries, "by_level": by_level, "decision_evaluation": decisions,
        "artifact_dir": str(root.resolve()), "causal_ntr": None,
        "limitations": ["bounded domain compiler and repair", "single synthetic environment", "repeat stability is descriptive; no significance claim"]}
    (root / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (root / "comparison.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    return report
