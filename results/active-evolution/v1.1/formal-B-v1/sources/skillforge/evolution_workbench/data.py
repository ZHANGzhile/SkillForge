"""Read recorded evidence; never run probes, update beliefs or activate a Skill."""
import json
from pathlib import Path

from ..evolution_schemas import fingerprint


ROOT = Path(__file__).resolve().parents[2] / "results/active-evolution/v1/formal-v1"


def read(path, default=None):
    if not Path(path).exists():
        return default
    return json.loads(Path(path).read_text(encoding="utf-8"))


class EvolutionView:
    def __init__(self, root=ROOT):
        self.root = Path(root)

    def index(self):
        record = read(self.root / "protocol.json")
        if record is None:
            return {"ready": False, "runs": [], "reason": "Formal protocol is not available"}
        if record["protocol_hash"] != fingerprint(record["protocol"]):
            raise ValueError("protocol identity mismatch")
        protocol = record["protocol"]
        cpu = read(self.root / "cpu-report.json")
        continuous = read(self.root / "continuous-report.json")
        model = read(self.root / "model-report.json")
        runs = []
        for row in (cpu or {}).get("runs", []):
            runs.append({"key": f"cpu/{row['world']}/{row['seed']}/{row['method']}", "stage": "cpu",
                         "world": row["world"], "seed": row["seed"], "method": row["method"],
                         "status": row["status"], "queries": row["queries"],
                         "false_allow": row["false_allow"], "false_block": row["false_block"]})
        lineage = []
        for epoch, world in enumerate(protocol["continuous_epochs"]["worlds"], 1):
            for method in protocol["config"]["methods"]:
                base = self.root / "continuous" / str(epoch) / method
                node, test = read(base / "lineage.json"), read(base / "test.json")
                if node is None or test is None:
                    continue
                metric = test["metrics"]
                runs.append({"key": f"epoch/{epoch}/{method}", "stage": f"epoch-{epoch}", "world": world,
                             "seed": protocol["continuous_epochs"]["seed"], "method": method,
                             "status": "VERIFIED" if node["accepted_update"] else "RETAINED",
                             "queries": metric["queries"], "false_allow": metric["false_allow"], "false_block": metric["false_block"]})
                lineage.append({**metric, "patch": node["effective_hypothesis"], "previous_patch": node["previous_hypothesis"]})
        return {"ready": True, "protocol_hash": record["protocol_hash"], "runs": runs,
                "cpu": cpu["aggregate"] if cpu else None,
                "cpu_completed": len(cpu["runs"]) if cpu else len(list((self.root / "cpu").glob("*/*/*/metrics.json"))),
                "continuous_complete": continuous is not None, "lineage": lineage,
                "model_complete": model is not None,
                "model_completed_pairs": len(model["runs"]) if model else len(list((self.root / "model-layer").glob("*/*/*/report.json"))),
                "model": model, "delivery": read(self.root / "delivery-summary.json"),
                "cpu_audit": read(self.root / "independent-audit.json"), "delivery_audit": read(self.root / "delivery-audit.json"),
                "model_settings": protocol["model_settings"], "cost_gate": protocol["cost_gate"]}

    def locate(self, key):
        selected = next((r for r in self.index()["runs"] if r["key"] == key), None)
        if selected is None:
            raise KeyError("unknown completed experiment run")
        parts = key.split("/")
        base = self.root.joinpath(*parts) if selected["stage"] == "cpu" else self.root / "continuous" / parts[1] / parts[2]
        learning = base if selected["stage"] == "cpu" else base / "learning"
        return selected, base, learning

    def trace(self, key):
        selected, base, learning = self.locate(key)
        learner = learning / "learner"
        journals = [read(p) for p in sorted((learner / "belief").glob("belief_step_*.json"))]
        if not journals or journals[0].get("kind") != "initial":
            raise ValueError("missing recorded belief initializer")
        initial = journals[0]["snapshot"]
        if fingerprint(initial) != journals[0]["snapshot_hash"]:
            raise ValueError("belief initializer mismatch")
        hypotheses = {h["hypothesis_id"]: h for h in initial["hypotheses"]}
        def top(rows):
            return [{**r, "hypothesis": hypotheses[r["hypothesis_id"]]} for r in rows[:6]]
        pairs = sorted(zip(initial["hypotheses"], initial["posterior"]), key=lambda item: (-item[1], item[0]["hypothesis_id"]))
        state = {"entropy": initial["entropy"], "other_posterior": sum(p for h, p in pairs if h["kind"] == "other"),
                 "posterior_top": top([{"hypothesis_id": h["hypothesis_id"], "posterior": p} for h, p in pairs[:6]])}
        prior = state
        seed_state = state
        seed_updates = 0
        updates = {}
        previous_digest = fingerprint(journals[0])
        for record in journals[1:]:
            if record["previous_digest"] != previous_digest:
                raise ValueError("belief journal chain mismatch")
            previous_digest = fingerprint(record)
            state = {"entropy": record["entropy"], "other_posterior": record["other_posterior"],
                     "posterior_top": top(record["posterior_top"])}
            updates[record["evidence"]["evidence_id"]] = {"before": prior, "after": state}
            prior = state
            if record["evidence"]["split"] == "seed":
                seed_state, seed_updates = state, seed_updates + 1
        queries = []
        prior = seed_state
        packet = read(learning / "learner-packet.json")
        candidates = {c["candidate_id"]: c for c in packet["candidates"]}
        for path in sorted((learner / "queries").glob("query_*.json")):
            q = read(path)
            if q["row_hash"] != fingerprint({k: v for k, v in q.items() if k != "row_hash"}):
                raise ValueError("query evidence mismatch")
            update = updates.get(q["evidence"]["evidence_id"]) if q["learned"] else None
            if q["learned"] and update is None:
                raise ValueError("learned evidence missing from belief journal")
            after = update["after"] if update else prior
            chosen = next(r for r in q["ranked"] if r["candidate_id"] == q["candidate_id"])
            queries.append({"index": q["index"], "candidate_id": q["candidate_id"], "evidence": q["evidence"],
                            "learned": q["learned"], "selected": chosen, "ranked": q["ranked"][:5],
                            "candidate": candidates[q["candidate_id"]], "before": prior, "after": after,
                            "entropy_change": prior["entropy"] - after["entropy"], "row_hash": q["row_hash"]})
            prior = after
        validation = read(learning / "validation.json")
        if validation:
            validation = {k: v for k, v in validation.items() if k != "cases"}
        return {"run": selected, "hypothesis_count": len(hypotheses), "seed_updates": seed_updates,
                "gaps": read(learner / "gap.json", []), "seed_belief": seed_state, "queries": queries,
                "final_belief": prior, "summary": read(learning / "summary.json"),
                "effective": read(learning / "effective-version.json"), "candidate": read(learner / "candidate.json"),
                "validation": validation, "lineage": read(base / "lineage.json") if selected["stage"] != "cpu" else None,
                "metrics": read(base / "metrics.json") if selected["stage"] == "cpu" else read(base / "test.json")["metrics"],
                "learning": packet["learning"],
                "scope": "Recorded finite-model posterior, not calibrated probability. Viewing never runs an experiment."}

    def artifact(self, key, name):
        _, base, learning = self.locate(key)
        files = {"summary": learning / "summary.json", "candidate": learning / "learner/candidate.json",
                 "validation": learning / "validation.json", "effective": learning / "effective-version.json",
                 "test": base / "test.json", "lineage": base / "lineage.json"}
        path = files.get(name)
        if path is None or not path.is_file():
            raise KeyError("artifact unavailable")
        return path
