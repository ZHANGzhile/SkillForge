"""Report bounded new-policy adaptation after complete CPU replay."""
from pathlib import Path

from scripts.coordinator_io import atomic_json
from scripts.evaluate_boundary_adaptation import prepare, run
from scripts.evaluate_reuse_ablation import read
from scripts.report_boundary_representation import markdown_table


def report():
    audit = run(audit=True)
    _, root, _, _, _ = prepare()
    data = read(root / "report.json")
    tables = []
    for split in ("validation", "test"):
        rows = []
        for world, value in data["worlds"].items():
            for group, splits in value["summary"].items():
                r = splits[split]
                rows.append([world, group, f"{r['false_allow']}/{r['inapplicable']}", f"{r['false_block']}/{r['applicable']}",
                    r["procedure_success"], r["initial_unknown"], r["remaining_unknown"], r["queries"], r["blocked_writes"], r["tool_calls"], r["actual_violations"]])
        tables.append({"headers": [split + " world", "Group", "False allow", "False block", "Procedure success", "Initial UNKNOWN", "Remaining UNKNOWN", "Queries", "Blocked writes", "All tools", "Actual violations"], "rows": rows})
    learned = {"headers": ["World", "Train success/failure", "Added condition", "Matches manual"], "rows": []}
    for world, r in data["worlds"].items():
        conditions = [s["condition"] for s in r["learned_conditions"]["steps"]]
        learned["rows"].append([world, f"{r['train_positive']}/{r['train_negative']}", str(conditions), r["learned_matches_manual"]])
    text = "\n\n".join(markdown_table(t) for t in [learned, *tables])
    zh = ("# 新规则适应实验结果\n\n[English](en/BOUNDARY_ADAPTATION_RESULTS.md)\n\n"
          "固定schema驱动有限学习器，在两个独立变化的业务世界中分别归纳出禁止shipment.status=PROCESSING、禁止order.status=PENDING。"
          "两次使用同一算法与候选域；拟合只接收旧业务边界和当前版本train成功/失败快照，不接收新规则函数或手写参考条件。\n\n"
          "完成192条实际程序探针、504次分组Gate/执行测量，并在CPU重新执行、重新拟合后通过审核。每世界train12、validation12、test72，属于预先设计的合成组合，不能当作72个独立政策变化。\n\n" + text + "\n\n"
          "## 结论与代价\n\n"
          "物流规则变化下，旧边界错误放行6/54，更新后0/54，18个可执行案例全部保留；订单规则变化下，8/56降为0/56，16个可执行案例全部保留。"
          "测试中的无效写入尝试分别6→0、8→0，三组实际非法状态变化均0。旧边界实际程序成功数没有减少，因为工具层拒绝保护了状态；本轮没有模型自动拒绝/转人工的EOC评测。\n\n"
          "每世界72个测试中，查询从144增为216。物流规则的总工具数234→288，订单规则232→280。因此新边界减少了到达工具拦截点的尝试，但增加查询成本；不能只报告错误放行下降而宣称总体更省。"
          "manual与learned条件相同，本轮支持受限条件空间内的经验适应，不支持超越完整新规则、发现任意新特征或开放世界泛化。\n\n"
          "四字段域、有限eq/in候选、旧完整policy均为人工先验；训练使用完整记录快照，未限制为模型当时读到的信息。新schema驱动搜索与首版按family限定字段的算法分别归档；没有根据某个新世界改学习器代码。"
          "环境的新规则仅在隔离CPU进程的原工具事务内检查，不改线上policy，原写入权限、幂等与退款程序保留。\n\n"
          "审核：`python -m scripts.evaluate_boundary_adaptation --audit`，会重放全部CPU证据并重拟合；完整规格、训练输入、程序审计与报告见results/boundary-adaptation/v1。\n")
    en = ("# Bounded adaptation to changed business rules\n\n[中文](../BOUNDARY_ADAPTATION_RESULTS.md)\n\n"
          "One frozen schema-driven learner inferred shipment.status=PROCESSING and order.status=PENDING exclusions in two independently changed policy worlds. "
          "Both use the same algorithm and candidate domains. Fitting receives the old business boundary and current-version train success/failure snapshots, never the new policy function or manual reference.\n\n"
          "All 192 controlled procedure probes and 504 grouped Gate/execution measurements passed CPU re-execution and refitting. Each world has 12 train, 12 validation and 72 test combinations. These are synthetic combinations, not 72 independent policy changes.\n\n" + text + "\n\n"
          "## Findings and cost\n\n"
          "For the shipment change, false allowance fell from 6/54 to 0/54 while all 18 applicable cases remained executable. For the order change, it fell from 8/56 to 0/56 while all 16 remained executable. "
          "Blocked write attempts fell 6→0 and 8→0; actual illegal state changes remained zero in every group. Successful procedure counts were unchanged because the tool layer already rejected invalid writes. "
          "This experiment does not evaluate autonomous model refusal/escalation or full-task EOC.\n\n"
          "Read queries increased from 144 to 216 per world's 72 test cases. Total tools increased 234→288 for the shipment change and 232→280 for the order change. "
          "The updated boundary prevents invalid attempts at a measurable query cost; lower false allowance is not evidence of lower total cost. "
          "Learned boundaries match the complete manual references. This supports adaptation in a declared finite condition space, not superiority to complete new policy, arbitrary feature discovery or open-world generalization.\n\n"
          "The four feature domains, eq/in syntax and old complete policy are human priors. Training uses complete recorded snapshots, not only observations available to a model. "
          "This schema-driven search is separate from the first study's family-restricted candidate generator. The learner is not edited between worlds. "
          "New policy checks run only inside the original tool transaction in an isolated CPU process; deployed policy, authorization, idempotency and the refund procedure remain unchanged.\n\n"
          "Re-execute and refit: `python -m scripts.evaluate_boundary_adaptation --audit`. Frozen specifications, exact learning inputs, tool audits and reports: results/boundary-adaptation/v1.\n")
    Path("docs/BOUNDARY_ADAPTATION_RESULTS.md").write_text(zh, encoding="utf-8")
    Path("docs/en/BOUNDARY_ADAPTATION_RESULTS.md").write_text(en, encoding="utf-8")
    atomic_json(root / "workbench.json", {"boundary_tables": [learned, *tables], "audit": audit,
        "scope": "Controlled CPU procedure evidence, not model EOC. Human feature priors; extra queries; learned equals complete manual policy; no deployment change."})
    return audit


if __name__ == "__main__":
    print(report())
