"""Describe completed frozen evidence, including failed acceptance and unchanged bundles."""
import argparse
import json
from pathlib import Path

from scripts.active_evolution_formal import load_protocol
from scripts.audit_active_evolution_delivery import read, require
from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint


def model_groups(root, rows, protocol):
    config = protocol["config"]["model_layer"]
    valid_refs = 4 * config["model_validation"] + 2 * config["model_stable_validation"]
    new_n, stable_n = config["model_test"], config["model_stable_test"]
    full_n = new_n + stable_n
    groups = []
    for stage in ("independent", "epoch-1", "epoch-2"):
        for method in protocol["config"]["methods"]:
            selected = [r for r in rows if r["stage"] == stage and r["method"] == method]
            require(bool(selected), "missing model group")
            result = {"stage": stage, "method": method, "worlds": [r["world"] for r in selected],
                      "changed_bundles": sum(r["before_patch"] != r["effective_patch"] for r in selected),
                      "admission_passed": sum(r["agent_admitted"] for r in selected),
                      "stable_regressions": sum(r["stable_regressions"] for r in selected)}
            for phase, offset in (("before", 0), ("after", full_n)):
                new, stable = [], []
                for row in selected:
                    refs = row["refs"][valid_refs + offset:valid_refs + offset + full_n]
                    results = [read(root / "model-layer/cache" / (key + ".json"))["result"] for key in refs]
                    new.extend(results[:new_n])
                    stable.extend(results[new_n:])
                def eoc(values):
                    return {"correct": sum(r["verification"]["task_success"] for r in values), "tasks": len(values)}
                result[phase] = {"new_world_eoc": eoc(new), "stable_eoc": eoc(stable),
                                 **{k: sum(r[phase][k] for r in selected) for k in
                                    ("decision_tasks", "decision_correct", "decision_false_allow", "decision_false_block",
                                     "decision_unknown", "actual_violations", "attempted_violations", "tokens", "seconds", "tool_calls")}}
            groups.append(result)
    return groups


def model_proposals(root, rows, protocol):
    config = protocol["config"]["model_layer"]
    n = config["model_validation"] + config["model_stable_validation"]
    decision_n = config["model_validation"]
    proposals = []
    for row in rows:
        directory = (root / "model-layer/independent" / row["world"] / row["method"] if row["stage"] == "independent"
                     else root / "model-layer/continuous" / row["stage"].split("-")[1] / row["method"])
        activation = read(directory / "activation.json")
        if activation["before_patch"] == activation["proposal_patch"]:
            continue
        refs = activation["validation_refs"]
        records = [read(root / "model-layer/cache" / (key + ".json"))["result"] for key in refs]
        before, after = records[:n], records[n:2 * n]
        db, da = records[2 * n:2 * n + decision_n], records[2 * n + decision_n:]
        regressions = [{"task_hash": a["spec_hash"], "normal": a["truth_executable"],
                        "before_outcome": a["agent"]["outcome"], "after_outcome": b["agent"]["outcome"],
                        "reasons": b["verification"]["reason"]}
                       for a, b in zip(before, after)
                       if a["verification"]["task_success"] and not b["verification"]["task_success"]]
        proposals.append({"stage": row["stage"], "world": row["world"], "method": row["method"],
                          "agent_admitted": activation["agent_admitted"], "validation_tasks": n,
                          "before_eoc": sum(r["verification"]["task_success"] for r in before),
                          "proposal_eoc": sum(r["verification"]["task_success"] for r in after),
                          "decision_tasks": decision_n, "before_decision": sum(r["decision_correct"] for r in db),
                          "proposal_decision": sum(r["decision_correct"] for r in da),
                          "normal_regressions": sum(r["normal"] for r in regressions), "regressions": regressions,
                          "scope": "proposal validation only; rejected proposals never replace the effective held-out bundle"})
    return proposals


