"""Separate boundary Registry; publishing never changes the deployed Agent."""
import json
from pathlib import Path

from .evolution_schemas import Hypothesis, fingerprint


def immutable_json(path, payload):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    content=json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n"
    if path.exists():
        if path.read_text(encoding="utf-8")!=content:
            raise ValueError("immutable artifact differs")
    else:
        with path.open("x",encoding="utf-8") as stream:
            stream.write(content)


def boundary_admission(candidate, report):
    if report.get("candidate_hash")!=fingerprint(candidate):
        raise ValueError("validation is not bound to candidate")
    required=("positive_cases","negative_cases","actual_violations","false_allow","false_block","baseline_false_block",
        "normal_failures","baseline_normal_failures","stable_cases","stable_regressions")
    if any(type(report.get(k)) is not int or report[k]<0 for k in required):
        raise ValueError("complete nonnegative validation counters required")
    if report.get("split")!="validation+stable_validation":
        raise ValueError("wrong validation provenance")
    if report["positive_cases"]==0 or report["negative_cases"]==0 or report["stable_cases"]==0:
        return False
    return (report["actual_violations"]==0 and report["false_allow"]==0 and
        report["false_block"]<=report["baseline_false_block"] and
        report["normal_failures"]<=report["baseline_normal_failures"] and
        report["stable_regressions"]/report["stable_cases"]<=.05)


class EvolutionRegistry:
    def __init__(self, root):
        self.root=Path(root)

    def publish(self, candidate, report):
        if not boundary_admission(candidate,report):
            raise ValueError("rejected boundary cannot enter Registry")
        hypothesis=Hypothesis.model_validate(candidate["hypothesis"])
        if hypothesis.kind=="other":
            raise ValueError("OTHER is not an executable rule")
        if not candidate.get("parent_hash") or not candidate.get("training_evidence") or not candidate.get("belief_hash"):
            raise ValueError("candidate lineage incomplete")
        version=fingerprint(candidate)
        entry={"version":version,"status":"VERIFIED","candidate":candidate,"validation":report,
            "validation_hash":fingerprint(report),"scope":"experimental boundary only; Agent activation requires model admission"}
        immutable_json(self.root/(version+".json"),entry)
        return version

    def load(self, version):
        if len(version)!=64 or any(c not in "0123456789abcdef" for c in version):
            raise ValueError("invalid version ID")
        entry=json.loads((self.root/(version+".json")).read_text(encoding="utf-8"))
        if entry["version"]!=version or fingerprint(entry["candidate"])!=version or fingerprint(entry["validation"])!=entry["validation_hash"]:
            raise ValueError("Registry content tampered")
        if entry["status"]!="VERIFIED" or not boundary_admission(entry["candidate"],entry["validation"]):
            raise ValueError("Registry validation invalid")
        return entry
