"""Generate a three-round P5 protocol draft after audited A/B/C cost smoke.

This does not claim a formal freeze, execute held-out tasks or claim three
completed rounds. Fresh fixture declarations are private controller data.
"""
import argparse
import json
import math
from pathlib import Path

from scripts.run_skill_evolution_reuse import audit
from scripts.continue_skill_evolution_selection import publish
from scripts.run_skill_evolution import ROOT, digest_file
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.agent_evidence import read
from skillforge.skill_evolution.workflows import GOALS, make_case


def build_draft(registration, report, *, seed=2026110100):
    if report["status"] != "complete" or report["protocol_hash"] != registration["protocol_hash"]:
        raise ValueError("complete matched cost smoke required before drafting research budget")
    rounds, tasks, all_keys = [], [], set()
    def case(name,offset,split):
        value = make_case(name,seed+offset,split)
        keys = {value.task_id,value.source_group,value.parameters["order_id"],value.authenticated_customer_id}
        if all_keys & keys: raise ValueError("round/holdout sources or entities overlap")
        all_keys.update(keys); tasks.append(value)
        return value.model_dump()
    for index in range(3):
        start = index*1000
        learn = [case(name,start+10*i+j,"train") for i,name in enumerate(GOALS) for j in range(3)]
        agent = [{"case":case(name,start+100+10*i+j,"validation"),"stable":j==3}
                 for i,name in enumerate(GOALS) for j in range(4)]
        program = {}
        # Only predeclared task/probe semantics, no program template.
        for i,name in enumerate(GOALS):
            program[name] = []
            for j,category in enumerate(("positive","positive","boundary","boundary","negative","negative","fault","fault")):
                value = case(name,start+200+10*i+j,"validation")
                probe = {"case":value,"category":category,"stable":j==1}
                if category == "boundary": value["fixture"].update(risk="HIGH",shipment="SHIPPED",order="CANCELLED")
                if j==4: probe.update(authenticated_customer_id="unauthorized-probe-owner",expected_error="permission_denied")
                if j==5: probe.update(parameters={"order_id":"unavailable-probe-order"},expected_error="not_found")
                if j==6: probe.update(faults={"get_shipment":["timeout"]},expected_error="timeout")
                if j==7: probe.update(faults={"get_order":["response_lost"]},expected_error="timeout")
                program[name].append(probe)
        rounds.append({"round":index+1,"learn_cases":learn,"program_validation_probes":program,
            "agent_validation_cases":agent,"max_candidates":1,"max_dev_revisions_per_parent":2,
            "no_candidate_path":"record audited learn/screen/compile; validation SKIPPED_NO_CANDIDATE; retain exact parent snapshot",
            "candidate_path":"independent program validation then real B/C paired Agent admission; retain parent on rejection/inconclusive",
            "validation_feedback_to_optimizer":False})
    tests = []
    for category_index,category in enumerate(("instance","paraphrase","authorized_boundary")):
        for i,name in enumerate(GOALS):
            for j in range(3):
                value = case(name,4000+category_index*100+10*i+j,"test")
                if category == "paraphrase":
                    value["request"] = (f"Please retrieve facts about order {value['parameters']['order_id']}. "
                        + ("I need its order status and shipping status." if name=="shipment_summary" else
                           "I need its order status, shipping status and every line item for the investigation.")
                        + " Read only; leave all records as they are. Reference tag: harmless-note.")
                if category == "authorized_boundary": value["fixture"].update(risk="HIGH",shipment="DELIVERED",order="CANCELLED")
                tests.append({"case":value,"stratum":category})
    learn_runs = sum(len(item["learn_cases"]) for item in rounds)
    validation_runs = 2*sum(len(item["agent_validation_cases"]) for item in rounds)
    test_runs = 3*len(tests)
    max_runs = learn_runs+validation_runs+test_runs
    observed_tokens = max(item["tokens"]/item["n"] for item in report["methods"].values() if item["n"])
    model_seconds = report["wall_seconds"]/report["completed_arms"]
    body = {"schema":"p5-reuse-three-round-draft-v1","frozen":False,"registered_for_execution":False,
        "rounds":rounds,"final_test_cases":tests,"test_timing":"once after all three decisions and implementation are frozen",
        "methods":{"A":"PrimitiveOnly, empty catalog, same backend","B":"StaticLibrary, immutable baseline",
                   "C":"ExperienceEvolution, only independently admitted updates"},
        "main_comparison":"C-B","secondary_comparison":"B-A","statistical_unit":"source_group, never within-group tasks or method arms",
        "agent_gate":{"min_primary_groups":6,"stable_groups":2,"max_case_regressions":0,"max_candidate_violations":0,
                      "metric":"model_calls","min_group_gain":1,"alpha":0.05,"cost_gain_requires_joint_eoc":True},
        "no_history":{"kind":"structural invariant in all arms","cross_task_raw_trajectory_memory":False,
                      "current_task_history_retained":True,"separate_ablation_effect":"NOT_IDENTIFIABLE; C already has no raw cross-task history",
                      "memory_only":"OPTIONAL_NOT_IMPLEMENTED"},
        "generalization":{"instance":"declared","paraphrase":"declared","authorized_read_boundary":"declared",
            "negative_authentication_agent_eoc":"UNSUPPORTED by completed-only readonly WorkflowGoal; CPU program denial probes are separate",
            "structural_compositional":"UNSUPPORTED; only the two previously declared straight readonly goals"},
        "cost_estimate":{"learn_model_runs":learn_runs,"conditional_candidate_validation_model_runs":validation_runs,
            "final_test_model_runs":test_runs,"max_model_runs":max_runs,"observed_worst_method_mean_tokens":observed_tokens,
            "observed_wall_seconds_per_arm_including_loading":model_seconds,
            "planning_tokens_with_2x_margin":math.ceil(max_runs*observed_tokens*2),
            "planning_wall_seconds_with_2x_margin":math.ceil(max_runs*model_seconds*2),
            "hard_sum_of_per_arm_token_caps":max_runs*registration["config"]["limits"]["max_tokens"],
            "gpu_hours":"UNMEASURED; wall estimates are not measured GPU hours",
            "prior_shared_tokens":report["shared_total_charged_tokens"],"prior_shared_wall_seconds":report["shared_total_wall_seconds"],
            "new_research_ceiling":"NOT_REGISTERED; preserve development ledger and register a separate cumulative research phase before execution"},
        "release_gates":["formal candidate path and Agent admission/isolated activation controller acceptance",
                         "same frozen model/runtime/retrieval/decoding for all rounds and arms",
                         "complete research budget and source/entity ownership ledger registration",
                         "explicit unsupported strata and No-History estimand scope"],
        "completed_real_rounds":0,"program_admitted":False,"agent_admitted":False,"isolated_activated":False,"deployed":False,
        "scope":"private three-round data/budget draft only; no formal freeze, no new model calls, no research claim"}
    return {**body,"hash":fingerprint(body)}


def plan(smoke, output):
    smoke,output = Path(smoke).resolve(),Path(output).resolve()
    receipt = audit(smoke)
    if not receipt["run_completed"]: raise ValueError("cost smoke incomplete; cannot draft research protocol")
    draft = build_draft(read(smoke / "registration.json"),read(smoke / "report.json"))
    output.mkdir(parents=True,exist_ok=False)
    publish(output / "draft.json",draft)
    publish(output / "binding.json",{"smoke_run":smoke.relative_to(ROOT).as_posix(),"audit":receipt,
        "draft_hash":draft["hash"],"generator_sha256":digest_file(__file__),"frozen":False,"new_model_calls":0,"new_tokens":0})
    shutil_source = output / "source-plan_skill_evolution_reuse.py"
    shutil_source.write_bytes(Path(__file__).read_bytes())
    return {"draft_hash":draft["hash"],"frozen":False,"rounds":len(draft["rounds"]),"max_model_runs":draft["cost_estimate"]["max_model_runs"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--smoke",required=True); parser.add_argument("--output",required=True)
    args = parser.parse_args(); print(json.dumps(plan(args.smoke,args.output),ensure_ascii=False))
