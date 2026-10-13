import json
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from typing import Literal
from pydantic import BaseModel

from .benchmark import generate_tasks, run_benchmark
from .environment import Environment
from .learning import validate_skill
from .model import ModelClient, ScriptedPolicy
from .runtime import Runtime
from .skills import SkillRegistry, compile_skill as compile_contract

@asynccontextmanager
async def lifespan(app):
    from .workbench import Workbench
    workbench = Workbench()
    workbench.worker.start()
    app.state.workbench = workbench
    try:
        yield
    finally:
        workbench.worker.close()


app = FastAPI(title="SkillForge Research Workbench", version="0.2.0", lifespan=lifespan)
from .workbench import router as workbench_router
app.include_router(workbench_router)


@app.middleware("http")
async def same_origin_writes(request, call_next):
    from fastapi.responses import JSONResponse
    origin = request.headers.get("origin")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin and origin != str(request.base_url).rstrip("/"):
        return JSONResponse({"detail": "cross-origin writes are disabled"}, status_code=403)
    return await call_next(request)
ROOT = Path("results/api")


class SkillDemoRequest(BaseModel):
    family: Literal['modify_address', 'cancel_order', 'refund'] = 'modify_address'
    case: Literal['normal', 'shipped', 'high_risk'] = 'normal'


def skill_demo_job(job_id, request):
    from .skill_demo import run_case
    try:
        result = run_case(request.family, request.case)
        save_job(job_id, {'status':'completed', 'result':result})
    except Exception as exc:
        save_job(job_id, {'status':'failed', 'error':type(exc).__name__,
            'message':'无法完成真实模型演示。请确认本地 Student 已启动，并查看服务日志。'})


@app.post('/skill-demo/run', status_code=202)
def create_skill_demo(request: SkillDemoRequest, background: BackgroundTasks):
    job_id = str(uuid.uuid4())
    save_job(job_id, {'status':'pending'})
    background.add_task(skill_demo_job, job_id, request)
    return {'task_id':job_id}


@app.get('/skill-demo', response_class=HTMLResponse)
def skill_demo_page():
    return FileResponse(Path(__file__).parent / 'static' / 'skill_demo.html')


class RunRequest(BaseModel):
    scripted: bool = False
    case_index: int = 0


class CompileRequest(BaseModel):
    trajectories: list[dict]
    family: str = "modify_address"


def job_path(job_id):
    if not re.fullmatch(r"[a-f0-9-]{36}", job_id):
        raise HTTPException(400, "invalid job ID")
    return ROOT / f"{job_id}.json"


def save_job(job_id, payload):
    ROOT.mkdir(parents=True, exist_ok=True)
    path = job_path(job_id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def task_job(job_id, request):
    env = None
    try:
        task = generate_tasks()[request.case_index]
        env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
        result = Runtime(ScriptedPolicy() if request.scripted else ModelClient()).run(task, env, ROOT / "trajectories")
        save_job(job_id, {"status": "completed", "result": result})
    except Exception as exc:
        save_job(job_id, {"status": "failed", "error": type(exc).__name__})
    finally:
        if env:
            env.close()


@app.post("/tasks", status_code=202)
def create_task(request: RunRequest, background: BackgroundTasks):
    if not 0 <= request.case_index < len(generate_tasks()):
        raise HTTPException(400, "case_index must be 0..23")
    job_id = str(uuid.uuid4())
    save_job(job_id, {"status": "pending"})
    background.add_task(task_job, job_id, request)
    return {"task_id": job_id}


@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    path = job_path(task_id)
    if not path.exists():
        raise HTTPException(404, "task not found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/tasks/{task_id}/trace")
def get_trace(task_id: str):
    return get_task(task_id).get("result", {})


@app.get("/skills")
def get_skills():
    return [s.model_dump() for s in SkillRegistry().list()]


@app.get("/skills/{skill_id}")
def get_skill(skill_id: str):
    matches = [s for s in SkillRegistry().list() if s.skill_id == skill_id]
    if not matches:
        raise HTTPException(404, "skill not found")
    return max(matches, key=lambda s: s.version)


@app.post("/skills/compile")
def compile_skill(request: CompileRequest):
    try:
        skill = compile_contract(request.trajectories, request.family)
        existing = [s.version for s in SkillRegistry().list() if s.skill_id == skill.skill_id]
        skill.version = max(existing, default=0) + 1
        SkillRegistry().save(skill)
        return skill
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/skills/{skill_id}/validate")
def validate(skill_id: str):
    skill = get_skill(skill_id).model_copy(deep=True)
    skill.version += 1
    report = validate_skill(skill, generate_tasks("validation"))
    SkillRegistry().save(skill)
    return {"skill": skill, "validation": report}


def benchmark_job(job_id, scripted):
    try:
        summary, _ = run_benchmark(ScriptedPolicy() if scripted else ModelClient(), output_root=ROOT / "benchmarks")
        save_job(job_id, {"status": "completed", "summary": summary})
    except Exception as exc:
        save_job(job_id, {"status": "failed", "error": type(exc).__name__})


@app.post("/benchmark/run", status_code=202)
def benchmark(request: RunRequest, background: BackgroundTasks):
    job_id = str(uuid.uuid4())
    save_job(job_id, {"status": "pending"})
    background.add_task(benchmark_job, job_id, request.scripted)
    return {"run_id": job_id}


@app.get("/benchmark/{run_id}")
def benchmark_status(run_id: str):
    return get_task(run_id)


@app.get("/models")
def models():
    return {"configured_student": ModelClient().model, "connectivity": "run model-smoke to verify", "engineering_fixture": ScriptedPolicy.model}


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return FileResponse(Path(__file__).parent / 'static' / 'workbench.html')


@app.get("/engineering", response_class=HTMLResponse)
def engineering_dashboard():
    return """<!doctype html><html lang="zh"><meta charset="utf-8"><title>SkillForge</title>
    <style>body{max-width:1000px;margin:50px auto;font:17px system-ui;background:#101827;color:#e5e7eb}button,select{padding:12px;margin:8px}pre{white-space:pre-wrap;background:#1f2937;padding:24px}a{color:#7dd3fc}</style>
    <h1>SkillForge</h1><p>可验证技能学习 · 本地研究环境</p><p><a href="/skill-demo">打开真实模型 Skill 演示 →</a></p>
    <p>工程演示使用脚本策略，展示执行与状态验证，不代表模型能力。</p>
    <select id="case"><option value="0">修改地址</option><option value="1">已发货：拒绝修改</option><option value="3">处理中：转人工</option><option value="11">部分退款</option><option value="22">退款响应丢失与重试</option></select>
    <button onclick="run()">运行工程演示</button><a href="/docs">API 文档</a><pre id="out">选择案例，查看轨迹、状态变化和验证结果。</pre>
    <script>async function run(){const out=document.getElementById('out');out.textContent='执行中…';try{const r=await fetch('/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scripted:true,case_index:Number(document.getElementById('case').value)})});const j=await r.json();if(!r.ok)throw new Error(JSON.stringify(j));for(let i=0;i<60;i++){const x=await(await fetch('/tasks/'+j.task_id)).json();if(x.status!=='pending'){out.textContent=JSON.stringify(x,null,2);return;}await new Promise(r=>setTimeout(r,500));}out.textContent='任务仍在运行：'+j.task_id;}catch(e){out.textContent=String(e);}}</script></html>"""
