"""Read-only corpus diagnostics; never changes training or evaluation inputs."""
import argparse
from collections import Counter
import json
from pathlib import Path

from skillforge.prompts import PROMPTS
from skillforge.training_data import load_training_data


def diagnose(config_path, output):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    rows, pairs, audit = load_training_data(config["dataset"], config["bundle"], config["real_data"],
        config["supervision"], config["baseline"])
    actions, by_family, by_candidates, by_origin = Counter(), {}, {}, {}
    prompt_mismatches, history_counts = [], Counter()
    for row in rows:
        context = json.loads(row["messages"][1]["content"])
        target = json.loads(row["messages"][2]["content"])
        action = target["type"] + (":" + str(target.get("name")) if target["type"] in {"tool", "skill"} else "")
        actions[action] += 1
        family = context["family"]
        by_family.setdefault(family, Counter())[action] += 1
        availability = "skill_list_nonempty" if context.get("executable_skills") else "skill_list_empty"
        by_candidates.setdefault(availability, Counter())[action] += 1
        for origin in set(row["origins"]):
            by_origin.setdefault(origin, Counter())[action] += 1
        history_counts[str(len(context.get("history", [])))] += 1
        if row["messages"][0]["content"] != PROMPTS["v2"]:
            prompt_mismatches.append(row["example_id"])
    report = {"corpus_audit": audit, "actions": actions, "by_family": by_family,
        "by_candidate_availability": by_candidates, "by_origin": by_origin,
        "history_length": history_counts, "system_prompt_v2_mismatches": prompt_mismatches,
        "dpo_chosen": Counter(json.loads(p["chosen"])["type"] for p in pairs),
        "dpo_rejected": Counter(json.loads(p["rejected"])["type"] for p in pairs),
        "scope": "Descriptive counts of audited training data; correlations do not establish the cause of model failures. Origin counts may overlap after deduplication."}
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/training.cudnn.json")
    parser.add_argument("--output", default="results/training-diagnostics/main-v2/actions.json")
    args = parser.parse_args()
    print(json.dumps(diagnose(args.config, args.output), ensure_ascii=True, indent=2))
