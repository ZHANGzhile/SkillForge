import json
from pathlib import Path

report = {"compatible": False}
try:
    import torch
    import bitsandbytes as bnb
    import transformers
    import peft
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable")
    layer = bnb.nn.Linear4bit(64, 32, bias=False, compute_dtype=torch.bfloat16, quant_type="nf4").to("cuda")
    value = torch.randn(2, 64, device="cuda", dtype=torch.bfloat16, requires_grad=True)
    loss = layer(value).float().square().mean()
    loss.backward()
    torch.cuda.synchronize()
    if value.grad is None or not torch.isfinite(value.grad).all() or not value.grad.abs().sum() > 0:
        raise RuntimeError("NF4 backward produced no finite gradient")
    report = {"compatible": True, "gpu": torch.cuda.get_device_name(),
        "capability": list(torch.cuda.get_device_capability()), "cuda": torch.version.cuda,
        "torch": torch.__version__, "bitsandbytes": bnb.__version__,
        "transformers": transformers.__version__, "peft": peft.__version__,
        "nf4_loss": loss.item(), "backward_gradient_norm": value.grad.float().norm().item(),
        "scope": "CUDA NF4 forward/backward only; full Qwen adapter smoke is separate"}
except Exception as exc:
    report.update(error=type(exc).__name__, message=str(exc))
Path(".runtime/training-compatibility.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2), flush=True)
if not report["compatible"]:
    raise SystemExit(1)
