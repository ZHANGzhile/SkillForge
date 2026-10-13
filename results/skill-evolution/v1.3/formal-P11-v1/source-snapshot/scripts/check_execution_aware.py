"""Run all tests in a source-only copy and audit frozen/historical evidence."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from scripts.active_evolution_formal import load_protocol
from scripts.prepare_active_evolution import audit_baseline, file_hash
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint


def main():
    source = Path(__file__).resolve().parents[1]
    identity = "source-check-" + uuid.uuid4().hex
    copied = source / ".runtime" / ("execution-aware-" + identity)
    copied.mkdir(parents=True)
    for name in ("skillforge", "tests", "scripts", "configs"):
        shutil.copytree(source / name, copied / name, ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "model.local.json", "deployment.local.json"))
    shutil.copy2(source / "pyproject.toml", copied / "pyproject.toml")
    env = {k: v for k, v in os.environ.items() if not k.startswith("SKILLFORGE_")}
    env.update(PYTHONPATH=str(copied), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=copied, env=env,
                            capture_output=True, text=True, encoding="utf-8")
    historical = audit_baseline(source / "results/active-evolution/v1/preparation")
    protocol = load_protocol(source / "results/active-evolution/v1/formal-v1")
    output = source / "results/active-evolution/v1.1/development" / identity
    output.mkdir(parents=True)
    (output / "pytest.log").write_text(result.stdout+result.stderr, encoding="utf-8")
    report = {"passed": result.returncode == 0, "returncode": result.returncode, "historical_files": historical,
              "v1_frozen_protocol_hash": fingerprint(protocol), "v1_source_count": len(protocol["sources"]),
              "source_only_copy": str(copied), "sources": {str(p.relative_to(copied)): file_hash(p)
                   for name in ("skillforge", "tests", "scripts") for p in sorted((copied / name).rglob("*.py"))}}
    report["workspace_drift_after_copy"] = [p for p, digest in report["sources"].items()
                                              if file_hash(source / p) != digest]
    immutable_json(output / "report.json", report)
    print(result.stdout)
    print(json.dumps({"report": str(output / "report.json"), "passed": report["passed"], "historical": historical}))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
