"""Durable single-worker research runs. Interrupted mutations are never replayed."""
import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def now():
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "jobs.sqlite"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, request TEXT NOT NULL, request_key TEXT UNIQUE,
                status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                cancel_requested INTEGER NOT NULL DEFAULT 0, retry_of TEXT,
                result TEXT, error TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_job ON events(job_id,seq);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def decode(row):
        if row is None:
            raise KeyError("run not found")
        result = dict(row)
        for key in ("request", "result", "error"):
            result[key] = json.loads(result[key]) if result[key] is not None else None
        result["cancel_requested"] = bool(result["cancel_requested"])
        return result

    def submit(self, request, request_key=None, retry_of=None):
        encoded = json.dumps(request, ensure_ascii=False, sort_keys=True)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if request_key:
                existing = db.execute("SELECT * FROM jobs WHERE request_key=?", (request_key,)).fetchone()
                if existing:
                    if existing["request"] != encoded:
                        raise ValueError("idempotency key already binds a different request")
                    return self.decode(existing), False
            jid, timestamp = str(uuid.uuid4()), now()
            db.execute("INSERT INTO jobs(id,request,request_key,status,created_at,updated_at,retry_of) VALUES(?,?,?,'queued',?,?,?)",
                       (jid, encoded, request_key, timestamp, timestamp, retry_of))
            self._event(db, jid, "queued", {"retry_of": retry_of})
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()), True

    def get(self, jid):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())

    def list(self, limit=50, offset=0):
        with self.connect() as db:
            return [self.decode(r) for r in db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset))]

    @staticmethod
    def _event(db, jid, kind, payload):
        db.execute("INSERT INTO events(job_id,at,kind,payload) VALUES(?,?,?,?)", (jid, now(), kind, json.dumps(payload, ensure_ascii=False)))

    def event(self, jid, kind, payload):
        with self.connect() as db:
            self._event(db, jid, kind, payload)
            db.execute("UPDATE jobs SET updated_at=? WHERE id=?", (now(), jid))

    def events(self, jid, after=0, limit=100):
        self.get(jid)
        with self.connect() as db:
            return [{**dict(r), "payload": json.loads(r["payload"])} for r in db.execute(
                "SELECT * FROM events WHERE job_id=? AND seq>? ORDER BY seq LIMIT ?", (jid, after, limit))]

    def recover(self):
        """Only the process holding worker.lock may recover abandoned runs."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute("SELECT id FROM jobs WHERE status='running'").fetchall():
                error = {"type": "WorkerInterrupted", "message": "Execution stopped. Inspect persisted state; retry creates an isolated new run."}
                db.execute("UPDATE jobs SET status='interrupted',error=?,updated_at=? WHERE id=?", (json.dumps(error), now(), row["id"]))
                self._event(db, row["id"], "interrupted", error)

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=?", (now(), row["id"]))
            self._event(db, row["id"], "running", {})
            return self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone())

    def cancel(self, jid):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self.decode(db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())
            if row["status"] not in TERMINAL:
                status = "cancelled" if row["status"] == "queued" else row["status"]
                db.execute("UPDATE jobs SET cancel_requested=1,status=?,updated_at=? WHERE id=?", (status, now(), jid))
                self._event(db, jid, "cancel_requested", {"effective": status == "cancelled"})
        return self.get(jid)

    def finish(self, jid, status, result=None, error=None):
        if status not in TERMINAL:
            raise ValueError("invalid terminal state")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM jobs WHERE id=?", (jid,)).fetchone()
            if not row or row["status"] != "running":
                raise ValueError("only a running job can finish")
            db.execute("UPDATE jobs SET status=?,result=?,error=?,updated_at=? WHERE id=?",
                       (status, json.dumps(result), json.dumps(error), now(), jid))
            self._event(db, jid, status, {"error": error})

    def retry(self, jid, request_key=None):
        row = self.get(jid)
        if row["status"] not in {"failed", "cancelled", "interrupted"}:
            raise ValueError("only failed, cancelled or interrupted runs can be retried")
        # Bind retries to their parent even when two parents had identical inputs.
        request = {**row["request"], "retry_of": jid}
        return self.submit(request, request_key, retry_of=jid)

    def directory(self, jid):
        canonical = str(uuid.UUID(jid))
        if canonical != jid:
            raise ValueError("invalid run ID")
        return self.root / "runs" / canonical


class Worker:
    def __init__(self, store, execute):
        self.store, self.execute = store, execute
        self.stopping, self.wake = threading.Event(), threading.Event()
        self.thread = None

    def start(self):
        self.lock = (self.store.root / "worker.lock").open("a+b")
        if self.lock.seek(0, 2) == 0:
            self.lock.write(b"0")
            self.lock.flush()
        self.lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            raise RuntimeError("Another SkillForge worker owns this job store; use one API worker.")
        self.store.recover()
        self.thread = threading.Thread(target=self.run, name="skillforge-worker", daemon=True)
        self.thread.start()

    def run(self):
        try:
            while not self.stopping.is_set():
                job = self.store.claim()
                if not job:
                    self.wake.wait(0.5)
                    self.wake.clear()
                    continue
                jid = job["id"]
                try:
                    result = self.execute(job, lambda k, p: self.store.event(jid, k, p),
                        lambda: self.stopping.is_set() or self.store.get(jid)["cancel_requested"])
                    status = "cancelled" if result.get("outcome") == "cancelled" else "failed" if result.get("outcome") == "error" else "succeeded"
                    self.store.finish(jid, status, result=result)
                except Exception as exc:
                    self.store.finish(jid, "failed", error={"type": type(exc).__name__, "message": str(exc)[:1000]})
        finally:
            self.lock.close()

    def close(self):
        self.stopping.set()
        self.wake.set()
        if self.thread:
            # A pending model request is bounded by its configured HTTP timeout.
            # Keep the lock until it returns; no replacement worker can replay it.
            self.thread.join(timeout=5)

    @property
    def alive(self):
        return bool(self.thread and self.thread.is_alive())
