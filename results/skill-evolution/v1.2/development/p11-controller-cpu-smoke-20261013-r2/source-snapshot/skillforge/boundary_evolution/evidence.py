"""Trusted allowlist adapter from pinned actual public tool receipts.

The controller owns membership and raw hashes. Hashes establish identity, not
independent authenticity: model/candidate processes must not own this adapter.
Private snapshots, EOC, world and expected terminal outcomes are never exported.
"""
from ..evolution_schemas import EvidenceView, fingerprint
from ..evolution_evidence import READ_FIELDS, WRITES
from ..evolution_boundary import public_predictions
from ..execution_aware.contracts import VerificationReceipt, READS
from ..skill_evolution.catalog import Catalog
from .trigger import Interaction


class PublicReceiptAdapter:
    def __init__(self, members, catalog):
        self.members = {key: dict(value) for key, value in members.items()}
        self.catalog = Catalog(catalog.entries())

    def export(self, raw, task):
        member = self.members.get(task["task_id"])
        if (not member or member["task_hash"] != fingerprint(task) or member["raw_hash"] != fingerprint(raw)
                or raw["task_id"] != task["task_id"]):
            raise ValueError("public receipt is not an exact pinned task/source member")
        if set(task) != {"task_id", "family", "parameters", "request"}:
            raise ValueError("public task projection only")
        entry = self.catalog.get(member["skill_id"], member["parent_revision"])
        if entry["contract"]["family"] != task["family"]:
            raise ValueError("public task and parent Skill family mismatch")
        oid = task["parameters"]["order_id"]
        facts, writes, errors = {}, [], []
        mutation = WRITES[task["family"]]
        started = False
        for event in raw["tool_audit"]:
            name, args = event["tool_name"], event["arguments"]
            if args.get("order_id") != oid:
                continue
            error = event.get("error")
            if error:
                errors.append((name, error))
            if name == mutation:
                started = True
                writes.append(event)
            if not started and not error and name in READ_FIELDS:
                result = event.get("result") or {}
                facts.update({key: value for key, value in result.items() if key in READ_FIELDS[name]})
        amount = task["parameters"].get("amount")
        if type(amount) is int:
            facts["request.amount"] = amount
        if all(key in facts for key in ("payment.captured_amount", "payment.refunded_amount")):
            a, b = facts["payment.captured_amount"], facts["payment.refunded_amount"]
            facts["payment.remaining_amount"] = a - b
            if type(amount) is int:
                facts["refund.amount_valid"] = 0 <= b <= a and 0 < amount <= a - b
        baseline, guard = public_predictions(entry["contract"], facts, task["parameters"])
        label, feedback = "unknown", "unknown"
        committed = [event for event in writes if event.get("committed") and not event.get("error")]
        rejected = [event for event in writes if event.get("error") == "business_rule_rejected"]
        verified = []
        checkpoint = raw.get("execution_contract")
        if checkpoint is not None:
            body = checkpoint["body"]
            if checkpoint["hash"] != fingerprint(body) or body["task_id"] != task["task_id"]:
                raise ValueError("invalid public VerificationReceipt ledger identity")
            for value in body["receipts"]:
                receipt = VerificationReceipt(**value)
                op = body["operations"].get(receipt.request_id)
                if (receipt.status != "VERIFIED" or receipt.object_id != oid or receipt.mutation_tool != mutation
                        or receipt.verification_tool != READS[mutation] or not op or op["commit"] != "COMMITTED"
                        or op.get("superseded_by") or op.get("receipt_id") != receipt.receipt_id
                        or op["mutation_id"] != receipt.mutation_id or op["object_id"] != oid):
                    continue
                if not any(event["request_id"] == receipt.request_id for event in committed):
                    continue
                observed = receipt.to_dict()["observed_value"]
                expected = receipt.to_dict()["expected_postcondition"]
                if (op["expected"] != expected or not expected or not all(key in observed and
                        type(observed[key]) is type(value) and observed[key] == value for key, value in expected.items())):
                    continue
                # Bind to an actual subsequent same-object public read and ledger event.
                observation = next((event for event in body["events"] if event["sequence"] == receipt.event_sequence), None)
                if (not observation or observation.get("kind") != "observation" or observation.get("result") != observed
                        or observation.get("object_id") != oid or observation.get("tool") != READS[mutation]):
                    continue
                seen_write = False
                for event in raw["tool_audit"]:
                    if event["request_id"] == receipt.request_id and event["tool_name"] == mutation:
                        seen_write = True
                    elif (seen_write and event["tool_name"] == READS[mutation] and not event.get("error")
                          and event["arguments"].get("order_id") == oid and event.get("result") == observed):
                        verified.append(receipt.receipt_id)
                        break
        # Any transport/permission/program/verification ambiguity excludes the whole
        # interaction from Bayes evidence, even if a later unrelated call succeeded.
        codes = {error for _, error in errors}
        if codes & {"permission_denied", "not_found"}:
            feedback = "permission"
        elif codes & {"timeout", "temporary_unavailable", "connection_lost", "response_lost", "commit_unknown"}:
            feedback = "infrastructure"
        elif codes & {"invalid_arguments", "invalid_tool", "missing_idempotency_key", "idempotency_conflict"}:
            feedback = "arguments"
        elif codes - {"business_rule_rejected"}:
            feedback = "program"
        elif committed and guard is False:
            label, feedback = "executable", "immutable_guard"
        elif committed and verified:
            label, feedback = "executable", "business"
        elif rejected and not committed:
            label, feedback = "not_executable", "business"
        elif committed:
            feedback = "verification"
        elif raw.get("terminal_error") in {"wrong_terminal", "premature_stop"}:
            feedback = "termination"
        payload = {"trajectory_id": raw["trajectory_id"], "member_hash": member["task_hash"],
            "split": "explore" if member["probe_origin"] == "authorized_sandbox" else "seed",
            "policy_epoch": "public-stream", "family": task["family"], "observations": facts,
            "baseline_prediction": baseline, "guard_prediction": guard, "label": label,
            "origin": member["evidence_origin"], "tool_calls": len(raw["tool_audit"])}
        view = EvidenceView(evidence_id=fingerprint(payload), **payload)
        query_hash = fingerprint({"raw_hash": member["raw_hash"], "task_hash": member["task_hash"],
            "verified_receipts": sorted(verified)})
        body = {"source_group": member["source_group"], "object_id": oid,
            "parent_revision": entry["revision"], "evidence": view,
            "feedback": feedback, "probe_origin": member["probe_origin"],
            "sandbox_id": member.get("sandbox_id"), "query_receipt_hash": query_hash}
        return Interaction(receipt_id=fingerprint({**body, "evidence": view.model_dump(mode="json")}), **body)
