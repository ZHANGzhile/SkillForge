"""Evaluator-owned split generation. Learners receive only public projections."""
import itertools
import json
from pathlib import Path
import random

from scripts.active_evolution_worlds import policy, WORLDS
from skillforge.evolution_boundary import parent_identity, public_predictions
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import Candidate, fingerprint
from skillforge.policies import eligibility, valid_address

SPLITS = ("seed", "explore", "validation", "test", "stable_validation", "stable_test",
          "model_validation", "model_stable_validation", "model_test", "model_stable_test")
TEMPLATES = {
    "seed": "Observe the result of {family} on {order_id}, using {value}.",
    "explore": "Probe whether {order_id} permits {family} with {value}.",
    "validation": "Check this candidate on order {order_id}: {family}, {value}.",
    "test": "Apply {family} to {order_id}, with requested value {value}.",
    "stable_validation": "Keep existing service for {order_id}: {family} using {value}.",
    "stable_test": "Retain the supported operation {family} for {order_id}, {value}.",
    "model_validation": "Please handle {family} for my order {order_id}; requested value: {value}.",
    "model_stable_validation": "For {order_id}, carry out {family} if eligible, using {value}.",
    "model_test": "My request is {family} on purchase {order_id}, with {value}.",
    "model_stable_test": "I need {family} for purchase {order_id}. The requested value is {value}.",
}


def controlled_facts(spec):
    """Public experimental factors set by the probe designer, not secret state."""
    f = spec["fixture"]
    remaining = f["captured"] - f["refunded"]
    amount = spec["parameters"].get("amount")
    facts = {"customer.risk_level": f["risk"], "order.status": f["order"],
        "shipment.status": f["shipment"], "payment.status": f["payment"],
        "payment.captured_amount": f["captured"], "payment.refunded_amount": f["refunded"],
        "payment.remaining_amount": remaining}
    if spec["family"] == "refund":
        facts.update({"request.amount": amount, "refund.amount_valid": 0 < amount <= remaining})
    else:
        facts["address.valid"] = valid_address(spec["parameters"].get("new_address"))
    return facts


def public_candidate(spec, contract):
    facts = controlled_facts(spec)
    baseline, guard = public_predictions(contract, facts, spec["parameters"])
    return Candidate(candidate_id=spec["task_id"], member_hash=fingerprint(spec), observations=facts,
        baseline_prediction=baseline, guard_prediction=guard,
        cost=(7 if spec["family"] == "modify_address" else 6) / 7, mutation_probability=1.)


def state_for_policy(spec):
    return {k: v for k, v in controlled_facts(spec).items() if not k.startswith("request.")}


def _cases():
    # Shared finite factors, including off-grid values and threshold neighbours.
    # No world ID, new-rule predicate or answer drives the acquisition pool.
    for risk, order, shipment, payment, remaining, amount, address in itertools.product(
        ("LOW", "MEDIUM", "HIGH"), ("CONFIRMED", "PENDING", "CANCELLED"),
        ("NOT_STARTED", "PROCESSING", "SHIPPED", "DELIVERED"),
        ("CAPTURED", "PARTIALLY_REFUNDED", "FAILED"),
        (999,1000,1001,2999,3000,3001,4999,5000,5001,10000),
        (100,999,1000,1001,2999,3000,3001,4999,5000,5001), (True,False)):
        yield (risk, order, shipment, payment, remaining, amount, address)


def _spec(world, seed, split, index, factors):
    risk, order, shipment, payment, remaining, amount, address = factors
    family = "modify_address" if world == "W6" else "refund"
    uid = fingerprint(["active-evolution-dataset-v1",world,seed,split,index,factors])[:24]
    refunded = 1000 if payment == "PARTIALLY_REFUNDED" else 0
    parameters = {"order_id": "AO"+uid}
    parameters.update({"new_address": "Delivery lane 204" if address else "bad"} if family == "modify_address" else {"amount": amount})
    template = TEMPLATES[split]
    request = template.format(family=family,order_id=parameters["order_id"],value=parameters.get("amount", parameters.get("new_address")))
    return {"task_id": uid, "instance_id": uid, "policy_epoch": fingerprint(["epoch-v1",world]),
        "split":split, "family":family, "parameters":parameters,"template":template,"request":request,
        "fixture":{"order_id":parameters["order_id"],"customer_id":"AC"+uid,"risk":risk,"order":order,
                   "shipment":shipment,"payment":payment,"captured":remaining+refunded,"refunded":refunded}}


