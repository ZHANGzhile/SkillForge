"""Public-event selection trace. Opportunity truth belongs to the private auditor."""
from ..evolution_common.artifacts import clone
from ..evolution_schemas import fingerprint


ERRORS = {"NO_SEARCH", "RETRIEVAL_MISS", "NOT_LOADED", "GATE_INAPPLICABLE", "GATE_UNKNOWN",
          "OFFERED_NOT_SELECTED", "BINDING_ERROR", "SKILL_EXECUTION_ERROR",
          "MODEL_TERMINAL_ERROR", "SUCCESSFUL_PRIMITIVE_ALTERNATIVE"}


def refs(values):
    return sorted([{"skill_id": v["skill_id"], "revision": v["revision"]} for v in values],
                  key=lambda r: (r["skill_id"], r["revision"]))


def selection_start(context, catalog, searches, *, initial_loaded=False):
    available = refs([e for e in catalog.entries() if e["contract"]["status"] == "VERIFIED"])
    loaded = context["catalog"]["loaded_skills"]
    retrieved = { (r["skill_id"], r["revision"]): r for event in searches for r in event["results"] }
    return {"schema": "skill-selection-trace-v1", "provenance": "public_runtime_events",
            "model_visible_context_hash": fingerprint(context),
            "available_skill_set_hash": fingerprint(available), "available_verified": available,
            "retrieved": refs(retrieved.values()), "loaded": refs(loaded),
            "gate_status": [{"skill_id": v["skill_id"], "revision": v["revision"], **clone(v["gate"])} for v in loaded],
            "offered_to_model": refs(loaded), "selected_action": None, "executed_skill": None,
            "verification_result": None, "error_labels": [], "primary_cause": None,
            "initial_load_origin": "experimental_public_start" if initial_loaded else None}


def selection_finish(trace, step, receipts):
    action, result = step.get("action") or {}, step.get("result") or {}
    trace["selected_action"] = clone(action)
    trace["model_messages_hash"] = fingerprint(step.get("messages", []))
    labels = []
    error = step.get("error")
    if error in {"skill_not_loaded", "unknown_skill_revision", "skill_revision_conflict", "skill_dependency_not_loaded"}:
        labels.append("NOT_LOADED")
    if error == "skill_input_binding_mismatch":
        labels.append("BINDING_ERROR")
    if action.get("type") == "skill" and "internal_steps" in result:
        trace["executed_skill"] = {"skill_id": result["skill_id"], "revision": result["revision"],
                                   "success": result["success"], "gate_status": result["gate_status"]}
        if result["gate_status"] in {"INAPPLICABLE", "UNKNOWN"}:
            labels.append("GATE_" + result["gate_status"])
        elif not result["success"]:
            labels.append("SKILL_EXECUTION_ERROR")
        trace["verification_result"] = clone(result.get("verification"))
    elif action.get("type") == "skill" and error and not labels:
        labels.append("SKILL_EXECUTION_ERROR")
    trace["new_verification_receipts"] = clone(receipts)
    trace["error_labels"], trace["primary_cause"] = labels, next(iter(labels), None)
    # NO_SEARCH / RETRIEVAL_MISS / terminal truth / legal alternatives need private
    # independent opportunity and task evidence. Never infer them in the Agent.
