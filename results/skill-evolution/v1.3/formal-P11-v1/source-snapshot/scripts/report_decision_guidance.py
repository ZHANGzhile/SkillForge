"""Read-only audit and report for a completed/rejected guidance experiment."""
import argparse
from pathlib import Path

from scripts.coordinator_io import atomic_json
from scripts.evaluate_decision_guidance import admitted, decision_check, validate_system
from scripts.evaluate_reuse_ablation import read
from skillforge.benchmark import summarize
from skillforge.config import load_config
from skillforge.dataset import digest, load_dataset, task_hash
from skillforge.evaluation_checkpoints import read_checkpoint
from skillforge.experiment import load_bundle
from skillforge.training_data import file_hash


def audit_stage(folder, tasks, skills, identity, enabled):
    expected = {**identity, "stage": folder.name, "enabled": enabled,
                "task_hashes": {t.task_id: task_hash(t) for t in tasks}}
    if read(folder / "identity.json") != expected:
        raise ValueError("guidance stage identity mismatch")
    if {p.stem for p in (folder / "tasks").glob("*.json")} != set(expected["task_hashes"]):
        raise ValueError("incomplete system coverage")
    rows = []
    for task in tasks:
        row = read_checkpoint(folder / "tasks" / (task.task_id + ".json"), expected, task.task_id, task_hash(task))
        validate_system(row, task, expected, enabled)
        rows.append(row)
    probes = {s.skill_id + "-" + t.task_id: (s, t) for s in skills for t in tasks if s.family == t.family}
    if {p.stem for p in (folder / "decisions").glob("*.json")} != set(probes):
        raise ValueError("incomplete decision coverage")
    decisions = []
    for name, (skill, task) in probes.items():
        row = read_checkpoint(folder / "decisions" / (name + ".json"), {**expected, "skill_id": skill.skill_id}, task.task_id, task_hash(task))
        decision_check(row, task, enabled)
        decisions.append(row)
    valid = [r for r in decisions if not r.get("skipped")]
    report = {"identity": expected, "full_system": summarize(rows),
              "decision_level": {"evaluated": len(valid), "correct": sum(r["correct"] for r in valid), "skipped": len(decisions) - len(valid)}}
    if read(folder / "evaluation.json") != report:
        raise ValueError("summary does not match audited trajectories")
    return report, rows


