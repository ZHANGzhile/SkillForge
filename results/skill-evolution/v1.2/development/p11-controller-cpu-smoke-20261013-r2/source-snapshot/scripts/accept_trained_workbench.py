"""Real HTTP acceptance after trained Student deployment; no scripted fallback."""
import argparse
import copy
import json
from pathlib import Path
import sqlite3
import time
import uuid

import httpx

from skillforge.training import atomic_json
from skillforge.dataset import digest


def accept(url, output):
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    with httpx.Client(base_url=url.rstrip("/"), timeout=30, trust_env=False) as client:
        def api(method, path, **kwargs):
            response = client.request(method, "/api/v1" + path, **kwargs)
            response.raise_for_status()
            return response.json()
        health = api("GET", "/health")
        if health["training_gpu_reservation"] or not health["model"].startswith("Qwen3-4B-NF4-") or health["allowed_protocols"] != ["free_action"]:
            raise ValueError("acceptance requires the deployed HF Student with the GPU released")
        tasks = api("GET", "/dataset?split=validation")["tasks"]
        cases = []
        for family in ("modify_address", "cancel_order", "refund"):
            task = sorted((t for t in tasks if t["family"] == family and t["level"] == "A" and t["expected"]["allowed_outcomes"] == ["completed"]), key=lambda t: t["task_id"])[0]
            cases.append((family, {"task_id": task["task_id"]}))
        for outcome in ("refused", "escalated"):
            task = sorted((t for t in tasks if t["family"] == "modify_address" and t["expected"]["allowed_outcomes"] == [outcome]
                and not t["fixture"].get("wrong_customer") and not t["fixture"].get("faults")), key=lambda t: t["task_id"])[0]
            cases.append((outcome, {"task_id": task["task_id"]}))
        custom = copy.deepcopy(sorted((t for t in tasks if t["family"] == "refund" and t["level"] == "A"
            and t["parameters"]["amount"] < t["fixture"]["captured"]), key=lambda t: t["task_id"])[0])
        custom["fixture"].update(payment="PARTIALLY_REFUNDED", refunded=200)
        custom["expected"]["expected_state"]["payment.refunded_amount"] = 200 + custom["parameters"]["amount"]
        cases.append(("custom_partial_refund", {"task": custom}))
        atomic_json(root / "selection.json", {"health": health, "cases": cases,
            "scope": "predefined functional HTTP acceptance; not an additional generalization benchmark"})
        results = []
        for name, selection in cases:
            body = {**selection, "protocol": "free_action", "variant": "B3", "max_steps": 16}
            request_key = "trained-acceptance-" + uuid.uuid4().hex
            submission = api("POST", "/runs", json=body, headers={"Idempotency-Key": request_key})
            duplicate = api("POST", "/runs", json=body, headers={"Idempotency-Key": request_key})
            if duplicate["run_id"] != submission["run_id"] or duplicate["created"]:
                raise ValueError("duplicate HTTP submission created another run")
            run_id = submission["run_id"]
            deadline = time.monotonic() + 900
            while True:
                job = api("GET", "/runs/" + run_id)
                atomic_json(root / "progress.json", {"case": name, "run_id": run_id, "status": job["status"], "completed": len(results), "total": len(cases)})
                if job["status"] not in {"queued", "running"}:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("acceptance deadline; original run remains available: " + run_id)
                time.sleep(2)
            atomic_json(root / (name + "-job.json"), job)
            if job["status"] != "succeeded" or not job.get("result"):
                results.append({"name": name, "run_id": run_id, "passed": False, "status": job["status"], "error": job.get("error")})
                continue
            trajectory = api("GET", "/runs/" + run_id + "/artifacts/trajectory.json")
            if digest(trajectory) != digest(job["result"]):
                raise ValueError("downloaded trajectory differs from persisted result")
            if trajectory["model"] != health["model"] or trajectory["metrics"]["llm_calls"] <= 0:
                raise ValueError("acceptance did not execute the selected real model")
            if not trajectory["model_settings"].get("server_identity"):
                raise ValueError("actual Student identity is not pinned")
            if name.startswith("custom") and trajectory["dataset_id"] != "manual-unregistered":
                raise ValueError("custom task lost its separate provenance")
            database = client.get("/api/v1/runs/" + run_id + "/artifacts/environment.sqlite")
            database.raise_for_status()
            dbpath = root / (name + "-environment.sqlite")
            dbpath.write_bytes(database.content)
            with sqlite3.connect(dbpath) as db:
                if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("downloaded database is not valid")
            events, cursor = [], 0
            while True:
                page = api("GET", f"/runs/{run_id}/events?after={cursor}&limit=200")
                events.extend(page["events"])
                if page["next_cursor"] == cursor:
                    break
                cursor = page["next_cursor"]
            atomic_json(root / (name + "-events.json"), {"events": events})
            results.append({"name": name, "run_id": run_id, "passed": trajectory["verification"]["task_success"]
                and not trajectory["verification"]["actual_policy_violation"], "outcome": trajectory["outcome"],
                "metrics": trajectory["metrics"], "reasons": trajectory["verification"]["reason"],
                "duplicate_submission_reused": True, "database_verified": True, "events": len(events)})
            atomic_json(root / "partial.json", {"cases": results})
        report = {"passed": all(r["passed"] for r in results), "model": health["model"], "cases": results,
            "protocol": "HF NF4 free Action, actual HTTP Student and durable workbench",
            "scope": "functional acceptance, not generalization or browser visual acceptance"}
        atomic_json(root / "summary.json", report)
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = accept(args.url, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
