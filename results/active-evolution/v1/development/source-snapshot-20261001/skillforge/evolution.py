"""Boundary evolution controller. Probe/validator capabilities are injected.

No environment oracle, dataset fixture, terminal label or test loader is imported.
The caller must supply audited EvidenceViews and a trusted validation service.
"""
import json
from pathlib import Path
import random

from .active_learning import rank_candidates, stopping_reason
from .belief import BeliefState
from .evolution_journal import BeliefJournal
from .evolution_registry import EvolutionRegistry, boundary_admission, immutable_json
from .evolution_schemas import EvidenceView, fingerprint
from .gap_detection import detect_gaps


class EvolutionController:
    def __init__(self, root, identity, hypotheses, seed_evidence, candidates, probe, validate, registry):
        self.root=Path(root)
        self.identity=identity
        self.hypotheses=hypotheses
        self.seed_evidence=seed_evidence
        self.candidates=candidates
        self.probe=probe
        self.validate=validate
        self.registry=EvolutionRegistry(registry)
        self.signature={**identity,"hypotheses_hash":fingerprint([h.model_dump(mode="json") for h in hypotheses]),
            "seed_hash":fingerprint([e.model_dump() for e in seed_evidence]),
            "pool_hash":fingerprint([c.model_dump() for c in candidates])}

    def run(self, method="active", max_queries=20, random_seed=101):
        if method not in {"active","random"}:
            raise ValueError("development controller currently supports active/random only")
        signature={**self.signature,"method":method,"max_queries":max_queries,"random_seed":random_seed}
        immutable_json(self.root/"identity.json",signature)
        journal=BeliefJournal(self.root/"belief.sqlite",signature)
        belief=journal.restore()
        if belief is None:
            belief=BeliefState(self.hypotheses,self.identity["policy_epoch"])
            journal.append(belief)
        for index,evidence in enumerate(self.seed_evidence):
            if index<len(belief.history):
                if belief.history[index]["evidence"]!=evidence.model_dump():
                    raise ValueError("seed history changed")
            elif belief.update(evidence):
                journal.append(belief)
        immutable_json(self.root/"gap.json",detect_gaps(self.seed_evidence))
        # Replay durable queries before selecting new ones; a probe result is committed
        # before its belief update, so a crash in between never repeats that mutation.
        queries=[]
        for path in sorted((self.root/"queries").glob("*.json")) if (self.root/"queries").exists() else []:
            row=json.loads(path.read_text(encoding="utf-8"))
            if row.get("row_hash")!=fingerprint({k:v for k,v in row.items() if k!="row_hash"}) or row["index"]!=len(queries) or row["identity_hash"]!=fingerprint(signature) or fingerprint(row["evidence"])!=row["evidence_hash"]:
                raise ValueError("query checkpoint corrupted")
            if belief.update(row["evidence"]):
                journal.append(belief)
            queries.append(row)
        used={q["candidate_id"] for q in queries}
        if len(used)!=len(queries):
            raise ValueError("duplicate selected query")
        rng=random.Random(random_seed)
        random_order=sorted(c.candidate_id for c in self.candidates)
        rng.shuffle(random_order)
        while True:
            reason=stopping_reason(belief,self.candidates,len(queries),max_queries,
                [q["selected_eig"] for q in queries])
            if reason:
                break
            ranked=rank_candidates(belief,self.candidates,used)
            if not ranked:
                reason="pool_exhausted"
                break
            selected=ranked[0] if method=="active" else next(r for key in random_order if key not in used for r in ranked if r["candidate_id"]==key)
            evidence=EvidenceView.model_validate(self.probe(selected["candidate_id"]))
            if evidence.split!="explore":
                raise ValueError("probe returned non-exploration evidence")
            row={"index":len(queries),"identity_hash":fingerprint(signature),"candidate_id":selected["candidate_id"],
                "ranked":ranked,"selected_eig":selected["eig"],"evidence":evidence.model_dump(),
                "evidence_hash":fingerprint(evidence.model_dump())}
            row["row_hash"]=fingerprint(row)
            immutable_json(self.root/"queries"/f"query_{len(queries):03d}.json",row)
            belief.update(evidence)
            journal.append(belief)
            queries.append(row)
            used.add(selected["candidate_id"])
        journal.export(self.root/"belief")
        convergence=belief.convergence(self.candidates)
        result={"stop_reason":reason,"queries":len(queries),"convergence":convergence,"status":"INCONCLUSIVE",
            "scope":"development boundary controller; not a formal benchmark or Agent deployment"}
        if convergence["converged"]:
            hypothesis=next(h for h in self.hypotheses if h.hypothesis_id==convergence["hypothesis_id"])
            candidate={"parent_hash":self.identity["parent_hash"],"policy_epoch":self.identity["policy_epoch"],
                "hypothesis":hypothesis.model_dump(mode="json"),"belief_hash":fingerprint(belief.snapshot()),
                "training_evidence":[h["evidence"]["evidence_id"] for h in belief.history]}
            immutable_json(self.root/"candidate.json",candidate)
            validation_path=self.root/"validation.json"
            report=json.loads(validation_path.read_text(encoding="utf-8")) if validation_path.exists() else self.validate(candidate)
            immutable_json(validation_path,report)
            if boundary_admission(candidate,report):
                version=self.registry.publish(candidate,report)
                self.registry.load(version)
                result.update(status="VERIFIED",registry_version=version)
            else:
                result["status"]="REJECTED"
        immutable_json(self.root/"summary.json",result)
        return result
