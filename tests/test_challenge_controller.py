import json
import subprocess
import sys

import pytest

from skillforge.execution_aware.controller import ChallengeEvolutionController
from skillforge.evolution_schemas import Candidate
from test_belief import evidence, hypotheses
from test_evolution import validation


def controller(tmp_path, labels=None, rejected=False):
    pool = [Candidate(candidate_id=str(i), member_hash=str(i), observations={"shipment.status": "PROCESSING", "request.amount": 100+i},
                      baseline_prediction=True, cost=1, mutation_probability=1) for i in range(3)]
    seed = [evidence(100+i, split="seed", label="executable") for i in range(8)]
    calls = []
    def probe(cid):
        calls.append(cid)
        c = pool[int(cid)]
        return evidence(cid, member_hash=cid, observations=c.observations,
                        label=(labels or {}).get(cid, "executable"))
    c = ChallengeEvolutionController(tmp_path, {"policy_epoch": "p", "parent_hash": "public-parent"},
        hypotheses(), seed, pool, probe, lambda candidate: validation(candidate, rejected), tmp_path/"registry")
    return c, calls


def test_controller_gates_confident_h0_charges_queries_and_resumes(tmp_path):
    c, calls = controller(tmp_path)
    result = c.run("active_v2")
    assert result["queries"] == 2 and result["belief_converged"]
    assert result["h0_challenge"]["passed"] and len(calls) == 2
    assert result["status"] == "UNCHANGED" and not result["boundary_admitted"]
    assert c.run("active_v2") == result and len(calls) == 2
    first = json.loads((tmp_path/"queries/query_000.json").read_text(encoding="utf-8"))
    assert first["h0_challenge_before"]["status"] == "challenge_required"


def test_budget_exhaustion_does_not_create_h0_candidate(tmp_path):
    c, calls = controller(tmp_path, {"0": "unknown", "1": "unknown", "2": "unknown"})
    result = c.run("active_v2", max_queries=2)
    assert result["raw_belief_converged"] and not result["belief_converged"]
    assert result["stop_reason"] == "inconclusive_budget_exhausted"
    assert len(calls) == 2 and result["queries_to_convergence"] is None
    assert not (tmp_path/"candidate.json").exists()


def test_h0_failed_validation_is_preserved(tmp_path):
    c, _ = controller(tmp_path, rejected=True)
    result = c.run("active_v2")
    assert result["belief_converged"] and result["status"] == "UNCHANGED"
    assert result["boundary_validation_passed"] is False and not result["boundary_admitted"]


def test_old_active_behavior_does_not_acquire_challenge_queries(tmp_path):
    c, calls = controller(tmp_path)
    result = c.run("active")
    assert result["queries"] == 0 and result["h0_challenge"] is None and calls == []


@pytest.mark.parametrize("mode", ["file", "environment", "policies"])
def test_new_learner_worker_keeps_private_data_boundary(tmp_path, mode):
    secret = tmp_path/"gold.json"; secret.write_text("PRIVATE")
    packet = {"output": str(tmp_path/"learner")}
    packet.update({"access_probe": str(secret)} if mode == "file" else {"import_probe": mode})
    result = subprocess.run([sys.executable, "-m", "skillforge.execution_aware.learner_worker"],
                            input=json.dumps(packet)+"\n", capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"type": "access_denied"}
