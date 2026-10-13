"""Real saved invalid output stays failed; the auditor must not repair actions."""
import json
import shutil

import pytest

from scripts.run_skill_evolution import ROOT
from scripts.audit_boundary_stage2_arm_v2 import audit_arm
from skillforge.skill_evolution.agent_evidence import read
from skillforge.skill_evolution.catalog import Catalog
from skillforge.boundary_runtime.catalog import BoundaryCatalog


def collected():
    root = ROOT / "results/skill-evolution/v1.3/formal-P11-v1"
    folder = root / "agent/physical/9"
    if not folder.exists(): pytest.skip("requires the actual saved formal invalid-Action arm")
    p = read(root / "protocol.json")
    base = Catalog.load(root / "catalog.json")
    return folder, (read(folder / "case.json"), BoundaryCatalog(base.entries(), read(folder / "boundaries.json")),
        read(root / "agent/model-identity.json"), p["limits"]), read(folder / "charge-context.json")


def test_actual_known_usage_invalid_action_remains_failed_with_exact_fees():
    folder, args, charges = collected()
    value = audit_arm(folder, *args, **charges)
    assert value["row"]["agent"]["outcome"] == "error"
    assert not value["row"]["verification"]["task_success"]
    request = value["row"]["agent"]["model_requests"][-1]
    assert request["status"] == "failed" and request["charged_tokens"] == 3905 and request["usage_known"]
    assert value["status"]["charged_tokens"] == 14852


def test_corrected_action_cannot_replace_a_real_failed_model_output(tmp_path):
    folder, args, charges = collected()
    copied = tmp_path / "arm"; shutil.copytree(folder, copied)
    row = read(copied / "result.json")
    row["agent"]["steps"][-1]["model_response"] = '{"type":"refuse"}'
    (copied / "result.json").write_text(json.dumps(row), encoding="utf-8")
    with pytest.raises(ValueError): audit_arm(copied, *args, **charges)
