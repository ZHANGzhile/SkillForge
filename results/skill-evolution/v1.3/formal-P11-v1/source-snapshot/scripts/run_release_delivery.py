"""Wait for research completion, then deploy and verify the actual local product."""
import json
import os
from pathlib import Path
import subprocess
import time

from scripts.coordinator_io import atomic_json
from skillforge.jobs import Worker, JobStore

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    guard = Worker(JobStore(".runtime/release-delivery-lock"), lambda *_: None)
    guard.start()
    marker = Path(".runtime/release-delivery.json")
    run_id = time.strftime("%Y%m%d-%H%M%S")
    logs = Path("results/release-logs") / run_id
    logs.mkdir(parents=True)
    python = str(ROOT / ".venv/Scripts/python.exe")
    def status(stage, **kwargs):
        atomic_json(marker, {"stage": stage, "at": time.time(), "run_id": run_id, **kwargs})
    def run(stage, args, env=None):
        logfile = logs / (stage + ".log")
        with logfile.open("w", encoding="utf-8") as stream:
            process = subprocess.Popen(args, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            while process.poll() is None:
                status(stage, pid=process.pid, log=str(logfile))
                time.sleep(5)
        if process.returncode:
            raise RuntimeError(stage + " failed; inspect " + str(logfile))
    try:
        while True:
            finish = json.loads(Path(".runtime/research-finish.json").read_text(encoding="utf-8"))
            status("waiting_for_research", research_stage=finish["stage"])
            if finish["stage"] == "failed":
                raise RuntimeError("research continuation failed: " + finish.get("message", "inspect its log"))
            if finish["stage"] == "completed":
                break
            pipeline = json.loads(Path(".runtime/training-pipeline.json").read_text(encoding="utf-8"))
            if pipeline["stage"] == "failed" or time.time() - pipeline["at"] > 180:
                raise RuntimeError("research pipeline failed or heartbeat became stale")
            time.sleep(10)
        run("select-from-validation", [python, "-m", "scripts.select_deployment_model"])
        plan = json.loads(Path("configs/training-runs.json").read_text(encoding="utf-8"))
        selection = json.loads((Path(plan["evaluation_root"]) / "deployment-selection.json").read_text(encoding="utf-8"))
        chosen = selection["label"]
        run("deploy", ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/deploy_trained_project.ps1", "-Stage", chosen])
        acceptance = Path("results/workbench-acceptance") / ("trained-" + chosen.lower() + "-" + run_id)
        run("real-http-acceptance", [python, "-m", "scripts.accept_trained_workbench", "--output", str(acceptance)])
        env = dict(os.environ)
        env.setdefault("SKILLFORGE_PLAYWRIGHT_MODULE", "C:/Users/jiojio/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright")
        node = os.getenv("SKILLFORGE_NODE", "C:/Users/jiojio/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe")
        run("browser-acceptance", [node, "scripts/verify_trained_ui.cjs", str(acceptance / "summary.json")], env)
        run("source-only-regression", [python, "-m", "scripts.check_clean_checkout"])
        # Summaries and status documents are emitted only after real acceptance.
        run("report", [python, "-m", "scripts.write_research_report"])
        result = json.loads((acceptance / "summary.json").read_text(encoding="utf-8"))
        deployment = Path("results/workbench-acceptance/trained-deployment.json")
        verified = json.loads(deployment.read_text(encoding="utf-8-sig"))
        verified.update(end_to_end_verified=True, acceptance=str(acceptance), browser_verified=True)
        atomic_json(deployment, verified)
        Path("docs/DELIVERY_STATUS.md").write_text(
            "# 本地研究项目交付验收\n\n"
            + "更新时间：" + time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n"
            + "正式SFT/DPO权重、同协议验证/test双评测、去Gate消融、12例三次稳定性、真实HF工作台HTTP及浏览器验收均已完成。\n\n"
            + "部署模型：`" + result["model"] + "`。按预声明validation策略选择，不按test挑选；选择证据保存在evaluation目录deployment-selection.json。\n\n"
            + "真实验收：`" + str(acceptance) + "`。研究结果和限制见[研究报告](RESEARCH_REPORT.md)，运行恢复见[运行手册](RUNBOOK.md)。\n\n"
            + "这是受限合成领域的本地研究交付；远端CI、Docker实跑及生产业务部署未作为已通过项。ZIP校验结果以.runtime/release-delivery.json的最终completed状态为准。\n", encoding="utf-8")
        readme = Path("README.md")
        paragraphs = readme.read_text(encoding="utf-8").split("\n\n")
        paragraphs[2] = "本地研究闭环已完成：正式工作台、三类冻结Skill、216个任务、真实B0–B3基线、正式QLoRA SFT/DPO适配器、同协议双评测、消融与错误分析。私有" + chosen + " Student已通过真实HTTP及浏览器验收。研究结论与限制以[研究报告](docs/RESEARCH_REPORT.md)为准，不由训练loss推断。"
        paragraphs[3] = "最新验收见[交付状态](docs/DELIVERY_STATUS.md)，面试讲解见[项目复盘](docs/PROJECT_INTERVIEW_TRACE.md)，恢复命令见[运行手册](docs/RUNBOOK.md)。下方旧Ollama实验与新HF/NF4评测是不同协议，分开报告。"
        readme.write_text("\n\n".join(paragraphs), encoding="utf-8")
        for filename in ("docs/PROGRESS.md", "docs/PROJECT_INTERVIEW_TRACE.md"):
            path = Path(filename)
            original = path.read_text(encoding="utf-8")
            title, rest = original.split("\n", 1)
            path.write_text(title + "\n\n**最新自动验收更新：**正式训练、独立评测、稳定性及私有工作台真实验收已完成；详见[交付状态](DELIVERY_STATUS.md)与[研究报告](RESEARCH_REPORT.md)。下文带日期的中断描述作为历史trace保留。\n" + rest, encoding="utf-8")
        release = "release/SkillForge-" + run_id + ".zip"
        run("package", [python, "-m", "scripts.package_project", "--output", release])
        status("completed", release=release, acceptance=str(acceptance), report="docs/RESEARCH_REPORT.md")
    except BaseException as exc:
        status("failed", error=type(exc).__name__, message=str(exc))
        raise
    finally:
        guard.close()


if __name__ == "__main__":
    main()
