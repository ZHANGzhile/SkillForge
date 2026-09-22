"""Package source, trained adapters and auditable evidence only after completion."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from skillforge.dataset import digest
from skillforge.training_data import file_hash, load_training_data
from skillforge.training_lineage import audit_parent_checkpoint
from skillforge.evaluation_checkpoints import read_checkpoint


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def readiness():
    plan = read("configs/training-runs.json")
    config = read(plan["config"])
    train, evaluation = Path(plan["root"]), Path(plan["evaluation_root"])
    required = [train / stage / "result.json" for stage in ("smoke", "sft", "dpo")]
    required += [evaluation / (label + "-" + split) / "evaluation.json"
        for label in ("Base", "SFT", "DPO") for split in ("validation", "test")]
    required += [evaluation / "DPO-no-gate-test/evaluation.json", evaluation / "comparison.json",
        evaluation / "frozen_models.json", Path("results/training-environment/nf4-compatibility.json"),
        Path("results/workbench-acceptance/clean-checkout.json")]
    required += [evaluation / "stability" / label / "evaluation.json" for label in ("Base", "SFT", "DPO")]
    missing = [str(path) for path in required if not path.is_file()]
    report = {"ready": False, "missing": missing, "training_root": str(train), "evaluation_root": str(evaluation)}
    if missing:
        return report
    _, _, audit = load_training_data(config["dataset"], config["bundle"], config["real_data"], config["supervision"], config["baseline"])
    for stage in ("smoke", "sft", "dpo"):
        folder = train / stage
        result, run = read(folder / "result.json"), read(folder / "run.json")
        if (result["status"] != "completed" or result["smoke_only"] != (stage == "smoke") or not result["adapter_updated"]
                or result["adapter_hash"] != file_hash(folder / "adapter/adapter_model.safetensors")
                or result["run_hash"] != run["run_hash"] or run["config"] != config or run["corpus_audit"] != audit
                or run["trainer_source_hash"] != file_hash("skillforge/training.py")):
            raise ValueError("training release evidence mismatch: " + stage)
        if run.get("parent_checkpoint") != (audit_parent_checkpoint(run["parent_checkpoint"]["path"], config,
                run["stage"], audit, run["sft_adapter_hash"]) if run.get("parent_checkpoint") else None):
            raise ValueError("parent checkpoint evidence mismatch")
    if not read("results/training-environment/nf4-compatibility.json")["compatible"]:
        raise ValueError("GPU compatibility was not verified")
    for label in ("Base", "SFT", "DPO"):
        folder = evaluation / (label + "-validation")
        from scripts.audit_validation import audit as audit_validation
        identity = read(folder / "identity.json")
        val_report = audit_validation(folder, plan["config"], plan["validation_loss_data"])
        test_identity = read(evaluation / (label + "-test") / "identity.json")
        if any(identity[key] != test_identity[key] for key in ("model_settings", "source_hash", "runtime_config", "config_hash")):
            raise ValueError("validation/test model or protocol mismatch")
        for task_id, task_hash in identity["task_hashes"].items():
            read_checkpoint(folder / "tasks" / (task_id + ".json"), identity, task_id, task_hash)
        if val_report["full_system"]["tasks"] != len(identity["task_hashes"]):
            raise ValueError("validation coverage mismatch")
        if not val_report.get("validation_loss") or val_report["validation_loss"]["examples"] <= 0:
            raise ValueError("held-out validation loss is missing")
        if identity["likelihood_manifest_sha256"] != file_hash(Path(plan["validation_loss_data"]) / "manifest.json"):
            raise ValueError("validation likelihood corpus mismatch")
    from scripts.report_post_training import summarize_runs
    comparison = summarize_runs(evaluation)
    from scripts.evaluate_stability import audit as audit_stability
    stability = {label: audit_stability(evaluation, label) for label in ("Base", "SFT", "DPO")}
    source_hash = digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path("skillforge").glob("*.py"))})
    if comparison["identity"]["source_hash"] != source_hash:
        raise ValueError("current source differs from the evaluated release")
    cpu_check = read("results/workbench-acceptance/clean-checkout.json")
    if not cpu_check["passed"] or cpu_check.get("source_hash") != source_hash:
        raise ValueError("the current release needs a passing source-only regression")
    return {**report, "ready": True, "source_hash": source_hash, "corpus_hash": audit["corpus_hash"],
        "summary": comparison["summary"], "stability_pass_all": {label: row["pass_all_repeats"] for label, row in stability.items()},
        "scope": "bounded synthetic local research project; no universal capability claim"}


def package(output, report):
    plan, config = read("configs/training-runs.json"), read(read("configs/training-runs.json")["config"])
    selected = {}
    def add(path, exclude_checkpoints=False):
        path = Path(path)
        resolved = path.resolve()
        if ROOT != resolved and ROOT not in resolved.parents:
            raise ValueError("release input must stay within the project")
        for file in sorted(path.rglob("*")) if path.is_dir() else [path]:
            if not file.is_file() or file.is_symlink():
                continue
            relative = file.resolve().relative_to(ROOT)
            if "__pycache__" in relative.parts or file.suffix == ".pyc" or file.name in {"model.local.json", "deployment.local.json"}:
                continue
            if exclude_checkpoints and any(part.startswith("checkpoint-") for part in relative.parts):
                continue
            selected[relative.as_posix()] = file
    for name in ("skillforge", "scripts", "tests", "configs", "docs", "models", ".github", "README.md", "pyproject.toml", "package.json",
            "requirements-lock.txt", "requirements-training.txt", "requirements-training-lock.txt", "requirements-report.txt", "Dockerfile", "compose.yaml", ".env.example", ".gitignore"):
        add(name)
    for path in Path(".").glob("*.cmd"):
        add(path)
    for path in (config["dataset"], Path(config["bundle"]).parent, Path(config["baseline"]).parent,
            config["real_data"], config["supervision"], "results/real-v2-combined", "results/training-environment",
            "results/workbench-acceptance", "results/training-diagnostics", plan["evaluation_root"]):
        add(path)
    add(plan["validation_loss_data"])
    for entry in read("configs/evidence.json"):
        add(Path(entry["path"]).parent)
    add(plan["root"], exclude_checkpoints=True)
    for checkpoint in plan.get("resume_checkpoints", {}).values():
        add(checkpoint)
        add(Path(checkpoint).parent / "run.json")
        for name in ("training-source.py", "pipeline-plan.json"):
            add(Path(checkpoint).parent.parent / name)
    target = Path(output).resolve()
    if ROOT not in target.parents or target.exists():
        raise ValueError("choose a new release file inside the project")
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"readiness": report, "files": {}}
    temporary = target.with_suffix(".partial")
    with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        for name, file in sorted(selected.items()):
            manifest["files"][name] = {"bytes": file.stat().st_size, "sha256": file_hash(file)}
            archive.write(file, "SkillForge/" + name)
        archive.writestr("SkillForge/release-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(temporary) as archive:
        for name, entry in manifest["files"].items():
            h = hashlib.sha256()
            with archive.open("SkillForge/" + name) as source:
                for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
                    h.update(block)
            if h.hexdigest() != entry["sha256"]:
                raise ValueError("release archive content mismatch: " + name)
    temporary.replace(target)
    return {"path": str(target), "bytes": target.stat().st_size, "sha256": file_hash(target), "files": len(selected)}


if __name__ == "__main__":
    import os
    os.chdir(ROOT)
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--output", default="release/SkillForge.zip")
    args = parser.parse_args()
    status = readiness()
    Path("results").mkdir(exist_ok=True)
    Path("results/release-readiness.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.check_only or not status["ready"]:
        print(json.dumps(status, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(package(args.output, status), indent=2))
    if not status["ready"]:
        raise SystemExit(2)
