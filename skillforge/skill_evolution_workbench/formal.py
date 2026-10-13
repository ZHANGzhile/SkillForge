"""Read-only continuous formal-engineering evidence and conservative live fees."""
from pathlib import Path
import hashlib

from .data import checked, read, ROOT
from ..evolution_schemas import fingerprint


FORMAL_ROOT = ROOT / "results/skill-evolution/v1.3/formal-P11-v1"


def formal_status(root=None):
    root = Path(root or FORMAL_ROOT)
    p = checked(root / "protocol.json")
    if not p: return {"started": False, "state": "NOT_STARTED", "deployed": False}
    cpu, agent = checked(root / "cpu/report.json"), checked(root / "agent/report.json")
    ca, aa = checked(root / "cpu/independent-audit.json"), checked(root / "agent/independent-audit.json")
    continuation = checked(root / "agent/continuation-v2/manifest.json")
    if continuation:
        if continuation["protocol_hash"] != p["hash"] or not agent or continuation["original_partial_report_hash"] != agent["hash"]:
            raise ValueError("auditor continuation is not bound to original frozen partial results")
        agent, aa = checked(root / "agent/continuation-v2/report.json"), checked(root / "agent/continuation-v2/independent-audit.json")
    for r, a in ((cpu, ca), (agent, aa)):
        if r and r["protocol_hash"] != p["hash"]: raise ValueError("formal result/protocol mismatch")
        if a and (not r or not a["passed"] or a["report_hash"] != r["hash"]): raise ValueError("formal audit/result mismatch")
    stages = [checked(path) for path in (root / "agent").glob("*/*/*/decision-before-test.json")]
    completed_stages = len(list((root / "agent").glob("*/*/*/complete.json")))
    statuses = [read(path) for path in (root / "agent/physical").glob("*/collection-status.json")]
    workflow = read(root / "workflow-status.json") or {}
    observed, pending = sum(s["charged_tokens"] for s in statuses), 0
    for folder in (root / "agent/physical").glob("*"):
        if not folder.is_dir() or (folder / "collection-status.json").exists(): continue
        values = list((folder / "checkpoints").glob("*/snapshot.json"))
        if not values: continue
        value = read(max(values, key=lambda v: int(v.parent.name)))
        if value["hash"] != fingerprint(value["body"]): raise ValueError("formal live checkpoint integrity mismatch")
        for i, request in enumerate(value["body"]["runtime"]["model_requests"]):
            if request["status"] == "pending":
                approval = read(folder / "admissions" / (str(i) + ".json"))
                if approval and approval["approved"]: observed += request["reserved_tokens"]; pending += 1
            else: observed += request["charged_tokens"]
    planned = len(p["agent_worlds"]) * len(p["sequence_seeds"]) * 3
    return {"started": True, "state": "AUDITED" if ca and aa else "FAILED_OR_INCOMPLETE" if workflow.get("state") == "FAILED_OR_INCOMPLETE" or agent and not agent["complete"]
        else "COMPLETE_PENDING_AUDIT" if cpu and agent else "RUNNING", "protocol_hash": p["hash"], "scale": p["scale"],
        "cpu_completed_runs": len(cpu["runs"]) if cpu else len(list((root / "cpu").glob("*/*/*/*/result.json"))),
        "cpu_planned_runs": len(p["cpu_worlds"]) * len(p["sequence_seeds"]) * 3 * len(p["cpu_methods"]),
        "agent_completed_stages": completed_stages, "agent_planned_stages": planned,
        "physical_completed_arms": sum(s["completed"] for s in statuses), "pending_requests": pending,
        "observed_tokens": observed, "shared_observed_tokens": p["prior_tokens"] + observed, "phase_cap_tokens": p["phase_tokens"],
        "funnel": {"planned": planned, **{key: sum(bool(s[key]) for s in stages) for key in
            ("belief_converged", "boundary_admitted", "agent_admitted", "isolated_activated")}},
        "stages": [{k: s[k] for k in ("key", "decision", "queries", "parent_bundle_hash", "effective_bundle_hash")} for s in stages],
        "failure": (agent or {}).get("failure") or (workflow.get("detail") if workflow.get("state") == "FAILED_OR_INCOMPLETE" else None), "deployed": False,
        "auditor_continuation": bool(continuation),
        "scope": "工程规模；world-sequence 独立聚类，不能把 task 当独立样本。CPU 父链与真实 Agent 父链分开；全局预算包含开发历史。"}


def formal_artifact(name):
    if name not in {"protocol.json", "cpu/report.json", "cpu/independent-audit.json", "agent/report.json", "agent/independent-audit.json",
            "agent/continuation-v2/manifest.json", "agent/continuation-v2/report.json", "agent/continuation-v2/independent-audit.json",
            "agent/original-partial-report.json"}:
        raise KeyError("artifact outside read-only allowlist")
    if name == "agent/original-partial-report.json": name = "agent/report.json"
    elif name in {"agent/report.json", "agent/independent-audit.json"} and (FORMAL_ROOT / "agent/continuation-v2/manifest.json").exists():
        name = "agent/continuation-v2/" + name.split("/")[-1]
    path = FORMAL_ROOT / name
    if not path.is_file(): raise KeyError("artifact not yet complete")
    checked(path)
    return path


def formal_trace(index, root=None):
    if type(index) is not int or index < 0: raise KeyError("nonnegative physical index required")
    folder = Path(root or FORMAL_ROOT) / "agent/physical" / str(index)
    row = read(folder / "result.json")
    if not row: raise KeyError("physical arm not yet complete")
    proof = checked(folder / "independent-audit.json")
    if proof and (not proof["passed"] or proof["evidence_index"]["result.json"] != hashlib.sha256((folder / "result.json").read_bytes()).hexdigest()):
        raise ValueError("physical arm differs from independent audit evidence index")
    return {"status": "ARM_REPLAY_AUDITED" if proof else "COMPLETE_PENDING_ARM_AUDIT", "physical_index": index,
        "case": read(folder / "case.json"), "evidence": row,
        "scope": "individual arm evidence; not completion/audit of the full continuous study"}
