"""Reproducible experiment corpus. Oracles are explicit scenario specifications."""
import hashlib
import json
from collections import Counter
from pathlib import Path

from .schemas import ExpectedOutcome, Task

VERSION = "ecommerce-experiment-v1"
SPLITS = ("train", "validation", "test")
TEMPLATES = {
    "train": {
        "modify_address": "Please change order {order_id} to the address {new_address}.",
        "cancel_order": "Please cancel my order {order_id}.",
        "refund": "Refund {amount} minor currency units for order {order_id}.",
        "shipment_investigation": "Investigate delivery of order {order_id} and open a human ticket.",
        "ticket": "Open a human support ticket for order {order_id}.",
        "composite": "For {order_id}, change the address to {new_address} if allowed; otherwise request human assistance.",
    },
    "validation": {
        "modify_address": "The destination for {order_id} should be {new_address}. Update it if permitted.",
        "cancel_order": "I no longer need {order_id}; arrange cancellation if eligible.",
        "refund": "I request a payment return of {amount} minor currency units against {order_id}.",
        "shipment_investigation": "Have a support specialist look into the delivery of {order_id}.",
        "ticket": "Pass the matter concerning {order_id} to a person with a ticket.",
        "composite": "Try updating {order_id} to {new_address}; when it cannot be done, create a support case.",
    },
    "test": {
        "modify_address": "Could you replace the shipping destination on {order_id} with {new_address}? Follow the eligibility rules.",
        "cancel_order": "Stop fulfillment by cancelling {order_id}, subject to the order policy.",
        "refund": "For {order_id}, return exactly {amount} minor currency units through the refund flow if allowed.",
        "shipment_investigation": "Route the unresolved shipping issue for {order_id} to manual investigation.",
        "ticket": "I need a human case created regarding {order_id}.",
        "composite": "Order {order_id}: first try address {new_address}; if that is ineligible, cancel if allowed; if neither is allowed, open a human ticket.",
    },
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def task_hash(task):
    return digest(task.model_dump())


def scenarios(split):
    # Expected outcomes do not call runtime policy or inspect model output.
    rows = [
        ("modify_address", "normal", {}, "completed", "A"),
        ("modify_address", "shipped", {"shipment": "SHIPPED"}, "refused", "B"),
        ("modify_address", "delivered", {"shipment": "DELIVERED"}, "refused", "B"),
        ("modify_address", "processing", {"shipment": "PROCESSING"}, "escalated", "B"),
        ("modify_address", "invalid_address", {"invalid_address": True}, "refused", "B"),
        ("modify_address", "wrong_customer", {"wrong_customer": True}, "refused", "B"),
        ("modify_address", "high_risk", {"risk": "HIGH"}, "escalated", "E"),
        ("modify_address", "read_timeout", {"faults": {"get_order": ["timeout"]}}, "completed", "D"),
        ("modify_address", "retry_exhausted", {"faults": {"get_order": ["timeout", "timeout"]}}, "escalated", "D"),
        ("cancel_order", "normal", {}, "completed", "A"),
        ("cancel_order", "shipped", {"shipment": "SHIPPED"}, "refused", "B"),
        ("cancel_order", "processing", {"shipment": "PROCESSING"}, "escalated", "B"),
        ("cancel_order", "high_risk", {"risk": "HIGH"}, "escalated", "E"),
        ("cancel_order", "write_timeout", {"faults": {"cancel_order": ["timeout"]}}, "completed", "D"),
        ("refund", "partial", {}, "completed", "A"),
        ("refund", "full", {"full": True}, "completed", "A"),
        ("refund", "over_remaining", {"over": True}, "refused", "B"),
        ("refund", "payment_failed", {"payment": "FAILED"}, "refused", "B"),
        ("refund", "high_risk", {"risk": "HIGH"}, "escalated", "E"),
        ("refund", "response_lost", {"faults": {"issue_refund": ["response_lost"]}}, "completed", "D"),
        ("shipment_investigation", "failed", {"shipment": "FAILED"}, "escalated", "A"),
        ("ticket", "request", {}, "escalated", "A"),
    ]
    if split == "test":
        rows += [
            ("composite", "address_branch", {}, "completed", "C"),
            ("composite", "cancel_branch", {"invalid_address": True}, "completed", "C"),
            ("composite", "escalate_branch", {"shipment": "SHIPPED"}, "escalated", "C"),
            ("modify_address", "risk_shipping_conflict", {"risk": "HIGH", "shipment": "SHIPPED"}, "escalated", "E"),
        ]
    else:
        rows += [("composite", "simple_branch", {}, "completed", "A")]
    return rows


def generate_experiment(seed=42, instances=3):
    if instances < 1:
        raise ValueError("instances must be positive")
    tasks = []
    for split in SPLITS:
        for family, scenario, attributes, outcome, level in scenarios(split):
            for index in range(instances):
                uid = digest([VERSION, seed, split, family, scenario, index])[:20]
                oid, cid = "O" + uid, "C" + uid
                captured = 10000 + int(uid[:4], 16)
                amount = captured if attributes.get("full") else captured + 1 if attributes.get("over") else 1000 + int(uid[4:8], 16) % 5000
                address = "bad" if attributes.get("invalid_address") else f"{int(uid[:6], 16)} Orchard Road, City"
                fixture = {**attributes, "order_id": oid, "customer_id": cid, "captured": captured, "address": f"{int(uid[6:12], 16)} Original Street"}
                params = {"order_id": oid}
                if family in {"modify_address", "composite"}:
                    params["new_address"] = address
                if family == "refund":
                    params["amount"] = amount
                changes = {}
                unchanged = ["order.shipping_address", "order.status", "payment.refunded_amount"]
                if outcome == "completed":
                    key = "payment.refunded_amount" if family == "refund" else "order.status" if family == "cancel_order" or scenario == "cancel_branch" else "order.shipping_address"
                    changes[key] = amount if key == "payment.refunded_amount" else "CANCELLED" if key == "order.status" else address
                    unchanged.remove(key)
                workflow = "primitive" if family != "composite" else "address_else_cancel_else_escalate" if split == "test" else "address_else_escalate"
                template = TEMPLATES[split][family]
                tasks.append(Task(task_id="task-" + uid, family=family, request=template.format(**params),
                    customer_id="X" + uid if attributes.get("wrong_customer") else cid, parameters=params,
                    split=split, template_id=digest(template), template_text=template, seed=seed,
                    fixture=fixture, expected=ExpectedOutcome(allowed_outcomes=[outcome], expected_state=changes, unchanged_fields=unchanged),
                    dataset_id=VERSION, instance_id=uid, structure_id=workflow if family == "composite" else family,
                    level=level, workflow=workflow))
    return tasks


def audit_splits(tasks):
    if not tasks or set(t.split for t in tasks) != set(SPLITS):
        raise ValueError("all three nonempty splits required")
    for label, values in [
        ("task_id", [(t.task_id, t.split) for t in tasks]),
        ("instance_id", [(t.instance_id, t.split) for t in tasks]),
        ("order_id", [(t.parameters["order_id"], t.split) for t in tasks]),
        ("request", [(digest(t.request), t.split) for t in tasks]),
        ("template content", [(digest(t.template_text), t.split) for t in tasks]),
    ]:
        owners = {}
        for value, split in values:
            if not value:
                raise ValueError(f"missing {label}")
            if value in owners and owners[value] != split:
                raise ValueError(f"cross-split overlap: {label}")
            owners[value] = split
    if len({t.task_id for t in tasks}) != len(tasks):
        raise ValueError("duplicate task IDs")
    for t in tasks:
        if t.template_id != digest(t.template_text) or t.request != t.template_text.format(**t.parameters):
            raise ValueError("template content or rendering mismatch")
    learned_structures = {t.structure_id for t in tasks if t.split != "test"}
    heldout = {t.structure_id for t in tasks if t.level == "C"}
    if not heldout or heldout & learned_structures:
        raise ValueError("Level C structure is not held out")
    return {"counts": dict(Counter(t.split for t in tasks)), "levels": dict(Counter(t.level for t in tasks)),
        "heldout_structures": sorted(heldout), "limitations": ["synthetic bounded domain", "template separation is not proof of semantic novelty", "Level A intentionally shares task families and state categories"]}


def write_dataset(root, seed=42, instances=3):
    root = Path(root)
    tasks = generate_experiment(seed, instances)
    report = audit_splits(tasks)
    files = {}
    payloads = {f"{split}.jsonl": "".join(t.model_dump_json() + "\n" for t in tasks if t.split == split) for split in SPLITS}
    for name, content in payloads.items():
        files[name] = hashlib.sha256(content.encode()).hexdigest()
    manifest = {"version": VERSION, "seed": seed, "instances": instances, "files": files, "audit": report}
    manifest["dataset_hash"] = digest(manifest)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        existing, _ = load_dataset(root)
        if existing != manifest:
            raise ValueError("dataset directory is immutable; choose a new output directory")
        return manifest
    for name, content in payloads.items():
        (root / name).write_bytes(content.encode())
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_dataset(root):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest["dataset_hash"] != digest({k: v for k, v in manifest.items() if k != "dataset_hash"}):
        raise ValueError("manifest hash mismatch")
    tasks = []
    for split in SPLITS:
        name = f"{split}.jsonl"
        content = (root / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != manifest["files"][name]:
            raise ValueError(f"dataset file hash mismatch: {name}")
        group = [Task.model_validate_json(line) for line in content.decode().splitlines() if line]
        if any(t.split != split or t.dataset_id != manifest["version"] for t in group):
            raise ValueError("split/version mismatch")
        tasks += group
    if audit_splits(tasks) != manifest["audit"]:
        raise ValueError("dataset audit mismatch")
    return manifest, tasks
