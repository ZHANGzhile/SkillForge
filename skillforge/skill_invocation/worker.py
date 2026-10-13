"""Unchanged HF prompt/weights and public-only RPC; new explicit invocation path."""
from skillforge.skill_evolution.worker import main as original
from skillforge.interview_sprint.adapters import bind
from .runtime import run_agent,sources

if __name__=='__main__':
    frozen=sources()
    runtime=bind(run_agent,{'sources':lambda:frozen})
    bind(original,{'run_agent':runtime})()
