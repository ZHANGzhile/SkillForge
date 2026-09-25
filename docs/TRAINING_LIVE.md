# 训练实时进度

更新时间：2026-09-25 15:50:18

当前阶段：`sft`

此文件由训练流水线自动更新；进度与完成结论以实际结果文件为准。

```json
{
  "pid": 38296,
  "log": "results\\training\\main-v3\\logs\\sft-1790342817.log",
  "progress": {
    "status": "training",
    "stage": "sft",
    "step": 47,
    "total_steps": 318,
    "epoch": 0.2967640094711918,
    "elapsed_seconds": 1391.975739955902,
    "gpu_allocated_bytes": 3661595648,
    "gpu_peak_allocated_bytes": 7166130688,
    "loss": 0.0234,
    "grad_norm": 0.2290887087583542,
    "learning_rate": 9.758486875152766e-05
  }
}
```

阶段顺序：环境与GPU检查 → 完整模型训练smoke → SFT → DPO → Validation → 模型冻结 → Test → 去Gate消融 → 报告。
