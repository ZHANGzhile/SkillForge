"""Measure a complete Qwen training example with an explicitly selected SDPA backend."""
import argparse
import json
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import set_seed

from skillforge.training import load_base, encode_example, collate_one, completion_logps, atomic_json
from skillforge.training_data import load_training_data


def profile(backend, output):
    config = json.loads(Path("configs/training.json").read_text(encoding="utf-8"))
    config["sdpa_backend"] = backend
    set_seed(config["seed"])
    if backend == "cudnn":
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        torch.backends.cuda.enable_math_sdp(False)
        torch.backends.cuda.enable_cudnn_sdp(True)
    torch.backends.cuda.matmul.allow_tf32 = True
    report = {"backend": backend, "stages": [], "completed": False}
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    def record(stage, started, **values):
        torch.cuda.synchronize()
        report["stages"].append({"stage": stage, "seconds": time.perf_counter() - started,
            "allocated_bytes": torch.cuda.memory_allocated(), "peak_allocated_bytes": torch.cuda.max_memory_allocated(), **values})
        atomic_json(target, report)
        print(json.dumps(report["stages"][-1]), flush=True)
    try:
        start = time.perf_counter()
        model, tokenizer = load_base(config)
        model = prepare_model_for_kbit_training(model, gradient_checkpointing_kwargs={"use_reentrant": False})
        model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=0,
            target_modules="all-linear", bias="none", task_type="CAUSAL_LM"))
        record("loaded", start)
        sft, _, _ = load_training_data(config["dataset"], config["bundle"], config["real_data"], config["supervision"], config["baseline"])
        rows = [encode_example(tokenizer, r["messages"][:-1], r["messages"][-1]["content"], config["max_length"]) for r in sft]
        longest = max((r for r in rows if r), key=lambda r: len(r["input_ids"]))
        batch = {k: v.to("cuda") for k, v in collate_one([longest]).items()}
        torch.cuda.reset_peak_memory_stats()
        model.train()
        start = time.perf_counter()
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            sums, counts = completion_logps(model, batch)
            loss = -(sums / counts).mean()
        record("forward", start, loss=float(loss.detach()), tokens=len(longest["input_ids"]))
        start = time.perf_counter()
        loss.backward()
        grads = [p.grad for p in model.parameters() if p.requires_grad and p.grad is not None]
        finite = all(bool(torch.isfinite(g).all()) for g in grads)
        nonzero = any(bool(g.abs().sum() > 0) for g in grads)
        record("backward", start, finite_gradients=finite, nonzero_gradients=nonzero)
        if not finite or not nonzero:
            raise ValueError("invalid adapter gradients")
        model.zero_grad(set_to_none=True)
        model.eval()
        start = time.perf_counter()
        with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            generated = model.generate(input_ids=batch["input_ids"][:, :128], attention_mask=batch["attention_mask"][:, :128], max_new_tokens=8,
                do_sample=False, use_cache=True, pad_token_id=tokenizer.eos_token_id)
        record("generation_with_cache", start, output_tokens=int(generated.shape[1] - 128))
        report["completed"] = True
    except BaseException as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        atomic_json(target, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["auto", "cudnn"], required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    profile(args.backend, args.output)