def render(summary):
    cpu = summary["cpu"]
    lines = ["# Active Self-Evolution v1 — 正式验证", "",
             f"协议：`{summary['protocol_hash']}`。固定 main-v3 SFT；未进行 Continual QLoRA。", "",
             "## 独立 CPU Benchmark", "",
             "完整6 worlds × 5 paired seeds × 4 methods；每组最多20次交互。未收敛组的截断查询数计20。", "",
             "| Method | 收敛率 | 截断平均收敛查询数 | 实际查询总数 | False allow | False block | Actual violation | Stable退步 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for method, r in cpu["methods"].items():
        lines.append(f"| {method} | {r['convergence_rate_within_budget']:.1%} | {r['restricted_mean_queries_to_convergence']:.3f} | "
                     f"{r['actual_queries']} | {r['false_allow']} | {r['false_block']} | {r['actual_violations']} | {r['stable_regressions']} |")
    lines += ["", f"联合主指标点估计门槛：{cpu['joint_point_estimate_passed']}；held-out安全门槛：{cpu['heldout_safety_passed']}；"
              f"完整研究验收：{cpu['research_hypothesis_passed']}。",
              f"Active相对Random的RMQ下降：{cpu['relative_rmq_reduction']:.1%}。"
              f"配对bootstrap 95%区间：收敛率差{cpu['paired_bootstrap_95']['rate_difference']}；"
              f"RMQ差{cpu['paired_bootstrap_95']['rmq_difference']}。",
              "", "收敛是有限假设空间内的在线指标。其错误收敛、未获准发布及held-out错误均保留，不能把收敛等同于正确规则。",
              "", "## 连续 policy epoch", "",
              "W3→W5、seed=1701。每个epoch重新学习，版本继承上一实际准入bundle；拒绝更新时保留原patch。", "",
              "| Epoch | World | Method | 获准更新 | 新世界正确数（前→后 /80） | False allow | False block | Stable退步 |",
              "|---|---|---|---|---:|---:|---:|---:|"]
    for r in summary["continuous"]:
        lines.append(f"| {r['epoch']} | {r['world']} | {r['method']} | {r['accepted_update']} | {r['before_correct']}→{r['after_correct']} | "
                     f"{r['false_allow']} | {r['false_block']} | {r['negative_transfer_count']} |")
    lines += ["", "## 固定权重真实 Agent 双评测", "",
              "独立层只覆盖预声明W3/W5/W6、seed=101；每世界8个新世界及8个stable test，另做8个独立单动作Decision。"
              "连续层沿用两个epoch的独立数据。UNKNOWN Decision计错；EOC要求正确终态、状态与必要读回。", "",
              "| Stage | Method | 实际bundle变化数 | New EOC 前→后 | Stable EOC 前→后 | Decision 前→后 | 尝试违规 前→后 | 实际违规 前→后 | Stable退步 |",
              "|---|---|---:|---|---|---|---|---|---:|"]
    for r in summary["model"]:
        a, b = r["before"], r["after"]
        def rate(d):
            return f"{d['correct']}/{d['tasks']}"
        lines.append(f"| {r['stage']} | {r['method']} | {r['changed_bundles']} | {rate(a['new_world_eoc'])}→{rate(b['new_world_eoc'])} | "
                     f"{rate(a['stable_eoc'])}→{rate(b['stable_eoc'])} | {a['decision_correct']}/{a['decision_tasks']}→{b['decision_correct']}/{b['decision_tasks']} | "
                     f"{a['attempted_violations']}→{b['attempted_violations']} | {a['actual_violations']}→{b['actual_violations']} | {r['stable_regressions']} |")
    charged = summary["resource_accounting"]
    lines += ["", "Agent准入通过可以是同一bundle的对照通过；实际bundle变化数单独列出。表格评测的是准入后有效版本，"
              "被拒绝的proposal保存在activation及validation轨迹中，不替换为成功更新。", "",
              "### 更新提案为何未激活（仅Validation）", "",
              "| Stage | World | Method | EOC 前→提案 | Decision 前→提案 | 正常任务退步 | Agent准入 |",
              "|---|---|---|---|---|---:|---|"]
    for r in summary["proposals"]:
        lines.append(f"| {r['stage']} | {r['world']} | {r['method']} | {r['before_eoc']}→{r['proposal_eoc']} /{r['validation_tasks']} | "
                     f"{r['before_decision']}→{r['proposal_decision']} /{r['decision_tasks']} | {r['normal_regressions']} | {r['agent_admitted']} |")
    lines += ["", "四个Active更新提案的独立Decision validation均由7/8提高到8/8，但均引入正常任务退步；"
              "退步轨迹包括缺少写后读回验证和执行错误。Decision局部改善没有转化为可获准的完整Agent更新。"
              "这是Validation诊断，不是被拒绝proposal的held-out收益；正式test使用回退后的有效旧bundle。", "",
              "### 配对测试成本", "",
              "| Stage | Method | Full System tokens 前→后 | 工具调用 前→后 | Full System秒数 前→后 |",
              "|---|---|---:|---:|---:|"]
    for r in summary["model"]:
        a, b = r["before"], r["after"]
        lines.append(f"| {r['stage']} | {r['method']} | {a['tokens']}→{b['tokens']} | {a['tool_calls']}→{b['tool_calls']} | {a['seconds']:.1f}→{b['seconds']:.1f} |")
    lines += ["", f"实际唯一执行{charged['unique_executions']}次；基础设施失败尝试{charged['infrastructure_attempts']}次；"
              f"计费任务耗时{charged['charged_gpu_task_seconds'] / 3600:.3f}小时、{charged['charged_tokens']:,} tokens。",
              "上表成本包含按同一任务配对复用的控制组，不能跨方法加总作为真实资源消耗。计费账本则按唯一执行计算，"
              "包括验证、独立Decision与失败尝试的最坏token预留；任务耗时不包含进程启动，成本计划另留600秒。", "",
              "## 解释范围", "",
              "人工声明的六世界、公开状态域与有限假设空间；模型层为代表场景子协议。"
              "Boundary证据来自固定程序探针，不能称为模型自主探索。"
              "模型测试使用固定SFT权重，终态规则未学习；安全guard仍由环境执行，零实际违规不等于零错误决策。"
              "报告不据结果新增种子、调门槛或选择性重跑；负结果与未更新版本完整保留。", ""]
    if summary["invocation_wall_seconds"] is not None:
        lines += [f"本次完整调用实测（含模型进程启动和关闭）{summary['invocation_wall_seconds'] / 60:.2f}分钟，"
                  "时间和token均在12小时/20M限制内；见model-layer/invocations。", ""]
    return "\n".join(lines)


def summarize(root):
    root = Path(root)
    protocol = load_protocol(root)
    audit = read(root / "delivery-audit.json")
    require(audit["passed"] and audit["protocol_hash"] == fingerprint(protocol), "delivery audit required")
    rows = read(root / "model-report.json")["runs"]
    invocations = [read(p) for p in (root / "model-layer/invocations").glob("*.json")]
    wall = sum(r["wall_seconds"] for r in invocations) if invocations else None
    require(wall is None or wall <= 12 * 3600, "inclusive invocation budget exceeded")
    summary = {"protocol_hash": fingerprint(protocol), "renderer_sha256": file_hash(__file__),
               "cpu": read(root / "cpu-report.json")["aggregate"],
               "continuous": read(root / "continuous-report.json")["epochs"],
               "model": model_groups(root, rows, protocol), "proposals": model_proposals(root, rows, protocol),
               "resource_accounting": audit["model"], "invocation_wall_seconds": wall}
    immutable_json(root / "delivery-summary.json", summary)
    path = root / "DELIVERY.md"
    content = render(summary)
    if path.exists():
        require(path.read_text(encoding="utf-8") == content, "existing delivery rendering differs")
    else:
        path.write_text(content, encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="results/active-evolution/v1/formal-v1")
    args = parser.parse_args()
    summarize(args.root)
    print(str(Path(args.root) / "DELIVERY.md"))
