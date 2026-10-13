"""Reuse the frozen public-only worker RPC with the versioned dossier Runtime."""
from skillforge.skill_evolution.worker import main as original
from .adapters import bind, run_agent, sources

if __name__ == "__main__":
    # Hash controller provenance BEFORE the unchanged guard prohibits scripts/.
    # The Agent later receives only this inert identity, never script contents.
    frozen_sources = sources()
    guarded_runtime = bind(run_agent, {"runtime_sources": lambda: frozen_sources})
    bind(original, {"run_agent": guarded_runtime})()
