import json
import os
import hashlib
from pathlib import Path

import httpx

from .schemas import Action
from .prompts import PROMPTS
from .dataset import digest


class ModelClient:
    """OpenAI-compatible, visible action-only decisions; never consumes oracle state."""

    def __init__(self, url=None, model=None, key=None):
        profile_path = Path(os.getenv("SKILLFORGE_MODEL_CONFIG", "configs/model.local.json"))
        profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
        self.url = (url or os.getenv("SKILLFORGE_MODEL_URL") or profile.get("url", "http://localhost:8001/v1")).rstrip("/")
        self.model = model or os.getenv("SKILLFORGE_MODEL_NAME") or profile.get("model", "student")
        self.key = key or os.getenv("SKILLFORGE_API_KEY", "local")
        self.timeout = profile.get("timeout_seconds", 60)
        self.request_options = {k: profile[k] for k in ["max_tokens", "reasoning_effort", "seed"] if k in profile}
        self.adapter = profile.get("adapter", "openai")
        if self.adapter not in {"openai", "ollama_qwen3_raw"}:
            raise ValueError("Unsupported model adapter")
        self.tokens = 0
        self.prompt_version = profile.get("prompt_version", "v1")
        if self.prompt_version not in PROMPTS:
            raise ValueError("Unsupported prompt version")
        self.system_prompt = PROMPTS[self.prompt_version]
        self.last_messages = []
        self.require_server_identity = profile.get("require_server_identity", False)
        self.expected_fingerprint = None
        self.settings = {"model": self.model, "endpoint": self.url, "timeout_seconds": self.timeout,
            "prompt_version": self.prompt_version, "system_prompt": self.system_prompt,
            "prompt_sha256": hashlib.sha256(self.system_prompt.encode()).hexdigest(),
            "temperature": 0, "response_format": "json_object", "adapter": self.adapter, **self.request_options}

    def pin_identity(self):
        if not self.require_server_identity:
            return
        try:
            with httpx.Client(timeout=min(self.timeout, 5), trust_env=False) as client:
                response = client.get(self.url.removesuffix("/v1") + "/health")
                response.raise_for_status()
                report = response.json()
        except httpx.HTTPError as exc:
            raise ValueError("private Student is unavailable; start the selected trained model first") from exc
        if report.get("ready") is not True or report.get("model") != self.model or not isinstance(report.get("settings"), dict):
            raise ValueError("private Student identity does not match the selected model")
        self.settings["server_identity"] = report["settings"]
        self.expected_fingerprint = digest(report["settings"])

    def decide(self, context):
        if self.require_server_identity and self.expected_fingerprint is None:
            self.pin_identity()
        self.last_messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ]
        if self.adapter == "ollama_qwen3_raw":
            # Pinned Qwen3 ChatML renderer bypasses Ollama 0.34 chat-template /
            # thinking-parser incompatibility. Only the final JSON is consumed.
            prompt = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in self.last_messages)
            prompt += "<|im_start|>assistant\n<think>\n\n</think>\n\n"
            options = {"temperature": 0, "num_predict": self.request_options.get("max_tokens", 512)}
            if "seed" in self.request_options:
                options["seed"] = self.request_options["seed"]
            with httpx.Client(timeout=self.timeout, trust_env=False) as client:
                response = client.post(self.url.removesuffix("/v1") + "/api/generate",
                    json={"model": self.model, "prompt": prompt, "raw": True, "stream": False,
                          "format": "json", "options": options})
                response.raise_for_status()
                payload = response.json()
            self.tokens += payload.get("prompt_eval_count", 0) + payload.get("eval_count", 0)
            return Action.model_validate_json(payload["response"])
        with httpx.Client(timeout=self.timeout, trust_env=False) as client:
            response = client.post(self.url + "/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
                json={"model": self.model, "messages": self.last_messages, "temperature": 0, "response_format": {"type": "json_object"}, **self.request_options})
            response.raise_for_status()
            payload = response.json()
        self.tokens += payload.get("usage", {}).get("total_tokens", 0)
        if self.require_server_identity and payload.get("system_fingerprint") != self.expected_fingerprint:
            raise ValueError("private Student changed after the task was submitted")
        return Action.model_validate_json(payload["choices"][0]["message"]["content"])


class ScriptedPolicy:
    """Deterministic engineering fixture. Never report this as an LLM baseline."""
    model = "scripted-engineering-only"
    tokens = 0

    def decide(self, context):
        from .policies import eligibility
        state, params = context["observations"], context["parameters"]
        history = context["history"]
        if history and history[-1].get("result", {}).get("error") in {"timeout", "temporary_unavailable", "retry_budget_exhausted"}:
            return Action(type="escalate", arguments={"reason": "skill operation retry exhausted"})
        if any(e.get("retry_exhausted") for e in context.get("gate_observations", [])):
            return Action(type="escalate", arguments={"reason": "gate state read retry exhausted"})
        if any(e.get("error") in {"permission_denied", "not_found"} for e in context.get("gate_observations", [])):
            return Action(type="refuse")
        if history and history[-1].get("error") in {"permission_denied", "not_found"}:
            return Action(type="refuse")
        if history and history[-1].get("error") in {"timeout", "temporary_unavailable", "retry_budget_exhausted"}:
            return Action(type="escalate", arguments={"reason": "retry exhausted"})
        if any(s.get("action", {}).get("type") == "skill" and s.get("result", {}).get("success") for s in history):
            return Action(type="stop")
        reads = [("get_order", "order.status"), ("get_customer", "customer.risk_level")]
        if context["family"] != "refund":
            reads.insert(1, ("get_shipment", "shipment.status"))
        for tool, field in reads:
            if field not in state:
                return Action(type="tool", name=tool, arguments={"order_id": params["order_id"]})
        family = context["family"]
        if family in {"ticket", "shipment_investigation"}:
            return Action(type="escalate", arguments={"reason": "manual investigation"})
        tool = {"modify_address": "update_shipping_address", "cancel_order": "cancel_order", "refund": "issue_refund", "composite": "update_shipping_address"}[family]
        if family == "refund" and "payment.status" not in state:
            return Action(type="tool", name="get_payment", arguments={"order_id": params["order_id"]})
        if history and history[-1].get("error") in {"timeout", "temporary_unavailable"}:
            return Action(type="escalate", arguments={"reason": "retry exhausted"})
        mutations = {tool, "cancel_order"} if family == "composite" else {tool}
        executed = any(s.get("action", {}).get("name") in mutations and s.get("result", {}).get("ok") for s in history)
        if executed:
            check = "get_payment" if family == "refund" else "get_order"
            if history[-1].get("action", {}).get("name") == check:
                return Action(type="stop")
            return Action(type="tool", name=check, arguments={"order_id": params["order_id"]})
        decision = eligibility(tool, state, params)
        if family == "composite" and decision != "allow" and context.get("workflow") == "address_else_cancel_else_escalate":
            tool = "cancel_order"
            decision = eligibility(tool, state, {"order_id": params["order_id"]})
        if family == "composite" and decision != "allow":
            decision = "escalate"
        if decision == "refuse":
            return Action(type="refuse")
        if decision == "escalate":
            return Action(type="escalate", arguments={"reason": "policy boundary"})
        for skill in context["executable_skills"]:
            if skill["family"] == family:
                return Action(type="skill", name=skill["skill_id"], arguments=params)
        arguments = {"order_id": params["order_id"]} if tool == "cancel_order" else params
        return Action(type="tool", name=tool, arguments=arguments)
