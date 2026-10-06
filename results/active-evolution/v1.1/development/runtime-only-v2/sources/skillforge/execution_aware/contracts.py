"""Public-observation-only execution obligations and immutable verification evidence."""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json

from ..environment import ToolError
from ..evolution_schemas import fingerprint
from ..tool_schemas import INPUTS, ValidationError


READS = {"issue_refund": "get_payment", "update_shipping_address": "get_order", "cancel_order": "get_order"}
KNOWN_REJECTIONS = {"business_rule_rejected", "permission_denied", "not_found", "invalid_arguments",
                    "invalid_tool", "idempotency_conflict"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class VerificationReceipt:
    schema_version: str
    mutation_id: str
    request_id: str
    object_id: str
    mutation_tool: str
    verification_tool: str
    expected_postcondition_json: str
    observed_value_json: str
    status: str
    timestamp: str
    source: str
    event_sequence: int
    evidence_hash: str

    @property
    def receipt_id(self):
        return fingerprint(asdict(self))

    def to_dict(self):
        out = asdict(self)
        out["expected_postcondition"] = json.loads(out.pop("expected_postcondition_json"))
        out["observed_value"] = json.loads(out.pop("observed_value_json"))
        return {"receipt_id": self.receipt_id, **out}


class ExecutionContract:
    """One task's ledger. persist must durably save snapshots before dispatch.

    Reconciliation is an optional capability supplied by a trusted tool adapter;
    it must return authoritative per-request evidence, never evaluator labels.
    No capability means STILL_UNKNOWN, not an inferred unsuccessful commit.
    """

    def __init__(self, task_id, persist=None):
        self.task_id = task_id
        self.observations = {}
        self.operations = {}
        self.receipts = []
        self.events = []
        self.persist = persist
        self.sequence = 0

    def _event(self, kind, **payload):
        self.sequence += 1
        self.events.append({"sequence": self.sequence, "kind": kind, **payload})
        if self.persist:
            self.persist(self.checkpoint())

    def checkpoint(self):
        body = {"schema": "execution-contract-v1", "task_id": self.task_id, "observations": self.observations,
                "operations": self.operations, "receipts": [asdict(r) for r in self.receipts],
                "events": self.events, "sequence": self.sequence}
        body = json.loads(canonical(body))
        return {"body": body, "hash": fingerprint(body)}

    @classmethod
    def restore(cls, checkpoint, task_id, persist=None):
        body = json.loads(canonical(checkpoint["body"]))
        if fingerprint(body) != checkpoint["hash"] or body["schema"] != "execution-contract-v1" or body["task_id"] != task_id:
            raise ValueError("checkpoint identity/integrity mismatch")
        obj = cls(task_id, persist)
        obj.observations, obj.operations = body["observations"], body["operations"]
        obj.receipts = [VerificationReceipt(**r) for r in body["receipts"]]
        obj.events, obj.sequence = body["events"], body["sequence"]
        # In-flight dispatch could have committed even if the last saved state was PREPARED.
        for op in obj.operations.values():
            if op["commit"] == "PREPARED":
                op["commit"] = "COMMIT_UNKNOWN"
        obj._event("restored")
        return obj

    def request_id(self, tool, args):
        # Logical task identity, not step number: repeated intentions never double-write.
        return self.task_id + ":" + fingerprint([tool, args])

    def pending(self):
        return [op for op in self.operations.values() if op["commit"] not in {"REJECTED", "NOT_COMMITTED"}
                and (op["commit"] != "COMMITTED" or op["verification"] != "VERIFIED")]

    def _expected(self, name, args):
        state = self.observations.get(args["order_id"], {})
        if name == "issue_refund":
            before, amount = state.get("payment.refunded_amount"), args.get("amount")
            if type(before) is not int or type(amount) is not int or amount <= 0:
                raise ToolError("missing_public_refund_baseline")
            return {"payment.refunded_amount": before + amount}
        if name == "update_shipping_address":
            if not isinstance(args.get("new_address"), str):
                raise ToolError("invalid_arguments")
            return {"order.shipping_address": args["new_address"]}
        if name == "cancel_order":
            return {"order.status": "CANCELLED"}
        raise ToolError("unsupported_execution_contract")

    def _observe(self, name, args, value, source):
        oid = args.get("order_id")
        response_oid = value.get("payment.order_id") if name == "get_payment" else value.get("order.order_id") if name == "get_order" else None
        if name in {"get_payment", "get_order"} and response_oid != oid:
            raise ToolError("read_object_mismatch")
        if oid:
            self.observations.setdefault(oid, {}).update({k: v for k, v in value.items() if "." in k})
        self._event("observation", tool=name, object_id=oid, source=source, result=value)
        for op in self.operations.values():
            if op["commit"] != "COMMITTED" or op["verification"] == "VERIFIED" or op["object_id"] != oid or READS[op["tool"]] != name:
                continue
            # Matching returned object identity is mandatory, not just caller arguments.
            success = response_oid == oid and all(k in value and type(value[k]) is type(v) and value[k] == v for k, v in op["expected"].items())
            receipt = VerificationReceipt("verification-receipt-v1", op["mutation_id"], op["request_id"], oid,
                op["tool"], name, canonical(op["expected"]), canonical(value), "VERIFIED" if success else "VERIFY_FAILED",
                datetime.now(timezone.utc).isoformat(), source, self.sequence,
                fingerprint([op["mutation_id"], self.sequence, name, args, value]))
            self.receipts.append(receipt)
            op["verification"] = receipt.status
            op["receipt_id"] = receipt.receipt_id
            self._event("verification", receipt_id=receipt.receipt_id, status=receipt.status, source=source)

    def call(self, tool_call, name, args, key, source="model"):
        args = json.loads(canonical(args))
        if name not in INPUTS:
            raise ToolError("invalid_tool")
        try:
            args = INPUTS[name].model_validate(args).model_dump()
        except ValidationError as exc:
            raise ToolError("invalid_arguments") from exc
        if name not in READS:
            if self.pending() and name not in {"get_payment", "get_order"}:
                self._event("intervention", action="blocked_pending_action", tool=name)
                raise ToolError("verification_required")
            self._event("tool_dispatch", tool=name, arguments=args, source=source)
            try:
                value = tool_call(name, args, key)
                self._observe(name, args, value, source)
                return value
            except ToolError as exc:
                self._event("tool_error", tool=name, error=exc.code, source=source)
                for op in self.pending():
                    if op["commit"] == "COMMITTED" and op["object_id"] == args.get("order_id") and READS[op["tool"]] == name:
                        receipt = VerificationReceipt("verification-receipt-v1", op["mutation_id"], op["request_id"],
                            op["object_id"], op["tool"], name, canonical(op["expected"]), canonical({"error": exc.code}),
                            "VERIFY_FAILED", datetime.now(timezone.utc).isoformat(), source, self.sequence,
                            fingerprint([op["mutation_id"], self.sequence, exc.code]))
                        self.receipts.append(receipt)
                        op["verification"] = "VERIFY_FAILED"; op["receipt_id"] = receipt.receipt_id
                        self._event("verification", receipt_id=receipt.receipt_id, status=receipt.status, source=source)
                raise
        request_id = self.request_id(name, args)
        previous = self.operations.get(request_id)
        if previous:
            if previous["commit"] == "COMMITTED" and previous["verification"] == "VERIFIED":
                self._event("intervention", action="prevented_repeat_mutation", request_id=request_id)
                return json.loads(canonical(previous["response"]))
            if previous["commit"] != "NOT_COMMITTED":
                self._event("intervention", action="blocked_pending_mutation", request_id=request_id)
                raise ToolError("commit_unknown" if previous["commit"] == "COMMIT_UNKNOWN" else "verification_required")
            if previous["attempts"] >= 2:
                raise ToolError("mutation_retry_exhausted")
        if self.pending():
            self._event("intervention", action="blocked_pending_mutation", request_id=request_id)
            raise ToolError("verification_required")
        if previous is None:
            expected = self._expected(name, args)
            previous = {"mutation_id": fingerprint([request_id, expected]), "request_id": request_id,
                        "object_id": args["order_id"], "tool": name, "arguments": args, "expected": expected,
                        "baseline": dict(self.observations.get(args["order_id"], {})), "attempts": 0,
                        "verification": "VERIFY_REQUIRED", "reconciliation_attempts": 0}
            self.operations[request_id] = previous
        previous["commit"] = "PREPARED"; previous["attempts"] += 1
        self._event("mutation_prepared", request_id=request_id, source=source)
        try:
            value = tool_call(name, args, request_id)
        except Exception as exc:
            previous["commit"] = "REJECTED" if isinstance(exc, ToolError) and exc.code in KNOWN_REJECTIONS else "COMMIT_UNKNOWN"
            self._event("mutation_error", request_id=request_id, error=getattr(exc, "code", type(exc).__name__), source=source)
            raise
        if value.get("ok") is not True:
            previous["commit"] = "COMMIT_UNKNOWN"
            self._event("mutation_unconfirmed", request_id=request_id)
            raise ToolError("commit_unknown")
        previous["commit"] = "COMMITTED"; previous["response"] = value
        # Later writes invalidate earlier terminal evidence, without changing immutable receipts.
        for op in self.operations.values():
            if op is not previous and op["object_id"] == previous["object_id"] and op["verification"] == "VERIFIED":
                op["superseded_by"] = previous["mutation_id"]
        self._event("mutation_confirmed", request_id=request_id, source=source)
        return value

    def reconcile(self, request_id, lookup=None):
        op = self.operations[request_id]
        if op["commit"] != "COMMIT_UNKNOWN":
            raise ValueError("only unknown commits can reconcile")
        if lookup is None or op["reconciliation_attempts"] >= 2:
            self._event("reconciliation", request_id=request_id, status="STILL_UNKNOWN", reason="no_capability_or_budget")
            return "STILL_UNKNOWN"
        op["reconciliation_attempts"] += 1
        self._event("intervention", action="reconciliation_lookup", request_id=request_id)
        try:
            evidence = lookup(request_id)
        except Exception as exc:
            self._event("reconciliation", request_id=request_id, status="STILL_UNKNOWN", error=type(exc).__name__)
            return "STILL_UNKNOWN"
        status = evidence.get("status")
        if (evidence.get("request_id") != request_id or evidence.get("authoritative") is not True
                or not evidence.get("evidence_id") or status not in {"COMMITTED", "NOT_COMMITTED"}):
            status = "STILL_UNKNOWN"
        if status != "STILL_UNKNOWN":
            op["commit"] = status
            if status == "COMMITTED":
                op["response"] = evidence.get("response", {"ok": True})
        self._event("reconciliation", request_id=request_id, status=status, evidence=evidence)
        return status

    def verify_pending(self, tool_call):
        for op in list(self.pending()):
            if op["commit"] != "COMMITTED":
                raise ToolError("commit_unknown")
            self._event("intervention", action="forced_readback", request_id=op["request_id"])
            try:
                self.call(tool_call, READS[op["tool"]], {"order_id": op["object_id"]},
                          op["request_id"] + ":verify", source="runtime")
            except ToolError:
                op["verification"] = "VERIFY_FAILED"
                self._event("verification_failed", request_id=op["request_id"])
                raise
            if op["verification"] != "VERIFIED":
                raise ToolError("verification_failed")

    def terminal_ready(self, parameters, family, single_goal=False):
        if not single_goal or self.pending():
            return False
        tool = {"refund": "issue_refund", "modify_address": "update_shipping_address", "cancel_order": "cancel_order"}.get(family)
        required = {"refund": ("order_id", "amount"), "modify_address": ("order_id", "new_address"), "cancel_order": ("order_id",)}.get(family)
        if not tool or any(k not in parameters for k in required):
            return False
        args = {k: parameters[k] for k in required}
        op = self.operations.get(self.request_id(tool, args))
        return bool(op and op["commit"] == "COMMITTED" and op["verification"] == "VERIFIED" and not op.get("superseded_by"))

    def metrics(self):
        interventions = [e for e in self.events if e["kind"] == "intervention"]
        return {"runtime_intervention_count": len(interventions),
                "forced_readback_count": sum(e["action"] == "forced_readback" for e in interventions),
                "auto_termination_count": sum(e["action"] == "auto_termination" for e in interventions)}
