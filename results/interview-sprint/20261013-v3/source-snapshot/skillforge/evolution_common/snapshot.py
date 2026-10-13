"""Private environment forks: SQLite backup plus all non-database runtime state."""
import hashlib
import json
from pathlib import Path
import random
import shutil
import sqlite3

from ..environment import Environment
from ..evolution_registry import immutable_json
from ..evolution_schemas import fingerprint
from .artifacts import clone


REQUIRED = {"identity", "execution_contract", "loaded_refs", "budget", "steps", "state",
            "retry_state", "termination_source", "outcome", "decisions", "tool_calls",
            "skill_events", "search_events", "load_events", "tokens", "model_requests", "status"}


def save_snapshot(root, env, runtime, rng):
    if set(runtime) != REQUIRED:
        raise ValueError("complete runtime checkpoint required")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    target = sqlite3.connect(root / "environment.sqlite")
    try:
        env.db.backup(target)
    finally:
        target.close()
    body = {"schema": "evolution-snapshot-v1", "runtime": clone(runtime), "audit": clone(env.audit),
            "faults": clone(env.faults), "order_id": env.order_id, "random_state": clone(rng.getstate()),
            "database_sha256": hashlib.sha256((root / "environment.sqlite").read_bytes()).hexdigest()}
    immutable_json(root / "snapshot.json", {"body": body, "hash": fingerprint(body)})
    return fingerprint(body)


def restore_snapshot(root, destination, identity):
    root, destination = Path(root), Path(destination)
    entry = json.loads((root / "snapshot.json").read_text(encoding="utf-8"))
    body = entry["body"]
    if (fingerprint(body) != entry["hash"] or body["schema"] != "evolution-snapshot-v1"
            or body["runtime"]["identity"] != identity or set(body["runtime"]) != REQUIRED
            or hashlib.sha256((root / "environment.sqlite").read_bytes()).hexdigest() != body["database_sha256"]):
        raise ValueError("snapshot identity/integrity mismatch")
    if destination.exists() or destination.resolve() == (root / "environment.sqlite").resolve():
        raise ValueError("restore requires a fresh independent database")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as stream, (root / "environment.sqlite").open("rb") as src:
        shutil.copyfileobj(src, stream)
    env = Environment(path=str(destination), fixture={"order_id": body["order_id"]})
    env.audit, env.faults = clone(body["audit"]), clone(body["faults"])
    rng = random.Random()
    def tuples(value):
        return tuple(tuples(v) for v in value) if isinstance(value, list) else value
    rng.setstate(tuples(body["random_state"]))
    return env, clone(body["runtime"]), rng
