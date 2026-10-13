"""Read-only P9 attribution of every nontrivial v1 proposal validation pair."""
import argparse
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path

from skillforge.evolution_schemas import fingerprint


READS = {"issue_refund": "get_payment", "update_shipping_address": "get_order", "cancel_order": "get_order"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def events(result):
    """Align business events (including DSL calls), not model step offsets."""
    out = [{"kind": "tool", "name": e["tool_name"], "arguments": e["arguments"],
            "error": e["error"], "result": e["result"], "committed": e["committed"],
            "pointer": f"/result/tool_audit/{i}"} for i, e in enumerate(result["tool_audit"])]
    for i, step in enumerate(result["agent"]["steps"]):
        action = step.get("action", {})
        if action.get("type") in {"stop", "refuse", "escalate"} or step.get("error") == "model_error":
            out.append({"kind": "terminal", "name": action.get("type", step.get("error")),
                        "arguments": action.get("arguments", {}), "error": step.get("error"),
                        "error_type": step.get("error_type"), "pointer": f"/result/agent/steps/{i}"})
    return out


def diagnose(result):
    audit = result["tool_audit"]
    missing = []
    for i, event in enumerate(audit):
        name = event["tool_name"]
        if name not in READS or not event["committed"]:
            continue
        oid = event["arguments"]["order_id"]
        # A read must follow this mutation and precede the next same-object write.
        end = next((j for j in range(i + 1, len(audit)) if audit[j]["tool_name"] in READS
                    and audit[j]["arguments"].get("order_id") == oid), len(audit))
        matching = [j for j in range(i + 1, end) if audit[j]["tool_name"] == READS[name]
                    and audit[j]["arguments"].get("order_id") == oid and not audit[j]["error"]]
        if not matching:
            missing.append(f"/result/tool_audit/{i}")
    invalid = [f"/result/agent/steps/{i}" for i, s in enumerate(result["agent"]["steps"])
               if s.get("error") == "model_error" and s.get("error_type") == "ValidationError"]
    labels, evidence = [], []
    if missing:
        labels.append("missing_post_write_verification"); evidence.extend(missing)
        if result["agent"]["outcome"] == "completed":
            labels.append("premature_stop")
    if invalid:
        labels.append("invalid_action_schema"); evidence.extend(invalid)
    if not labels and not result["verification"]["task_success"]:
        labels.append("unknown")
    violation = None
    if missing:
        violation = {"obligation_origin": missing[0], "detected_at": "/result/agent/outcome",
                     "required": "successful matching-object read after committed mutation",
                     "observed": "execution ended without matching read"}
    elif invalid:
        violation = {"detected_at": invalid[0], "required": "valid Action schema",
                     "observed": "ValidationError; original response retained at referenced model_response"}
    return {"primary": labels[0] if labels else None, "secondary": labels[1:], "evidence": evidence,
            "first_supported_contract_violation": violation,
            "final_eoc_reasons": result["verification"]["reason"]}


def pair(before, after, refs):
    for key in ("task_hash", "contract", "model", "protocol_hash", "world", "decision_only"):
        if before["identity"][key] != after["identity"][key]:
            raise ValueError(f"unpaired identity: {key}")
    a, b = before["result"], after["result"]
    if a["spec_hash"] != b["spec_hash"] or a["agent"]["model_settings"] != b["agent"]["model_settings"]:
        raise ValueError("unpaired spec or decoding")
    ea, eb = events(a), events(b)
    signature = lambda e: fingerprint([e["kind"], e["name"], e["arguments"], e.get("error")])
    sa, sb = list(map(signature, ea)), list(map(signature, eb))
    prefix = next((i for i, (x, y) in enumerate(zip(sa, sb)) if x != y), min(len(sa), len(sb)))
    actions_a = [s.get("action", {"error": s.get("error")}) for s in a["agent"]["steps"]]
    actions_b = [s.get("action", {"error": s.get("error")}) for s in b["agent"]["steps"]]
    divergence = next((i for i, (x, y) in enumerate(zip(actions_a, actions_b)) if x != y),
                      min(len(actions_a), len(actions_b)))
    ca = a["agent"]["steps"][0]["context"]; cb = b["agent"]["steps"][0]["context"]
    success_a, success_b = a["verification"]["task_success"], b["verification"]["task_success"]
    decision_only = before["identity"]["decision_only"]
    if decision_only:
        success_a, success_b = a["decision_correct"], b["decision_correct"]
    return {"task_hash": a["spec_hash"], "cache_refs": refs, "identities": [before["identity"], after["identity"]],
            "evaluation_kind": "first_decision" if decision_only else "full_system_eoc",
            "runtime": [a["agent"]["protocol"], b["agent"]["protocol"]],
            "model_settings_hash": fingerprint(a["agent"]["model_settings"]),
            "first_context_changed_fields": sorted(k for k in ca.keys() | cb.keys() if ca.get(k) != cb.get(k)),
            "first_action_divergence": None if actions_a == actions_b else divergence,
            "common_event_prefix": prefix,
            "event_alignment": SequenceMatcher(a=sa, b=sb, autojunk=False).get_opcodes(),
            "events_before": ea, "events_proposal": eb,
            "before_success": success_a, "proposal_success": success_b,
            "change": "regression" if success_a and not success_b else "improvement" if success_b and not success_a else "unchanged",
            "normal": a["truth_executable"], "diagnosis": None if decision_only else diagnose(b)}


def build(root):
    packet = read(root / "protocol.json"); protocol = packet["protocol"]
    if fingerprint(protocol) != packet["protocol_hash"]:
        raise ValueError("protocol hash mismatch")
    config = protocol["config"]["model_layer"]
    n = config["model_validation"] + config["model_stable_validation"]
    dn = config["model_validation"]
    evidence = {}
    def cached(ref):
        path = root / "model-layer/cache" / (ref + ".json")
        c = read(path)
        if fingerprint(c["identity"]) != ref or fingerprint(c["result"]) != c["result_hash"]:
            raise ValueError("cache integrity failed")
        evidence[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return c
    proposals = []
    for path in sorted((root / "model-layer").glob("**/activation.json")):
        activation = read(path)
        if activation["before_patch"] == activation["proposal_patch"]:
            continue
        refs = activation["validation_refs"]
        if len(refs) != 2 * n + 2 * dn:
            raise ValueError("validation matrix incomplete")
        evidence[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        full = [pair(cached(refs[i]), cached(refs[n + i]), [refs[i], refs[n + i]]) for i in range(n)]
        decision = [pair(cached(refs[2*n+i]), cached(refs[2*n+dn+i]), [refs[2*n+i], refs[2*n+dn+i]]) for i in range(dn)]
        proposals.append({"activation": str(path.relative_to(root)), "agent_admitted": activation["agent_admitted"],
                          "full_system_pairs": full, "decision_pairs": decision,
                          "decision_validation": {"before_correct": sum(p["before_success"] for p in decision),
                                                  "proposal_correct": sum(p["proposal_success"] for p in decision), "n": dn}})
    pairs = [p for proposal in proposals for p in proposal["full_system_pairs"]]
    regressions = [p for p in pairs if p["change"] == "regression"]
    return {"schema": "execution-attribution-v1", "scope": "private offline validation diagnosis; not heldout or causal repair evidence",
            "protocol_hash": packet["protocol_hash"], "input_hashes": evidence,
            "summary": {"proposals": len(proposals), "full_system_pairs": len(pairs),
                        "decision_pairs": sum(len(p["decision_pairs"]) for p in proposals),
                        "changes": dict(Counter(p["change"] for p in pairs)),
                        "regression_primary_causes": dict(Counter(p["diagnosis"]["primary"] for p in regressions))},
            "proposals": proposals}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("results/active-evolution/v1/formal-v1"))
    parser.add_argument("--output", type=Path, default=Path("results/active-evolution/v1.1/attribution-v1"))
    args = parser.parse_args()
    if args.root.resolve() == args.output.resolve() or args.root.resolve() in args.output.resolve().parents:
        raise ValueError("output must be outside frozen input")
    report = build(args.root)
    args.output.mkdir(parents=True, exist_ok=True)
    report["attributor_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (args.output / "proposal_regression_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    lines = ["# P9 proposal validation attribution", "", "Offline diagnosis only; no new model inference or holdout claims.", "", json.dumps(report["summary"], ensure_ascii=False), "",
             "| Proposal | Pair | Primary cause | Evidence cache |", "|---|---:|---|---|"]
    for proposal in report["proposals"]:
        for i, p in enumerate(proposal["full_system_pairs"]):
            if p["change"] == "regression":
                lines.append(f"| {proposal['activation']} | {i} | {p['diagnosis']['primary']} | {p['cache_refs'][1]} |")
    (args.output / "REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
