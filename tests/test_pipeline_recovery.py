import pytest

from scripts import run_training_pipeline as pipeline


def test_progress_file_sharing_failure_resumes_without_changing_protocol(tmp_path, monkeypatch):
    log = tmp_path / "failure.log"
    log.write_text("PermissionError: [WinError 5] 'progress.tmp' -> 'progress.json'")
    calls = []
    def child(stage, args):
        calls.append(list(args))
        if len(calls) == 1:
            raise pipeline.ChildFailure(stage, 1, log)
    monkeypatch.setattr(pipeline, "_command_once", child)
    monkeypatch.setattr(pipeline, "status", lambda *args, **kwargs: None)
    args = ["-m", "scripts.evaluate_trained_student", "--label", "Base", "--output", str(tmp_path)]
    pipeline.command("Base-validation", args)
    assert calls == [args, args + ["--resume"]]


def test_cuda_failure_is_not_retried_as_file_contention(tmp_path, monkeypatch):
    log = tmp_path / "failure.log"
    log.write_text("RuntimeError: CUDA out of memory")
    calls = []
    def child(stage, args):
        calls.append(args)
        raise pipeline.ChildFailure(stage, 1, log)
    monkeypatch.setattr(pipeline, "_command_once", child)
    with pytest.raises(pipeline.ChildFailure, match="failed"):
        pipeline.command("Base-validation", ["-m", "scripts.evaluate_trained_student"])
    assert len(calls) == 1


def test_coordinator_atomic_write_retries_are_bounded(monkeypatch):
    from scripts import coordinator_io
    attempts = []
    def unavailable(path, value):
        attempts.append((path, value))
        raise PermissionError("shared by Windows reader")
    monkeypatch.setattr(coordinator_io, "write_once", unavailable)
    monkeypatch.setattr(coordinator_io.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError):
        coordinator_io.atomic_json("progress.json", {"step": 1})
    assert len(attempts) == 6
    assert all(item == ("progress.json", {"step": 1}) for item in attempts)
