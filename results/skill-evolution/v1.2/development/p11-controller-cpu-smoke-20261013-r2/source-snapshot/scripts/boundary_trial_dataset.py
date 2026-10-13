"""Private split ownership and public-factor design, independent of answers."""
import itertools
import random

from scripts.active_evolution_dataset import _spec, coverage_core
from skillforge.evolution_schemas import fingerprint


def cpu_specs(world, seed, stage, split, count):
    family_world = "W6" if world == "W6" else "W1"
    family = "modify_address" if world == "W6" else "refund"
    core = coverage_core(family)
    # Full three-factor cube is declared for ALL refund worlds. It is not chosen
    # from the hidden structural policy and cannot reveal its changed predicate.
    if family == "refund":
        for risk, ship, pay in itertools.product(("LOW", "MEDIUM"), ("NOT_STARTED", "PROCESSING"), ("CAPTURED", "PARTIALLY_REFUNDED")):
            value = (risk, "CONFIRMED", ship, pay, 10000, 1000, True)
            if value not in core: core.append(value)
    if split.startswith("stable"):
        # Predeclared stable service strata, never selected after seeing a
        # candidate. Include positives and immutable negatives.
        core = [("LOW", "CONFIRMED", "NOT_STARTED", "CAPTURED", 10000, 1000, True),
                ("HIGH", "CONFIRMED", "NOT_STARTED", "CAPTURED", 10000, 1000, True),
                ("LOW", "CONFIRMED", "NOT_STARTED", "FAILED", 10000, 1000, True),
                ("MEDIUM", "CONFIRMED", "NOT_STARTED", "PARTIALLY_REFUNDED", 10000, 1000, True)]
    rows = []
    rng = random.Random(fingerprint([seed, stage, split]))
    for i in range(count):
        factors = core[i] if i < len(core) else rng.choice(core)
        # Independent entities/IDs across world, stage and all source splits.
        local_seed = int(fingerprint(["continuous-study", world, seed, stage, split])[:12], 16)
        row = _spec(family_world, local_seed, split, i, factors)
        row["policy_epoch"] = fingerprint(["opaque-public-segment", seed, stage])
        rows.append(row)
    return rows


def daily_spec(world, seed, stage, index):
    family_world = "W6" if world == "W6" else "W1"
    factors = ("LOW" if world == "W6" else "MEDIUM", "CONFIRMED", "PROCESSING",
               "CAPTURED" if world == "W6" else "PARTIALLY_REFUNDED", 10000, 1000, True)
    local_seed = int(fingerprint(["daily-stream", world, seed, stage])[:12], 16)
    row = _spec(family_world, local_seed, "seed", index, factors)
    row["policy_epoch"] = "public-stream"
    return row
