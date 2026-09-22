"""Render an evidence-backed Markdown report and exportable research figures.

Can run before held-out evaluation finishes: missing evidence stays explicitly
pending. A partial evaluation is never promoted to a final comparison.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path

from skillforge.training_data import file_hash


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def percent(value):
    return "未定义" if value is None else f"{value:.1%}"


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
        + ["| " + " | ".join(str(v).replace("|", "\\|") for v in row) + " |" for row in rows])


def generate(output="docs/RESEARCH_REPORT.md"):
    cache = Path(".runtime/matplotlib-cache").resolve()
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plan = read("configs/training-runs.json")
    config = read(plan["config"])
    train, evaluation = Path(plan["root"]), Path(plan["evaluation_root"])
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    assets = destination.parent / "assets/research"
    assets.mkdir(parents=True, exist_ok=True)
    evidence = {}
    def source(path):
        evidence[str(path)] = file_hash(path)
        return read(path)
    def save(fig, name):
        fig.savefig(assets / (name + ".png"), dpi=170, bbox_inches="tight")
        fig.savefig(assets / (name + ".svg"), bbox_inches="tight")
        plt.close(fig)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    baseline = source(config["baseline"])
    labels = [r["label"] for r in baseline["summary"]]
    values = [r["task_success_rate"] for r in baseline["summary"]]
    fig, ax = plt.subplots(figsize=(9, 4))
    bars = ax.bar(labels, values, color="#386c9c")
    ax.bar_label(bars, labels=[f"{v:.1%}" for v in values], padding=4)
    ax.set(ylim=(0, 1), ylabel="Expected Outcome Contract pass rate",
        title="Original Ollama/Q4 free-action baseline (78 tasks per group)")
    fig.text(.5, .01, "Single run; zero Skill calls in all groups. Not evidence of Skill execution gains.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .05, 1, 1))
    save(fig, "original-baseline")
    lines = ["# SkillForge 实验与技术报告", "", f"生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}", "",
        "本报告由实际结果文件生成，来源文件哈希另存于同目录的 RESEARCH_REPORT.sources.json。合成领域、单一随机种子，描述性结果不等于显著性或真实业务泛化。", "",
        "## 研究问题与实现", "",
        "研究对象是带适用边界的可执行技能，以及模型对技能、拒绝和转人工的选择。有限DSL支持call/assert/finish；Gate返回APPLICABLE/INAPPLICABLE/UNKNOWN，补查成本计入工具与延迟。Tool在事务内检查身份和业务policy，并保存mutation幂等记录。Expected Outcome Contract独立约束最终结局、状态与必要证据。", "",
        "技能边界使用train成功轨迹、失败轨迹和business policy，validation完成准入及最多两轮领域修订。冻结数据集有69 train、69 validation、78 test，包含test独占组合结构，仍不构成开放域泛化证明。", "",
        "## 后训练之前的真实基线", "",
        table(["组别", "任务数", "EOC合格率", "Skill尝试", "实际违规率"],
            [[r["label"], r["tasks"], percent(r["task_success_rate"]), r["skill_reuse_attempts"], percent(r["actual_policy_violation_rate"])] for r in baseline["summary"]]), "",
        "![原始基线](assets/research/original-baseline.png)", "",
        "原始自由Action组实际Skill调用均为0，不能从这些数字推导执行复用收益。B3自动Gate可提供额外观察，因此系统变化不必来自Skill执行。受限目录的27个validation及6个网页验收是另一协议，不混入此表。", "",
        "## 训练数据与正式权重", "",
        "真实轨迹筛出181个动作目标但没有Skill目标；独立标注的确定性契约教师提供186个目标，合并去重355个SFT例子，其中33个Skill动作。135个同上下文、同SQLite快照执行分支形成90对DPO偏好。教师llm_calls=0，不冒充真实模型成绩。validation另外冻结141个目标，只用于likelihood，不进入优化数据。", "",
        f"基座revision：`{config['revision']}`。NF4 double quant、BF16、LoRA r={config['lora_r']}、alpha={config['lora_alpha']}、batch=1、gradient accumulation={config['gradient_accumulation_steps']}、seed={config['seed']}。SFT为{config['sft_epochs']}轮，DPO为{config['dpo_epochs']}轮。", ""]
    training_rows = []
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    for stage, ax in zip(("sft", "dpo"), axes):
        result_path = train / stage / "result.json"
        if not result_path.exists():
            training_rows.append([stage.upper(), "未完成", "—", "—", "—"])
            continue
        result = source(result_path)
        adapter = train / stage / "adapter/adapter_model.safetensors"
        if result["status"] != "completed" or result["smoke_only"] or file_hash(adapter) != result["adapter_hash"]:
            raise ValueError("formal training evidence mismatch: " + stage)
        evidence[str(adapter)] = result["adapter_hash"]
        training_rows.append([stage.upper(), result["global_step"], f"{result['metrics']['train_loss']:.5f}",
            f"{result['max_gpu_memory_bytes'] / 1e9:.2f} GB", result["adapter_updated"]])
        metric_path = train / stage / "metrics.jsonl"
        evidence[str(metric_path)] = file_hash(metric_path)
        metrics = [json.loads(line) for line in metric_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        points = {row["step"]: row["loss"] for row in metrics if "loss" in row}
        ax.plot(sorted(points), [points[k] for k in sorted(points)], color="#386c9c", linewidth=1.5)
        ax.set(title=stage.upper() + " logged training loss", xlabel="Optimizer step", ylabel="Loss")
        ax.grid(alpha=.2)
    fig.tight_layout()
    save(fig, "training-loss")
    lines += [table(["阶段", "最终步数", "Trainer loss", "峰值allocated", "实际权重更新"], training_rows), "",
        "![训练loss](assets/research/training-loss.png)", "",
        "SFT曲线仅包含当前运行保存的日志，恢复前步骤不虚构补点。Trainer汇总loss与验证token加权loss不是同一口径；SFT和DPO目标不同，二者loss不能横向作为模型优劣。显存为PyTorch峰值allocated，不是整机占用。", ""]
    lines += ["## 已完成的独立验证", ""]
    validation_rows = []
    for label in ("Base", "SFT", "DPO"):
        folder = evaluation / (label + "-validation")
        if (folder / "evaluation.json").is_file():
            from scripts.audit_validation import audit as audit_validation
            validated = audit_validation(folder, plan["config"], plan["validation_loss_data"])
            source(folder / "evaluation.json")
            valid_cases = [row for group in validated["decision_level"] for row in group["cases"] if not row.get("skipped")]
            decision_accuracy = sum(row["correct"] for row in valid_cases) / len(valid_cases) if valid_cases else None
            validation_rows.append([label, validated["full_system"]["tasks"], percent(validated["full_system"]["task_success_rate"]),
                percent(decision_accuracy), validated["full_system"]["skill_reuse_attempts"], f"{validated['validation_loss']['token_weighted_loss']:.4f}"])
    if validation_rows:
        lines += [table(["模型", "任务数", "EOC合格率", "决策准确率", "Skill尝试", "验证token loss"], validation_rows), "",
            "仅展示本组全部完成且经逐条检查点重算审核的validation。缺席模型仍在运行或尚未完成；本表不替代最终test。", ""]
    else:
        lines += ["尚无完整通过审核的validation报告。", ""]
    comparison_path = evaluation / "comparison.json"
    if comparison_path.exists():
        from scripts.report_post_training import summarize_runs
        comparison = summarize_runs(evaluation)
        source(comparison_path)
        rows = comparison["summary"]
        lines += ["## 同协议后训练独立测试", "",
            "Base/SFT/DPO共享HF/NF4/cuDNN、自由Action、verified Skills及任务集。Base是相同技能上下文中的未微调模型，不能与原Ollama B0当成同一控制条件。", "",
            table(["模型", "EOC合格率", "决策准确率", "Skill尝试", "适用精度", "模型违规尝试", "实际违规", "验证loss"],
                [[r["label"], percent(r["task_success_rate"]), percent(r["decision_accuracy"]), r["skill_reuse_attempts"],
                  percent(r["skill_applicability_precision"]), percent(r["model_attempted_policy_violation_rate"]),
                  percent(r["actual_policy_violation_rate"]), f"{r['validation_token_loss']:.4f}" if r['validation_token_loss'] is not None else "未完成"] for r in rows]), ""]
        fig, ax = plt.subplots(figsize=(9, 4))
        positions = list(range(len(rows)))
        ax.bar([x-.18 for x in positions], [r["task_success_rate"] for r in rows], .36, label="Full system EOC")
        ax.bar([x+.18 for x in positions], [r["decision_accuracy"] or 0 for r in rows], .36, label="Fixed-candidate decision")
        ax.set(xticks=positions, xticklabels=[r["label"] for r in rows], ylim=(0, 1), ylabel="Rate", title="Held-out test, identical HF/NF4 protocol")
        ax.legend(loc="upper left", bbox_to_anchor=(0, 1.17), ncol=2)
        fig.tight_layout()
        save(fig, "post-training")
        lines += ["![后训练对照](assets/research/post-training.png)", "", "### 同任务配对变化", "",
            table(["模型", "Base失败→成功", "Base成功→失败"], [[k, v["helped"], v["hurt"]] for k, v in comparison["paired_vs_base"].items()]), "",
            "这些是相同任务上的描述性变化，不是因果NTR或显著性检验。", "", "### A–E分层", "",
            table(["模型", "层级", "数量", "EOC合格率"], [[label, level, group["tasks"], percent(group["task_success_rate"])] for label, levels in comparison["by_level"].items() for level, group in levels.items()]), "",
            "### 按任务领域分层", "",
            table(["模型", "领域", "数量", "EOC合格率"], [[label, family, group["tasks"], percent(group["task_success_rate"])] for label, families in comparison["by_family"].items() for family, group in families.items()]), "",
            "### 执行成本", "",
            table(["模型", "平均工具数", "平均Gate读取", "平均LLM调用", "平均tokens", "平均秒数"],
                [[r["label"], f"{r['average_tool_calls']:.2f}", f"{r['average_gate_tool_calls']:.2f}",
                  f"{r['average_llm_calls']:.2f}", f"{r['average_tokens']:.0f}", f"{r['average_latency_ms']/1000:.2f}"] for r in rows]), "",
            "工具成本包括Gate补查和Skill内部调用；延迟是本机串行测量，不将不同后端、硬件的耗时直接归因于算法。", "",
            "### 结局与失败分析", ""]
        categories = next(iter(comparison["supplementary_diagnostics"].values()))["task_counts"]
        lines += [table(["诊断", *[r["label"] for r in rows]],
            [[category, *[comparison["supplementary_diagnostics"][r["label"]]["task_counts"][category] for r in rows]] for category in categories]), "",
            "补充诊断按任务计数、允许重叠，依据已执行证据生成，不改原始verdict。tool_error_not_recovered在本表要求最终EOC失败；failure_to_stop仅在非复合任务已验证Skill成功后仍继续调用并耗尽预算时标记。wrong_reuse_associated_failure是关联，因果negative_transfer仍为null。", ""]
        for label in [r["label"] for r in rows]:
            breakdown = comparison["outcome_breakdown"][label]
            lines += [f"**{label}**：观察到的结局 `{json.dumps(breakdown['observed'], ensure_ascii=False)}`；符合EOC的结局 `{json.dumps(breakdown['correct_under_expected_outcome_contract'], ensure_ascii=False)}`。", "",
                f"错误分类：`{json.dumps(comparison['error_categories'][label], ensure_ascii=False)}`。", ""]
            failures = comparison["failed_tasks"][label]
            if failures:
                lines += [table(["失败任务", "领域", "原因"], [[r["task_id"], r["family"], ", ".join(r["reasons"] + r["categories"])] for r in failures[:5]]), "",
                    "上表为任务顺序中的前5个失败示例，完整失败清单保留在comparison.json，未按表现挑选。", ""]
    else:
        lines += ["## 后训练评测状态：未完成", "",
            "尚无通过完整审核的comparison.json。本报告不使用部分任务外推总体成绩，也不根据训练loss宣称SFT或DPO有效。当前实时阶段见TRAINING_LIVE.md。", ""]
    stability = []
    for label in ("Base", "SFT", "DPO"):
        path = evaluation / "stability" / label / "evaluation.json"
        if path.exists():
            from scripts.evaluate_stability import audit as audit_stability
            row = audit_stability(evaluation, label)
            source(path)
            stability.append([label, row["tasks"], row["repeats"], percent(row["pass_all_repeats"]), percent(row["outcome_consistency_rate"])])
    lines += ["## 重复执行稳定性", ""]
    if len(stability) == 3:
        lines += [table(["模型", "固定任务数", "次数", "三次全部合格", "结局一致率"], stability), "",
            "预先按三类primitive Skill×A/B/D/E各选task ID字典序首个任务，共12个；主test为第1次，额外2次独立环境。相同greedy设置，无抽样种子变化，属于描述性重复稳定性，不是pass@k或独立随机试验。", ""]
    else:
        lines += ["预声明子集已冻结在configs/stability.json；三组重复执行尚未全部完成，不给出稳定性结论。", ""]
    lines += ["## 复现与限制", "",
        "- 运行 `python -m scripts.run_training_pipeline` 恢复流水线；已有活跃流水线时不要重复启动。",
        "- 报告重建：`python -m scripts.write_research_report`；绘图依赖见requirements-report.txt。",
        "- 训练与评测检查模型、语料、任务、配置和代码身份；已完成权重不无记录覆盖。",
        "- 模型违规尝试、自动Gate尝试与实际违规分别解释；旧轨迹缺新归因字段时返回null。",
        "- 当前是单种子、受限合成领域，缺少真实业务、多模型和大规模泛化验证。",
        "- GPU评测串行执行，但期间存在CPU回归与文档工作；延迟是本机观察值，不是独占整机的严格性能基准。",
        "- 不适用复用与失败的关联不是因果负迁移；无相应反事实证据时causal NTR保持null。",
        "- 生产身份治理、外部支付幂等、多租户、高可用不在当前本地研究验收范围。", ""]
    destination.write_text("\n".join(lines), encoding="utf-8")
    destination.with_suffix(".sources.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"report": str(destination.resolve()), "held_out_complete": comparison_path.exists(), "figures": str(assets.resolve())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/RESEARCH_REPORT.md")
    args = parser.parse_args()
    print(json.dumps(generate(args.output), ensure_ascii=False, indent=2))
