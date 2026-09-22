"""Formal research task entry point; protocol and evidence remain explicit."""
import json
import os
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import Field, model_validator

from .dataset import digest, load_dataset
from .environment import Environment
from .experiment import load_bundle
from .jobs import JobStore, Worker
from .menu_model import MenuModelClient
from .model import ModelClient, ScriptedPolicy
from .runtime import Runtime
from .schemas import SkillContract, StrictModel, Task

router = APIRouter(prefix="/api/v1")


class RunSubmission(StrictModel):
    task_id: str | None = None
    task: Task | None = None
    protocol: Literal["free_action", "skill_menu"] = "skill_menu"
    variant: Literal["B0", "B1", "B2", "B3", "B3-no-gate"] = "B3"
    max_steps: int = Field(default=16, ge=1, le=64)
    engineering: bool = False

    @model_validator(mode="after")
    def selection(self):
        if (self.task_id is None) == (self.task is None):
            raise ValueError("provide exactly one of task_id or task")
        if self.protocol == "skill_menu" and (self.variant != "B3" or self.engineering):
            raise ValueError("skill_menu requires real Student and B3; it is a distinct protocol")
        return self


def code_hash():
    return digest({p.name: p.read_text(encoding="utf-8") for p in sorted(Path(__file__).parent.glob("*.py"))})


def training_reserves_gpu():
    path = Path(".runtime/training-pipeline.json")
    if not path.is_file():
        return None
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("stage") not in {"completed", "failed"} and 0 <= time.time() - state.get("at", 0) < 60:
        return state.get("stage")
    return None


