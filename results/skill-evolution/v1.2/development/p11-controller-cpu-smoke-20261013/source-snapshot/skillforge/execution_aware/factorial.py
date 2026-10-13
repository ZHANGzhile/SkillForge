"""Paired world-seed effects. Tasks are never resampled as independent units."""
import math
import random


ARMS = ("old_old", "old_proposal", "new_old", "new_proposal")


def effects(arms):
    if set(arms) != set(ARMS) or any(not math.isfinite(v) or not 0 <= v <= 1 for v in arms.values()):
        raise ValueError("complete four-arm EOC rates required")
    return {"runtime_effect": arms["new_old"]-arms["old_old"],
            "bundle_effect_under_new_runtime": arms["new_proposal"]-arms["new_old"],
            "interaction": (arms["new_proposal"]-arms["new_old"])-(arms["old_proposal"]-arms["old_old"])}


def paired_factorial(rows, *, seed=110901, replicates=5000):
    if not rows or replicates < 100:
        raise ValueError("nonempty cohort and sufficient bootstrap replicates required")
    keys = [(r["world"], r["seed"]) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("world-seed is the independent unit; aggregate nested tasks/repetitions first")
    if any(not r.get("complete", False) for r in rows):
        raise ValueError("incomplete units cannot silently disappear from formal inference")
    modes = {r["bundle_scope"] for r in rows}
    if len(modes) != 1 or not modes <= {"candidate", "effective"}:
        raise ValueError("candidate and effective-bundle estimands must be separate")
    groups = {}
    for row in rows:
        groups.setdefault(row["world"], []).append(effects(row["arms"]))
    names = tuple(effects(rows[0]["arms"]))
    def average(grouped, key):
        # World weights fixed equal; then paired seeds weighted equally in world.
        return sum(sum(r[key] for r in values)/len(values) for values in grouped.values())/len(grouped)
    point = {key: average(groups, key) for key in names}
    rng = random.Random(seed); draws = {key: [] for key in names}
    for _ in range(replicates):
        sampled = {world: [rng.choice(values) for _ in values] for world, values in groups.items()}
        for key in names:
            draws[key].append(average(sampled, key))
    ci = {}
    for key, values in draws.items():
        values.sort()
        ci[key] = [values[int(.025*replicates)], values[min(replicates-1, int(.975*replicates))]]
    return {"world_seed_units": len(rows), "seeds_per_world": {w: len(v) for w, v in groups.items()},
            "bundle_scope": next(iter(modes)), "point_estimates": point, "paired_bootstrap_95": ci,
            "bootstrap": {"seed": seed, "replicates": replicates, "unit": "world-seed", "stratified_by": "world"},
            "scope": "finite declared worlds; percentile intervals with few seeds have limited resolution; no task-level pseudoreplication"}
