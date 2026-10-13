"""Local serial GPU pipeline with persistent stages; exits at the first failure."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from scripts.coordinator_io import atomic_json
from skillforge.training_data import file_hash, load_training_data
from skillforge.dataset import digest

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
PLAN = json.loads(Path("configs/training-runs.json").read_text(encoding="utf-8"))
TRAIN = Path(PLAN["root"])
EVAL = Path(PLAN["evaluation_root"])
STATUS = Path(".runtime/training-pipeline.json")
PYTHON = str(ROOT / ".venv-train/Scripts/python.exe")


def status(stage, **kwargs):
    atomic_json(STATUS, {"stage": stage, "at": time.time(), **kwargs})
    live = "# 训练实时进度\n\n更新时间：" + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
    live += "当前阶段：`" + stage + "`\n\n"
    live += "此文件由训练流水线自动更新；进度与完成结论以实际结果文件为准。\n\n"
    live += "```json\n" + json.dumps(kwargs, ensure_ascii=False, indent=2) + "\n```\n"
    live += "\n阶段顺序：环境与GPU检查 → 完整模型训练smoke → SFT → DPO → Validation → 模型冻结 → Test → 去Gate消融 → 报告。\n"
    Path("docs/TRAINING_LIVE.md").write_text(live, encoding="utf-8")


class ChildFailure(RuntimeError):
    def __init__(self, stage, code, logfile):
        self.logfile = logfile
        super().__init__(f"{stage} failed with exit code {code}; inspect {logfile}")


def _command_once(stage, args):
    log_root = TRAIN / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    logfile = log_root / (stage + "-" + str(int(time.time())) + ".log")
    status(stage, log=str(logfile))
    with logfile.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen([PYTHON, "-u", *args], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        status(stage, pid=process.pid, log=str(logfile))
        while process.poll() is None:
            progress = None
            if "--output" in args:
                progress_path = Path(args[args.index("--output") + 1]) / "progress.json"
                if progress_path.exists():
                    progress = json.loads(progress_path.read_text(encoding="utf-8"))
            status(stage, pid=process.pid, log=str(logfile), progress=progress)
            time.sleep(10)
        code = process.returncode
    if code:
        raise ChildFailure(stage, code, logfile)


def command(stage, args):
    args = list(args)
    for attempt in range(3):
        try:
            return _command_once(stage, args)
        except ChildFailure as exc:
            tail = exc.logfile.read_text(encoding="utf-8", errors="replace")[-6000:]
            module = args[1] if args[:1] == ["-m"] and len(args) > 1 else None
            # Windows readers can briefly deny an atomic progress-file rename.
            # Resume re-audits every saved record; never reinterpret this as a
            # model outcome or relax a model/data/code identity check.
            transient_progress_lock = ("PermissionError" in tail and "WinError 5" in tail
                and "progress.tmp" in tail and "progress.json" in tail)
            if (attempt == 2 or not transient_progress_lock
                    or module not in {"scripts.evaluate_trained_student", "scripts.evaluate_stability"}):
                raise
            if module == "scripts.evaluate_trained_student" and "--resume" not in args:
                args.append("--resume")
            status(stage, recovery="transient_windows_progress_file_lock", retry=attempt + 1, previous_log=str(exc.logfile))
            time.sleep(1)


def training(stage, smoke=False):
    output = TRAIN / ("smoke" if smoke else stage)
    if (output / "result.json").exists():
        result = json.loads((output / "result.json").read_text(encoding="utf-8"))
        if result["status"] != "completed" or result["smoke_only"] != smoke:
            raise ValueError("invalid completed stage")
        if file_hash(output / "adapter/adapter_model.safetensors") != result["adapter_hash"]:
            raise ValueError("completed adapter hash mismatch")
        run = json.loads((output / "run.json").read_text(encoding="utf-8"))
        config = json.loads(Path(PLAN["config"]).read_text(encoding="utf-8"))
        if run["config"] != config or run["trainer_source_hash"] != file_hash("skillforge/training.py"):
            raise ValueError("completed training stage config/source mismatch")
        _, _, audit = load_training_data(config["dataset"], config["bundle"], config["real_data"], config["supervision"], config["baseline"])
        sft_hash = file_hash(TRAIN / "sft/adapter/adapter_model.safetensors") if stage == "dpo" else None
        if (run["corpus_audit"] != audit or run["sft_adapter_hash"] != sft_hash or run["stage"] != stage
                or run["run_hash"] != digest({k: v for k, v in run.items() if k != "run_hash"})
                or result["run_hash"] != run["run_hash"]):
            raise ValueError("completed training stage corpus/reference/identity mismatch")
        return
    args = ["-m", "scripts.train_student", "--stage", stage, "--config", PLAN["config"], "--output", str(output)]
    if stage == "dpo":
        args += ["--sft-adapter", str(TRAIN / "sft/adapter")]
    if smoke:
        args += ["--smoke"]
    elif PLAN.get("resume_checkpoints", {}).get(stage):
        args += ["--resume-checkpoint", PLAN["resume_checkpoints"][stage]]
    if output.exists():
        args += ["--resume"]
    command("smoke" if smoke else stage, args)


def evaluation(label, split, ablation=False):
    output = EVAL / (label + ("-no-gate" if ablation else "") + "-" + split)
    # The evaluator audits and reconstructs completed runs without loading the
    # GPU; skipping by report-file existence would bypass resume validation.
    args = ["-m", "scripts.evaluate_trained_student", "--config", PLAN["config"], "--label", label,
        "--split", split, "--output", str(output)]
    if label != "Base":
        args += ["--adapter", str(TRAIN / label.lower() / "adapter")]
    if output.exists():
        args += ["--resume"]
    if ablation:
        args += ["--no-gate"]
    command(output.name, args)


if __name__ == "__main__":
    # Reuse the OS lock implementation without starting another task worker.
    from skillforge.jobs import JobStore, Worker
    guard = Worker(JobStore(".runtime/training-pipeline-lock"), lambda *_: None)
    guard.start()
    try:
        status("waiting_for_environment")
        while True:
            marker = Path(".runtime/training-bootstrap.json")
            current = json.loads(marker.read_text(encoding="utf-8-sig")) if marker.exists() else {}
            if current.get("stage") == "failed":
                raise RuntimeError("training environment failed: " + current["message"])
            if current.get("stage") == "ready":
                break
            status("waiting_for_environment", bootstrap=current)
            time.sleep(10)
        status("waiting_for_verified_model")
        config = json.loads(Path(PLAN["config"]).read_text(encoding="utf-8"))
        while not (Path(config["base_model"]) / "download_manifest.json").exists():
            status("waiting_for_verified_model", model=config["base_model"])
            time.sleep(10)
        training("sft", smoke=True)
        training("sft")
        training("dpo")
        for label in PLAN["evaluation_labels"]:
            evaluation(label, "validation")
        EVAL.mkdir(parents=True, exist_ok=True)
        frozen = {"config_hash": file_hash(PLAN["config"]), "protocol": PLAN["protocol"],
            "adapters": {label: file_hash(TRAIN / label.lower() / "adapter/adapter_model.safetensors") for label in ["SFT", "DPO"]},
            "selection": "fixed prespecified training recipe; no test feedback used"}
        target = EVAL / "frozen_models.json"
        if target.exists() and json.loads(target.read_text(encoding="utf-8")) != frozen:
            raise ValueError("held-out model freeze mismatch")
        atomic_json(target, frozen)
        for label in PLAN["evaluation_labels"]:
            evaluation(label, "test")
        evaluation("DPO", "test", ablation=True)
        command("summarize", ["-m", "scripts.report_post_training", "--root", str(EVAL)])
        status("completed", training_root=str(TRAIN), evaluation_root=str(EVAL))
    except BaseException as exc:
        status("failed", error=type(exc).__name__, message=str(exc))
        raise
    finally:
        guard.close()