def report(plan_path="configs/decision-guidance.json"):
    plan = read(plan_path)
    config, root = read(plan["training_config"]), Path(plan["output"])
    selection = read(root / "selection.json")
    identity = selection["identity"]
    manifest, original = load_dataset(config["dataset"])
    fresh_manifest, fresh = load_dataset(plan["fresh_dataset"])
    bundle, skills = load_bundle(config["bundle"], manifest["dataset_hash"])
    hashes = {"plan_sha256": file_hash(plan_path), "config_sha256": file_hash(plan["training_config"]),
        "profile_sha256": file_hash(plan["client_profile"]), "evaluator_hash": file_hash(Path(__file__).with_name("evaluate_decision_guidance.py")),
        "guidance_hash": file_hash(Path(__file__).with_name("decision_guidance.py")),
        "client_auditor_hash": file_hash(Path(__file__).with_name("evaluate_reuse_ablation.py")),
        "source_hash": digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path("skillforge").glob("*.py"))}),
        "runtime_config": load_config(), "dataset_hash": manifest["dataset_hash"],
        "fresh_dataset_hash": fresh_manifest["dataset_hash"], "bundle_hash": bundle["bundle_hash"],
        "reference_sha256": file_hash(Path(plan["reference_validation"]) / "evaluation.json")}
    if any(identity[k] != value for k, value in hashes.items()):
        raise ValueError("experiment source/config/data changed")
    if identity["model_settings"] != read(Path(plan["reference_validation"]) / "evaluation.json")["model_settings"]:
        raise ValueError("reference model mismatch")
    reports, rows = {}, {}
    reports["validation"], rows["validation"] = audit_stage(root / "validation", [t for t in original if t.split == "validation"], skills, identity, True)
    expected_selection = {"admitted": admitted(reports["validation"], plan["validation_gate"]), "split": "validation",
        "gate": plan["validation_gate"], "validation_report_sha256": file_hash(root / "validation/evaluation.json"), "identity": identity}
    if selection != expected_selection:
        raise ValueError("admission decision differs from validation evidence")
    if selection["admitted"]:
        for label, enabled in (("control", False), ("guided", True)):
            reports[label], rows[label] = audit_stage(root / label, [t for t in fresh if t.split == "test"], skills, identity, enabled)
        if read(root / "comparison.json") != {"identity": identity, "selection": selection, "arms": {k: reports[k] for k in ("control", "guided")}, "scope": plan["scope"], "causal_ntr": None}:
            raise ValueError("comparison differs from evidence")
    elif any((root / name).exists() for name in ("control", "guided", "comparison.json")):
        raise ValueError("test evidence exists despite validation rejection")
    lines = ["# 决策提示实验 v1 结果", "", "固定main-v3 SFT权重，仅增加可见状态的policy提示；这是提示干预，不是新训练或Skill执行器改进。", "",
        "准入：" + ("通过，按预声明继续新实例双组评测。" if selection["admitted"] else "**未通过预声明validation门槛，已停止，未进入新实例test，当前部署不变。**"), "",
        "| 阶段 | EOC合格 | 决策正确/有效 | 模型违规尝试率 | 实际违规率 | 平均LLM调用 | 平均token |", "|---|---:|---:|---:|---:|---:|---:|"]
    baseline = read(Path(plan["reference_validation"]) / "evaluation.json")
    baseline_decisions = [r for group in baseline["decision_level"] for r in group["cases"] if not r.get("skipped")]
    lines += [f"| 原validation参考 | {round(baseline['full_system']['task_success_rate'] * baseline['full_system']['tasks'])}/{baseline['full_system']['tasks']} | {sum(r['correct'] for r in baseline_decisions)}/{len(baseline_decisions)} | {baseline['full_system']['model_attempted_policy_violation_rate']:.2%} | {baseline['full_system']['actual_policy_violation_rate']:.2%} | {baseline['full_system']['average_llm_calls']:.4f} | {baseline['full_system']['average_tokens']:.2f} |"]
    for label, evaluation in reports.items():
        s, d = evaluation["full_system"], evaluation["decision_level"]
        lines.append(f"| {label} | {round(s['task_success_rate']*s['tasks'])}/{s['tasks']} | {d['correct']}/{d['evaluated']} | {s['model_attempted_policy_violation_rate']:.2%} | {s['actual_policy_violation_rate']:.2%} | {s['average_llm_calls']:.4f} | {s['average_tokens']:.2f} |")
    old_cases = {r["task_id"]: r for r in baseline_decisions}
    new_cases = [read(p) for p in sorted((root / "validation/decisions").glob("*.json")) if not read(p).get("skipped")]
    if set(old_cases) != {r["task_id"] for r in new_cases}:
        raise ValueError("validation decision comparison coverage mismatch")
    paired = [{"task_id": r["task_id"], "old_correct": old_cases[r["task_id"]]["correct"], "new_correct": r["correct"],
        "target": r.get("target"), "old_action": old_cases[r["task_id"]].get("action"), "new_action": r.get("action"),
        "error_kind": None if r["correct"] else "outside_fixed_candidate_set" if (r.get("action") or {}).get("type") == "tool" else "wrong_terminal_or_invalid_action"} for r in new_cases]
    improvements = sum(not r["old_correct"] and r["new_correct"] for r in paired)
    regressions = sum(r["old_correct"] and not r["new_correct"] for r in paired)
    atomic_json(root / "validation/decision-comparison.json", {"scope": "Retrospective paired validation probes; not full-system task failures or same-context causal NTR", "improvements": improvements, "regressions": regressions, "cases": paired})
    old_s, new_s = baseline["full_system"], reports["validation"]["full_system"]
    lines += ["", f"validation配对决策：{improvements}例改善、{regressions}例退步。系统Skill调用由{old_s['skill_reuse_attempts']}降为{new_s['skill_reuse_attempts']}；平均LLM调用变化{new_s['average_llm_calls']/old_s['average_llm_calls']-1:+.2%}，平均token变化{new_s['average_tokens']/old_s['average_tokens']-1:+.2%}。", "",
        "## 全部决策错误", "", "| task ID | 目标 | 实际Action | 原判断是否正确 | 错误类型 |", "|---|---|---|---|---|"]
    for row in paired:
        if not row["new_correct"]:
            action = row["new_action"] or {}
            lines.append(f"| {row['task_id']} | {row['target']} | {action.get('type')}/{action.get('name', '')} | {row['old_correct']} | {row['error_kind']} |")
    lines += ["", "输出primitive工具在自由执行协议中可能合法，但不满足这个明确限定skill/refuse/escalate的决策探针；不能把候选协议错误当成环境实际违规。新增提示与动作分布变化相关，尚未分离具体哪条提示、长度或格式造成变化。"]
    lines += ["", "## 全部系统失败", "", "| 阶段 | task ID | 任务族 | outcome |", "|---|---|---|---|"]
    for label, records in rows.items():
        for r in records:
            if not r["verification"]["task_success"]:
                lines.append(f"| {label} | {r['task_id']} | {r['task_family']} | {r['outcome']} |")
    lines += ["", "原validation已多次查看；提示设计受旧test失败分析启发，但没有将旧轨迹作为训练样本或输入答案。新实例仍来自已知生成器与结构，不证明未知业务泛化。原validation参考为直接HF，本次为HTTP，因此不比较严格延迟。", "",
        "成功与否均按同一预声明门槛保留，不降低门槛、不用新test挑提示。新增提示token已计入；没有替换模型Action，实际发送的model_input_context与原context分别存档并重建审核。", "",
        "原始证据：results/decision-guidance/v1。报告仅从完整双评测检查点生成，重算状态链、EOC、模型输入、决策判定与汇总。工程测试通过不等于模型能力提高。"]
    Path("docs/DECISION_GUIDANCE_RESULTS.md").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    receipt = {"passed": True, "admitted": selection["admitted"], "stages": list(reports),
        "reporter_sha256": file_hash(__file__), "report_sha256": file_hash("docs/DECISION_GUIDANCE_RESULTS.md"),
        "selection_sha256": file_hash(root / "selection.json")}
    atomic_json(root / "audit.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="configs/decision-guidance.json")
    print(report(parser.parse_args().plan))
