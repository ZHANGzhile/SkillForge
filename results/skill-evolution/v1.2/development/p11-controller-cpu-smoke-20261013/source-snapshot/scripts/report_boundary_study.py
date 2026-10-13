"""Audit-first bilingual boundary-study reports; never turn partial runs into scores."""
from collections import Counter
import json
from pathlib import Path

from scripts.audit_boundary_preparation import audit as audit_preparation
from scripts.boundary_learning import features, oracle
from scripts.coordinator_io import atomic_json
from scripts.evaluate_boundary_gate import clustered_interval
from scripts.audit_boundary_study import audit_gate, audit_system, load_prepared
from skillforge.policies import MUTATIONS
from skillforge.dataset import digest
from skillforge.training_data import file_hash


def table(headers, rows):
    return ["| " + " | ".join(map(str, headers)) + " |", "|" + "---|" * len(headers),
            *["| " + " | ".join(map(str, row)) + " |" for row in rows]]


def metrics(rows, tasks):
    normal = [r for r in rows if tasks[r["task_id"]].expected.allowed_outcomes == ["completed"]]
    return {"tasks": len(rows), "passed": sum(r["verification"]["task_success"] for r in rows),
            "task_success_rate": sum(r["verification"]["task_success"] for r in rows) / len(rows),
            "normal_tasks": len(normal), "normal_passed": sum(r["verification"]["task_success"] for r in normal),
            "actual_policy_violation_rate": sum(r["verification"]["actual_policy_violation"] for r in rows) / len(rows),
            "model_attempt_tasks": sum(r["policy_attempts"]["model_triggered"] for r in rows),
            "blocked_writes": sum(e["tool_name"] in MUTATIONS and e["error"] == "business_rule_rejected" for r in rows for e in r["tool_audit"]),
            "forced_blocked_writes": sum(r["boundary_experiment"]["forced_tool_policy_attempts"] for r in rows),
            "skill_reuse_attempts": sum(r["metrics"]["skill_calls"] for r in rows),
            "normal_successful_skill_uses": sum(e.get("success", False) for r in normal for e in r["skill_events"]),
            "gate_labeled_inapplicable_skill_attempts": sum(e.get("applicable") is False for r in rows for e in r["skill_events"]),
            "skill_execution_business_rejections": sum(e.get("error") == "business_rule_rejected" for r in rows for e in r["skill_events"]),
            "gate_blocked_skill_attempts": sum(bool(e.get("blocked")) or e.get("error") == "precondition_failed" for r in rows for e in r["skill_events"]),
            "unknown_skill_attempts": sum(e.get("applicable") is None for r in rows for e in r["skill_events"]),
            "budget_exhausted": sum(r["outcome"] == "max_steps_exceeded" for r in rows),
            "recovery_failures_after_rejection": sum(not r["verification"]["task_success"] and (any(e.get("blocked") for e in r["skill_events"]) or any(e["error"] == "business_rule_rejected" for e in r["tool_audit"])) for r in rows),
            "llm_calls": sum(r["metrics"]["llm_calls"] for r in rows), "tokens": sum(r["metrics"]["tokens"] for r in rows),
            "tool_calls": sum(r["metrics"]["tool_calls"] for r in rows), "gate_tool_calls": sum(r["metrics"]["gate_tool_calls"] for r in rows)}


def interval(left, right, tasks, fn, plan, normal_only=False):
    values = {}
    for tid in left:
        task = tasks[tid]
        if normal_only and task.expected.allowed_outcomes != ["completed"]:
            continue
        values.setdefault(task.structure_id, []).append(fn(left[tid]) - fn(right[tid]))
    return clustered_interval([sum(v) / len(v) for v in values.values()], plan["seed"], plan["bootstrap_samples"])


