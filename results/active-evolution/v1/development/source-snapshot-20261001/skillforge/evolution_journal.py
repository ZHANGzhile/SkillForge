"""Transactional append-only belief checkpoints; exact identity required to resume."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .belief import BeliefState
from .evolution_schemas import fingerprint


class BeliefJournal:
    def __init__(self, path, identity):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.identity_hash=fingerprint(identity)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS identity (singleton INTEGER PRIMARY KEY CHECK(singleton=1), digest TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS checkpoints (step INTEGER PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL)")
            row=db.execute("SELECT digest FROM identity WHERE singleton=1").fetchone()
            if row and row[0]!=self.identity_hash:
                raise ValueError("evolution identity changed; new run required")
            db.execute("INSERT OR IGNORE INTO identity VALUES(1,?)",(self.identity_hash,))

    def append(self, belief):
        snapshot=belief.snapshot()
        # Recompute before persistence so caller mutation cannot manufacture a state.
        BeliefState.restore(snapshot)
        step=len(snapshot["history"])
        content=json.dumps(snapshot,ensure_ascii=False,sort_keys=True,allow_nan=False)
        hashed=fingerprint(snapshot)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            found=db.execute("SELECT digest FROM checkpoints WHERE step=?",(step,)).fetchone()
            if found:
                if found[0]!=hashed:
                    raise ValueError("immutable belief step differs")
                return
            previous=db.execute("SELECT step,payload FROM checkpoints ORDER BY step DESC LIMIT 1").fetchone()
            if step!=(previous[0]+1 if previous else 0):
                raise ValueError("belief journal must be contiguous")
            if previous:
                before=json.loads(previous[1])
                if snapshot["history"][:-1]!=before["history"] or snapshot["hypotheses"]!=before["hypotheses"]:
                    raise ValueError("belief history prefix changed")
            db.execute("INSERT INTO checkpoints VALUES(?,?,?)",(step,content,hashed))

    def restore(self):
        with closing(sqlite3.connect(self.path)) as db:
            rows=db.execute("SELECT step,payload,digest FROM checkpoints ORDER BY step").fetchall()
        if not rows:
            return None
        last=None
        for expected,(step,payload,hashed) in enumerate(rows):
            snapshot=json.loads(payload)
            if step!=expected or len(snapshot["history"])!=step or fingerprint(snapshot)!=hashed:
                raise ValueError("belief journal corrupted")
            current=BeliefState.restore(snapshot)
            if last and current.history[:-1]!=last.history:
                raise ValueError("belief history fork")
            last=current
        return last

    def export(self, directory):
        self.restore()
        root=Path(directory)
        root.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db:
            rows=db.execute("SELECT step,payload FROM checkpoints ORDER BY step").fetchall()
        for step,payload in rows:
            path=root/f"belief_step_{step:03d}.json"
            if path.exists():
                if json.loads(path.read_text(encoding="utf-8"))!=json.loads(payload):
                    raise ValueError("immutable exported belief differs")
            else:
                with path.open("x",encoding="utf-8") as stream:
                    stream.write(payload+"\n")
