"""Reuse the strict dossier Runtime without action or argument repair."""
import hashlib
from pathlib import Path
from skillforge.interview_sprint import adapters as original

PROTOCOL = "interview-binding-discovery-v1"


def sources():
    root = Path(__file__).resolve().parents[2]
    values = original.sources()
    paths = [*Path(__file__).parent.glob("*.py"),
             *(root/"scripts"/n for n in ("run_interview_binding.py", "run_interview_reference.py",
               "continue_interview_sprint.py", "collect_skill_evolution_learn.py",
               "run_skill_evolution.py", "evolution_budget.py", "evolution_forks.py")),
             * (root/"skillforge/interview_reference").glob("*.py")]
    for path in paths:
        values[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return values


run_agent = original.bind(original.run_agent, {"PROTOCOL": PROTOCOL, "runtime_sources": sources})
