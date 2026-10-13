"""Cooperatively guarded public learner RPC; no private dataset/oracle packet."""
import json
from pathlib import Path
import sys

from .learner import learn_public
from .acquisition import ProbeOptions
from ..evolution_schemas import Candidate, EvidenceView, Hypothesis, fingerprint
from ..evolution_config import LearningOptions
from ..evolution_registry import immutable_json
from ..execution_aware.learner_worker import install_access_guard


def main():
    packet = json.loads(sys.stdin.readline())
    root = Path(packet["output"]).resolve()
    install_access_guard(root)
    def rpc(kind, **body):
        print(json.dumps({"type": kind, **body}), flush=True)
        response = json.loads(sys.stdin.readline())
        if response["type"] != "response": raise ValueError("unexpected supervisor message")
        return response["value"]
    def probe(candidate_id): return EvidenceView.model_validate(rpc("probe", candidate_id=candidate_id))
    def expand(requests): return [Candidate.model_validate(row) for row in rpc("expand", requests=requests)]
    result = learn_public(packet["method"], [Hypothesis.model_validate(row) for row in packet["hypotheses"]],
        [EvidenceView.model_validate(row) for row in packet["seed_evidence"]],
        [Candidate.model_validate(row) for row in packet["candidates"]], probe, expand,
        learning=LearningOptions.model_validate(packet["learning"]),
        probe_options=ProbeOptions.model_validate(packet["probe_options"]))
    body = {**result, "public_packet_hash": fingerprint(packet)}
    saved = {**body, "hash": fingerprint(body)}
    immutable_json(root / "candidate-frozen.json", saved)
    print(json.dumps({"type": "completed", "result_hash": saved["hash"]}), flush=True)


if __name__ == "__main__": main()
