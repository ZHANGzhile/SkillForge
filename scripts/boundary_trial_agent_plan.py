"""Private predeclared real Agent task strata, with no outcome-based selection."""
from scripts.boundary_trial_dataset import daily_spec, cpu_specs
from scripts.boundary_stage2_evaluator import expected_task
from skillforge.evolution_schemas import fingerprint


def agent_stage(world, seed, stage):
    actual_world = world if stage < 2 else "H0"
    values = []
    for i in range(4):
        spec = daily_spec(world, seed, stage, i + 100)
        values.append({"partition": "daily", "stable": False, "spec": spec,
                       "faults": {"get_customer": ["timeout"]} if i == 3 else {}})
    for i in range(8):
        spec = daily_spec(world, seed, stage, i + 200)
        spec["split"] = "validation"
        if i >= 5:
            spec["fixture"].update(shipment="NOT_STARTED", risk="HIGH" if i == 6 else "LOW")
        if spec["family"] == "refund": spec["parameters"]["amount"] = 1000 + i
        values.append({"partition": "validation", "stable": i >= 6, "spec": spec, "faults": {}})
    for i in range(2):
        spec = daily_spec(world, seed, stage, i + 300)
        spec["split"] = "test"
        if i == 1: spec["fixture"].update(shipment="NOT_STARTED", risk="LOW")
        if spec["family"] == "refund": spec["parameters"]["amount"] = 1200 + i
        values.append({"partition": "test", "stable": i == 1, "spec": spec, "faults": {}})
    for value in values:
        spec = value["spec"]
        value.update(world=actual_world, source_group="continuous-agent-" + spec["task_id"],
            task=expected_task(spec["task_id"], spec["family"], spec["fixture"], spec["parameters"], actual_world,
                split="train" if value["partition"] == "daily" else value["partition"], seed=seed + stage))
    return values
