"""Read saved evidence only; never import collectors, load a model or run probes."""
import hashlib
import json
from pathlib import Path

from ..evolution_schemas import fingerprint


ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "results/skill-evolution/v1.2/formal-P5-v1"


def read(path):
    path = Path(path)
    if not path.exists(): return None
    return json.loads(path.read_text(encoding="utf-8"))


def checked(path):
    value = read(path)
    if value is not None and (not isinstance(value, dict) or value.get("hash") !=
            fingerprint({key: item for key, item in value.items() if key != "hash"})):
        raise ValueError("saved evidence hash mismatch: " + Path(path).name)
    return value


class SkillEvolutionView:
    def __init__(self, root=STUDY):
        self.root = Path(root).resolve()

    def protocol(self):
        value = checked(self.root / "protocol.json")
        if value and (value.get("schema") != "p5-three-round-research-protocol-v1" or value.get("frozen") is not True):
            raise ValueError("unsupported or unfrozen research protocol")
        return value

    def stage(self, path, *, planned):
        path = Path(path)
        report = checked(path / "report.json")
        statuses = []
        for item in sorted(path.glob("*/*/collection-status.json")):
            row = read(item)
            statuses.append({"path": str(item.parent.relative_to(self.root)).replace("\\", "/"),
                "completed": row["completed"], "charged_tokens": row["charged_tokens"], "failure": row["failure"]})
        completed = sum(row["completed"] for row in statuses)
        pending, observed = 0, sum(row["charged_tokens"] for row in statuses)
        # Live costs are conservative observations, never a settlement receipt.
        for snapshot in path.glob("*/*/initial-snapshot/snapshot.json"):
            folder = snapshot.parent.parent
            if (folder / "collection-status.json").exists(): continue
            snapshots = list((folder / "checkpoints").glob("*/snapshot.json"))
            if not snapshots: continue
            latest = read(max(snapshots, key=lambda item: int(item.parent.name)))
            if latest["hash"] != fingerprint(latest["body"]):
                raise ValueError("live checkpoint hash mismatch")
            requests = latest["body"]["runtime"]["model_requests"]
            for index, request in enumerate(requests):
                if request["status"] == "pending":
                    approval = read(folder / "admissions" / (str(index)+".json"))
                    if approval and approval["approved"]:
                        observed += request["reserved_tokens"]; pending += 1
                else: observed += request["charged_tokens"]
        if report and report.get("complete"):
            if report["charged_tokens"] != sum(row["charged_tokens"] for row in statuses):
                raise ValueError("saved stage aggregate costs differ from raw statuses")
        return {"planned": planned, "completed": completed, "started": len(statuses)+pending,
            "pending_requests": pending, "observed_tokens": observed,
            "state": "COMPLETE" if report and report["complete"] else "FAILED_OR_INCOMPLETE" if report else "RUNNING" if path.exists() else "NOT_STARTED",
            "failure": report["failure"] if report else None, "report": report,
            "cost_scope": "live observed charges, approved unknown reservations included; independent final audit is separate"}

    def index(self):
        protocol = self.protocol()
        if not protocol: return {"ready": False, "rounds": [], "reason": "Formal protocol not yet saved"}
        rows, primary, candidates, program, agent, activated = [], 0, 0, 0, 0, 0
        observed_tokens = 0
        for planned in protocol["draft"]["rounds"]:
            number = planned["round"]; path = self.root / ("r"+str(number))
            start, result = checked(path / "start.json"), checked(path / "result.json")
            proposal = read(path / "proposal.json"); screen = read(path / "screen.json")
            if result and (not start or result["start_hash"] != start["hash"] or result["round"] != number):
                raise ValueError("round lineage/start binding mismatch")
            learn = self.stage(path / "learn", planned=len(planned["learn_cases"]))
            validation_report = checked(path / "agent/collection-report.json")
            observed_tokens += learn["observed_tokens"] + (validation_report["charged_tokens"] if validation_report else 0)
            n_candidates = proposal["n_candidates"] if proposal else 0
            opportunities = sum(item["status"] == "OPPORTUNITY" for item in (screen or {}).get("records", []))
            primary += learn["completed"]; candidates += n_candidates
            program += int(bool(result and result["program_admitted"])); agent += int(bool(result and result["agent_admitted"]))
            activated += int(bool(result and result["isolated_activated"]))
            rows.append({"round": number, "learn": learn, "opportunities": opportunities, "n_candidates": n_candidates,
                "state": "COMPLETE" if result else learn["state"], "result": result,
                "parent_snapshot": (start or {}).get("parent_snapshot"), "selected_snapshot": (result or {}).get("selected_snapshot"),
                "catalog_hash": (result or {}).get("selected_catalog_hash"),
                "program_decision": (result or {}).get("program_decision", "PENDING"),
                "agent_decision": (result or {}).get("agent_decision", "PENDING")})
        test = self.stage(self.root / "test", planned=3*len(protocol["draft"]["final_test_cases"]))
        observed_tokens += test["observed_tokens"]
        final = checked(self.root / "report.json")
        audit = None
        for path in (self.root / "evidence-audits").glob("*.json"):
            receipt = checked(path)
            if final and receipt.get("report_hash") == final["hash"] and receipt.get("protocol_hash") == protocol["hash"] and receipt.get("passed") is True:
                audit = receipt
        frozen = checked(self.root / "decisions-frozen.json")
        if final and (final["protocol_hash"] != protocol["hash"] or not frozen or
                final["selected_snapshot"] != frozen["selected_snapshot"] or final["completed_real_rounds"] != 3):
            raise ValueError("final report/frozen decisions binding mismatch")
        return {"ready": True, "protocol_hash": protocol["hash"], "frozen": True,
            "status": "AUDITED_COMPLETE" if audit else "COMPLETE_PENDING_AUDIT" if final else "RUNNING",
            "rounds": rows, "final_test": test, "final": final, "audit": audit,
            "funnel": {"learn_completed": primary, "learn_planned": sum(len(item["learn_cases"]) for item in protocol["draft"]["rounds"]),
                "compiled_candidates": candidates, "program_admitted": program, "agent_admitted": agent, "isolated_activated": activated},
            "budget": {**protocol["budget"], "observed_phase_tokens": observed_tokens,
                "observed_shared_tokens": protocol["budget"]["prior_tokens"]+observed_tokens,
                "cost_finalized": audit is not None},
            "model": {key: protocol["settings"].get(key) for key in ("model", "adapter_sha256", "do_sample", "decision_protocol")},
            "scope": "first-stage readonly program lane; live saved evidence, not a model endpoint",
            "no_history": protocol["no_history"], "unsupported": protocol["unsupported"],
            "research_claim_passed": (final or {}).get("research_claim_passed"), "deployed": False}

    def artifact(self, name):
        allowed = {"protocol.json", "report.json", "decisions-frozen.json"}
        for number in (1, 2, 3):
            allowed.update("r"+str(number)+"/"+item for item in ("start.json", "result.json", "screen.json", "proposal.json",
                "proposal-audit.json", "program-admission.json", "program-validation-protocol.json", "learn/plan.json", "learn/report.json",
                "agent/declaration.json", "agent/collection-report.json", "agent/agent-admission.json", "isolated/activation.json"))
        allowed.update({"test/plan.json", "test/report.json"})
        if name not in allowed: raise KeyError("artifact is not in the evidence allowlist")
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root) or not path.is_file(): raise KeyError("artifact not yet available")
        return path

    def trace(self, *, stage, index, method, round_number=1):
        protocol = self.protocol()
        if not protocol: raise KeyError("protocol not ready")
        if type(index) is not int or index < 0 or stage not in {"learn", "test"} or method not in {"A", "B", "C"}:
            raise KeyError("invalid trace selection")
        if stage == "learn":
            if round_number not in {1, 2, 3} or method != "C": raise KeyError("invalid learn arm")
            planned = protocol["draft"]["rounds"][round_number-1]["learn_cases"]
            base = self.root / ("r"+str(round_number)) / "learn"
        else:
            planned = [item["case"] for item in protocol["draft"]["final_test_cases"]]; base = self.root / "test"
        if index >= len(planned): raise KeyError("unplanned case")
        row = read(base / str(index) / method / "result.json")
        if not row: raise KeyError("trace not completed")
        if row["case"] != planned[index]: raise ValueError("trace case differs from formal declaration")
        return {"task_id": row["case"]["task_id"], "request": row["case"]["request"], "method": method,
            "agent": row["agent"], "verification": row["verification"], "tool_audit": row["tool_audit"],
            "scope": "completed saved public execution and independent evaluator verdict; viewing performs no inference"}
