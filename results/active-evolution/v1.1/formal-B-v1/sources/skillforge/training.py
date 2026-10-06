"""Single-GPU NF4 QLoRA SFT/DPO with completion-only losses and resumable checkpoints."""
import json
import math
import os
import time
from collections import Counter
from pathlib import Path

from .dataset import digest
from .training_data import file_hash, load_training_data
from .training_lineage import audit_parent_checkpoint


def render_prompt(messages):
    if [m["role"] for m in messages] != ["system", "user"]:
        raise ValueError("training uses one frozen system/user decision context")
    prompt = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
    return prompt + "<|im_start|>assistant\n<think>\n\n</think>\n\n"


def encode_example(tokenizer, prompt_messages, completion, max_length):
    prefix = tokenizer.encode(render_prompt(prompt_messages), add_special_tokens=False)
    target = tokenizer.encode(completion + "<|im_end|>", add_special_tokens=False)
    if not target or len(prefix) + len(target) > max_length:
        return None
    return {"input_ids": prefix + target, "labels": [-100] * len(prefix) + target,
        "attention_mask": [1] * (len(prefix) + len(target))}


def completion_logps(model, batch):
    """Project only the completion's preceding states to the large Qwen vocabulary.

    Identical causal likelihood to a full projection, much less GPU memory. The
    single-example batch restriction makes padding/target offsets unambiguous.
    """
    import torch
    labels = batch["labels"]
    if labels.shape[0] != 1:
        raise ValueError("tail-projection loss requires batch size one")
    active = torch.nonzero(labels[0] != -100, as_tuple=False).flatten()
    if not len(active) or int(active[0]) == 0:
        raise ValueError("completion must follow a masked prompt")
    start = int(active[0])
    keep = labels.shape[1] - start + 1
    outputs = model(input_ids=batch["input_ids"], attention_mask=batch["attention_mask"],
        logits_to_keep=keep, use_cache=False)
    logits = outputs.logits[:, :-1, :].float()
    target = labels[:, start:]
    mask = target != -100
    safe = target.masked_fill(~mask, 0)
    logps = logits.log_softmax(-1).gather(-1, safe.unsqueeze(-1)).squeeze(-1)
    return (logps * mask).sum(-1), mask.sum(-1)


def preference_loss(chosen, rejected, reference_chosen, reference_rejected, beta):
    import torch.nn.functional as F
    margin = beta * ((chosen - rejected) - (reference_chosen - reference_rejected))
    return -F.logsigmoid(margin).mean()


def collate_one(features):
    import torch
    if len(features) != 1:
        raise ValueError("one example per GPU microbatch is required")
    row = features[0]
    if "chosen" in row:
        return {"chosen": collate_one([row["chosen"]]), "rejected": collate_one([row["rejected"]]),
            "reference_chosen": torch.tensor([row["reference_chosen"]], dtype=torch.float32),
            "reference_rejected": torch.tensor([row["reference_rejected"]], dtype=torch.float32)}
    return {key: torch.tensor([row[key]], dtype=torch.long) for key in ("input_ids", "labels", "attention_mask")}


