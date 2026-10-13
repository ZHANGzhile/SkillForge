"""Trusted adapter: export tool-visible evidence, never database snapshots."""
import copy

from .evolution_schemas import EvidenceView, fingerprint

READ_FIELDS = {"get_customer": {"customer.risk_level"}, "get_order": {"order.status"},
    "get_shipment": {"shipment.status"}, "get_payment": {"payment.status", "payment.captured_amount", "payment.refunded_amount"},
    "validate_address": {"address.valid"}}
WRITES = {"refund": "issue_refund", "modify_address": "update_shipping_address", "cancel_order": "cancel_order"}


class EvidenceBoundary:
    """Membership comes from a frozen manifest, not a caller-supplied split tag."""
    def __init__(self, manifest):
        self.manifest = copy.deepcopy(manifest)

    def export(self, trajectory, task, baseline_prediction, guard_prediction=True):
        member = self.manifest["members"].get(task["task_id"])
        if not member or member["hash"] != fingerprint(task):
            raise ValueError("task is not a frozen manifest member")
        if member["split"] not in {"seed", "explore"} or task["split"] != member["split"]:
            raise ValueError("learning evidence must be seed/explore")
        if trajectory["task_id"] != task["task_id"] or trajectory["policy_epoch"] != self.manifest["policy_epoch"]:
            raise ValueError("evidence task/policy identity mismatch")
        facts, wrote, rejected, checked = {}, False, False, False
        write_tool = WRITES[task["family"]]
        # Only pre-mutation reads teach preconditions; audit before/after are never used.
        for entry in trajectory["tool_audit"]:
            name = entry["tool_name"]
            if name == write_tool:
                rejected |= entry.get("error") == "business_rule_rejected"
                wrote |= bool(entry.get("committed")) and not entry.get("error")
            if not entry.get("error") and name in READ_FIELDS:
                result = entry.get("result") or {}
                if not wrote and not rejected:
                    facts.update({k: v for k, v in result.items() if k in READ_FIELDS[name]})
                elif wrote and name == ("get_payment" if task["family"] == "refund" else "get_order"):
                    checked = True
        amount = task["parameters"].get("amount")
        if type(amount) is int:
            facts["request.amount"] = amount
        if all(k in facts for k in ("payment.captured_amount", "payment.refunded_amount")):
            remaining = facts["payment.captured_amount"] - facts["payment.refunded_amount"]
            facts["payment.remaining_amount"] = remaining
            if type(amount) is int:
                facts["refund.amount_valid"] = 0 <= facts["payment.refunded_amount"] <= facts["payment.captured_amount"] and 0 < amount <= remaining
        # Success is supplied by the trusted fixed-procedure executor after postcondition checks.
        label = "executable" if wrote and checked and trajectory.get("procedure_success") is True else "not_executable" if rejected and not wrote else "unknown"
        payload = {"trajectory_id": trajectory["trajectory_id"], "member_hash": member["hash"], "split": member["split"],
            "policy_epoch": trajectory["policy_epoch"], "family": task["family"], "observations": facts,
            "baseline_prediction": baseline_prediction, "guard_prediction": guard_prediction, "label": label, "origin": trajectory["origin"],
            "tool_calls": len(trajectory["tool_audit"])}
        return EvidenceView(evidence_id=fingerprint(payload), **payload)
