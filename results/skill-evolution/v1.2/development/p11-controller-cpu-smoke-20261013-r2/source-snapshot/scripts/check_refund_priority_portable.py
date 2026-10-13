"""Independent-directory, offline evidence audit without absolute artifact reads."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid


def check():
    project = Path.cwd()
    root = project / ".runtime" / ("refund-priority-portable-" + uuid.uuid4().hex)
    root.mkdir(parents=True)
    for name in ("scripts", "skillforge", "configs", "data/boundary-study-v1", "results/boundary-study/v1", "results/refund-priority/v1"):
        shutil.copytree(project / name, root / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "model.local.json"))
    for name in ("results/real-v2-frozen/frozen.json", "results/post-training/main-v3/fresh/SFT/identity.json", "docs/REFUND_PRIORITY_PLAN.md"):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(project / name, target)
    code = '''
from pathlib import Path
import socket
from scripts.evaluate_refund_priority import run
original = Path.open
def restricted(self, *args, **kwargs):
    if self.is_absolute():
        raise AssertionError('Absolute artifact read: ' + str(self))
    return original(self, *args, **kwargs)
def no_network(*args, **kwargs):
    raise AssertionError('Audit attempted network access')
Path.open = restricted
socket.socket.connect = no_network
socket.create_connection = no_network
print(run(audit=True))
'''
    done = subprocess.run([sys.executable, "-c", code], cwd=root,
        env=dict(os.environ, PYTHONPATH=str(root), PYTHONUTF8="1", PYTHONIOENCODING="utf-8"), capture_output=True, text=True, encoding="utf-8")
    receipt = {"passed": done.returncode == 0, "independent_copy": str(root), "network": "blocked", "absolute_artifact_opens": "blocked",
        "stdout": done.stdout, "stderr": done.stderr}
    (project / "results/workbench-acceptance/refund-priority-portable.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt))
    return done.returncode


if __name__ == "__main__":
    raise SystemExit(check())
