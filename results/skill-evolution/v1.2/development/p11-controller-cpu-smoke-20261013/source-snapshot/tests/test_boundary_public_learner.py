"""Public-only learner and cooperative process guard; CPU toy mechanics."""
import subprocess
import sys

from skillforge.boundary_evolution.learner import learn_public
from skillforge.boundary_evolution.acquisition import ProbeOptions
from skillforge.evolution_config import LearningOptions
from skillforge.evolution_schemas import EvidenceView
from test_boundary_acquisition import belief, candidates, evidence


def test_learner_charges_unknown_and_cannot_exceed_registered_budget():
    b, pool = belief(), candidates()
    calls = []
    def probe(key):
        calls.append(key)
        c = next(c for c in pool if c.candidate_id == key)
        return evidence(c, "unknown", key).model_copy(update={"split": "explore"})
    def expand(requests):
        assert requests == []
        return []
    result = learn_public("BroadOnly", b.hypotheses, [evidence(pool[2])], pool, probe, expand,
        learning=LearningOptions(max_queries=2), probe_options=ProbeOptions(max_generated_candidates=0))
    assert len(calls) <= 2 and len(calls) == len(result["queries"])
    assert not result["activated"]
    assert all(q["evidence"]["label"] == "unknown" for q in result["queries"])


def test_guard_denies_private_result_reads_and_evaluator_imports(tmp_path):
    code = '''
from pathlib import Path
import sys
from skillforge.boundary_evolution.learner import learn_public
from skillforge.execution_aware.learner_worker import install_access_guard
install_access_guard(sys.argv[1])
for action in [lambda: Path('results/skill-evolution/v1.2/formal-P5-v1/report.json').read_text(),
               lambda: __import__('scripts.active_evolution_worlds')]:
    try: action()
    except PermissionError: pass
    else: raise AssertionError('private capability escaped public learner')
print('guarded')
'''
    run = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "guarded"
