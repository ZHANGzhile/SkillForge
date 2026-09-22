import re


def terms(text):
    return set(re.findall(r"\w+", text.lower()))


def retrieve_memory(task_request, family, trajectories, top_k=1):
    """Transparent lexical baseline. Train-only, no snapshots/oracle in prompt."""
    if any(t.get("split") != "train" for t in trajectories):
        raise ValueError("memory index accepts train trajectories only")
    query = terms(task_request)
    def score(t):
        words = terms(t["user_request"])
        return (t["task_family"] == family, len(query & words) / max(1, len(query | words)))
    selected = sorted(trajectories, key=score, reverse=True)[:top_k]
    return [{"trajectory_id": t["trajectory_id"], "user_request": t["user_request"],
        "steps": [{"action": s["action"], "observation": s.get("result"), "error": s.get("error")} for s in t["steps"]]}
        for t in selected]
