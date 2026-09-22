"""Run CPU regression from a source-only copy without this machine's artifacts."""
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from skillforge.dataset import digest


def check():
    source = Path(__file__).resolve().parents[1]
    root = source / ".runtime" / ("clean-check-" + uuid.uuid4().hex)
    root.mkdir(parents=True)
    for name in ("skillforge", "tests", "scripts", "configs"):
        shutil.copytree(source / name, root / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "model.local.json"))
    shutil.copy2(source / "pyproject.toml", root / "pyproject.toml")
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("SKILLFORGE_"):
            env.pop(key)
    env["PYTHONPATH"] = str(root)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=root, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    (root / "pytest.log").write_text(completed.stdout, encoding="utf-8")
    report = {"passed": completed.returncode == 0, "source_only_copy": str(root),
        "source_hash": digest({p.name: p.read_text(encoding="utf-8") for p in sorted((root / "skillforge").glob("*.py"))}),
        "excluded": ["data", "results", ".runtime", "configs/model.local.json"],
        "python": sys.executable, "returncode": completed.returncode, "log": str(root / "pytest.log")}
    output = source / "results" / "workbench-acceptance" / "clean-checkout.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(completed.stdout)
    print(json.dumps(report, indent=2))
    return completed.returncode


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(check())
