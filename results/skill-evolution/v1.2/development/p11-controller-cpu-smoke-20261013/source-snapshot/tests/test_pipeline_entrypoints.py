"""Exercise the same subprocess import boundary used by the GPU coordinator."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", [
    "scripts.train_student", "scripts.evaluate_trained_student",
    "scripts.report_post_training", "scripts.validation_loss", "scripts.package_project",
])
def test_module_entrypoints_import_without_pythonpath(module):
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run([sys.executable, "-m", module, "--help"],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
