"""UI-only read evidence tests; outside frozen model execution source index."""
import hashlib
import json

import pytest

from .formal import formal_trace
from ..evolution_schemas import fingerprint


def test_trace_is_readonly_and_binds_its_actual_arm_audit(tmp_path):
    folder = tmp_path / "agent/physical/0"; folder.mkdir(parents=True)
    path = folder / "result.json"; path.write_text('{"agent":{"steps":[]}}', encoding="utf-8")
    body = {"passed": True, "evidence_index": {"result.json": hashlib.sha256(path.read_bytes()).hexdigest()}}
    (folder / "independent-audit.json").write_text(json.dumps({**body, "hash": fingerprint(body)}))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert formal_trace(0, tmp_path)["status"] == "ARM_REPLAY_AUDITED"
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    path.write_text('{"agent":{"steps":["changed"]}}', encoding="utf-8")
    with pytest.raises(ValueError, match="evidence index"): formal_trace(0, tmp_path)


def test_incomplete_and_arbitrary_path_traces_are_not_served(tmp_path):
    for index in (-1, "../secret", 100):
        with pytest.raises(KeyError): formal_trace(index, tmp_path)
