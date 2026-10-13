"""P0 development identity and cost gate. Does not open any historical test data."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

from skillforge.evolution_schemas import fingerprint


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ValueError(f"immutable artifact differs: {path}")
        return
    with path.open("x", encoding="utf-8") as stream:
        stream.write(content)


def baseline(root):
    paths = subprocess.check_output(["git", "ls-files", "-z"]).decode("utf-8").split("\0")
    # Hash existing tracked code/config/data/results. No semantic test data reads.
    files = {p: file_hash(p) for p in paths if p and Path(p).is_file()}
    value = {"head": subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip(),
        "files": files, "scope": "SHA256 of tracked pre-evolution files; no experiment interpretation"}
    write_new(Path(root)/"baseline.json", value)
    return {"files": len(files), "manifest_hash": fingerprint(value)}


def audit_baseline(root):
    value = json.loads((Path(root)/"baseline.json").read_text(encoding="utf-8"))
    changed = [p for p, h in value["files"].items() if not Path(p).is_file() or file_hash(p) != h]
    if changed:
        raise ValueError(f"protected historical files changed: {changed}")
    return {"passed": True, "files": len(value["files"])}


def cost_plan(config, smoke=None):
    model = config["model_layer"]
    worlds = model.get("worlds",config["worlds"])
    if not worlds or not set(worlds)<=set(config["worlds"]):
        raise ValueError("model worlds must be a nonempty predeclared subset")
    groups = len(worlds)*len(config["methods"])*model["repeats"]
    stages = {"validation_full_system": groups*(model["model_validation"]+model["model_stable_validation"]),
        "final_full_system": groups*(model["model_test"]+model["model_stable_test"]),
        "decision_probes": groups*(model["model_validation"]+model["model_test"]),
        "before_reference": len(worlds)*(model["model_validation"]+model["model_stable_validation"]+model["model_test"]+model["model_stable_test"]),
        "seed_runs": len(worlds)*config["splits"]["seed"],
        "sequential_epochs": 2*len(config["methods"])*(model["model_validation"]+model["model_stable_validation"]+model["model_test"]+model["model_stable_test"])}
    total = sum(stages.values())
    retry_tasks = math.ceil(total*model.get("global_retry_fraction",model["infrastructure_retries"]))
    estimate = None if smoke is None else {"hours_at_p95": total*smoke["p95_seconds"]/3600,
        "tokens_at_mean": total*smoke["mean_tokens"],
        "hours_with_retry_reserve": (total+retry_tasks)*smoke["p95_seconds"]/3600,
        "tokens_with_retry_reserve": (total+retry_tasks)*smoke["mean_tokens"]}
    return {"status": "pending_real_model_smoke" if smoke is None else "estimated_not_frozen",
        "worlds": worlds, "stages": stages, "total_tasks": total, "estimates": estimate,
        "global_retry_tasks": retry_tasks,
        "formal_model_execution_enabled": False,
        "scope": "Conservative task accounting; real measurements and source identity required before freeze"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/active-evolution-v1.json")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    root = Path(config["output"])/"preparation"
    if args.audit:
        print(json.dumps(audit_baseline(root)))
    else:
        result = baseline(root)
        write_new(root/"cost-plan.json", cost_plan(config))
        write_new(root/"protocol-draft.json", config)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
