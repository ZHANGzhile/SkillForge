"""Evaluator supervisor: private datasets/probes stay outside learner process."""
from contextlib import closing
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading

from scripts.active_evolution_dataset import EvaluationStore, public_candidate
from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_boundary import parent_identity
from skillforge.evolution_evidence import EvidenceBoundary
from skillforge.evolution_registry import EvolutionRegistry, boundary_admission, immutable_json
from skillforge.evolution_schemas import Hypothesis, fingerprint
from skillforge.evolution_validation import counters
from skillforge.hypothesis import generate_hypotheses
from skillforge.sandbox_probe import run_probe

FEATURE_FIELDS = {"customer.risk_level", "order.status", "shipment.status", "payment.status",
                  "request.amount", "payment.remaining_amount"}


def evaluator_identity(store):
    paths = [Path(__file__), Path("scripts/active_evolution_dataset.py"), Path("scripts/active_evolution_worlds.py"),
             Path("scripts/active_evolution_model_design.py"), Path("skillforge/evolution_execution.py"), Path("skillforge/skills.py"),
             Path("skillforge/sandbox_probe.py"), Path("skillforge/evolution_validation.py"), Path("skillforge/environment.py")]
    return {"dataset_hash": fingerprint(store.manifest),
        "validator_code_hash": fingerprint({p.name:file_hash(p) for p in paths}),
        "require_adaptation_opportunity": True,
        "validation_members": {key:value for key,value in store.manifest["members"].items()
                               if value["split"] in {"validation","stable_validation"}}}


class Evaluator:
    def __init__(self, dataset, output):
        self.store = EvaluationStore(dataset)
        self.output = Path(output)
        self.contract = json.loads((Path(dataset)/"parent-skill.json").read_text(encoding="utf-8"))
        if parent_identity(self.contract) != self.store.manifest["parent"]:
            raise ValueError("frozen parent contract differs")
        self.boundary = EvidenceBoundary(self.store.manifest)
        self.admission_identity = evaluator_identity(self.store)

    def probe_record(self, spec):
        target = self.output/"private-probes"/(spec["task_id"]+".json")
        identity = {"task_hash":fingerprint(spec), "validator_code_hash":self.admission_identity["validator_code_hash"],
                    "parent_hash":self.store.manifest["parent"]["contract_hash"]}
        if target.exists():
            saved = json.loads(target.read_text(encoding="utf-8"))
            if saved["identity"] != identity or saved["result_hash"] != fingerprint(saved["result"]):
                raise ValueError("private probe identity/content changed")
            return saved["result"]
        result = run_probe(spec, self.store.manifest["world"],contract=self.contract)
        immutable_json(target, {"identity":identity,"result":result,"result_hash":fingerprint(result)})
        return result

    def evidence(self, spec):
        candidate = public_candidate(spec,self.contract)
        return self.boundary.export(self.probe_record(spec),spec,candidate.baseline_prediction,candidate.guard_prediction)

    def measure(self, hypothesis, splits, candidate=None, freeze=None):
        rows=[]
        for split in splits:
            for spec in self.store.read(split,candidate,freeze):
                public=public_candidate(spec,self.contract)
                probe=self.probe_record(spec)
                # Label strictly from executed fixed procedure; infrastructure errors
                # cannot silently become negative labels or correctness scores.
                truth=probe["procedure_success"]
                if not truth and not any(a.get("error")=="business_rule_rejected" for a in probe["tool_audit"]):
                    raise RuntimeError("probe does not establish applicability; evaluation incomplete")
                prediction=hypothesis.predict(public.observations,public.baseline_prediction,public.guard_prediction)
                rows.append({"task_id":spec["task_id"],"task_hash":fingerprint(spec),"split":split,
                    "probe_hash":fingerprint(probe),"truth":truth,"prediction":prediction,
                    "baseline_prediction":public.baseline_prediction,"procedure_success":truth,
                    "actual_violations":probe["actual_violations"],"probe_tool_calls":len(probe["tool_audit"]),
                    "scope":"forced applicability probe, not autonomous Agent EOC"})
        return rows

    def validate(self,candidate):
        if candidate["admission_identity"]!=self.admission_identity:
            raise ValueError("candidate was frozen for a different evaluator")
        h=Hypothesis.model_validate(candidate["hypothesis"])
        cases=self.measure(h,("validation","stable_validation"))
        return {"candidate_hash":fingerprint(candidate),"split":"validation+stable_validation",
            "admission_identity":self.admission_identity,"cases":cases,"cases_hash":fingerprint(cases),**counters(cases)}

    def audit_report(self,candidate,report):
        # Recompute row values from hashed actual probe records; aggregate-only
        # forged receipts never reach the production publication call below.
        if self.validate(candidate)!=report:
            raise ValueError("validation differs from executed evidence")


