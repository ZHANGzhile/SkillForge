"""Append-only isolated parent chain with replayed layered admission.

The trusted owner supplies the independent raw-evidence auditor. Model and
learner workers never receive that capability. No production pointer is changed.
"""
from pathlib import Path

from ..boundary_runtime.catalog import BoundaryCatalog
from ..evolution_registry import immutable_json
from ..evolution_common.artifacts import clone
from ..skill_evolution.agent_evidence import read
from .proposal import checked, hashed, candidate_catalog, propose
from .validation import boundary_gate, agent_gate


class LineageController:
    def __init__(self, root, initial, *, protocol_hash, evidence_auditor, mode="engineering"):
        if mode not in {"engineering", "real_model"} or not callable(evidence_auditor) or not protocol_hash:
            raise ValueError("explicit evidence owner, protocol and mode required")
        self.root, self.initial, self.current = Path(root), initial, initial
        self.protocol_hash, self.auditor, self.mode = protocol_hash, evidence_auditor, mode
        self.history = []
        for path in sorted(self.root.glob("stage-*.json")):
            saved = read(path)
            if path.name != f"stage-{len(self.history):04d}.json": raise ValueError("noncontiguous lineage journal")
            expected = self._transition(saved["input"])
            if expected != saved: raise ValueError("lineage content or parent replay differs")
            self.history.append(saved)

    def _transition(self, data):
        if data["parent_bundle_hash"] != self.current.bundle_hash:
            raise ValueError("stale parent: rejected candidates cannot become future parents")
        proposal, result = data.get("proposal"), data.get("learner_result")
        decision, candidate, proof = "RETAIN_PARENT", None, None
        if proposal is not None:
            checked(proposal)
            if result is None or propose(self.current, data["skill_id"], result,
                    certificate_options=data.get("certificate_options")) != proposal:
                raise ValueError("proposal differs from public learning/support replay")
            if proposal["schema"] == "skill-bound-boundary-proposal-v1" and proposal["decision"] == "PROPOSE_BOUNDARY":
                candidate = candidate_catalog(self.current, proposal)
                decision = "BOUNDARY_NOT_EVALUATED"
                if data.get("boundary_plan") is not None:
                    plan, br = data["boundary_plan"], data["boundary_report"]
                    if (plan["proposal_hash"] != proposal["hash"] or plan["parent_bundle_hash"] != self.current.bundle_hash or
                            plan["candidate_bundle_hash"] != candidate.bundle_hash or boundary_gate(plan, br["cases"]) != br):
                        raise ValueError("Boundary gate/proposal evidence mismatch")
                    decision = br["decision"]
                    if decision == "BOUNDARY_GATE_PASSED" and data.get("agent_report") is not None:
                        ar = data["agent_report"]
                        if agent_gate(br, ar["pairs"], **ar["options"]) != ar:
                            raise ValueError("Agent gate evidence mismatch")
                        decision = ar["decision"]
                        if decision == "AGENT_GATE_PASSED":
                            proof = self.auditor(clone(data), self.current, candidate)
                            checked(proof)
                            if (proof.get("schema") != "boundary-lineage-independent-evidence-audit-v1" or
                                    proof.get("passed") is not True or proof.get("mode") != self.mode or
                                    proof.get("proposal_hash") != proposal["hash"] or
                                    proof.get("boundary_report_hash") != br["hash"] or
                                    proof.get("agent_report_hash") != ar["hash"] or
                                    not proof.get("raw_evidence_index_hash")):
                                raise ValueError("passing independent evidence replay required")
                            decision = "ENGINEERING_ACTIVATED" if self.mode == "engineering" else "ISOLATED_ACTIVATED"
                            self.current = candidate
            elif proposal["schema"] == "boundary-proposal-abstention-v1": decision = proposal["decision"]
        else:
            if result is not None: raise ValueError("completed learner result cannot disappear from journal")
            if data.get("reason") not in {"NO_CHANGE", "NO_TRIGGER", "INFRASTRUCTURE", "CANCELLED", "BUDGET_EXHAUSTED"}:
                raise ValueError("explicit no-update reason required")
            decision = data["reason"]
        return hashed({"schema": "isolated-boundary-lineage-stage-v1", "stage": len(self.history),
            "protocol_hash": self.protocol_hash, "mode": self.mode,
            "previous_stage_hash": self.history[-1]["hash"] if self.history else None,
            "input": clone(data), "decision": decision, "effective_bundle_hash": self.current.bundle_hash,
            "boundary_admitted": proof is not None and self.mode == "real_model",
            "agent_admitted": proof is not None and self.mode == "real_model",
            "isolated_activated": decision == "ISOLATED_ACTIVATED", "deployed": False,
            "independent_audit": proof})

    def finish(self, data):
        # Compute without changing the committed in-memory parent until durable
        # publication succeeds. A conflict leaves the previous parent intact.
        old = self.current
        try:
            record = self._transition(clone(data))
            immutable_json(self.root / f"stage-{len(self.history):04d}.json", record)
        except BaseException:
            self.current = old
            raise
        self.history.append(record)
        return record

    def checkpoint(self):
        return hashed({"schema": "isolated-boundary-lineage-checkpoint-v1", "protocol_hash": self.protocol_hash,
            "initial_bundle_hash": self.initial.bundle_hash, "effective_bundle_hash": self.current.bundle_hash,
            "stages": [r["hash"] for r in self.history], "mode": self.mode, "deployed": False})
