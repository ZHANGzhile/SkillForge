"""Audit an independent artifact copy with absolute file reads and network blocked."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


def check():
    project = Path.cwd()
    root = project / ".runtime" / ("repeatability-portable-" + uuid.uuid4().hex)
    root.mkdir(parents=True)
    for name in ("scripts", "skillforge", "configs", "data/boundary-study-v1", "results/boundary-study/v1", "results/boundary-repeatability/v1"):
        shutil.copytree(project / name, root / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "model.local.json"))
    for name in ("results/real-v2-frozen/frozen.json", "results/post-training/main-v3/fresh/SFT/identity.json", "docs/BOUNDARY_REPEATABILITY_PLAN.md"):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project / name, target)
    code = '''
from pathlib import Path
import socket
from scripts.evaluate_boundary_repeatability import run
original = Path.open
def restricted(self, *args, **kwargs):
    if self.is_absolute():
        raise AssertionError('Audit attempted absolute-path access: ' + str(self))
    return original(self, *args, **kwargs)
def no_network(*args, **kwargs):
    raise AssertionError('Read-only audit attempted network access')
Path.open = restricted
socket.socket.connect = no_network
socket.create_connection = no_network
print(run(audit=True))
'''
    env = dict(os.environ, PYTHONPATH=str(root), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, encoding="utf-8")
    receipt = {"passed": done.returncode == 0, "independent_copy": str(root), "absolute_artifact_opens": "blocked",
               "network": "blocked", "stdout": done.stdout, "stderr": done.stderr}
    (project / "results/workbench-acceptance/boundary-repeatability-portable.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt))
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(check())
