"""Bind persisted evaluations to their execution identity and original payload."""
import json
from pathlib import Path

from .dataset import digest
from .training import atomic_json


def save_checkpoint(path, payload, identity):
    if "_checkpoint" in payload:
        raise ValueError("reserved checkpoint metadata")
    record = {**payload, "_checkpoint": {
        "identity_hash": digest(identity), "payload_hash": digest(payload)}}
    atomic_json(path, record)
    return record


def read_checkpoint(path, identity, task_id, task_hash=None):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    payload = {k: v for k, v in record.items() if k != "_checkpoint"}
    expected = {"identity_hash": digest(identity), "payload_hash": digest(payload)}
    if record.get("_checkpoint") != expected:
        raise ValueError("evaluation checkpoint identity/content mismatch")
    if record.get("task_id") != task_id or (task_hash is not None and record.get("task_hash") != task_hash):
        raise ValueError("evaluation checkpoint task mismatch")
    return record