class Workbench:
    def __init__(self, root=None, dataset=None, bundle=None):
        self.store = JobStore(root or os.getenv("SKILLFORGE_JOB_ROOT", "results/workbench"))
        self.dataset = Path(dataset or os.getenv("SKILLFORGE_DATASET", "data/experiment-v1"))
        self.bundle = Path(bundle or os.getenv("SKILLFORGE_BUNDLE", "results/real-v2-frozen/frozen.json"))
        self.loaded_code_hash = code_hash()
        self.worker = Worker(self.store, self.execute)

    @staticmethod
    def model(request):
        model = ScriptedPolicy() if request["engineering"] else MenuModelClient() if request["protocol"] == "skill_menu" else ModelClient()
        if isinstance(model, ModelClient):
            model.pin_identity()
        return model

    def freeze(self, submission):
        if code_hash() != self.loaded_code_hash:
            raise ValueError("project code changed; restart the API before submitting new runs")
        if not submission.engineering and training_reserves_gpu():
            raise ValueError("本机训练流水线正在使用或准备使用 GPU，请在训练结束后提交真实模型任务；报告和历史记录仍可查看。")
        manifest, tasks = load_dataset(self.dataset)
        request = submission.model_dump(exclude={"task_id", "task"})
        if submission.task is not None:
            task = submission.task.model_copy(deep=True)
            # Manual tasks never acquire membership in a frozen training corpus.
            task.dataset_id = "manual-unregistered"
            task.task_id = "manual-" + digest(task.model_dump())[:24]
            if not task.expected.allowed_outcomes:
                raise ValueError("manual tasks require a nonempty Expected Outcome Contract")
            request["origin"] = "manual"
        else:
            task = next((t for t in tasks if t.task_id == submission.task_id), None)
            if task is None:
                raise KeyError("dataset task not found")
            request["origin"] = "dataset"
        if submission.protocol == "skill_menu" and (task.family not in {"modify_address", "cancel_order", "refund"} or task.workflow != "primitive"):
            raise ValueError("skill_menu supports the three primitive Skill families; use free_action for other workflows")
        request["task"] = task.model_dump()
        request["dataset_hash"] = manifest["dataset_hash"]
        request["bundle_hash"] = None
        if submission.variant != "B0":
            bundle, _ = load_bundle(self.bundle, manifest["dataset_hash"])
            if bundle["engineering_only"] and not submission.engineering:
                raise ValueError("engineering Skill sources cannot enter real model research runs")
            request["bundle_hash"] = bundle["bundle_hash"]
        model = self.model(request)
        request["model_settings"] = getattr(model, "settings", {"model": model.model})
        request["code_hash"] = self.loaded_code_hash
        return request

    def execute(self, job, emit, cancelled):
        request = job["request"]
        task = Task.model_validate(request["task"])
        if not request["engineering"] and training_reserves_gpu():
            raise ValueError("GPU reserved by the training pipeline; retry after training completes")
        if request["code_hash"] != self.loaded_code_hash or request["code_hash"] != code_hash():
            raise ValueError("code changed after submission; create a new run to record the new version")
        model = self.model(request)
        if getattr(model, "settings", {"model": model.model}) != request["model_settings"]:
            raise ValueError("model configuration changed after submission; create a new run")
        skills, memory = [], []
        if request["bundle_hash"]:
            bundle, verified_skills = load_bundle(self.bundle, request["dataset_hash"])
            if bundle["bundle_hash"] != request["bundle_hash"]:
                raise ValueError("frozen bundle changed after submission")
            if request["variant"] == "B1":
                memory = bundle["memory"]
            elif request["variant"] == "B2":
                skills = [SkillContract.model_validate(s) for s in bundle["naive_skills"]]
            else:
                skills = verified_skills
        root = self.store.directory(job["id"])
        root.mkdir(parents=True, exist_ok=False)
        (root / "request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        env = Environment(path=root / "environment.sqlite", fixture=task.fixture, faults=task.fixture.get("faults"))
        try:
            result = Runtime(model, skills=skills, memory=memory, max_steps=request["max_steps"],
                verified=request["variant"] not in {"B2", "B3-no-gate"}).run(task, env, on_event=emit, cancelled=cancelled)
        finally:
            env.close()
        result.update({"run_id": job["id"], "protocol": request["protocol"], "variant": request["variant"],
            "engineering_only": request["engineering"], "origin": request["origin"],
            "bundle_hash": request["bundle_hash"], "source_code_hash": request["code_hash"],
            "model_exchanges": getattr(model, "exchanges", [])})
        temporary = root / "trajectory.tmp"
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(root / "trajectory.json")
        return result


def service(request):
    workbench = getattr(request.app.state, "workbench", None)
    if workbench is None:
        raise HTTPException(503, "workbench lifespan has not started")
    return workbench


def lookup(request, run_id):
    try:
        return service(request).store.get(run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


def public_job(job, full=True):
    if full:
        return job
    task = job["request"]["task"]
    result = job["result"] or {}
    return {k: job[k] for k in ("id", "status", "created_at", "updated_at", "cancel_requested", "retry_of", "error")} | {
        "task_id": task["task_id"], "family": task["family"], "split": task["split"], "request": task["request"],
        "protocol": job["request"]["protocol"], "variant": job["request"]["variant"],
        "engineering_only": job["request"]["engineering"], "verification": result.get("verification"), "outcome": result.get("outcome")}


@router.get("/health")
def health(request: Request):
    wb = service(request)
    model = ModelClient()
    return {"status": "ready" if wb.worker.alive else "worker_unavailable", "worker_alive": wb.worker.alive,
        "model": model.model, "allowed_protocols": ["skill_menu", "free_action"] if model.adapter == "ollama_qwen3_raw" else ["free_action"],
        "training_gpu_reservation": training_reserves_gpu(),
        "storage": str(wb.store.root), "schema_version": 1, "execution": "single_worker_isolated_simulation"}


@router.get("/dataset")
def dataset(request: Request, split: Literal["train", "validation", "test"] | None = None):
    manifest, tasks = load_dataset(service(request).dataset)
    return {"manifest": manifest, "tasks": [t.model_dump() for t in tasks if split is None or t.split == split]}


@router.get("/skills")
def skills(request: Request):
    wb = service(request)
    manifest, _ = load_dataset(wb.dataset)
    bundle, contracts = load_bundle(wb.bundle, manifest["dataset_hash"])
    return {"bundle_hash": bundle["bundle_hash"], "engineering_only": bundle["engineering_only"], "skills": [s.model_dump() for s in contracts]}


@router.post("/runs", status_code=202)
def submit(request: Request, payload: RunSubmission, idempotency_key: str | None = Header(default=None, max_length=200)):
    wb = service(request)
    try:
        job, created = wb.store.submit(wb.freeze(payload), idempotency_key)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, str(exc)) from exc
    wb.worker.wake.set()
    return {"run_id": job["id"], "status": job["status"], "created": created}


@router.get("/runs")
def runs(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return {"runs": [public_job(j, full=False) for j in service(request).store.list(limit, offset)]}


@router.get("/runs/{run_id}")
def run(request: Request, run_id: str):
    return lookup(request, run_id)


@router.get("/runs/{run_id}/events")
def events(request: Request, run_id: str, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
    lookup(request, run_id)
    items = service(request).store.events(run_id, after, limit)
    return {"events": items, "next_cursor": items[-1]["seq"] if items else after}


@router.post("/runs/{run_id}/cancel")
def cancel(request: Request, run_id: str):
    lookup(request, run_id)
    return public_job(service(request).store.cancel(run_id), full=False)


@router.post("/runs/{run_id}/retry", status_code=202)
def retry(request: Request, run_id: str, idempotency_key: str | None = Header(default=None, max_length=200)):
    lookup(request, run_id)
    wb = service(request)
    try:
        job, created = wb.store.retry(run_id, idempotency_key)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    wb.worker.wake.set()
    return {"run_id": job["id"], "created": created}


@router.get("/runs/{run_id}/artifacts/{name}")
def artifact(request: Request, run_id: str, name: str):
    job = lookup(request, run_id)
    if name not in {"request.json", "trajectory.json", "environment.sqlite"}:
        raise HTTPException(404, "unknown artifact")
    if name == "environment.sqlite" and job["status"] in {"queued", "running"}:
        raise HTTPException(409, "database download requires a terminal run")
    path = service(request).store.directory(run_id) / name
    if not path.is_file():
        raise HTTPException(404, "artifact not available; interrupted runs retain events and committed database state")
    return FileResponse(path, filename=f"{run_id}-{name}")


@router.get("/reports")
def reports():
    registry = Path("configs/evidence.json")
    entries = json.loads(registry.read_text(encoding="utf-8")) if registry.exists() else []
    output = []
    for entry in entries:
        path = Path(entry["path"])
        output.append({**entry, "available": path.is_file(), "data": json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None})
    state = training_status()
    statuses = {}
    for stage in ("sft", "dpo"):
        entry = state.get("stages", {}).get(stage, {})
        statuses[stage] = (entry.get("result") or entry.get("progress") or {}).get("status", "not_trained")
    statuses["post_training_evaluation"] = "completed" if state.get("post_training_comparison") else "pending"
    return {"reports": output, "training": statuses}


@router.get("/training")
def training_status():
    def read(path):
        path = Path(path)
        return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else None
    plan = read("configs/training-runs.json")
    if not plan:
        return {"configured": False}
    root = Path(plan["root"])
    downloads = {}
    download_processes = read(".runtime/training-downloads.json") or {}
    for name in ("torch", "model"):
        prefix = download_processes.get(name + "_log")
        if not prefix:
            continue
        path = Path(prefix + ".out.log")
        rows = {}
        verified = False
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if "chunks" in entry:
                    rows[entry["file"]] = {"completed": entry["chunks"], "total": entry["total"]}
                verified = verified or entry.get("verified") is True or entry.get("complete") is True
        downloads[name] = {"files": rows, "verified": verified,
            "completed_chunks": sum(r["completed"] for r in rows.values()), "total_chunks": sum(r["total"] for r in rows.values())}
    stages = {}
    for stage in plan["stages"]:
        stages[stage] = {"progress": read(root / stage / "progress.json"),
            "result": read(root / stage / "result.json"), "data": read(root / stage / "data_report.json")}
    return {"configured": True, "protocol": plan["protocol"], "stages": stages, "downloads": downloads,
        "bootstrap": read(".runtime/training-bootstrap.json"), "pipeline": read(".runtime/training-pipeline.json"),
        "gpu": read(".runtime/training-compatibility.json"),
        "teacher_data": read("results/training-data/contract-supervision-v1/manifest.json"),
        "post_training_comparison": read(Path(plan["evaluation_root"]) / "comparison.json")}
