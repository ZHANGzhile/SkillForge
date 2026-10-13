"""Finish a validation-qualified recovery candidate through real product delivery."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from scripts.coordinator_io import atomic_json
from scripts import run_training_pipeline as pipeline
from scripts import recovery_release
from scripts.package_project import package, readiness
from skillforge.jobs import JobStore, Worker

ROOT = Path(__file__).resolve().parents[1]


def main(resume_acceptance=None):
    os.chdir(ROOT)
    plan = recovery_release.read("configs/recovery-runs.json")
    pipeline.PLAN, pipeline.TRAIN, pipeline.EVAL = plan, Path(plan["root"]), Path(plan["evaluation_root"])
    marker = Path(".runtime/recovery-delivery.json")
    run_id = time.strftime("%Y%m%d-%H%M%S")
    logs = Path("results/recovery-release-logs") / run_id
    logs.mkdir(parents=True)
    watcher = Worker(JobStore(".runtime/recovery-delivery-lock"), lambda *_: None)
    watcher.start()
    gpu = None
    python = str(ROOT / ".venv/Scripts/python.exe")
    def status(stage, **kwargs):
        atomic_json(marker, {"stage": stage, "at": time.time(), "run_id": run_id, **kwargs})
    def run(stage, args, env=None):
        log = logs / (stage + ".log")
        with log.open("w", encoding="utf-8") as stream:
            process = subprocess.Popen(args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=stream,
                stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            while process.poll() is None:
                status(stage, pid=process.pid, log=str(log))
                time.sleep(5)
        if process.returncode:
            raise RuntimeError(stage + " failed; inspect " + str(log))
    try:
        if resume_acceptance:
            acceptance = Path(resume_acceptance).resolve()
            allowed = (ROOT / "results/workbench-acceptance").resolve()
            if allowed not in acceptance.parents:
                raise ValueError("resume acceptance must be inside the project acceptance directory")
            status("auditing_saved_acceptance", acceptance=str(acceptance))
            selected = recovery_release.freeze()
            recovery_release.audit_acceptance(acceptance)
            acceptance = acceptance.relative_to(ROOT)
        else:
            while True:
                state = recovery_release.read(".runtime/recovery-pipeline.json")
                if state["stage"] == "failed":
                    raise RuntimeError("recovery training/validation failed: " + state.get("message", "inspect logs"))
                if state["stage"] == "validation_completed":
                    if not state["eligible_for_product_acceptance"]:
                        raise RuntimeError("candidate failed validation eligibility; no test-driven deployment fallback")
                    break
                main_state = recovery_release.read(".runtime/training-pipeline.json")
                if time.time() - main_state["at"] > 180:
                    raise RuntimeError("training heartbeat is stale; inspect original GPU process before resuming")
                status("waiting_for_validation", training_stage=main_state["stage"])
                time.sleep(10)
            status("freezing_validation_choice")
            selected = recovery_release.freeze()
            gpu = Worker(JobStore(".runtime/training-pipeline-lock"), lambda *_: None)
            gpu.start()
            reference_plan = recovery_release.read("configs/training-runs.json")
            for label, config, adapter, model_label in (
                ("DPO-reference", plan["reference_config"], str(Path(reference_plan["root"]) / "dpo/adapter"), "DPO"),
                ("SFT", plan["config"], str(pipeline.TRAIN / "sft/adapter"), "SFT")):
                output = pipeline.EVAL / "fresh" / label
                args = ["-m", "scripts.evaluate_fresh_holdout", "--config", config,
                    "--dataset", plan["fresh_holdout_dataset"], "--adapter", adapter,
                    "--label", model_label, "--output", str(output)]
                if output.exists():
                    args.append("--resume")
                status("fresh-holdout-" + label)
                pipeline.command("fresh-holdout-" + label, args)
            status("research_report")
            recovery_release.report()
            gpu.close()
            gpu = None
            pipeline.status("completed", recovery_candidate=True, evaluation_root=str(pipeline.EVAL), deployment_pending=True)
            run("deploy", ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                "scripts/deploy_trained_project.ps1", "-Stage", "SFT", "-Recovery"])
            acceptance = Path("results/workbench-acceptance") / ("recovery-sft-" + run_id)
            run("real-http-acceptance", [python, "-m", "scripts.accept_trained_workbench", "--output", str(acceptance)])
            env = dict(os.environ)
            env.setdefault("SKILLFORGE_PLAYWRIGHT_MODULE", "C:/Users/jiojio/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright")
            node = os.getenv("SKILLFORGE_NODE", "C:/Users/jiojio/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")
            run("browser-acceptance", [node, "scripts/verify_trained_ui.cjs", str(acceptance / "summary.json")], env)
        run("source-only-regression", [python, "-m", "scripts.check_clean_checkout"])
        audited = recovery_release.audit_acceptance(acceptance)
        deployment_path = Path("results/workbench-acceptance/trained-deployment.json")
        deployment = recovery_release.read(deployment_path)
        deployment.update(end_to_end_verified=True, browser_verified=True, acceptance=str(acceptance))
        atomic_json(deployment_path, deployment)
        Path("docs/DELIVERY_STATUS.md").write_text(
            "# 本地研究项目交付验收\n\n" + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
            + "main-v3 SFT通过validation准入，完成新实例双评测；原六项真实HTTP功能验收与浏览器签收通过。"
            + "研究效果与局限见[恢复训练报告](RECOVERY_RESULTS.md)，原main-v2成绩和失败记录完整保留。\n\n"
            + "真实验收目录：`" + str(acceptance) + "`；adapter SHA-256：`" + selected["adapter_sha256"] + "`。\n\n"
            + "ZIP逐文件核验完成以.runtime/recovery-delivery.json的completed状态为准。本地合成领域验收不代表生产部署或所有任务成功。\n", encoding="utf-8")
        release_report = readiness()
        if not release_report["ready"]:
            raise RuntimeError("original research release audit is not ready")
        release_report["recovery"] = {"selection": selected, "acceptance": audited}
        extra = [plan["root"], plan["evaluation_root"], plan["fresh_holdout_dataset"],
            recovery_release.read(plan["config"])["supervision"], "results/recovery-release-logs"]
        status("packaging")
        archive = package("release/SkillForge-recovery-" + run_id + ".zip", release_report, extra_paths=extra)
        atomic_json(Path("results/recovery-release.json"), {"archive": archive, "acceptance": str(acceptance), "selection": selected})
        status("completed", archive=archive, acceptance=str(acceptance))
    except BaseException as exc:
        status("failed", error=type(exc).__name__, message=str(exc))
        if gpu is not None:
            pipeline.status("failed", error=type(exc).__name__, message=str(exc))
        raise
    finally:
        if gpu is not None:
            gpu.close()
        watcher.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-acceptance", help="Re-audit passed HTTP/browser evidence and resume the final regression/package stages")
    main(parser.parse_args().resume_acceptance)
