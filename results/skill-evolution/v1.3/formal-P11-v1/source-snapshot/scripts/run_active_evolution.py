"""Engineering vertical slice. Formal benchmark is intentionally not unlocked."""
import argparse
import itertools
import json
from pathlib import Path

from scripts.prepare_active_evolution import file_hash
from skillforge.evolution import EvolutionController
from skillforge.evolution_evidence import EvidenceBoundary
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import Candidate, Hypothesis, fingerprint
from skillforge.hypothesis import generate_hypotheses
from skillforge.sandbox_probe import run_probe


def make_spec(index, split, risk, shipment):
    uid=fingerprint(["engineering-vertical-slice",split,index,risk,shipment])[:20]
    return {"task_id":uid,"split":split,"family":"refund","policy_epoch":"engineering-W1",
        "template":f"engineering-{split}-refund-template", "request":f"{split}: refund order {uid}",
        "fixture":{"order_id":"O"+uid,"customer_id":"C"+uid,"risk":risk,"shipment":shipment},
        "parameters":{"order_id":"O"+uid,"amount":100}}


def public_candidate(spec):
    # These are declared, experimentally set factors, not hidden database reads.
    return Candidate(candidate_id=spec["task_id"],observations={"customer.risk_level":spec["fixture"]["risk"],
        "shipment.status":spec["fixture"]["shipment"]},baseline_prediction=spec["fixture"]["risk"]!="HIGH",cost=1,mutation_probability=1)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",default="configs/active-evolution-v1.json")
    parser.add_argument("--engineering",action="store_true")
    parser.add_argument("--output",default="results/active-evolution/v1/development/vertical-slice-v1")
    parser.add_argument("--method",choices=("active","random"),default="active")
    args=parser.parse_args()
    if not args.engineering:
        parser.error("Formal execution locked: dataset isolation, model runtime and Cost Gate not yet signed off. Use --engineering for the development slice.")
    root=Path(args.output)
    config=json.loads(Path(args.config).read_text(encoding="utf-8"))
    seed=[make_spec(0,"seed","LOW","NOT_STARTED"),make_spec(1,"seed","LOW","PROCESSING")]
    pool=[make_spec(i,"explore",r,s) for i,(r,s) in enumerate(itertools.product(("LOW","MEDIUM","HIGH"),("NOT_STARTED","PROCESSING","SHIPPED","DELIVERED")))]
    validation=[make_spec(i,"validation",r,s) for i,(r,s) in enumerate(itertools.product(("LOW","MEDIUM","HIGH"),("NOT_STARTED","PROCESSING","SHIPPED","DELIVERED")))]
    stable=[make_spec(i,"stable_validation",r,s) for i,(r,s) in enumerate(itertools.product(("LOW","MEDIUM","HIGH"),("NOT_STARTED","SHIPPED")))]
    manifest={"policy_epoch":"engineering-W1","members":{s["task_id"]:{"hash":fingerprint(s),"split":s["split"]} for s in seed+pool+validation+stable}}
    sources=list(Path("skillforge").glob("*evolution*.py"))+[Path("skillforge")/name for name in ("belief.py","gap_detection.py","hypothesis.py","sandbox_probe.py","active_learning.py")]+[Path("scripts/run_active_evolution.py"),Path("scripts/active_evolution_worlds.py")]
    identity={"policy_epoch":"engineering-W1","parent_hash":fingerprint("engineering-public-old-refund-boundary"),
        "engineering_only":True,"manifest_hash":fingerprint(manifest),"config_hash":fingerprint(config),
        "code_hash":fingerprint({str(p):file_hash(p) for p in sorted(sources)})}
    immutable_json(root/"run-identity.json",identity)
    immutable_json(root/"manifest.json",manifest)
    boundary=EvidenceBoundary(manifest)
    def probe_record(spec):
        target=root/"private-probes"/(spec["task_id"]+".json")
        if target.exists():
            envelope=json.loads(target.read_text(encoding="utf-8"))
            if envelope["spec_hash"]!=fingerprint(spec) or envelope["result_hash"]!=fingerprint(envelope["result"]):
                raise ValueError("probe evidence corrupted")
            return envelope["result"]
        result=run_probe(spec,"W1")
        immutable_json(target,{"spec_hash":fingerprint(spec),"result_hash":fingerprint(result),"result":result})
        return result
    seed_evidence=[boundary.export(probe_record(s),s,public_candidate(s).baseline_prediction) for s in seed]
    by_id={s["task_id"]:s for s in pool}
    def probe(key):
        spec=by_id[key]
        return boundary.export(probe_record(spec),spec,public_candidate(spec).baseline_prediction)
    def validate(candidate):
        # Evaluator-only: all labels below come from actual guarded procedure runs.
        hypothesis=Hypothesis.model_validate(candidate["hypothesis"])
        report={"candidate_hash":fingerprint(candidate),"split":"validation+stable_validation",
            "positive_cases":0,"negative_cases":0,"actual_violations":0,"false_allow":0,"false_block":0,
            "baseline_false_block":0,"normal_failures":0,"baseline_normal_failures":0,"stable_cases":len(stable),"stable_regressions":0}
        cases=[]
        for spec in validation+stable:
            result=probe_record(spec)
            visible=public_candidate(spec)
            truth=result["procedure_success"]
            if not truth and not any(a.get("error")=="business_rule_rejected" for a in result["tool_audit"]):
                raise RuntimeError("validation probe inconclusive")
            predicted=hypothesis.predict(visible.observations,visible.baseline_prediction)
            if predicted is None:
                raise ValueError("candidate UNKNOWN on validation support")
            report["actual_violations"]+=result["actual_violations"]
            if spec["split"]=="validation":
                report["positive_cases" if truth else "negative_cases"]+=1
                report["false_allow"]+=int(predicted and not truth)
                report["false_block"]+=int(not predicted and truth)
                report["baseline_false_block"]+=int(not visible.baseline_prediction and truth)
                report["normal_failures"]+=int(truth and not predicted)
                report["baseline_normal_failures"]+=int(truth and not visible.baseline_prediction)
            else:
                report["stable_regressions"]+=int(visible.baseline_prediction==truth and predicted!=truth)
            cases.append({"task_id":spec["task_id"],"split":spec["split"],"truth":truth,"predicted":predicted,"probe_hash":fingerprint(result)})
        report["cases"]=cases
        return report
    hs=generate_hypotheses(["customer.risk_level","shipment.status"])
    controller=EvolutionController(root/"controller",identity,hs,seed_evidence,[public_candidate(s) for s in pool],probe,validate,root/"registry")
    report=controller.run(method=args.method,max_queries=config["learning"]["max_queries"])
    # Load published version and execute fresh instances as a boundary-level check.
    if report["status"]=="VERIFIED":
        entry=controller.registry.load(report["registry_version"])
        h=Hypothesis.model_validate(entry["candidate"]["hypothesis"])
        followup=[]
        for i,shipment in enumerate(("PROCESSING","NOT_STARTED")):
            spec=make_spec(i,"post_publish","MEDIUM",shipment)
            visible=public_candidate(spec)
            allowed=h.predict(visible.observations,visible.baseline_prediction)
            executed=probe_record(spec) if allowed else None
            followup.append({"task_id":spec["task_id"],"registry_version":entry["version"],"allowed":allowed,
                "procedure_success":executed["procedure_success"] if executed else None,"mutation_attempted":bool(executed)})
        immutable_json(root/"post-publish.json",followup)
    immutable_json(root/"summary.json",report)
    print(json.dumps(report,ensure_ascii=False))


if __name__=="__main__":
    main()
