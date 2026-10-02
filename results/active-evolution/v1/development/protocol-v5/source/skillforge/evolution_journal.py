"""Transactional delta journal: one hypothesis table, replayable evidence chain."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .belief import BeliefState, entropy
from .evolution_schemas import fingerprint


class BeliefJournal:
    def __init__(self, path, identity):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.identity_hash = fingerprint({"journal_format": "delta-v2", "identity": identity})
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1), digest TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS checkpoints (step INTEGER PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL)")
            row = db.execute("SELECT digest FROM identity WHERE singleton=1").fetchone()
            if row and row[0] != self.identity_hash:
                raise ValueError("evolution identity changed; new run required")
            db.execute("INSERT OR IGNORE INTO identity VALUES(1,?)", (self.identity_hash,))

    def append(self, belief):
        step = len(belief.history)
        snapshot = belief.snapshot()
        snapshot_hash = fingerprint(snapshot)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            found = db.execute("SELECT payload FROM checkpoints WHERE step=?", (step,)).fetchone()
            if found:
                if json.loads(found[0])["snapshot_hash"] != snapshot_hash:
                    raise ValueError("immutable belief step differs")
                return
            previous = db.execute("SELECT step,payload,digest FROM checkpoints ORDER BY step DESC LIMIT 1").fetchone()
            if step != (previous[0] + 1 if previous else 0):
                raise ValueError("belief journal must be contiguous")
            if step == 0:
                record = {"kind": "initial", "snapshot": snapshot, "snapshot_hash": snapshot_hash}
            else:
                prefix = dict(snapshot)
                prefix["history"] = snapshot["history"][:-1]
                prefix["posterior"] = snapshot["history"][-1]["before"]
                prefix["entropy"] = entropy(prefix["posterior"])
                previous_record = json.loads(previous[1])
                if fingerprint(prefix) != previous_record["snapshot_hash"]:
                    raise ValueError("belief history prefix changed")
                posterior = belief.posterior
                top = sorted(range(len(posterior)), key=lambda i: (-posterior[i], belief.hypotheses[i].hypothesis_id))[:10]
                record = {"kind": "evidence", "evidence": snapshot["history"][-1]["evidence"],
                    "snapshot_hash": snapshot_hash, "previous_digest": previous[2],
                    "posterior_hash": fingerprint(posterior), "entropy": snapshot["entropy"],
                    "posterior_top": [{"hypothesis_id": belief.hypotheses[i].hypothesis_id, "posterior": posterior[i]} for i in top],
                    "other_posterior": sum(posterior[i] for i,h in enumerate(belief.hypotheses) if h.kind == "other")}
            payload = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False)
            db.execute("INSERT INTO checkpoints VALUES(?,?,?)", (step, payload, fingerprint(record)))

    def restore(self):
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute("SELECT step,payload,digest FROM checkpoints ORDER BY step").fetchall()
        belief, previous = None, None
        for expected, (step, payload, hashed) in enumerate(rows):
            record = json.loads(payload)
            if step != expected or fingerprint(record) != hashed:
                raise ValueError("belief journal corrupted")
            if step == 0:
                if record["kind"] != "initial":
                    raise ValueError("missing journal initializer")
                belief = BeliefState.restore(record["snapshot"])
            else:
                if record["kind"] != "evidence" or record["previous_digest"] != previous:
                    raise ValueError("belief history fork")
                if not belief.update(record["evidence"]):
                    raise ValueError("duplicate journal evidence")
                if fingerprint(belief.posterior) != record["posterior_hash"] or entropy(belief.posterior) != record["entropy"]:
                    raise ValueError("posterior replay differs")
            if len(belief.history) != step or fingerprint(belief.snapshot()) != record["snapshot_hash"]:
                raise ValueError("belief snapshot replay differs")
            previous = hashed
        return belief

    def export(self, directory):
        self.restore()
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute("SELECT step,payload FROM checkpoints ORDER BY step").fetchall()
        for step, payload in rows:
            path = root / f"belief_step_{step:03d}.json"
            if path.exists():
                if json.loads(path.read_text(encoding="utf-8")) != json.loads(payload):
                    raise ValueError("immutable exported belief differs")
            else:
                with path.open("x", encoding="utf-8") as stream:
                    stream.write(payload + "\n")
