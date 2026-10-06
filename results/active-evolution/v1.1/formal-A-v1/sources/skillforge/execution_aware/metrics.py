"""Evaluator-side scoring: execution interventions are not learned capability."""


def paired_execution_metrics(before, after):
    if len(before) != len(after) or not before:
        raise ValueError("nonempty complete paired task set required")
    counts = dict(autonomous_eoc=0, runtime_assisted_eoc=0, runtime_intervention_rate=0,
                  rescued_by_runtime=0, regressions=0, forced_readback_count=0, auto_termination_count=0)
    seen = set()
    for old, new in zip(before, after):
        if old["spec_hash"] != new["spec_hash"] or new["spec_hash"] in seen:
            raise ValueError("unpaired or duplicate task")
        seen.add(new["spec_hash"])
        succeeded = new["verification"]["task_success"]
        was_success = old["verification"]["task_success"]
        interventions = new["agent"]["interventions"]
        helped = interventions["runtime_intervention_count"] > 0
        counts["autonomous_eoc"] += succeeded and not helped
        counts["runtime_assisted_eoc"] += succeeded and helped
        counts["runtime_intervention_rate"] += helped
        counts["rescued_by_runtime"] += succeeded and not was_success and helped
        counts["regressions"] += was_success and not succeeded
        for name in ("forced_readback_count", "auto_termination_count"):
            counts[name] += interventions[name]
    return {"n": len(after), "counts": counts,
            "rates": {k: v / len(after) for k, v in counts.items() if not k.endswith("_count")},
            "scope": "paired observed rescue; interventions are system behavior, not model learning"}
