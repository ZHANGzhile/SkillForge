"""Conservative trace compiler for parameterized straight read-only workflows.

Compilation preserves observed order and provenance. It never uses a family
template, synthesizes a missing probe, changes a boundary, or admits a Skill.
"""
from ..evolution_schemas import fingerprint
from ..policies import POLICY_VERSION, READS
from ..schemas import SkillContract, SkillStep
from .workflows import GOALS


VERSION = "readonly-trace-compiler-v1"


def compile_opportunity(opportunity, normalized, *, min_sources=3, min_model_call_saving=1):
    if opportunity["status"] != "OPPORTUNITY":
        return {"status": "NO_USEFUL_CANDIDATE", "reason": "opportunity_not_admitted", "candidate": None}
    if min_sources < 3 or min_model_call_saving < 1:
        raise ValueError("cannot weaken conservative opportunity thresholds")
    by_id = {row["trajectory_id"]: row for row in normalized}
    if len(by_id) != len(normalized) or len(set(opportunity["trajectory_ids"])) != len(opportunity["trajectory_ids"]):
        raise ValueError("duplicate trajectory identity")
    support = [by_id[identity] for identity in opportunity["trajectory_ids"]]
    pattern = opportunity["pattern"]
    if not support or fingerprint(pattern) != opportunity["pattern_id"]:
        raise ValueError("opportunity pattern identity mismatch")
    for row in support:
        if (row["split"] != "train" or not row["usable_success"] or row["normalization_error"] or
                row["pattern"] != pattern or row["pattern_id"] != opportunity["pattern_id"] or
                row["goal_hash"] != pattern["goal_hash"] or
                any(row["verification"][key] for key in ("attempted_policy_violation", "actual_policy_violation",
                                                         "attempted_workflow_violation", "actual_workflow_violation")) or
                not row["verification"]["task_success"]):
            raise ValueError("candidate requires consistent successful learn-only support")
        events = row["events"]
        if [{"tool": event["tool"], "arguments": event["arguments"]} for event in events] != pattern["calls"]:
            raise ValueError("event/pattern mismatch")
        for index, event in enumerate(events):
            if (event["error"] or event["origin"] not in {"model", "skill", "runtime", "gate/hydrate"} or
                    event["source"] != {"trajectory_id": row["trajectory_id"], "audit_index": index}):
                raise ValueError("invalid node source or decision origin")
    sources = sorted({row["source_group"] for row in support})
    saving = sum(row["model_calls"] for row in support) / len(support) - 4
    if (len(sources) < min_sources or sources != opportunity["source_groups"] or saving < min_model_call_saving or
            saving != opportunity["expected_model_call_saving"] or opportunity["expected_skill_decisions"] != 4):
        raise ValueError("opportunity support/utility mismatch")
    nodes = [{**call, "sources": [row["events"][index]["source"] for row in support]}
             for index, call in enumerate(pattern["calls"])]
    if nodes != opportunity["nodes"]:
        raise ValueError("opportunity node provenance mismatch")
    goal = GOALS[support[0]["workflow_id"]]
    if any(row["workflow_id"] != goal.workflow_id for row in support) or goal.identity != pattern["goal_hash"]:
        raise ValueError("public workflow goal mismatch")
    structure = fingerprint({"inputs": pattern["inputs"], "calls": pattern["calls"]})
    duplicate = any(any(item.get("program_structure_hash") == structure for item in row["static_coverage"])
                    for row in support)
    expected_checks = {"novel_program_structure": not duplicate, "independent_sources": True,
                       "valid_generalization_target": True, "expected_incremental_utility": True}
    if opportunity["checks"] != expected_checks or not all(expected_checks.values()):
        raise ValueError("opportunity checks mismatch")
    if opportunity["program_structure_hash"] != structure:
        raise ValueError("program structure identity mismatch")
    covered = any(any(item["covers_goal"] for item in row["static_coverage"]) for row in support)
    if covered != opportunity["static_goal_covered"]:
        raise ValueError("static coverage mismatch")
    if covered:
        return {"status": "POTENTIAL_DUPLICATE", "reason": "existing_goal_coverage_requires_revision_governance", "candidate": None}
    # Bindings beyond public order input and non-dotted result data require a
    # separately implemented DSL extension; never guess instance constants.
    if (pattern["inputs"] != ["order_id"] or not pattern["calls"] or
            any(call["tool"] not in READS - {"validate_address"} or
                call["arguments"] != {"order_id": "$input.order_id"} for call in pattern["calls"])):
        return {"status": "UNSUPPORTED", "reason": "binding_or_tool_outside_readonly_subset", "candidate": None}
    if not set(goal.required_evidence).issubset({call["tool"] for call in pattern["calls"]}):
        raise ValueError("trace is missing public goal evidence")
    if len(nodes) + 1 > 12:
        return {"status": "UNSUPPORTED", "reason": "dsl_node_limit", "candidate": None}
    postconditions = {field: "$input.order_id" for fields in goal.required_evidence.values()
                      for field in fields if field.endswith(".order_id")}
    if not postconditions:
        return {"status": "UNSUPPORTED", "reason": "no_expressible_identity_postcondition", "candidate": None}
    skill = SkillContract(skill_id="trace_" + structure[:16], family=goal.workflow_id, inputs=pattern["inputs"],
        preconditions=[], forbidden_conditions=[],
        procedure=[SkillStep(kind="call", tool=node["tool"], arguments=node["arguments"]) for node in nodes] +
                  [SkillStep(kind="finish")], postconditions=postconditions,
        source_trajectory_ids=[row["trajectory_id"] for row in support], policy_version=POLICY_VERSION, status="CANDIDATE")
    provenance = [{"node_index": index, "kind": "call", "sources": node["sources"],
                   "origins": [row["events"][index]["origin"] for row in support]} for index, node in enumerate(nodes)]
    provenance.append({"node_index": len(nodes), "kind": "finish", "sources":
                       [{"trajectory_id": row["trajectory_id"], "evidence": "independently_verified_completed_outcome"} for row in support]})
    body = {"schema": "trace-compiled-readonly-candidate-v1", "compiler_version": VERSION,
            "skill": skill.model_dump(), "goal_hash": goal.identity, "purpose": goal.public_goal,
            "program_structure_hash": structure, "opportunity_hash": fingerprint(opportunity),
            "source_groups": sources, "raw_trajectory_hashes": {row["trajectory_id"]: row["raw_trajectory_hash"] for row in support},
            "node_provenance": provenance, "postcondition_source": "predeclared public goal identity fields",
            "support_domain": "authorized order reads under fixed policy; straight sequence only",
            "limitations": ["item-list and full factual completeness require independent workflow EOC",
                            "syntactic fingerprint is not a semantic equivalence proof"],
            "expected_model_call_saving": saving, "utility_is_estimate": True,
            "program_admitted": False, "agent_admitted": False, "isolated_activated": False, "deployed": False}
    return {"status": "CANDIDATE", "reason": None, "candidate": {**body, "hash": fingerprint(body)}}


def compile_screen(screen):
    """A no-op is a first-class result, not a request to lower thresholds."""
    results = [{"pattern_id": item["pattern_id"], **compile_opportunity(
        item, screen["normalized"], min_sources=screen["min_sources"],
        min_model_call_saving=screen["min_model_call_saving"])} for item in screen["records"]]
    n = sum(row["candidate"] is not None for row in results)
    return {"schema": "trace-compiler-screen-v1", "compiler_version": VERSION,
            "status": "CANDIDATES_PROPOSED" if n else "NO_USEFUL_CANDIDATE", "n_candidates": n,
            "results": results, "program_admitted": False, "agent_admitted": False,
            "research_claim_passed": None, "isolated_activated": False, "deployed": False}
