"""V2 adapter over the frozen v1 evaluator; v1 files and evidence stay immutable."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import time

from scripts import evaluate_refund_priority as engine
from scripts.coordinator_io import atomic_json
from scripts.evaluate_reuse_ablation import read
from scripts.refund_priority_scoped import ScopedPriorityClient, activation_proof, enabled, render
from skillforge.jobs import JobStore, Worker
from skillforge.training_data import file_hash

PLAN = "configs/refund-priority-scoped.json"
original_prepare = engine.prepare


def source_input_proof():
    root = Path("results/refund-priority/v1")
    completion = read(root / "completed.json")
    inputs = read(root / "freeze.json")["inputs"]
    counts = {"original_contexts": 0, "unchanged": 0, "activated": 0}
    for key, expected_hash in completion["runs"].items():
        path = root / "runs" / (key + ".json")
        if file_hash(path) != expected_hash:
            raise ValueError("v1 source evidence changed")
        row = read(path)
        contexts = [s["context"] for s in row["steps"]] if "steps" in row else [inputs[row["task_id"]]["original_context"]]
        for context in contexts:
            a, b = (json.dumps(render(context, arm), ensure_ascii=False) for arm in ("control", "priority"))
            if (a != b) != enabled(context):
                raise ValueError("v2 activation differs on real v1 source context")
            counts["original_contexts"] += 1
            counts["activated" if a != b else "unchanged"] += 1
    return counts


def _prepare():
    plan, source, root, tasks, boundaries, frozen = original_prepare()
    tasks = {tid: t for tid, t in tasks.items() if t.family == "refund"}
    frozen["task_hashes"] = {tid: h for tid, h in frozen["task_hashes"].items() if tid in tasks}
    frozen["jobs"] = {k: j for k, j in frozen["jobs"].items() if j["task"] in tasks}
    used = {j["input"] for j in frozen["jobs"].values() if "input" in j}
    frozen["inputs"] = {h: v for h, v in frozen["inputs"].items() if h in used}
    frozen["order"] = {stage: [k for k in order if k in frozen["jobs"]] for stage, order in frozen["order"].items()}
    files = ("docs/REFUND_PRIORITY_SCOPED_PLAN.md", "scripts/refund_priority_scoped.py", __file__,
        "configs/refund-priority.json", "results/refund-priority/v1/freeze.json", "results/refund-priority/v1/completed.json", "results/refund-priority/v1/report.json")
    # __file__ is normalized explicitly; never freeze a machine-specific source path.
    for path in files:
        p = "scripts/evaluate_refund_priority_scoped.py" if path == __file__ else path
        frozen["files"][p] = file_hash(p)
    frozen["activation_proof"] = activation_proof()
    frozen["source_input_proof"] = source_input_proof()
    return plan, source, root, tasks, boundaries, frozen


def progress(root, stage, done, total, **extra):
    value = {"stage": stage, "completed": done, "total": total, "at": time.time(), **extra}
    atomic_json(root / "progress.json", value)
    Path("docs/REFUND_PRIORITY_SCOPED_LIVE.md").write_text("# 退款优先级v2实时记录\n\n```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```\n", encoding="utf-8")


@contextmanager
def configured():
    bindings = {"PLAN": PLAN, "render": render, "PriorityClient": ScopedPriorityClient, "prepare": _prepare, "progress": progress}
    previous = {key: getattr(engine, key) for key in bindings}
    try:
        for key, value in bindings.items():
            setattr(engine, key, value)
        yield
    finally:
        for key, value in previous.items():
            setattr(engine, key, value)


def prepare():
    with configured():
        return _prepare()


def run(audit=False):
    with configured():
        return engine.run(audit=audit)


def freeze():
    with configured():
        return engine.freeze()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    for arg in ("freeze", "run", "audit"):
        group.add_argument("--" + arg, action="store_true")
    args = parser.parse_args()
    lock = None
    try:
        if not args.audit:
            lock = Worker(JobStore(".runtime/refund-priority-scoped-lock"), lambda *_: None)
            lock.start()
        print(json.dumps(freeze() if args.freeze else run(audit=args.audit)))
    finally:
        if lock:
            lock.close()