def generate(world, seed, counts):
    if world not in WORLDS or not set(counts) <= set(SPLITS) or any(type(n) is not int or n < 1 for n in counts.values()):
        raise ValueError("invalid world or split specification")
    # Common factors/order across refund worlds; each split has independent RNG.
    pool = list(_cases())
    rows = []
    for split, count in counts.items():
        rng = random.Random(fingerprint(["factor-sampling-v1",seed,split]))
        shuffled = rng.sample(pool, len(pool))
        accepted = []
        # Balance old-policy applicable/nonapplicable, not new-policy truth.
        # Stable partitions alone deliberately exclude changed-label states.
        quotas = {True: count//2, False: count-count//2}
        for factors in shuffled:
            spec = _spec(world,seed,split,len(accepted),factors)
            tool = "update_shipping_address" if spec["family"] == "modify_address" else "issue_refund"
            old = eligibility(tool,state_for_policy(spec),spec["parameters"]) == "allow"
            if quotas[old] == 0:
                continue
            if "stable" in split and (policy(world,tool,state_for_policy(spec),spec["parameters"]) == "allow") != old:
                continue
            accepted.append(spec)
            quotas[old] -= 1
            if len(accepted) == count:
                break
        if len(accepted) != count:
            raise ValueError("insufficient declared factor support")
        rows.extend(accepted)
    return rows


def audit_splits(rows):
    seen = {name:{} for name in ("task_id","instance_id","order_id","customer_id","request","template")}
    for row in rows:
        values={"task_id":row["task_id"],"instance_id":row["instance_id"],"order_id":row["fixture"]["order_id"],
            "customer_id":row["fixture"]["customer_id"],"request":row["request"],"template":row["template"]}
        for name,value in values.items():
            previous=seen[name].get(value)
            if previous is not None and (previous!=row["split"] or name not in {"template"}):
                raise ValueError(f"duplicate/cross-split {name}")
            seen[name][value]=row["split"]
        if row["parameters"]["order_id"]!=row["fixture"]["order_id"] or row["instance_id"]!=row["task_id"]:
            raise ValueError("object binding mismatch")
    return {split:sum(r["split"]==split for r in rows) for split in sorted({r["split"] for r in rows})}


def write_dataset(root, world, seed, counts, contract):
    root=Path(root)
    rows=generate(world,seed,counts)
    audit=audit_splits(rows)
    manifest={"format":"active-evolution-dataset-v1","world":world,"seed":seed,
        "policy_epoch":fingerprint(["epoch-v1",world]),"counts":audit,"parent":parent_identity(contract),
        "members":{r["task_id"]:{"hash":fingerprint(r),"split":r["split"]} for r in rows},
        "public_factor_scope":"controlled experimental settings; state combinations may recur across splits; not structural novelty"}
    for split in counts:
        immutable_json(root/(split+".json"),[r for r in rows if r["split"]==split])
    immutable_json(root/"parent-skill.json",contract)
    immutable_json(root/"manifest.json",manifest)
    return manifest


class EvaluationStore:
    """Evaluator-only access. Candidate freeze precedes held-out file opens."""
    def __init__(self, root):
        self.root=Path(root)
        self.manifest=json.loads((self.root/"manifest.json").read_text(encoding="utf-8"))

    def read(self, split, candidate=None, freeze=None):
        if split not in SPLITS:
            raise ValueError("unknown split")
        if split in {"test","stable_test","model_test","model_stable_test"}:
            if candidate is None or freeze is None or freeze.get("candidate_hash")!=fingerprint(candidate) or freeze.get("dataset_hash")!=fingerprint(self.manifest):
                raise PermissionError("held-out access requires candidate/dataset freeze")
        rows=json.loads((self.root/(split+".json")).read_text(encoding="utf-8"))
        expected={k for k,v in self.manifest["members"].items() if v["split"]==split}
        if {r["task_id"] for r in rows}!=expected or len(rows)!=len(expected):
            raise ValueError("split membership mismatch")
        for row in rows:
            if row["split"]!=split or fingerprint(row)!=self.manifest["members"][row["task_id"]]["hash"]:
                raise ValueError("split content changed")
        return rows
