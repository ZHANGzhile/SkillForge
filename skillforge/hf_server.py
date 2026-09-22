"""Single-worker, local-only serving for the trained NF4 Student."""
import json
import os
import threading
import time
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import Field

from .hf_model import HFModelClient
from .prompts import PROMPTS
from .schemas import StrictModel
from .dataset import digest


@asynccontextmanager
async def lifespan(app):
    label = os.getenv("SKILLFORGE_HF_LABEL", "SFT")
    plan = json.loads(Path("configs/training-runs.json").read_text(encoding="utf-8"))
    adapter = os.getenv("SKILLFORGE_HF_ADAPTER", str(Path(plan["root"]) / label.lower() / "adapter"))
    config = os.getenv("SKILLFORGE_HF_CONFIG", plan["config"])
    app.state.model = HFModelClient(config_path=config, adapter=None if label == "Base" else adapter, label=label)
    app.state.lock = threading.Lock()
    try:
        yield
    finally:
        app.state.model.close()


app = FastAPI(title="SkillForge Trained Student", lifespan=lifespan)


class Message(StrictModel):
    role: Literal["system", "user"]
    content: str


class ChatRequest(StrictModel):
    model: str
    messages: list[Message] = Field(min_length=2, max_length=2)
    temperature: Literal[0] = 0
    max_tokens: Literal[512] = 512
    seed: Literal[42] = 42
    response_format: dict = Field(default_factory=lambda: {"type": "json_object"})
    stream: Literal[False] = False


@app.get("/health")
def health():
    return {"ready": True, "model": app.state.model.model, "settings": app.state.model.settings}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": app.state.model.model, "object": "model", "owned_by": "local"}]}


@app.post("/v1/chat/completions")
def chat(request: ChatRequest):
    if request.model != app.state.model.model:
        raise HTTPException(404, "requested model is not loaded")
    if [m.role for m in request.messages] != ["system", "user"] or request.messages[0].content != PROMPTS["v2"]:
        raise HTTPException(400, "Student requires the frozen v2 system/user decision protocol")
    if request.response_format != {"type": "json_object"}:
        raise HTTPException(400, "only JSON Action responses are supported")
    try:
        context = json.loads(request.messages[1].content)
        if not isinstance(context, dict):
            raise ValueError("decision context must be an object")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    with app.state.lock:
        before = app.state.model.tokens
        try:
            action = app.state.model.decide(context)
        except Exception as exc:
            raise HTTPException(502, {"error": type(exc).__name__, "message": str(exc)[:500]}) from exc
        used = app.state.model.tokens - before
    return {"id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion", "created": int(time.time()),
        "model": request.model, "system_fingerprint": digest(app.state.model.settings),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": action.model_dump_json()}, "finish_reason": "stop"}],
        "usage": {"total_tokens": used}}