def run_worker(packet, probe, timeout=120):
    output=Path(packet["output"])
    output.mkdir(parents=True,exist_ok=True)
    env={k:v for k,v in os.environ.items() if not k.startswith("SKILLFORGE_")}
    env.update(PYTHONUTF8="1",PYTHONIOENCODING="utf-8")
    events=queue.Queue()
    with (output/"worker.stderr.log").open("a",encoding="utf-8") as errors:
        process=subprocess.Popen([sys.executable,"-m","skillforge.evolution_worker"],cwd=Path(__file__).resolve().parents[1],
            env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True,encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
        def read_messages():
            for line in process.stdout:
                events.put(line)
            events.put(None)
        reader=threading.Thread(target=read_messages,daemon=True)
        reader.start()
        try:
            process.stdin.write(json.dumps(packet,ensure_ascii=False)+"\n")
            process.stdin.flush()
            while True:
                line=events.get(timeout=timeout)
                if line is None:
                    raise RuntimeError("learner exited; inspect worker.stderr.log")
                message=json.loads(line)
                if message["type"]=="probe":
                    evidence=probe(message["candidate_id"])
                    process.stdin.write(json.dumps({"type":"evidence","value":evidence.model_dump()},ensure_ascii=False)+"\n")
                    process.stdin.flush()
                elif message["type"] in {"completed","access_denied"}:
                    process.stdin.close()
                    if process.wait(timeout=5)!=0:
                        raise RuntimeError("learner completion failed")
                    return message
                else:
                    raise ValueError("invalid learner RPC request")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            if not process.stdin.closed:
                process.stdin.close()
            reader.join(timeout=2)


def run_method(dataset, output, method, learning, seed, evaluate_test=False):
    output=Path(output)
    evaluator=Evaluator(dataset,output/"evaluator")
    store=evaluator.store
    seed_rows=store.read("seed")
    pool=store.read("explore")
    seed_evidence=[evaluator.evidence(row) for row in seed_rows]
    observed=set().union(*(e.observations for e in seed_evidence)) & FEATURE_FIELDS
    hypotheses=generate_hypotheses(observed,max_predicates=learning["max_predicates"])
    identity={"policy_epoch":store.manifest["policy_epoch"],"parent_hash":store.manifest["parent"]["contract_hash"],
        "parent_identity":store.manifest["parent"],"dataset_hash":fingerprint(store.manifest),
        "admission_identity":evaluator.admission_identity,
        "learner_code_hash":fingerprint({p.name:file_hash(p) for p in Path("skillforge").glob("*.py")})}
    by_id={s["task_id"]:s for s in pool}
    packet={"output":str((output/"learner").resolve()),"identity":identity,"method":method,"random_seed":seed,
        "learning":learning,"hypotheses":[h.model_dump(mode="json") for h in hypotheses],
        "seed_evidence":[e.model_dump() for e in seed_evidence],
        "candidates":[public_candidate(s,evaluator.contract).model_dump() for s in pool],
        "passive_order":[s["task_id"] for s in pool]}
    immutable_json(output/"learner-packet.json",packet)
    message=run_worker(packet,lambda key:evaluator.evidence(by_id[key]),timeout=300)
    result=message["result"]
    candidate_path=output/"learner/candidate.json"
    candidate=json.loads(candidate_path.read_text(encoding="utf-8")) if candidate_path.exists() else None
    effective=Hypothesis(hypothesis_id="H0",kind="no_change")
    if candidate is not None:
        report=evaluator.validate(candidate)
        evaluator.audit_report(candidate,report)
        immutable_json(output/"validation.json",report)
        if Hypothesis.model_validate(candidate["hypothesis"]).kind=="no_change":
            result["status"]="UNCHANGED"
        elif method!="no_adapt":
            if boundary_admission(candidate,report):
                registry=EvolutionRegistry(output/"registry")
                version=registry.publish(candidate,report)
                effective=Hypothesis.model_validate(registry.load(version)["candidate"]["hypothesis"])
                result.update(status="VERIFIED",registry_version=version)
            else:
                result["status"]="REJECTED"
    frozen={"effective_hypothesis":effective.model_dump(mode="json"),"proposal_hash":fingerprint(candidate),
            "identity_hash":fingerprint(identity),"decision":result["status"]}
    freeze={"candidate_hash":fingerprint(frozen),"dataset_hash":fingerprint(store.manifest)}
    immutable_json(output/"effective-version.json",frozen)
    immutable_json(output/"evaluation-freeze.json",freeze)
    if evaluate_test:
        test_cases=evaluator.measure(effective,("test","stable_test"),frozen,freeze)
        immutable_json(output/"test.json",{"freeze":freeze,"cases":test_cases})
    result.update(hypothesis_count=len(hypotheses),formal_test_executed=evaluate_test)
    immutable_json(output/"summary.json",result)
    return result
