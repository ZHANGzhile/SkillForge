"""Identical local HF/NF4 serving protocol for Base, SFT and DPO comparisons."""
import json
from pathlib import Path

from .prompts import PROMPTS
from .schemas import Action
from .training import load_base, render_prompt
from .training_data import file_hash


class HFModelClient:
    @staticmethod
    def settings_for(config, adapter, label):
        import torch
        return {"model": "Qwen3-4B-NF4-" + label, "revision": config["revision"], "adapter": "hf_nf4_local",
            "adapter_sha256": file_hash(Path(adapter) / "adapter_model.safetensors") if adapter else None,
            "system_prompt": PROMPTS["v2"], "prompt_version": "v2", "decision_protocol": "free_action",
            "quantization": "NF4 double quantization", "compute_dtype": "bfloat16", "max_tokens": 512,
            "sdpa_backend": config.get("sdpa_backend", "auto"),
            "response_format": "unconstrained_json_requested", "do_sample": False,
            "serving_code_hash": file_hash(__file__), "torch": torch.__version__}

    def __init__(self, config_path="configs/training.json", adapter=None, label="Base"):
        import torch
        from peft import PeftModel, prepare_model_for_kbit_training
        self.config = json.loads(Path(config_path).read_text(encoding="utf-8"))
        base, self.tokenizer = load_base(self.config)
        # Match the train/reference precision of embeddings and normalizations.
        base = prepare_model_for_kbit_training(base, use_gradient_checkpointing=False)
        self.network = PeftModel.from_pretrained(base, adapter, is_trainable=False) if adapter else base
        self.network.eval()
        self.model = "Qwen3-4B-NF4-" + label
        self.tokens = 0
        self.max_tokens = 512
        self.settings = self.settings_for(self.config, adapter, label)
        self.last_messages = []
        self.fatal_error = None

    def decide(self, context):
        import torch
        self.last_messages = [{"role": "system", "content": PROMPTS["v2"]},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)}]
        encoded = self.tokenizer(render_prompt(self.last_messages), return_tensors="pt", add_special_tokens=False)
        size = encoded["input_ids"].shape[1]
        if size + self.max_tokens > 16384:
            raise ValueError("decision exceeds the frozen 16k serving context budget")
        try:
            encoded = encoded.to("cuda")
            with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                output = self.network.generate(**encoded, max_new_tokens=self.max_tokens, do_sample=False,
                    use_cache=True, pad_token_id=self.tokenizer.eos_token_id, eos_token_id=self.tokenizer.eos_token_id)
        except RuntimeError as exc:
            # Runtime records ordinary model errors as failed task outcomes.
            # The evaluator must separately stop on an unusable CUDA backend.
            self.fatal_error = f"{type(exc).__name__}: {exc}"
            raise
        completion = output[0, size:]
        self.tokens += size + len(completion)
        self.last_response = self.tokenizer.decode(completion, skip_special_tokens=True)
        return Action.model_validate_json(self.last_response)

    def close(self):
        import gc
        import torch
        del self.network
        gc.collect()
        torch.cuda.empty_cache()
