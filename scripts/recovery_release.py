"""Audit, freeze and report the recovery candidate without using test to select."""
import argparse
import json
from pathlib import Path

from scripts.audit_validation import audit as audit_validation
from scripts.coordinator_io import atomic_json
from scripts.evaluate_fresh_holdout import audit as audit_fresh
from skillforge.dataset import digest, load_dataset, task_hash
from skillforge.environment import Environment
from skillforge.schemas import Task
from skillforge.training_data import file_hash, load_training_data
from skillforge.verifier import verify


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def selection():
    plan = read("configs/recovery-runs.json")
    config = read(plan["config"])
    _, _, corpus = load_training_data(config["dataset"], config["bundle"], config["real_data"], config["supervision"], config["baseline"])
    for stage in ("smoke", "sft"):
        root = Path(plan["root"]) / stage
        result, run, data = read(root / "result.json"), read(root / "run.json"), read(root / "data_report.json")
        if (result["status"] != "completed" or not result["adapter_updated"] or result["smoke_only"] != (stage == "smoke")
                or result["adapter_hash"] != file_hash(root / "adapter/adapter_model.safetensors")
                or run["config"] != config or run["corpus_audit"] != corpus
                or run["trainer_source_hash"] != file_hash("skillforge/training.py")
                or run["run_hash"] != digest({k: v for k, v in run.items() if k != "run_hash"})
                or result["run_hash"] != run["run_hash"] or data["oversize_skipped"]):
            raise ValueError("recovery training identity or complete-context coverage mismatch")
    folder = Path(plan["evaluation_root"]) / "SFT-validation"
    candidate = audit_validation(folder, plan["config"], plan["validation_loss_data"])
    reference = audit_validation(plan["reference_evaluation"], plan["reference_config"], plan["validation_loss_data"])
    adapter_hash = file_hash(Path(plan["root"]) / "sft/adapter/adapter_model.safetensors")
    if candidate["model_settings"]["adapter_sha256"] != adapter_hash:
        raise ValueError("candidate validation does not use the completed adapter")
    if (candidate["full_system"]["actual_policy_violation_rate"] != 0
            or candidate["full_system"]["task_success_rate"] < reference["full_system"]["task_success_rate"]):
        raise ValueError("candidate did not meet the predeclared validation eligibility rule")
    manifest, _ = load_dataset(plan["fresh_holdout_dataset"])
    if manifest["dataset_hash"] != plan["fresh_holdout_dataset_hash"]:
        raise ValueError("predeclared fresh holdout changed")
    return {"label": "SFT", "training_root": plan["root"], "adapter_sha256": adapter_hash,
        "reference_adapter_sha256": reference["model_settings"]["adapter_sha256"], "selection_split": "validation",
        "plan_sha256": file_hash("configs/recovery-runs.json"), "config_sha256": file_hash(plan["config"]),
        "candidate_validation_sha256": file_hash(folder / "evaluation.json"),
        "reference_validation_sha256": file_hash(Path(plan["reference_evaluation"]) / "evaluation.json"),
        "fresh_holdout_dataset_hash": manifest["dataset_hash"],
        "rule": "Zero actual violations and validation EOC at least main-v2 DPO; fresh test never selects the model."}


def freeze():
    result = selection()
    path = Path(read("configs/recovery-runs.json")["evaluation_root"]) / "recovery-selection.json"
    if path.exists() and read(path) != result:
        raise ValueError("recovery model selection changed after freezing")
    atomic_json(path, result)
    return result


def check():
    plan = read("configs/recovery-runs.json")
    root = Path(plan["evaluation_root"])
    selected = selection()
    if read(root / "recovery-selection.json") != selected:
        raise ValueError("frozen recovery selection mismatch")
    reports = {}
    for label, config in (("DPO-reference", plan["reference_config"]), ("SFT", plan["config"])):
        reports[label] = audit_fresh(root / "fresh" / label, config, plan["fresh_holdout_dataset"])
        expected = selected["adapter_sha256"] if label == "SFT" else selected["reference_adapter_sha256"]
        if reports[label]["model_settings"]["adapter_sha256"] != expected:
            raise ValueError("fresh evaluation used a different adapter")
    return {"ready_for_http_acceptance": True, "selection": selected,
        "fresh_summaries": {k: v["full_system"] for k, v in reports.items()}}


