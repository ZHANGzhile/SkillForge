"""Read-only consolidation of revised P1 development evidence, not efficacy."""
import argparse
import json
from pathlib import Path

from scripts.run_skill_evolution import digest_file, ROOT
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def summarize(organic, forks, output):
    organic, forks, output = Path(organic), Path(forks), Path(output)
    rows = [read(p) for p in sorted(organic.glob("*/result.json"))]
    arms = [read(p) for p in sorted(forks.glob("*/*/result.json"))]
    ordinary, paired = read(organic / "report.json"), read(forks / "report.json")
    fork_limits = read(forks / "registration.json")["config"]["limits"]
    discovery_enabled = bool(fork_limits["max_search"] or fork_limits["max_load"])
    prior_forks = []
    for prior in paired["shared_prior_cost"]:
        path = ROOT / prior["path"]
        previous = read(path / "report.json")
        if previous.get("pairs"):
            prior_forks.append({"run": prior["path"], "pairs": previous["pairs"], "n": previous["n"],
                                "status": previous["status"], "failure": previous.get("failure"),
                                "eoc": previous["eoc"], "report_sha256": digest_file(path / "report.json"),
                                "failures": [{"task_id": r["task_id"], "arm": r["arm"], "outcome": r["agent"]["outcome"],
                                              "errors": [s["error"] for s in r["agent"]["steps"] if s.get("error")]}
                                             for p in sorted(path.glob("*/*/result.json")) for r in [read(p)]
                                             if not r["verification"]["task_success"]]})
    counts = {name: sum(r["selection_funnel"]["organic_funnel"][name] for r in rows) for name in
              ("eligible", "searched", "retrieved", "loaded", "gate_applicable", "offered", "selected", "executed", "verified")}
    full_chains = [r["task_id"] for r in rows if r["selection_funnel"]["organic_funnel"]["verified"]]
    complete_ids = {p.parent.name for p in forks.glob("*/pair-check.json")}
    continuation = None
    if (forks / "continuation.json").exists():
        manifest = read(forks / "continuation.json")
        continuation = {"parent": manifest["parent"], "continuation_hash": manifest["continuation_hash"],
                        "inherited_cases": paired["n"] - paired["incremental_cases"],
                        "new_cases": paired["incremental_cases"],
                        "incremental_charged_tokens": paired["charged_tokens_including_incomplete"],
                        "incremental_wall_seconds": paired["wall_seconds"]}
    def stats(values):
        n = len(values)
        return {"n": n, "eoc": sum(r["verification"]["task_success"] for r in values),
                "autonomous_eoc": sum(r["verification"]["task_success"] and not r["agent"]["interventions"]["runtime_intervention_count"] for r in values),
                "runtime_assisted_eoc": sum(r["verification"]["task_success"] and bool(r["agent"]["interventions"]["runtime_intervention_count"]) for r in values),
                "runtime_intervention_rate": sum(bool(r["agent"]["interventions"]["runtime_intervention_count"]) for r in values) / n if n else None,
                "rescued_by_runtime": None,
                "rescued_by_runtime_reason": "No matched execution-contract-off counterfactual; assisted EOC alone does not identify rescue",
                "forced_readback_count": sum(r["agent"]["interventions"]["forced_readback_count"] for r in values),
                "auto_termination_count": sum(r["agent"]["interventions"]["auto_termination_count"] for r in values),
                "attempted_violations": sum(r["verification"]["attempted_policy_violation"] for r in values),
                "actual_violations": sum(r["verification"]["actual_policy_violation"] for r in values),
                "model_calls": sum(r["agent"]["metrics"]["llm_calls"] for r in values),
                "tokens": sum(r["agent"]["metrics"]["tokens"] for r in values),
                "skill_tasks": sum(bool(r["agent"]["skill_events"]) for r in values),
                "primitive_alternatives": sum(r["selection_funnel"]["raw_counts"]["legal_primitive_alternative"] for r in values)}
    result = {"schema": "revised-p1-development-summary-v1", "organic": stats(rows),
              "organic_funnel": counts, "full_chain_tasks": full_chains,
              "availability_pairs": paired["pairs"],
              "continuation": continuation,
              "organic_protocol": read(organic / "registration.json")["protocol"],
              "fork_protocol": read(forks / "registration.json")["protocol"],
              "fork_discovery_enabled_in_both_arms": discovery_enabled,
              "prior_availability_smokes": prior_forks,
              "provided": stats([r for r in arms if r["arm"] == "provided"]),
              "withheld": stats([r for r in arms if r["arm"] == "withheld"]),
              "paired_provided": stats([r for r in arms if r["arm"] == "provided" and r["task_id"] in complete_ids]),
              "paired_withheld": stats([r for r in arms if r["arm"] == "withheld" and r["task_id"] in complete_ids]),
              "unpaired_arms": [{"task_id": r["task_id"], "arm": r["arm"], "eoc": r["verification"]["task_success"]} for r in arms if r["task_id"] not in complete_ids],
              "fork_run_completed": paired["status"] == "complete", "fork_failure": paired["failure"],
              "shared_tokens_including_prior_and_failure": paired["shared_total_charged_tokens"],
              "shared_wall_seconds_including_prior_and_failure": paired["shared_total_wall_seconds"],
              "plumbing_passed": bool(full_chains and paired["engineering_passed"] and ordinary["status"] == "complete"),
              "agent_smoke_passed": bool(paired["status"] == "complete" and len(arms) == paired["planned"] and
                                          len(rows) == ordinary["planned"] and all(r["verification"]["task_success"] and
                                          not r["verification"]["attempted_policy_violation"] and
                                          not r["verification"]["actual_policy_violation"] for r in rows + arms)),
              "research_claim_passed": None, "isolated_activated": False, "deployed": False,
              "inputs": {str(organic / "report.json"): digest_file(organic / "report.json"),
                         str(forks / "report.json"): digest_file(forks / "report.json")},
              "generator_sha256": digest_file(__file__),
              "scope": "P1 engineering and small fixed-model dev smoke; initial full-task opportunities only; static library only; no statistical improvement or new Skill learning claim"}
    result["summary_hash"] = fingerprint(result)
    output.mkdir(parents=True, exist_ok=False)
    immutable_json(output / "summary.json", result)
    lines = ["# 新版 P1 开发验证结果", "", "固定 main-v3；全部结果为 dev。没有生成或激活新 Skill，没有研究收益或显著性主张。", "",
             "## 自然调用", "", f"{result['organic']['eoc']}/{len(rows)} EOC；{result['organic']['attempted_violations']} 违规尝试，{result['organic']['actual_violations']} 实际违规。",
             "", "独立初始完整任务机会漏斗（单位 task-revision，不是全任务分母）：", "",
             " → ".join(f"{name}={value}" for name, value in counts.items()), "",
             f"自然调用协议：`{result['organic_protocol']}`；最终分叉协议：`{result['fork_protocol']}`。两批是独立诊断，不能跨批计算同协议效果。", "",
             "## 同状态可见性分叉", "", "同一快照、公开读取、历史前缀、模型和预算；仅初始目录加载项不同。" +
             ("两臂均允许后续正常搜索/加载，因此这是初始预加载与自然发现的比较，不是正式 PrimitiveOnly。" if discovery_enabled else "两臂均禁用搜索/加载；零搜索预算会影响恢复，不能直接当作正式 PrimitiveOnly。"), "",
             "| Task | Arm | EOC | Skill calls | Model calls | Tokens | Runtime interventions |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for row in arms:
        a = row["agent"]
        lines.append(f"| {row['task_id']} | {row['arm']} | {int(row['verification']['task_success'])} | {len(a['skill_events'])} | {a['metrics']['llm_calls']} | {a['metrics']['tokens']} | {a['interventions']['runtime_intervention_count']} |")
    if continuation:
        lines += ["", f"本目录继承 {continuation['inherited_cases']} 个已完成臂，只新执行 {continuation['new_cases']} 个从未启动的臂。原 partial 报告保持不变；续跑新增成本为 {continuation['incremental_charged_tokens']:,} tokens / {continuation['incremental_wall_seconds']:.2f} 秒。继承臂不是新增独立样本，也没有重复计费。", "",
                  f"续跑身份：`{continuation['continuation_hash']}`；每次推理在既有 checkpoint ACK 前有不可变预算准入回执。"]
    lines += ["", "## 结论边界与成本", "",
              "原始失败、未加载调用和 primitive 替代保留；调用率不能替代 EOC。Runtime assisted 不直接等于 rescued，缺少关闭 contract 的配对消融时不估计后者。",
              "", f"共享开发账本累计 {result['shared_tokens_including_prior_and_failure']:,} tokens / {result['shared_wall_seconds_including_prior_and_failure']:.2f} 秒，包含既有两轮和加载模型前失败记录。CPU 准备、机会执行及工具内部成本另见原始报告。",
              "", "下一出口是 P2 的公开工作流与独立 EOC、真实 learn 数据及 Opportunity/TraceCompiler；真实 PrimitiveOnly/StaticLibrary/ExperienceEvolution 公平对照须在 P5 冻结并执行。此 smoke 不是正式 P5 泛化实验或模型比较。", ""]
    if paired["status"] != "complete":
        lines += ["## 未完成部分", "", f"本组只完成 {paired['pairs']} 个完整配对，另有 {len(result['unpaired_arms'])} 个单臂；单臂不进入配对效应。",
                  "", f"原因：`{paired['failure']}`。目前采用启动前预留整任务上限的保守预算检查；剩余额度小于单臂上限时不启动，不能把未执行结果填为成功。",
                  "", "P1 工程观测与已完成诊断可以审计，但本组计划尚未完成；正式准入与研究结论均未通过。下一步先补预算调度/安全续跑与 PrimitiveOnly 基线诊断，再推进 P2 的独立工作流目标。", ""]
    if prior_forks:
        lines += ["## 保留的历史分叉与停止记录", ""]
        for previous in prior_forks:
            lines += [f"`{previous['run']}`：{previous['eoc']}/{previous['n']} EOC。", ""]
            if previous["status"] != "complete":
                lines += [f"历史报告状态 `{previous['status']}`：`{previous['failure']}`。后续继承完成不改写该报告，也不把继承部分算作另一组独立样本。", ""]
            for failure in previous["failures"]:
                lines.append(f"- {failure['task_id']} / {failure['arm']}: {failure['outcome']}; {', '.join(failure['errors'])}")
            lines += ["", "首轮模型把 primitive 工具名输出为 Skill，随后调用零预算搜索。该失败用于公开接口的开发修正，不能把修正前后差异当作新技能学习收益。", ""]
    with (output / "REPORT.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organic", required=True); parser.add_argument("--forks", required=True); parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.organic, args.forks, args.output), ensure_ascii=False))
