"""Continue the existing serial evaluation with predeclared repeats and plots.

Waits for the main coordinator; never runs a second GPU workload beside it.
Failures remain explicit and require resuming this command after remediation.
"""
import json
import os
from pathlib import Path
import subprocess
import time

from scripts.coordinator_io import atomic_json


ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    from scripts.run_training_pipeline import command, status, PLAN, TRAIN, EVAL
    from skillforge.jobs import Worker, JobStore
    watcher = Worker(JobStore(".runtime/research-finish-lock"), lambda *_: None)
    watcher.start()
    marker = Path(".runtime/research-finish.json")
    guard = None
    try:
        while True:
            state = json.loads(Path(".runtime/training-pipeline.json").read_text(encoding="utf-8"))
            atomic_json(marker, {"stage": "waiting_for_main_evaluation", "at": time.time(), "main_stage": state["stage"]})
            if state["stage"] == "failed":
                raise RuntimeError("main evaluation failed: " + state.get("message", "inspect its log"))
            if state["stage"] == "completed":
                break
            if time.time() - state["at"] > 120:
                raise RuntimeError("main evaluation heartbeat is stale; do not overlap GPU owners")
            time.sleep(10)
        # Same lock as the main coordinator: even a premature status update
        # cannot authorize overlapping GPU work.
        guard = Worker(JobStore(".runtime/training-pipeline-lock"), lambda *_: None)
        guard.start()
        for label in ("Base", "SFT", "DPO"):
            atomic_json(marker, {"stage": "stability-" + label, "at": time.time()})
            args = ["-m", "scripts.evaluate_stability", "--config", PLAN["config"], "--root", str(EVAL), "--label", label]
            if label != "Base":
                args += ["--adapter", str(TRAIN / label.lower() / "adapter")]
            command("stability-" + label, args)
        status("writing_research_report")
        subprocess.run([str(ROOT / ".venv/Scripts/python.exe"), "-m", "scripts.write_research_report"], cwd=ROOT, check=True)
        atomic_json(marker, {"stage": "completed", "at": time.time(), "report": "docs/RESEARCH_REPORT.md", "deployment_pending": True})
        status("completed", training_root=str(TRAIN), evaluation_root=str(EVAL), stability_completed=True,
            report="docs/RESEARCH_REPORT.md", deployment_pending=True)
    except BaseException as exc:
        atomic_json(marker, {"stage": "failed", "at": time.time(), "error": type(exc).__name__, "message": str(exc)})
        if guard is not None:
            status("failed", error=type(exc).__name__, message=str(exc))
        raise
    finally:
        if guard is not None:
            guard.close()
        watcher.close()


if __name__ == "__main__":
    main()
