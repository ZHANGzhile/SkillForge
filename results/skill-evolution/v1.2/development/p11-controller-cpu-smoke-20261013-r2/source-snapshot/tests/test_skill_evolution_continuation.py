"""End-to-end scripted RPC fixture; not real-model evidence."""
from contextlib import nullcontext
import json
import queue
import threading

import pytest

import scripts.continue_skill_evolution_selection as controller
import scripts.execution_aware_gpu_lease as lease
from skillforge.schemas import Action
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.runtime import run_agent
from test_skill_evolution_fork_audit import evidence, MessagesModel


class ScriptedSession:
    settings = MessagesModel.settings
    def __init__(self, *args, **kwargs):
        self.events, self.replies = queue.Queue(), queue.Queue()
        self.thread = None

    def send(self, packet):
        if packet["type"] != "run":
            self.replies.put(packet)
            return
        def work():
            def persist(value):
                self.events.put({"type": "checkpoint", "value": value})
                assert self.replies.get(timeout=5)["type"] == "checkpoint_saved"
            def tool(name, args, key, source):
                self.events.put({"type": "tool", "name": name, "arguments": args, "key": key, "source": source})
                response = self.replies.get(timeout=5)
                assert response["type"] == "tool_result"
                return response["result"]
            model = MessagesModel([Action(type="tool", name="cancel_order", arguments=packet["task"]["parameters"])])
            agent = run_agent(model, packet["task"], Catalog(packet["catalog"]), tool,
                              persist=persist, public_start=packet["public_start"], **packet["limits"])
            self.events.put({"type": "completed", "result": agent})
        self.thread = threading.Thread(target=work)
        self.thread.start()

    def receive(self, timeout=5):
        return self.events.get(timeout=timeout)

    def close(self):
        if self.thread:
            self.thread.join(timeout=5)
            assert not self.thread.is_alive()


def set_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def parent(evidence, tmp_path, monkeypatch):
    # Fixture evidence uses the same compiler/runtime as the parent. This is
    # a private temporary ROOT, not a production results rewrite.
    monkeypatch.setattr(controller, "ROOT", tmp_path)
    original_digest = controller.digest_file
    def digest(path):
        path = controller.Path(path)
        if not path.exists() and path.is_relative_to(tmp_path):
            path = controller.Path(__file__).resolve().parents[1] / path.relative_to(tmp_path)
        return original_digest(path)
    monkeypatch.setattr(controller, "digest_file", digest)
    import shutil
    for path in ["scripts/evolution_budget.py", "scripts/continue_skill_evolution_selection.py",
                 "scripts/run_skill_evolution.py", "scripts/run_skill_evolution_selection.py"]:
        dest = tmp_path / path; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(controller.Path(__file__).resolve().parents[1] / path, dest)
    reg = controller.read(evidence / "registration.json")
    reg["config"]["smoke"] = {"max_model_tokens": 500000, "max_wall_seconds": 1800}
    reg["protocol_hash"] = controller.fingerprint({k: v for k, v in reg.items() if k != "protocol_hash"})
    set_json(evidence / "registration.json", reg)
    report = controller.read(evidence / "report.json")
    report.update({"charged_tokens_including_incomplete": 0, "wall_seconds": 0, "shared_prior_cost": [],
                   "shared_total_charged_tokens": 0, "shared_total_wall_seconds": 0, "failure": "budget stop"})
    set_json(evidence / "report.json", report)
    monkeypatch.setattr(controller, "ModelSession", ScriptedSession)
    monkeypatch.setattr(lease, "GPUServiceLease", nullcontext)
    return evidence


@pytest.mark.parametrize("evidence", [True], indirect=True)
def test_continuation_inherits_without_rerun_and_audits_every_request(parent, tmp_path):
    old_bytes = (parent / "report.json").read_bytes()
    result = controller.continue_run(parent, tmp_path / "continued")
    assert result["status"] == "complete" and result["n"] == 2 and result["incremental_cases"] == 1
    assert result["eoc"] == 2 and result["charged_tokens_including_incomplete"] == 0
    assert (parent / "report.json").read_bytes() == old_bytes
    receipt = controller.audit_continuation(tmp_path / "continued")
    assert receipt["run_completed"] and receipt["pairs"] == 1
    assert len(list((tmp_path / "continued").glob("*/*/admissions/*.json"))) == 1


@pytest.mark.parametrize("evidence", [True], indirect=True)
def test_continuation_rejects_already_started_arm(parent):
    folder = parent / "p1-test/withheld"
    folder.mkdir()
    with pytest.raises(ValueError, match="already started"):
        controller.validate_parent(parent)


@pytest.mark.parametrize("evidence", [True], indirect=True)
def test_continuation_rejects_unreconciled_pending(parent):
    report = controller.read(parent / "report.json")
    report["unfinished_task_budget"] = {"used": {"tokens": 16384}}
    set_json(parent / "report.json", report)
    with pytest.raises(ValueError, match="pending"):
        controller.validate_parent(parent)


@pytest.mark.parametrize("evidence", [True], indirect=True)
def test_continuation_audit_rejects_changed_inherited_bytes(parent, tmp_path):
    output = tmp_path / "continued"
    controller.continue_run(parent, output)
    (output / "p1-test/provided/result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="inherited evidence changed"):
        controller.audit_continuation(output)


@pytest.mark.parametrize("evidence", [True], indirect=True)
def test_continuation_audit_recomputes_unknown_inflight_cost(parent, tmp_path):
    output = tmp_path / "continued"
    controller.continue_run(parent, output)
    folder = output / "p1-test/withheld"
    (folder / "result.json").unlink()
    (output / "p1-test/pair-check.json").unlink()
    import shutil
    for path in (folder / "checkpoints").iterdir():
        if path.name != "0":
            shutil.rmtree(path)
    report = controller.read(output / "report.json")
    report.update(status="blocked_or_incomplete", failure="fixture crash after approval", n=1, pairs=0, eoc=1,
                  incremental_cases=0, charged_tokens_including_incomplete=16384,
                  shared_total_charged_tokens=16384, engineering_passed=False,
                  unfinished_task_budget=controller.read(folder / "checkpoints/0/snapshot.json")["body"]["runtime"]["budget"])
    set_json(output / "report.json", report)
    assert controller.audit_continuation(output)["incremental_charged_tokens"] == 16384
    report.update(charged_tokens_including_incomplete=0, shared_total_charged_tokens=0)
    set_json(output / "report.json", report)
    with pytest.raises(ValueError, match="accounting mismatch"):
        controller.audit_continuation(output)
