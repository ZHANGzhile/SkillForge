"""Read-only Stage 2 saved evidence, including conservatively charged live work."""
from pathlib import Path

from .data import checked, read, ROOT


def stage2_status(root=None):
    root = Path(root or ROOT / "results/skill-evolution/v1.2")
    values = {}
    folders = {
        "trigger_engineering": root / "development/p6-controlled-tools-20261012-r2",
        "history_diagnostic": root / "preparation/p7-history-audit-20261012-r2",
        "acquisition_development": root / "development/p7-acquisition-ablation-20261012",
        "real_h0_smoke": root / "development/p6-real-runtime-smoke-20261012",
        "real_changed_smoke": root / "development/p9-changed-runtime-smoke-20261012",
        "independent_boundary_dev": root / "development/p10-independent-boundary-dev-20261012",
    }
    for name, folder in folders.items():
        report = checked(folder / "report.json")
        audit = checked(folder / "independent-audit.json")
        protocol = checked(folder / "protocol.json")
        if audit and (not report or audit["report_hash"] != report["hash"] or not audit["passed"]):
            raise ValueError("Stage 2 audit/report binding mismatch")
        if protocol and report and report.get("protocol_hash") != protocol["hash"]:
            raise ValueError("Stage 2 report/protocol binding mismatch")
        if name in {"real_h0_smoke", "real_changed_smoke"}:
            statuses = [read(path) for path in folder.glob("*/collection-status.json")]
            observed = sum(value["charged_tokens"] for value in statuses)
            pending = 0
            for path in folder.glob("*/initial-state.json"):
                arm = path.parent
                if (arm / "collection-status.json").exists(): continue
                snapshots = list((arm / "checkpoints").glob("*/snapshot.json"))
                if not snapshots: continue
                snapshot = read(max(snapshots, key=lambda p: int(p.parent.name)))
                from ..evolution_schemas import fingerprint
                if snapshot["hash"] != fingerprint(snapshot["body"]): raise ValueError("live Stage 2 checkpoint hash mismatch")
                for i, request in enumerate(snapshot["body"]["runtime"]["model_requests"]):
                    if request["status"] == "pending":
                        approval = read(arm / "admissions" / (str(i) + ".json"))
                        if approval and approval["approved"]:
                            observed += request["reserved_tokens"]; pending += 1
                    else: observed += request["charged_tokens"]
            values[name] = {"state": "AUDITED" if audit else "COMPLETE_PENDING_AUDIT" if report and report["complete"]
                else "FAILED_OR_INCOMPLETE" if report else "RUNNING" if protocol else "NOT_STARTED",
                "completed": sum(s["completed"] for s in statuses), "planned": len(protocol["cases"]) if protocol else 0,
                "observed_tokens": observed, "pending_requests": pending,
                "shared_observed_tokens": (protocol or {}).get("prior_tokens", 0) + observed,
                "phase_cap_tokens": (protocol or {}).get("phase_tokens"), "failure": (report or {}).get("failure"),
                "eoc": sum(row["eoc"] for row in (report or {}).get("rows", [])),
                "autonomous_eoc": sum(row["autonomous_eoc"] for row in (report or {}).get("rows", [])),
                "runtime_assisted_eoc": sum(row["runtime_assisted_eoc"] for row in (report or {}).get("rows", [])),
                "scope": "真实模型 H0 接口/成本开发验证；不代表边界自主进化" if name == "real_h0_smoke" else
                    "W1 学习候选 / W6 Oracle 接口开发对照；不是准入或正式效果", "audit_hash": (audit or {}).get("hash")}
        elif name == "independent_boundary_dev":
            values[name] = {"state": "AUDITED" if audit else "COMPLETE_PENDING_AUDIT" if report else "RUNNING" if protocol else "NOT_STARTED",
                "planned": len((protocol or {}).get("planned", [])), "boundary_gate_passed": sum(r["boundary_gate"] == "BOUNDARY_GATE_PASSED" for r in (report or {}).get("rows", [])),
                "abstentions": sum(r["proposal_decision"] != "PROPOSE_BOUNDARY" for r in (report or {}).get("rows", [])),
                "physical_probes": (report or {}).get("physical_probes", 0), "agent_admitted": False,
                "scope": "独立 CPU Boundary 验证；尚非真实 Agent 准入", "audit_hash": (audit or {}).get("hash")}
        elif name == "trigger_engineering":
            values[name] = {"state": "AUDITED" if audit else "PENDING", "events": (report or {}).get("checkpoint_replays", 0),
                "tool_calls": (report or {}).get("actual_tool_calls", 0), "scope": "受控 SQLite 工程流，非真实 Agent 日常流"}
        elif name == "history_diagnostic":
            values[name] = {"state": "COMPLETE" if report else "PENDING", "pairs": (report or {}).get("audited_pairs", 0),
                "queries": (report or {}).get("audited_v2_queries", 0), "h0_gate_entries": (report or {}).get("h0_gate_entries", 0),
                "fallback_errors": (report or {}).get("effective_fallback_errors", 0), "scope": "旧 v1.1 全量只读诊断；零新查询"}
        else:
            values[name] = {"state": "AUDITED" if audit else "COMPLETE_PENDING_AUDIT" if report else "RUNNING" if protocol else "NOT_STARTED",
                "runs": len((report or {}).get("runs", [])), "selected": (report or {}).get("selected"),
                "methods": (report or {}).get("methods", {}), "logical_queries": (report or {}).get("logical_explore_queries", 0),
                "physical_probes": (report or {}).get("physical_probes", 0), "scope": "新开发种子五方法消融；不是正式或 Agent 准入"}
    from .formal import formal_status
    formal = formal_status(root.parent / "v1.3/formal-P11-v1")
    return {"stages": values, "formal_stage2_started": formal["started"],
        "activated": bool(formal.get("funnel", {}).get("isolated_activated", 0)), "deployed": False}
