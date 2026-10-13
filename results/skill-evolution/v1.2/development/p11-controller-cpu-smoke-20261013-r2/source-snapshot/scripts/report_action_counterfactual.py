"""Generate bilingual reports from fully re-audited counterfactual branches."""
import argparse
from pathlib import Path

from scripts.coordinator_io import atomic_json
from scripts.evaluate_action_counterfactual import read, run
from skillforge.training_data import file_hash


def report(plan_path="configs/action-counterfactual.json"):
    result = run(plan_path, audit_only=True)
    plan = read(plan_path)
    root, paired = Path(plan["output"]), result["paired"]
    rows = [read(p) for p in sorted((root / "branches").glob("*.json"))]
    summaries = []
    for arm in ("skill", "primitive"):
        group = [r for r in rows if r["counterfactual"]["arm"] == arm]
        n = len(group)
        summaries.append({"label": arm, "tasks": n,
            "task_success_rate": sum(r["verification"]["task_success"] for r in group) / n if n else None,
            "skill_reuse_attempts": sum(r["metrics"]["skill_calls"] for r in group),
            "actual_policy_violation_rate": sum(r["verification"]["actual_policy_violation"] for r in group) / n if n else None,
            "model_attempted_policy_violation_rate": sum(r["policy_attempts"]["model_triggered"] for r in group) / n if n else None,
            "continuation_llm_calls": sum(r["metrics"]["llm_calls"] for r in group),
            "continuation_tokens": sum(r["metrics"]["tokens"] for r in group),
            "post_fork_tool_calls": sum(r["metrics"]["tool_calls"] - r["counterfactual"]["fork"]["prefix_tool_calls"] for r in group)})
    # Do not relabel forced mutations as model-generated intent. Report the
    # runtime's origin metric with this qualification, not as free-agent safety.
    scope = "Single forced-action intervention at eligible observed Skill-use contexts; real-model continuation. Runtime policy-attempt attribution includes forced actions. Population NTR remains null."
    atomic_json(root / "workbench.json", {"summary": summaries, "action_counterfactual": paired,
        "scope": scope, "evaluation_sha256": file_hash(root / "evaluation.json"), "reporter_sha256": file_hash(__file__)})
    ntr = paired["observed_reuse_counterfactual_ntr"]
    ntr_text = "null" if ntr is None else f"{ntr:.2%}"
    table = ["| Arm | Qualified / contexts | Actual violation rate | Real continuation calls | Continuation tokens | Post-fork tool calls |",
             "|---|---:|---:|---:|---:|---:|"]
    for s in summaries:
        table.append(f"| {s['label']} | {round((s['task_success_rate'] or 0)*s['tasks'])}/{s['tasks']} | {s['actual_policy_violation_rate']} | {s['continuation_llm_calls']} | {s['continuation_tokens']} | {s['post_fork_tool_calls']} |")
    cases = ["| Context | Family | Skill qualified | Primitive qualified | Skill helped | Skill harmed |", "|---|---|---|---|---|---|"]
    for c in paired["cases"]:
        cases.append(f"| {c['case_id']} | {c['family']} | {c['skill_passed']} | {c['primitive_passed']} | {c['skill_helped']} | {c['skill_harmed']} |")
    en = ["# Observed-use action counterfactuals", "", "[English README](../../README.md) | [中文结果](../ACTION_COUNTERFACTUAL_RESULTS.md)", "",
        f"Completed {paired['contexts']} paired contexts / {len(rows)} branches. Excluded observed calls: {len(result['identity']['exclusions'])}. Both arms reproduce the exact original context, complete SQLite dump, remaining fault queues, and replay position before the intervention.", "", *table, "",
        f"Paired improvements: {paired['helped']}; regressions: {paired['harmed']}. Observed-reuse counterfactual NTR: **{ntr_text}**, with {paired['primitive_successes']} primitive-success contexts as the denominator. Population causal NTR remains **null**.", "",
        "## What is controlled and what is measured", "",
        "The next action is forced to the original Skill or its corresponding primitive mutation. Every later action is chosen by the same pinned HTTP model. Skill candidates, Gate behavior, policy, retry limits and the total 16-step budget remain unchanged. The primitive arm may choose a Skill later; this is a one-action intervention, not a no-Skill system.", "",
        "Replay and the forced action do not count as model calls. Calls/tokens above are actual post-intervention model requests; tool counts start at the fork and include the forced action's internal operations. Neither arm is an entirely autonomous run from the original task start. Runtime origin labels on forced actions must not be interpreted as model-generated violation intent.", "",
        "The selection scans every observed Skill call, independently of the source outcome. Its support is narrow: offered Skills with a read-only prefix and remaining continuation budget. These source calls happen to belong to successful trajectories; this does not establish safety of incorrect, unoffered, or never-selected Skills. One deterministic rollout per arm is not a confidence bound or population-wide guarantee.", "",
        "The source test has already been inspected. No training, prompt changes, deployment selection, or claim of repairing the ten main-v3 failures follows from this experiment. Previous whole-system NTR fields are preserved. Full branch context/state and continuation evidence are in results/action-counterfactual/main-v3.", "", "## Paired cases", "", *cases]
    zh = ["# 已观察复用点的动作级反事实结果", "", "[English](en/ACTION_COUNTERFACTUAL_RESULTS.md)", "",
        f"已完成{paired['contexts']}对上下文、{len(rows)}条分支；排除{len(result['identity']['exclusions'])}个源调用点。分叉前原context、完整SQLite dump、剩余故障队列及执行位置一致，之后由同一固定HTTP模型真实续跑。", "", *table, "",
        f"改善{paired['helped']}例，退步{paired['harmed']}例；以primitive成功的{paired['primitive_successes']}个上下文为分母，observed-reuse counterfactual NTR为 **{ntr_text}**。总体population causal NTR仍为 **null**。", "",
        "只强制分叉处一个动作，之后模型自主决策。两臂保留同样的Skill候选和Gate，primitive臂后续仍可选Skill；不是全程禁用Skill。前缀重放和强制动作不计模型调用，表中的模型调用/token是真实续跑成本，工具计数从分叉处开始并包含强制动作的内部工具。不是从任务起点全自主执行的成本对照。", "",
        "Runtime对工具的原始发起者归因包含强制动作，不能把其中实验控制的写入称作模型自己产生的违规意图。实际违规仍按状态审核；强制/重放次数和实际模型输入单独保存。", "",
        "筛选扫描全部真实Skill调用，不按源结局筛选；但实际这批调用所在原轨迹均成功。覆盖只限已提供、已选择、有只读前缀及续跑预算的Skill使用点，不能推广到错误复用、未被选择的Skill或全部78个任务。每臂一次确定性续跑，不提供总体置信保证。", "",
        "源test已被查看，本轮不训练、不改prompt、不选部署、不声称修复原10个失败。旧B0/B3系统消融的NTR字段不改写。报告先重放分叉、核对所有分支与连续状态链，再重算配对结果。", "", "## 逐上下文对照", "", *cases]
    Path("docs/en").mkdir(exist_ok=True)
    Path("docs/en/ACTION_COUNTERFACTUAL_RESULTS.md").write_bytes(("\n".join(en) + "\n").encode("utf-8"))
    Path("docs/ACTION_COUNTERFACTUAL_RESULTS.md").write_bytes(("\n".join(zh) + "\n").encode("utf-8"))
    receipt = {"passed": True, "contexts": paired["contexts"], "branches": len(rows),
        "evaluation_sha256": file_hash(root / "evaluation.json"), "reporter_sha256": file_hash(__file__),
        "reports": {str(p): file_hash(p) for p in (Path("docs/ACTION_COUNTERFACTUAL_RESULTS.md"), Path("docs/en/ACTION_COUNTERFACTUAL_RESULTS.md"))}}
    atomic_json(root / "audit.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", default="configs/action-counterfactual.json")
    print(report(parser.parse_args().plan))
