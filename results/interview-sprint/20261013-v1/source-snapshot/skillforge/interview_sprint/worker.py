"""Reuse the frozen public-only worker RPC with the versioned dossier Runtime."""
from skillforge.skill_evolution.worker import main as original
from .adapters import bind, run_agent

if __name__ == "__main__":
    bind(original, {"run_agent": run_agent})()
