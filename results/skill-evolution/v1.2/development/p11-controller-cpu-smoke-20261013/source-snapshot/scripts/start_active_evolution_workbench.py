"""Start the Evolution view without rewriting historical deployment receipts."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.load(response)
    except OSError:
        return None


def free_port(port):
    with socket.socket() as stream:
        stream.settimeout(1)
        if stream.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError(f"Port {port} is occupied by an unverified service")


def launch(python, module, port, name, env):
    prefix = ROOT / ".runtime" / ("evolution-" + name)
    prefix.parent.mkdir(exist_ok=True)
    with Path(str(prefix) + ".stdout.log").open("ab") as out, Path(str(prefix) + ".stderr.log").open("ab") as err:
        process = subprocess.Popen([str(ROOT / python), "-m", "uvicorn", module, "--host", "127.0.0.1",
                                    "--port", str(port), "--workers", "1"], cwd=ROOT, env=env, stdout=out, stderr=err,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return process


def wait_health(process, url, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = get(url)
        if health is not None:
            return health
        if process.poll() is not None:
            break
        time.sleep(.5)
    raise RuntimeError("Service startup failed; inspect .runtime/evolution-*.stderr.log")


def stop_owned_web():
    import psutil
    offset = 0
    while True:
        result = get("http://127.0.0.1:8080/api/v1/runs?limit=100&offset=" + str(offset))
        if result is None:
            raise RuntimeError("Cannot verify Workbench task queue")
        if any(r["status"] in {"queued", "running"} for r in result["runs"]):
            raise RuntimeError("Workbench has live tasks; use --preview until they finish")
        if len(result["runs"]) < 100:
            break
        offset += 100
    owner = psutil.Process(int((ROOT / ".runtime/project-web.pid").read_text().strip()))
    children = owner.children(recursive=True)
    if any(p.name().lower() not in {"python.exe", "conhost.exe"} for p in children):
        raise RuntimeError("Unexpected Workbench descendant")
    processes = [owner] + [p for p in children if p.name().lower() == "python.exe"]
    for p in processes:
        if Path(p.cwd()).resolve() != ROOT or not {"skillforge.api:app", "skillforge.evolution_workbench.app:app"}.intersection(p.cmdline()):
            raise RuntimeError("Cannot verify ownership of the existing Workbench")
    for p in reversed(processes):
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs(processes, timeout=5)
    if alive:
        raise RuntimeError("Owned Workbench did not stop")


def start(preview=False):
    os.chdir(ROOT)
    env = dict(os.environ)
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    port = 8081 if preview else 8080
    endpoint = f"http://127.0.0.1:{port}/api/evolution/index"
    existing = get(endpoint)
    if existing and (preview or get("http://127.0.0.1:8080/api/v1/health")):
        return {"url": f"http://127.0.0.1:{port}/evolution", "reused": True, "preview": preview}
    if preview:
        free_port(port)
        process = launch(".venv/Scripts/python.exe", "skillforge.evolution_workbench.app:preview", port, "preview", env)
        wait_health(process, endpoint, 30)
        (ROOT / ".runtime/evolution-preview.pid").write_text(str(process.pid))
    else:
        if (ROOT / ".runtime/active-evolution-gpu-lease.json").exists():
            raise RuntimeError("Formal GPU evaluation is active; use --preview")
        audit = ROOT / "results/active-evolution/v1/formal-v1/delivery-audit.json"
        if not audit.exists() or not json.loads(audit.read_text(encoding="utf-8"))["passed"]:
            raise RuntimeError("Complete the frozen evaluation and delivery audit first, or use --preview")
        from scripts.active_evolution_formal import load_protocol
        from skillforge.evolution_schemas import fingerprint
        protocol = load_protocol(audit.parent)
        if json.loads(audit.read_text(encoding="utf-8"))["protocol_hash"] != fingerprint(protocol):
            raise RuntimeError("Delivery audit belongs to a different protocol")
        expected = protocol["model_settings"]["adapter_sha256"]
        student = get("http://127.0.0.1:8002/health")
        if student is None:
            free_port(8002)
            env.update(SKILLFORGE_HF_LABEL="SFT", SKILLFORGE_HF_CONFIG=str(ROOT / "configs/training.recovery-v1.json"),
                       SKILLFORGE_HF_ADAPTER=str(ROOT / "results/training/main-v3/sft/adapter"),
                       HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
            process = launch(".venv-train/Scripts/python.exe", "skillforge.hf_server:app", 8002, "student", env)
            (ROOT / ".runtime/trained-student.pid").write_text(str(process.pid))
            student = wait_health(process, "http://127.0.0.1:8002/health")
        if student.get("model") != "Qwen3-4B-NF4-SFT" or student["settings"]["adapter_sha256"] != expected:
            raise RuntimeError("Existing model differs from fixed main-v3; not replacing it")
        web = get("http://127.0.0.1:8080/api/v1/health")
        if web:
            stop_owned_web()
        free_port(8080)
        for key in ("SKILLFORGE_MODEL_URL", "SKILLFORGE_MODEL_NAME"):
            env.pop(key, None)
        env["SKILLFORGE_MODEL_CONFIG"] = str(ROOT / "configs/model.hf-sft.json")
        process = launch(".venv/Scripts/python.exe", "skillforge.evolution_workbench.app:app", 8080, "web", env)
        (ROOT / ".runtime/project-web.pid").write_text(str(process.pid))
        web = wait_health(process, "http://127.0.0.1:8080/api/v1/health", 30)
        if web["model"] != "Qwen3-4B-NF4-SFT" or not web["worker_alive"]:
            raise RuntimeError("Workbench startup identity mismatch")
        if get(endpoint) is None:
            raise RuntimeError("Evolution routes missing")
    return {"url": f"http://127.0.0.1:{port}/evolution", "reused": False, "preview": preview}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true", help="Read-only view without the Workbench task queue or model server")
    print(json.dumps(start(parser.parse_args().preview)))
