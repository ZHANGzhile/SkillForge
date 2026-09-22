# 训练实时进度

更新时间：2026-09-18 11:52:49

当前阶段：`completed`

此文件由训练流水线自动更新；进度与完成结论以实际结果文件为准。

```json
{
  "training_root": "results\\training\\main-v2",
  "evaluation_root": "results\\post-training\\main-v2",
  "stability_completed": true,
  "report": "docs/RESEARCH_REPORT.md",
  "deployment_pending": true
}
```

阶段顺序：环境与GPU检查 → 完整模型训练smoke → SFT → DPO → Validation → 模型冻结 → Test → 去Gate消融 → 报告。
