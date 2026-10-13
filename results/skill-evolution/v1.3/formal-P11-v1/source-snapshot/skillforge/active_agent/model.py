"""Same main-v3 weights and decoding, separately identified versioned prompt."""
import json
from pathlib import Path
from ..hf_model import HFModelClient
from ..training import render_prompt
from ..training_data import file_hash
from ..schemas import Action
from .policy_view import SYSTEM_PROMPT,SCHEMA


class VersionedModel(HFModelClient):
    def __init__(self,config_path,adapter):
        super().__init__(config_path,adapter,"SFT")
        self.settings.update(system_prompt=SYSTEM_PROMPT,prompt_version=SCHEMA,
            decision_protocol="active_agent_free_action_v1",serving_code_hash=file_hash(__file__))

    def decide(self,context):
        import torch
        self.last_messages=[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":json.dumps(context,ensure_ascii=False)}]
        encoded=self.tokenizer(render_prompt(self.last_messages),return_tensors="pt",add_special_tokens=False)
        size=encoded["input_ids"].shape[1]
        if size+self.max_tokens>16384:raise ValueError("decision exceeds 16k context budget")
        try:
            encoded=encoded.to("cuda")
            with torch.inference_mode(),torch.autocast(device_type="cuda",dtype=torch.bfloat16):
                output=self.network.generate(**encoded,max_new_tokens=self.max_tokens,do_sample=False,use_cache=True,
                    pad_token_id=self.tokenizer.eos_token_id,eos_token_id=self.tokenizer.eos_token_id)
        except RuntimeError as exc:
            self.fatal_error=type(exc).__name__+": "+str(exc)
            raise
        completion=output[0,size:]
        self.tokens+=size+len(completion)
        self.last_response=self.tokenizer.decode(completion,skip_special_tokens=True)
        return Action.model_validate_json(self.last_response)