def load_base(config):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise RuntimeError("CUDA GPU with BF16 support is required")
    backend = config.get("sdpa_backend", "auto")
    if backend not in {"auto", "cudnn"}:
        raise ValueError("unsupported SDPA backend")
    # Windows wheels lack Flash Attention. GQA can otherwise select the
    # quadratic math path; the explicitly tested cuDNN backend avoids it.
    torch.backends.cuda.enable_flash_sdp(backend == "auto")
    torch.backends.cuda.enable_mem_efficient_sdp(backend == "auto")
    torch.backends.cuda.enable_math_sdp(backend == "auto")
    torch.backends.cuda.enable_cudnn_sdp(True)
    root = Path(config["base_model"])
    download = json.loads((root / "download_manifest.json").read_text(encoding="utf-8"))
    if download["revision"] != config["revision"]:
        raise ValueError("downloaded model revision mismatch")
    for entry in download["files"]:
        path = root / entry["file"]
        if path.stat().st_size != entry["bytes"] or file_hash(path) != entry["sha256"]:
            raise ValueError("downloaded model file failed integrity check: " + entry["file"])
    tokenizer = AutoTokenizer.from_pretrained(root, local_files_only=True, trust_remote_code=False)
    tokenizer.pad_token = tokenizer.eos_token
    quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(root, quantization_config=quantization,
        device_map={"": 0}, torch_dtype=torch.bfloat16, attn_implementation="sdpa",
        local_files_only=True, trust_remote_code=False)
    model.config.use_cache = False
    return model, tokenizer


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def train(config_path, stage, output, sft_adapter=None, resume=False, smoke=False, resume_checkpoint=None):
    import torch
    from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
    from transformers import Trainer, TrainerCallback, TrainingArguments, set_seed
    from transformers.trainer_utils import get_last_checkpoint
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    set_seed(config["seed"])
    # The frozen reference and Trainer policy must use the same matmul mode.
    torch.backends.cuda.matmul.allow_tf32 = True
    sft_rows, dpo_rows, audit = load_training_data(config["dataset"], config["bundle"], config["real_data"], config["supervision"], config["baseline"])
    if stage not in {"sft", "dpo"}:
        raise ValueError("stage must be sft or dpo")
    if stage == "dpo" and not sft_adapter:
        raise ValueError("DPO requires the trained SFT adapter as policy and reference")
    root = Path(output)
    identity = {"config": config, "stage": stage, "corpus_audit": audit, "smoke_only": smoke,
        "sft_adapter_hash": file_hash(Path(sft_adapter) / "adapter_model.safetensors") if sft_adapter else None,
        "trainer_source_hash": file_hash(__file__)}
    if resume_checkpoint:
        if smoke:
            raise ValueError("smoke cannot inherit a formal training checkpoint")
        identity["parent_checkpoint"] = audit_parent_checkpoint(resume_checkpoint, config, stage, audit, identity["sft_adapter_hash"])
    identity["run_hash"] = digest(identity)
    if root.exists():
        if not resume:
            raise ValueError("output directory already exists; use explicit --resume")
        if json.loads((root / "run.json").read_text(encoding="utf-8")) != identity:
            raise ValueError("resume config/corpus/adapter/trainer mismatch")
        if (root / "result.json").exists():
            raise ValueError("completed training runs are immutable")
    else:
        root.mkdir(parents=True)
        atomic_json(root / "run.json", identity)
    started = time.time()
    atomic_json(root / "progress.json", {"status": "loading_model", "stage": stage, "smoke_only": smoke})
    model, tokenizer = load_base(config)
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False})
    if stage == "sft":
        model = get_peft_model(model, LoraConfig(r=config["lora_r"], lora_alpha=config["lora_alpha"],
            lora_dropout=config["lora_dropout"], target_modules="all-linear", bias="none", task_type="CAUSAL_LM"))
    else:
        model = PeftModel.from_pretrained(model, sft_adapter, is_trainable=True)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    if not trainable:
        raise ValueError("no trainable adapter parameters")
    examples, skipped = [], []
    action_counts, origin_counts = Counter(), Counter()
    if stage == "sft":
        for row in sft_rows:
            encoded = encode_example(tokenizer, row["messages"][:-1], row["messages"][-1]["content"], config["max_length"])
            if encoded:
                examples.append(encoded)
                action_counts[json.loads(row["messages"][-1]["content"])["type"]] += 1
                origin_counts.update(row["origins"])
            else:
                skipped.append(row["example_id"])
    else:
        for i, row in enumerate(dpo_rows):
            chosen = encode_example(tokenizer, row["messages"], row["chosen"], config["max_length"])
            rejected = encode_example(tokenizer, row["messages"], row["rejected"], config["max_length"])
            if chosen and rejected:
                examples.append({"chosen": chosen, "rejected": rejected})
            else:
                skipped.append(i)
    if not examples:
        raise ValueError("no complete untruncated training examples remain")
    if stage == "sft" and not action_counts["skill"]:
        raise ValueError("no executable Skill targets remain after length filtering")
    if smoke:
        examples = sorted(examples, key=lambda row: len(row["input_ids"]) if stage == "sft"
            else max(len(row[key]["input_ids"]) for key in ("chosen", "rejected")), reverse=True)[:config["gradient_accumulation_steps"]]
    data_report = {"examples": len(examples), "oversize_skipped": skipped, "truncation": "none",
        "sft_actions_after_length_filter": dict(action_counts), "sft_origins_after_length_filter": dict(origin_counts),
        "smoke_selection": "longest complete examples" if smoke else None,
        "trainable_parameters": trainable, "gpu": torch.cuda.get_device_name(), "torch": torch.__version__}
    atomic_json(root / "data_report.json", data_report)
    if stage == "dpo":
        reference_path = root / "reference_logps.json"
        if reference_path.exists():
            cache = json.loads(reference_path.read_text(encoding="utf-8"))
            if cache["run_hash"] != identity["run_hash"] or len(cache["values"]) != len(examples):
                raise ValueError("DPO reference cache identity mismatch")
            values = cache["values"]
        else:
            # Before any update, this model IS the SFT reference. Freeze all of
            # its completion log probabilities, then train the same adapter.
            model.eval()
            values = []
            with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                for i, row in enumerate(examples):
                    pair = []
                    for key in ("chosen", "rejected"):
                        batch = {k: v.to("cuda") for k, v in collate_one([row[key]]).items()}
                        pair.append(float(completion_logps(model, batch)[0].item()))
                    values.append(pair)
                    atomic_json(root / "progress.json", {"status": "reference_scoring", "completed": i + 1, "total": len(examples)})
            atomic_json(reference_path, {"run_hash": identity["run_hash"], "values": values})
        for row, pair in zip(examples, values):
            row.update(reference_chosen=pair[0], reference_rejected=pair[1])
    model.train()
    class LossTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
            if stage == "sft":
                logps, count = completion_logps(model, inputs)
                loss = -(logps / count).mean()
            else:
                chosen, _ = completion_logps(model, inputs["chosen"])
                rejected, _ = completion_logps(model, inputs["rejected"])
                loss = preference_loss(chosen, rejected, inputs["reference_chosen"], inputs["reference_rejected"], config["dpo_beta"])
            return (loss, {"loss": loss}) if return_outputs else loss
    class Progress(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            update = {"status": "training", "stage": stage, "step": state.global_step,
                "total_steps": state.max_steps, "epoch": state.epoch, "elapsed_seconds": time.time() - started,
                "gpu_allocated_bytes": torch.cuda.memory_allocated(), "gpu_peak_allocated_bytes": torch.cuda.max_memory_allocated(), **(logs or {})}
            atomic_json(root / "progress.json", update)
            with (root / "metrics.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(update) + "\n")
    args = TrainingArguments(output_dir=str(root), num_train_epochs=config[stage + "_epochs"],
        max_steps=1 if smoke else -1, per_device_train_batch_size=1,
        gradient_accumulation_steps=config["gradient_accumulation_steps"],
        learning_rate=config[stage + "_learning_rate"], bf16=True, tf32=True,
        gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False},
        logging_steps=1, save_steps=config["save_steps"], save_total_limit=2,
        optim="adamw_torch", report_to="none", remove_unused_columns=False,
        dataloader_num_workers=0, dataloader_pin_memory=False, seed=config["seed"],
        lr_scheduler_type="cosine", warmup_ratio=0.0 if smoke else 0.05, max_grad_norm=1.0,
        label_names=["labels"] if stage == "sft" else [], save_safetensors=True)
    trainer = LossTrainer(model=model, args=args, train_dataset=examples,
        data_collator=collate_one, processing_class=tokenizer, callbacks=[Progress()])
    trainer.model_accepts_loss_kwargs = False
    checkpoint = get_last_checkpoint(str(root)) if resume else None
    checkpoint = checkpoint or resume_checkpoint
    resumed_step = json.loads((Path(checkpoint) / "trainer_state.json").read_text(encoding="utf-8"))["global_step"] if checkpoint else 0
    def adapter_fingerprint():
        import hashlib
        h = hashlib.sha256()
        for name, parameter in model.named_parameters():
            if parameter.requires_grad:
                if not torch.isfinite(parameter).all():
                    raise ValueError("nonfinite trainable parameter: " + name)
                h.update(name.encode())
                h.update(parameter.detach().float().cpu().numpy().tobytes())
        return h.hexdigest()
    initial_adapter = adapter_fingerprint()
    try:
        result = trainer.train(resume_from_checkpoint=checkpoint)
        final_adapter = adapter_fingerprint()
        if not math.isfinite(result.training_loss) or initial_adapter == final_adapter:
            raise ValueError("training did not produce finite updated adapter weights")
        adapter = root / "adapter"
        model.save_pretrained(adapter, safe_serialization=True)
        tokenizer.save_pretrained(adapter)
        report = {"status": "completed", "stage": stage, "smoke_only": smoke,
            "resumed_from_step": resumed_step, "new_optimizer_steps": trainer.state.global_step - resumed_step,
            "global_step": trainer.state.global_step, "metrics": result.metrics,
            "elapsed_seconds": time.time() - started, "max_gpu_memory_bytes": torch.cuda.max_memory_allocated(),
            "adapter_hash": file_hash(adapter / "adapter_model.safetensors"), "run_hash": identity["run_hash"]}
        report["adapter_updated"] = initial_adapter != final_adapter
        atomic_json(root / "result.json", report)
        atomic_json(root / "progress.json", report)
        return report
    except BaseException as exc:
        atomic_json(root / "progress.json", {"status": "failed", "stage": stage, "error": type(exc).__name__,
            "message": str(exc)[:1500], "last_checkpoint": get_last_checkpoint(str(root))})
        raise