def audit_acceptance(folder):
    folder = Path(folder)
    selected = check()["selection"]
    summary, browser = read(folder / "summary.json"), read(folder / "browser.json")
    names = {"modify_address", "cancel_order", "refund", "refused", "escalated", "custom_partial_refund"}
    if (not summary["passed"] or len(summary["cases"]) != 6 or {r["name"] for r in summary["cases"]} != names
            or not browser["passed"] or browser["model"] != summary["model"]):
        raise ValueError("recovery requires all six HTTP cases and actual browser signoff")
    for row in summary["cases"]:
        job = read(folder / (row["name"] + "-job.json"))
        record = job["result"]
        task = Task.model_validate(job["request"]["task"])
        env = Environment(fixture=task.fixture)
        try:
            state = env.snapshot()
        finally:
            env.close()
        if state != record["initial_state"] or record["task_hash"] != task_hash(task):
            raise ValueError("HTTP acceptance task or initial state changed")
        for event in record["tool_audit"]:
            after = event["after_state"]
            delta = {k: {"before": state.get(k), "after": v} for k, v in after.items() if state.get(k) != v}
            if event["before_state"] != state or event["state_diff"] != delta:
                raise ValueError("HTTP acceptance audit state chain is incomplete or changed")
            state = after
        if state != record["final_state"]:
            raise ValueError("HTTP acceptance did not execute and verify its recorded final state")
        verdict = verify(task, record["initial_state"], record["final_state"], record["tool_audit"], record["outcome"])
        if (not row["passed"] or job["status"] != "succeeded" or job["id"] != row["run_id"]
                or verdict != record["verification"] or not verdict["task_success"] or verdict["actual_policy_violation"]
                or record["model_settings"]["server_identity"]["adapter_sha256"] != selected["adapter_sha256"]
                or record["metrics"]["llm_calls"] <= 0 or record["engineering_only"] or record["protocol"] != "free_action"):
            raise ValueError("HTTP acceptance did not execute and verify the frozen real candidate")
    return {"passed": True, "model": summary["model"], "cases": 6, "browser": True, "adapter_sha256": selected["adapter_sha256"]}


def report():
    checked = check()
    plan = read("configs/recovery-runs.json")
    root = Path(plan["evaluation_root"])
    lines = ["# main-v3 恢复训练结果", "", "本报告审核逐任务检查点后生成；模型仅按validation准入，未按新实例test选优。", "",
        "| 模型 | 新实例test EOC | 固定候选决策 | Skill调用 | 模型违规尝试 | 实际违规 |",
        "|---|---:|---:|---:|---:|---:|"]
    for label in ("DPO-reference", "SFT"):
        row = read(root / "fresh" / label / "evaluation.json")
        s = row["full_system"]
        probes = [p for g in row["decision_level"] for p in g["cases"] if not p.get("skipped")]
        lines.append(f"| {label} | {round(s['task_success_rate']*s['tasks'])}/{s['tasks']} | {sum(p['correct'] for p in probes)}/{len(probes)} | {s['skill_reuse_attempts']} | {s['model_attempted_policy_violation_rate']:.1%} | {s['actual_policy_violation_rate']:.1%} |")
    lines += ["", "新实例沿用已知生成器、任务族与结构；不能作为开放域或未知结构泛化证明。旧main-v2报告独立保留，旧test已被查看，不能重新当作首次独立测试。",
        "", "SFT语料由355增至1,267个样本，两轮训练的更新次数也增加；本实验未隔离数据内容与计算量因素。DPO-reference使用原main-v2权重，本轮候选为重新训练的SFT。",
        "", "实际产品验收另见工作台结果；研究评测完成不等于HTTP和浏览器验收通过。"]
    Path("docs/RECOVERY_RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return checked


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--acceptance")
    args = parser.parse_args()
    if args.freeze:
        value = freeze()
    elif args.acceptance:
        value = audit_acceptance(args.acceptance)
    elif args.report:
        value = report()
    else:
        value = check()
    print(json.dumps(value, ensure_ascii=True, indent=2))
