"""Same strict read-only Runtime, versioned only for provenance and prompt."""
import hashlib
from pathlib import Path

from skillforge.interview_sprint import adapters as original

PROTOCOL = "interview-reference-discovery-v1"


def sources():
    root = Path(__file__).resolve().parents[2]
    values = original.sources()
    dependencies = ["run_interview_reference.py", "continue_interview_sprint.py",
                    "collect_skill_evolution_learn.py", "run_skill_evolution.py", "evolution_budget.py", "evolution_forks.py"]
    for path in [*Path(__file__).parent.glob("*.py"), *(root/"scripts"/name for name in dependencies)]:
        if path.exists(): values[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return values


run_agent = original.bind(original.run_agent, {"PROTOCOL": PROTOCOL, "runtime_sources": sources})
