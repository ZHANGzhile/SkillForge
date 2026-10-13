"""Train-only, executed recovery curricula with explicitly labelled teachers.

Injected read actions create histories, but are never supervised targets. No
validation/test task or model-generated evaluation trace enters this corpus.
The frozen runtime, policy, skills and original main-v2 results are unchanged.
"""
import argparse
from collections import Counter
import copy
import json
from pathlib import Path

from skillforge.dataset import load_dataset, task_hash
from skillforge.environment import Environment
from skillforge.experiment import load_bundle, read_sources
from skillforge.model import ScriptedPolicy
from skillforge.provenance import audit_sources
from skillforge.runtime import Runtime
from skillforge.schemas import Action
from skillforge.supervision import messages, write_jsonl
from skillforge.training_data import file_hash, load_training_data


READ_PREFIXES = [[], ["get_order"], ["get_order", "get_order"],
    ["get_order", "get_payment", "get_order", "get_shipment"],
    ["get_order", "get_payment", "get_shipment", "get_customer", "get_order"]]
MUTATIONS = {"update_shipping_address", "cancel_order", "issue_refund"}


class RecoveryTeacher(ScriptedPolicy):
    def __init__(self, prefix, primitive=False, distract_after_write=False):
        self.prefix = list(prefix)
        self.primitive = primitive
        self.distract_after_write = distract_after_write
        self.target_steps = []
        self.injected_steps = []
        self.calls = 0
        self.post_write_reads = None

    def decide(self, context):
        step = self.calls
        self.calls += 1
        history = context["history"]
        unsafe_to_inject = (any(e.get("error") or e.get("retry_exhausted") for e in context.get("gate_observations", []))
            or (history and (history[-1].get("error") or history[-1].get("result", {}).get("error"))))
        if unsafe_to_inject:
            self.prefix.clear()
            self.post_write_reads = []
        if self.prefix:
            name = self.prefix.pop(0)
        else:
            written = any(s.get("action", {}).get("name") in MUTATIONS and s.get("result", {}).get("ok") for s in history)
            if self.distract_after_write and written and self.post_write_reads is None:
                self.post_write_reads = ["get_order", "get_shipment"]
            name = self.post_write_reads.pop(0) if self.post_write_reads else None
        if name:
            self.injected_steps.append(step)
            return Action(type="tool", name=name, arguments={"order_id": context["parameters"]["order_id"]})
        self.target_steps.append(step)
        # First learn recovery using the original teacher's verified rules.
        action = super().decide(context)
        already_executed = any((s.get("action", {}).get("type") == "skill" and s.get("result", {}).get("success"))
            or (s.get("action", {}).get("name") in MUTATIONS and s.get("result", {}).get("ok")) for s in history)
        if not unsafe_to_inject and not already_executed and context["executable_skills"] and not self.primitive:
            skill = next((s for s in context["executable_skills"] if s["family"] == context["family"]), None)
            if skill:
                action = Action(type="skill", name=skill["skill_id"], arguments=context["parameters"])
        if self.primitive and action.type == "skill":
            name = {"modify_address": "update_shipping_address", "cancel_order": "cancel_order", "refund": "issue_refund"}[context["family"]]
            action = Action(type="tool", name=name, arguments=context["parameters"])
        return action


def prepare(config_path, output):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    # Audit the immutable parent before extending it.
    _, _, parent_audit = load_training_data(config["dataset"], config["bundle"], config["real_data"], config["supervision"], config["baseline"])
    manifest, tasks = load_dataset(config["dataset"])
    bundle, skills = load_bundle(config["bundle"], manifest["dataset_hash"])
    root, parent = Path(output), Path(config["supervision"])
    root.mkdir(parents=True, exist_ok=False)
    records = read_sources(parent / "runtime.jsonl")
    rows = read_sources(parent / "sft.jsonl")
    inherited_rows = len(rows)
    failures, curriculum = [], []
    for task in [t for t in tasks if t.split == "train"]:
        for prefix_index, prefix in enumerate(READ_PREFIXES):
            for primitive in (False, True):
                for distract in (False, True) if primitive else (False,):
                    teacher = RecoveryTeacher(prefix, primitive, distract)
                    env = Environment(fixture=task.fixture, faults=task.fixture.get("faults"))
                    try:
                        record = Runtime(teacher, skills=skills).run(task, env)
                    finally:
                        env.close()
                    record["supervision_origin"] = "deterministic_contract_teacher"
                    record["recovery_curriculum"] = {"prefix_index": prefix_index, "primitive": primitive,
                        "distract_after_write": distract, "injected_steps": teacher.injected_steps,
                        "eligible_target_steps": teacher.target_steps}
                    records.append(record)
                    if not record["verification"]["task_success"] or record["verification"]["actual_policy_violation"]:
                        failures.append({"trajectory_id": record["trajectory_id"], "task_id": task.task_id,
                            "curriculum": record["recovery_curriculum"], "verification": record["verification"]})
                        continue
                    selected = 0
                    for step in record["steps"]:
                        action = step.get("action")
                        if step["step_id"] not in teacher.target_steps or not action or step.get("error") or step.get("result", {}).get("success") is False:
                            continue
                        rows.append({"messages": messages(step["context"], action), "split": "train",
                            "action_type": action["type"], "source_trajectory_id": record["trajectory_id"],
                            "source_step_id": step["step_id"], "task_id": task.task_id, "task_hash": task_hash(task),
                            "supervision_origin": "deterministic_contract_teacher", "protocol": "free_action_runtime",
                            "curriculum": "recovery-v1", "llm_calls": 0})
                        selected += 1
                    curriculum.append({"trajectory_id": record["trajectory_id"], "task_id": task.task_id, "targets": selected})
    audit_sources(records, tasks, allow_engineering=True)
    report = copy.deepcopy(json.loads((parent / "manifest.json").read_text(encoding="utf-8")))
    for name in ("counterfactuals.jsonl", "dpo.jsonl"):
        (root / name).write_bytes((parent / name).read_bytes())
    report.update(runtime_trajectories=len(records), runtime_passed=sum(r["verification"]["task_success"] for r in records),
        sft_examples=len(rows), sft_action_counts=dict(Counter(r["action_type"] for r in rows)),
        parent_manifest_sha256=file_hash(parent / "manifest.json"), parent_corpus_hash=parent_audit["corpus_hash"],
        recovery_curriculum={"version": "recovery-v1", "prefixes": READ_PREFIXES, "inherited_sft_rows": inherited_rows,
            "new_targets": len(rows)-inherited_rows, "verified_trajectories": len(curriculum), "failed_trajectories": len(failures),
            "injected_actions_are_targets": False, "task_split": "train", "builder_sha256": file_hash(__file__)},
        scope="Explicit deterministic train-only recovery supervision; injected reads excluded from SFT targets; original DPO pairs unchanged")
    report["files"] = {"runtime.jsonl": write_jsonl(root / "runtime.jsonl", records), "sft.jsonl": write_jsonl(root / "sft.jsonl", rows),
        "dpo.jsonl": file_hash(root / "dpo.jsonl"), "counterfactuals.jsonl": file_hash(root / "counterfactuals.jsonl"),
        "curriculum.jsonl": write_jsonl(root / "curriculum.jsonl", curriculum), "failures.jsonl": write_jsonl(root / "failures.jsonl", failures)}
    (root / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _, _, final_audit = load_training_data(config["dataset"], config["bundle"], config["real_data"], root, config["baseline"])
    return {"output": str(root), "audit": final_audit, "curriculum": report["recovery_curriculum"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/training.cudnn.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.config, args.output), ensure_ascii=True, indent=2))
