"""Explicit checkpoint migration for an attention-kernel-only training change."""
import json
from pathlib import Path

from .dataset import digest
from .training_data import file_hash


def audit_parent_checkpoint(path, config, stage, corpus_audit, sft_adapter_hash=None):
    path = Path(path)
    parent = json.loads((path.parent / "run.json").read_text(encoding="utf-8"))
    if parent["run_hash"] != digest({k: v for k, v in parent.items() if k != "run_hash"}):
        raise ValueError("parent training identity hash mismatch")
    recipe = lambda c: {k: v for k, v in c.items() if k != "sdpa_backend"}
    if (recipe(parent["config"]) != recipe(config) or parent["stage"] != stage or parent["smoke_only"]
            or parent["corpus_audit"] != corpus_audit or parent["sft_adapter_hash"] != sft_adapter_hash):
        raise ValueError("checkpoint migration requires the same recipe, corpus, stage and reference")
    required = {"adapter_model.safetensors", "adapter_config.json", "optimizer.pt", "scheduler.pt", "rng_state.pth", "trainer_state.json", "training_args.bin"}
    if not required <= {p.name for p in path.iterdir() if p.is_file()}:
        raise ValueError("checkpoint missing model/optimizer/scheduler/RNG state")
    state = json.loads((path / "trainer_state.json").read_text(encoding="utf-8"))
    if path.name != f"checkpoint-{state['global_step']}" or not 0 < state["global_step"] < state["max_steps"]:
        raise ValueError("parent must be an incomplete, step-bound checkpoint")
    return {"path": str(path), "parent_run_hash": parent["run_hash"], "parent_trainer_source_hash": parent["trainer_source_hash"],
        "global_step": state["global_step"], "change": "explicit SDPA backend; dataset, optimizer and training recipe preserved",
        "files": {p.name: file_hash(p) for p in sorted(path.iterdir()) if p.is_file()}}
