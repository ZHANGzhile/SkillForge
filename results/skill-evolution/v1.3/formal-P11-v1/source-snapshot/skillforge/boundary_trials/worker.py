"""Public-only worker for fixed reference and existing Active acquisition."""
import json
from pathlib import Path
import sys

from .reference import learn_reference
from ..boundary_evolution.learner import learn_public
from ..boundary_evolution.acquisition import ProbeOptions
from ..execution_aware.learner_worker import install_access_guard
from ..evolution_config import LearningOptions
from ..evolution_schemas import EvidenceView, Candidate, Hypothesis, fingerprint
from ..evolution_registry import immutable_json


def main():
    packet = json.loads(sys.stdin.readline())
    root = Path(packet["output"])
    install_access_guard(root)
    def probe(key):
        print(json.dumps({"type": "probe", "candidate_id": key}), flush=True)
        response = json.loads(sys.stdin.readline())
        if response["type"] != "response": raise ValueError("invalid probe response")
        return EvidenceView.model_validate(response["value"])
    hs, seeds, pool = ([Hypothesis.model_validate(h) for h in packet["hypotheses"]],
        [EvidenceView.model_validate(e) for e in packet["seed_evidence"]], [Candidate.model_validate(c) for c in packet["candidates"]])
    options = LearningOptions.model_validate(packet["learning"])
    if packet["method"] in {"OriginalActive", "ExistingActiveV2"}:
        def forbidden_expansion(requests): raise ValueError("no unselected acquisition candidate is enabled")
        result = learn_public(packet["method"], hs, seeds, pool, probe, forbidden_expansion, learning=options, probe_options=ProbeOptions())
    else: result = learn_reference(packet["method"], hs, seeds, pool, probe, learning=options, random_seed=packet["random_seed"])
    body = {**result, "public_packet_hash": fingerprint(packet)}
    saved = {**body, "hash": fingerprint(body)}
    immutable_json(root / "candidate-frozen.json", saved)
    print(json.dumps({"type": "completed", "result_hash": saved["hash"]}), flush=True)


if __name__ == "__main__": main()