def report(plan_path="configs/boundary-study.json"):
    preparation_audit = audit_preparation(plan_path)
    plan, root, all_tasks, boundaries, _ = load_prepared(plan_path)
    gate = audit_gate(plan_path, audit_only=True)
    tasks = {t.task_id: t for t in all_tasks if t.split == "test"}
    source = json.loads((root / "source-audit.json").read_text())
    source_rows = [[f["family"], f["negative_sources"], sum(v["admitted"] for v in f["leave_one_out"]),
                    sum(v.get("boundary_changed", False) for v in f["leave_one_out"]), "rejected"] for f in source["families"]]
    gate_rows = []
    for g in "ABCD":
        s = gate["summary"][g]["test"]
        gate_rows.append([g, f"{s['false_allow_rate']:.2%}", f"{s['false_block_rate']:.2%}", f"{s['normal_allow_coverage']:.2%}",
                          s["initial_unknown"], s["remaining_unknown"], s["queries"]])
    headers = ["Group", "False allow / 16", "False block / 8", "Normal coverage", "Initial UNKNOWN / 96", "Remaining UNKNOWN", "Queries / 96"]
    atomic_json(root / "workbench-gate.json", {"boundary_tables": [{"headers": headers, "rows": gate_rows}], "comparisons": gate["comparisons"],
                "scope": "Fixed-procedure Gate evaluation. Four observation masks per scenario are not independent samples. Training probes explicitly controlled, not autonomous LLM data."})
    introduction = ["# Fixed-program boundary learning study", "", "[中文](../BOUNDARY_STUDY_RESULTS.md) | [English README](../../README.md)", "",
                   "This study separates boundary selection from program encapsulation. Existing core code, model weights, tool policy and the three frozen procedures are unchanged. Experimental contracts remain VALIDATING and are not deployed.", "",
                   "## Original compiler audit", "", *table(["Family", "Negative sources", "Leave-one-out admitted", "Changed conditions", "All negatives removed"], source_rows), "",
                   "Where compilation remained admitted after removing one failure, predicate fields/operators/values did not change. Failures supplied provenance and admission evidence to prewritten conditions; this is not evidence of discovering new rules.", "",
                   "## New bounded learner and data", "",
                   "A retains constant declared features from successful train executions. B adds positive-preserving finite predicates that reject train failures. C uses complete declared policy. D applies the same refinement on top of C. B learned HIGH-risk exclusions for all three families and a FAILED-payment exclusion for refunds. D added no conditions. The full public C and D contracts are identical.", "",
                   "There are 23 train, 23 validation and 24 test tasks; nine test condition combinations are held out from this experiment's train/validation. Some business combinations were already discussed in earlier project experiments: this is not novel-policy or wholly unseen semantic generalization. Train evidence contains 8 successful controlled executions, 14 business-rejected executions and 1 excluded internal-binding failure (zero refund amount); none are presented as autonomous model trajectories.", "",
                   "Feature domains, family-field selection and derived validity predicates are human priors. Training uses complete recorded train snapshots, not just a model's partial observations; test labels never enter fitting. The learner selects bounded categorical conditions; it does not discover arithmetic or arbitrary predicates. A uses no negative validation labels; its constant-feature restrictions cannot be removed by this monotone refinement. All four groups remain in evaluation.", "",
                   "## Pure Gate test", "", *table(headers, gate_rows), "",
                   "Full-observation denominators are 16 inapplicable and 8 applicable contexts. Costs/UNKNOWN span all 96 mask-context pairs. B-A false-allow difference is -25 percentage points, paired scenario-cluster percentile bootstrap 95% interval [-50, -6.25] points; false-block difference is zero. D-C is zero. A reports fewer UNKNOWNs partly because it lacks conditions, not because it knows more.", "",
                   "The 2,000-resample intervals describe the selected synthetic scenario clusters, not a population guarantee. An all-zero sample yields a degenerate bootstrap interval; it does not prove zero future risk. Rule oracle labels were cross-checked against actual fixed-procedure execution. C matching this known-policy oracle is expected."]
    zh = ["# 固定程序边界学习对照结果", "", "[English](en/BOUNDARY_STUDY_RESULTS.md)", "",
          "本轮区分旧编译器审计与新增有限条件学习器。执行程序、模型权重、工具内policy与旧core冻结；实验契约保持VALIDATING，不进入部署。", "",
          "## 旧实现审计", "", *table(["任务族", "负例数", "移除单例仍准入", "条件变化数", "移除全部反例"], source_rows), "",
          "只要移除单条失败后仍能编译，边界字段/算子/值均未变化；移除全部失败则拒绝编译。旧实现的失败经验主要影响证据与准入，不能据此说它发现了新规则。", "",
          "## 新学习器与数据", "",
          "A从正例提取声明特征的常量条件，B用失败例作保留全部正例的有限条件精化；C是完整人工规则，D在C上做相同精化。B在三个任务族加入HIGH风险禁止条件，退款另加入FAILED支付禁止条件；D没有新增条件，C/D模型可见契约完全相同。", "",
          "train23、validation23、test24；test有9个未出现在本轮训练/验证中的组合场景族，但部分组合在项目历史中已被分析，不能称未知业务语义泛化。训练来自8条成功、14条工具业务拒绝及1条排除的内部绑定失败，全部是显式实验控制执行，不是自主模型轨迹。零金额退款无法绑定expected_total，保留排除原因而不伪标为工具拒绝。", "",
          "字段域、各族特征选择及refund.amount_valid等谓词是人工先验；训练使用完整train快照，不限于模型的局部观察，test标签不参与拟合。新算法只学习有限条件选择。A不通过负例验证调参，B不能移除A偶然过窄的条件。四组均完整评测。", "",
          "## 纯Gate测试", "", *table(headers, gate_rows), "",
          "完整观察的不适用分母16、适用分母8；UNKNOWN和查询成本覆盖每组96个掩码上下文。B-A错误放行差值-25个百分点，场景族配对bootstrap 95%区间[-50,-6.25]个百分点；错误拦截差值0。D-C为0。A的UNKNOWN更少部分源于少了条件，不能称认知更充分。", "",
          "2000次重采样只刻画当前合成场景族的不确定性；全零样本会产生退化区间，不证明未来风险为零。四种观察掩码不是四倍独立样本。oracle已用真实环境执行交叉核对；完整规则C与已知规则标签一致属预期现象。"]
    result = {"gate": gate["comparisons"], "system_complete": False}
    if (root / "system/completed.json").exists():
        expanded, completed = audit_system(plan_path, audit_only=True)
        repeated_inputs = {}
        for key, row in expanded.items():
            if key in completed["aliases"]:
                continue
            offset = row["boundary_experiment"]["forced_decisions"]
            for index, context in enumerate(row["boundary_experiment"]["actual_model_inputs"]):
                # ModelClient uses this exact unsorted JSON user-message string.
                text_key = digest(json.dumps(context, ensure_ascii=False))
                repeated_inputs.setdefault(text_key, []).append({"run": key, "step": index + offset, "action": row["steps"][index + offset]["action"]})
        repeats = {k: v for k, v in repeated_inputs.items() if len(v) > 1}
        divergent = {k: v for k, v in repeats.items() if len({digest(x["action"]) for x in v}) > 1}
        repeat_audit = {"repeated_exact_input_clusters": len(repeats), "divergent_action_clusters": len(divergent),
            "divergences": divergent, "scope": "Post-hoc read-only consistency check of exact serialized model contexts under the same pinned settings; aliases excluded. Cause not identified; no reruns or score replacement."}
        summaries, comparisons, counterfactuals = {}, {}, {}
        for group in "ABCD":
            summaries[group] = {mode: metrics([expanded[tid + "-" + group + "-" + mode] for tid in tasks], tasks) for mode in ("autonomous", "gate", "bypass")}
        for left, right in plan["primary_comparisons"]:
            l, r = ({tid: expanded[tid + "-" + g + "-autonomous"] for tid in tasks} for g in (left, right))
            normal = interval(l, r, tasks, lambda row: int(row["verification"]["task_success"]), plan, True)
            comparisons[left + "-" + right] = {"normal_success_difference": normal,
                "eoc_difference": interval(l, r, tasks, lambda row: int(row["verification"]["task_success"]), plan),
                "improved": [tid for tid in l if l[tid]["verification"]["task_success"] and not r[tid]["verification"]["task_success"]],
                "regressed": [tid for tid in l if r[tid]["verification"]["task_success"] and not l[tid]["verification"]["task_success"]],
                "supports_boundary_gain_with_normal_system_preserved": bool(gate["comparisons"][left + "-" + right]["supports_boundary_gain"] and normal["ci95"] and normal["ci95"][0] >= -plan["normal_success_margin"])}
            for metric in ("llm_calls", "tool_calls", "tokens"):
                comparisons[left + "-" + right][metric + "_difference"] = interval(l, r, tasks, lambda row: row["metrics"][metric], plan)
            comparisons[left + "-" + right]["blocked_write_difference"] = interval(l, r, tasks, lambda row: sum(e["tool_name"] in MUTATIONS and e["error"] == "business_rule_rejected" for e in row["tool_audit"]), plan)
        for g in "ABCD":
            pairs = []
            l, r = ({tid: expanded[tid + "-" + g + "-" + mode] for tid in tasks} for mode in ("gate", "bypass"))
            for tid in tasks:
                a, b = l[tid], r[tid]
                first = a["skill_events"][0]
                task = tasks[tid]
                full_state = {**a["initial_state"], **features(task.family, a["initial_state"], task.parameters)}
                truth = oracle(task.family, full_state, task.parameters)
                pairs.append({"task_id": tid, "cluster": tasks[tid].structure_id, "initial_gate_status": first["gate_status"],
                    "gate_status_timing": "first Skill attempt, after bounded hydration", "oracle_initial_applicability": truth,
                    "initial_false_block": bool(truth == "APPLICABLE" and (first.get("blocked") or first.get("error") == "precondition_failed")),
                    "gate_passed": a["verification"]["task_success"], "bypass_passed": b["verification"]["task_success"],
                    "forced_write_rejections_avoided": b["boundary_experiment"]["forced_tool_policy_attempts"] - a["boundary_experiment"]["forced_tool_policy_attempts"],
                    "gate_decisions_to_terminal": len(a["steps"]), "bypass_decisions_to_terminal": len(b["steps"]),
                    "gate_outcome": a["outcome"], "bypass_outcome": b["outcome"]})
            counterfactuals[g] = {"pairs": pairs, "initial_status_counts": dict(Counter(p["initial_gate_status"] for p in pairs)),
                "improved": sum(p["gate_passed"] and not p["bypass_passed"] for p in pairs),
                "regressed": sum(p["bypass_passed"] and not p["gate_passed"] for p in pairs),
                "forced_rejections_avoided": sum(p["forced_write_rejections_avoided"] for p in pairs),
                "eoc_difference": interval(l, r, tasks, lambda row: int(row["verification"]["task_success"]), plan),
                "tool_calls_difference": interval(l, r, tasks, lambda row: row["metrics"]["tool_calls"], plan)}
            for metric in ("llm_calls", "tokens"):
                counterfactuals[g][metric + "_difference"] = interval(l, r, tasks, lambda row: row["metrics"][metric], plan)
            counterfactuals[g]["forced_rejection_difference"] = interval(l, r, tasks, lambda row: row["boundary_experiment"]["forced_tool_policy_attempts"], plan)
            counterfactuals[g]["subgroups"] = {status: {"contexts": sum(p["initial_gate_status"] == status for p in pairs),
                "improved": sum(p["initial_gate_status"] == status and p["gate_passed"] and not p["bypass_passed"] for p in pairs),
                "regressed": sum(p["initial_gate_status"] == status and p["bypass_passed"] and not p["gate_passed"] for p in pairs)}
                for status in ("APPLICABLE", "INAPPLICABLE", "UNKNOWN")}
        result.update(system_complete=True, system=summaries, comparisons=comparisons, counterfactuals=counterfactuals,
                      actual_runs=completed["actual_runs"], logical_runs=completed["logical_runs"], aliases=len(completed["aliases"]), exact_input_consistency=repeat_audit)
        result["gate"] = {k: {**v, "system_gain_claim": comparisons[k]["supports_boundary_gain_with_normal_system_preserved"]} for k, v in gate["comparisons"].items()}
        auto_rows = [[g, s["passed"], f"{s['normal_passed']}/{s['normal_tasks']}", s["blocked_writes"], s["llm_calls"], s["tokens"], s["tool_calls"], s["budget_exhausted"]] for g in "ABCD" for s in [summaries[g]["autonomous"]]]
        auto_headers = ["Group", "EOC / 24", "Normal EOC", "Blocked writes", "Model calls", "Tokens", "Tools", "Budget exhausted"]
        cf_headers = ["Group", "Gate EOC", "Bypass EOC", "Improved", "Regressed", "Forced rejections avoided", "Gate tools", "Bypass tools"]
        cf_rows = [[g, summaries[g]["gate"]["passed"], summaries[g]["bypass"]["passed"], counterfactuals[g]["improved"], counterfactuals[g]["regressed"], counterfactuals[g]["forced_rejections_avoided"], summaries[g]["gate"]["tool_calls"], summaries[g]["bypass"]["tool_calls"]] for g in "ABCD"]
        atomic_json(root / "workbench-system.json", {"summary": [{"label": g, **summaries[g]["autonomous"]} for g in "ABCD"],
            "boundary_tables": [{"headers": auto_headers, "rows": auto_rows}, {"headers": cf_headers, "rows": cf_rows}],
            "scope": "216 actual / 288 logical runs; identical C/D public contracts explicitly aliased, not independent replications. Forced attempts excluded from autonomous model intent.", "comparisons": comparisons})
        introduction += ["", "## Real-model systems and candidate-point counterfactuals", "", f"{completed['actual_runs']} actual runs / {completed['logical_runs']} logical runs. Identical C/D public contracts reuse exactly audited trajectories through explicit aliases; these are not independent repeated runs.", "", *table(auto_headers, auto_rows), "", *table(cf_headers, cf_rows), "",
            "Each counterfactual starts before Gate queries with the same database, empty visible observations, fault queues and fixed program. Both arms force the same initial Skill attempt; only that attempt bypasses the Gate in the control. Later decisions use the pinned real model and the same group's boundaries. The Gate never chooses refusal/escalation. Forced attempts are separated from autonomous model intent; all query costs are included.", "",
            "The paired event breakdown and intervals are in results/boundary-study/v1/report.json. A better Gate score need not improve autonomous outcomes because the model already sees business policy and may avoid selecting the invalid Skill. D=C does not support learning beyond complete policy. No new-rule adaptation or deployment upgrade was performed."]
        zh += ["", "## 真实模型系统与候选点反事实", "", f"共{completed['actual_runs']}条真实执行、{completed['logical_runs']}条逻辑分支；C/D模型可见契约完全相同，使用显式等价引用，不当作独立重复。", "", *table(auto_headers, auto_rows), "", *table(cf_headers, cf_rows), "",
            "分叉在Gate查询之前，数据库、空初始观察、故障队列和固定程序一致。两臂都强制同一个初始Skill尝试，仅对照臂本次绕过Gate；后续由同一真实模型和同组边界自由续跑。Gate不替模型决定拒绝/转人工。实验强制尝试与模型自主意图分列；成本包含所有补查。", "",
            "逐点改善/退步、终态步数和区间见results/boundary-study/v1/report.json。Gate改善不必转化为自主系统成功率提升：模型仍看到业务policy，可能主动避开错误Skill。D=C不能支持学习超越完整规则。本轮不涉及新规则适应或部署升级。"]
        introduction += ["", "## Admission constraint and observed serving variability", "",
            "B-A did not meet the preregistered combined claim: autonomous normal-task EOC fell from 8/8 to 7/8 (difference -12.5 points; interval [-37.5, 0]). In the regressed partial-refund case, B's Gate offered the Skill, but the model immediately refused. This is not a Gate false block. A's five blocked autonomous writes were primitive tool actions, not executed Skills, so their reduction cannot be described as five autonomous wrong-Skill reuses prevented.", "",
            f"A post-hoc exact-input audit found {len(divergent)} divergent-action clusters among {len(repeats)} repeated serialized input clusters, excluding C/D aliases. Greedy settings did not imply observed bitwise repeatability. For example, B/C Gate branches on the same high-risk/failed-payment refund context produced different next actions despite identical serialized input and pinned settings. The cause is not established. We retain all records without rerunning to choose answers. Scenario-bootstrap intervals do not include repeated-serving variance; autonomous and continuation EOC differences should be treated as single-run descriptive evidence. C/D reuse expresses contract equivalence, not an empirical stability test.", "",
            "Portable CPU verification: `python -m scripts.audit_boundary_study`. Report regeneration: `python -m scripts.report_boundary_study`."]
        zh += ["", "## 未通过的正常收益约束与服务一致性检查", "",
            "B-A没有通过预声明的联合主张：自主正常任务由8/8降为7/8，差值-12.5个百分点，区间[-37.5,0]。退步的部分退款场景中，B的Gate已提供Skill，模型却立即refuse；这是模型终态错误，不是Gate误拦截。A自主执行中的5次被拦截写入全部来自primitive动作，不能写成避免了5次模型错误Skill复用。", "",
            f"事后只读检查发现：排除C/D等价引用后，{len(repeats)}组完全相同的序列化模型输入中，有{len(divergent)}组产生不同Action。greedy配置不等于观察到逐位可重复。例如高风险且支付失败的退款，B/C Gate分支的首个真实输入及模型身份相同，后续Action却不同。原因尚未确定；保留原结果，不重跑挑答案。场景bootstrap没有覆盖服务重复运行的方差，因此自主与续跑EOC差异应当作为单轮描述性结果。C/D复用表示契约等价，不是服务稳定性实验。", "",
            "跨机器CPU审核：`python -m scripts.audit_boundary_study`；重新生成报告：`python -m scripts.report_boundary_study`。"]
    else:
        introduction += ["", "Real-model system/counterfactual execution is still running. No partial score is reported."]
        zh += ["", "真实模型系统与候选点反事实仍在运行，部分轨迹不作为完整成绩。"]
    atomic_json(root / "report.json", result)
    for path, lines in (("docs/en/BOUNDARY_STUDY_RESULTS.md", introduction), ("docs/BOUNDARY_STUDY_RESULTS.md", zh)):
        Path(path).write_bytes(("\n".join(lines) + "\n").encode())
    atomic_json(root / "report-audit.json", {"passed": True, "preparation_audit": preparation_audit, "portable_auditor_sha256": file_hash("scripts/audit_boundary_study.py"), "preparation_auditor_sha256": file_hash("scripts/audit_boundary_preparation.py"), "system_complete": result["system_complete"], "reporter_sha256": file_hash(__file__),
        "report_sha256": file_hash(root / "report.json"), "reports": {p: file_hash(p) for p in ("docs/BOUNDARY_STUDY_RESULTS.md", "docs/en/BOUNDARY_STUDY_RESULTS.md")}})
    return {"system_complete": result["system_complete"], "gate_comparisons": gate["comparisons"]}


if __name__ == "__main__":
    print(json.dumps(report(), ensure_ascii=False))
