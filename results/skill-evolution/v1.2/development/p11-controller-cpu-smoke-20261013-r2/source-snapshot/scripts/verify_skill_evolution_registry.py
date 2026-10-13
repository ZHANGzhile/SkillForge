"""P4 registry/evidence CPU acceptance, preserving the real zero-candidate result."""
import argparse
from pathlib import Path
import shutil
import time

from scripts.continue_skill_evolution_selection import publish
from scripts.verify_skill_evolution_p4 import engineering_entry
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.agent_evidence import ROOT, read, digest, declare_evidence_protocol
from skillforge.skill_evolution.catalog import Catalog
from skillforge.skill_evolution.provenance import audit_compiler_run
from skillforge.skill_evolution.registry import VersionedRegistry
from skillforge.skill_evolution.runtime import runtime_sources


def hashed(body): return {**body, "hash": fingerprint(body)}


def reject_learn_as_validation(provenance, catalog):
    learn = ROOT / provenance["learn_run"]
    registration = read(learn / "registration.json")
    class NoHeldoutOwnership:
        owners = {}
    try:
        declare_evidence_protocol([{"case":read(learn / "private-learn-cases.json")[0],"stable":False}],
            catalog,catalog,read(learn / "model-identity.json"),
            {name.removeprefix("skillforge/"):value for name,value in registration["sources"].items() if name.startswith("skillforge/")},
            registration["config"]["limits"],NoHeldoutOwnership(),budget={"prior_tokens":0,"max_tokens":100000,"prior_wall":0,"max_wall":1000})
    except ValueError as exc:
        if "cannot enter Agent admission validation" not in str(exc): raise
        return True
    raise ValueError("learn evidence unexpectedly admitted to validation")


def run(output, compiler_run):
    output = Path(output).resolve(); output.mkdir(parents=True,exist_ok=False)
    started = time.perf_counter()
    sources = {"skillforge/" + name:value for name,value in runtime_sources().items()}
    sources["scripts/verify_skill_evolution_registry.py"] = digest(__file__)
    for name in ("scripts/evolution_budget.py","scripts/collect_skill_evolution_learn.py","scripts/compile_skill_evolution_traces.py"):
        sources[name] = digest(ROOT / name)
    for name, expected in sources.items():
        target = output / "source-snapshot" / name
        target.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(ROOT / name,target)
        if digest(target) != expected: raise ValueError("source changed during snapshot")
    publish(output / "source-index.json",sources)
    publish(output / "declaration.json",hashed({"mode":"CPU engineering", "compiler_run":Path(compiler_run).resolve().relative_to(ROOT).as_posix(),
        "sources_hash":fingerprint(sources), "operations":["legacy_import","retain_parent","engineering_deprecate","engineering_rollback"],
        "new_model_calls":0,"new_tokens":0,"formal_admission":False,"service_activation":False}))
    provenance = audit_compiler_run(compiler_run)
    if provenance["proposal"]["status"] != "NO_USEFUL_CANDIDATE" or provenance["proposal"]["n_candidates"]:
        raise ValueError("this acceptance runner only exercises the real no-candidate path")
    publish(output / "real-proposal-audit.json",provenance)
    catalog = Catalog.load(ROOT / provenance["learn_run"] / "catalog.json")
    registry = VersionedRegistry(output / "r")
    baseline = registry.bootstrap(catalog,reason="Import existing historical static baseline without claiming new admission",
        evidence=hashed({"schema":"legacy-baseline-import-evidence-v1","catalog_hash":catalog.hash,
                         "learn_run":provenance["learn_run"],"learn_report_sha256":provenance["collection_audit"]["report_sha256"]}))
    baseline_files = {str(path.relative_to(output)).replace("\\","/"):digest(path) for path in (output / "r").rglob("*.json")}
    retained = registry.retain(baseline,reason="NO_USEFUL_CANDIDATE",evidence=provenance)
    deprecated = registry.deprecate(retained,catalog.entries()[0]["revision"],reason="CPU engineering branch only; not a production deprecation",evidence=hashed({"scope":"engineering branch"}))
    restored = registry.rollback(deprecated,baseline,reason="CPU engineering rollback to exact imported ancestor",evidence=hashed({"scope":"engineering branch"}))
    receipt = read(ROOT / "results/skill-evolution/v1.2/development/p4-engineering-20261012-r3/program-admission.json")
    rejected = False
    try:
        registry.register_program(retained,engineering_entry(),program_admission=receipt,compiler_run=compiler_run,reason="must reject engineering receipt")
    except ValueError as exc:
        if "formal program admission required" not in str(exc): raise
        rejected = True
    heldout_guard = reject_learn_as_validation(provenance,catalog)
    report = {"schema":"p4-registry-engineering-report-v1","engineering_passed":True,
        "compiler_run":Path(compiler_run).resolve().relative_to(ROOT).as_posix(), "provenance_hash":provenance["hash"],
        "source_index_hash":fingerprint(sources), "baseline_files":baseline_files,
        "snapshots":{"baseline":baseline,"retained_parent":retained,"engineering_deprecated":deprecated,"engineering_rollback":restored},
        "real_candidates":0,"no_update_reason":"NO_USEFUL_CANDIDATE","retained_catalog_hash":catalog.hash,
        "real_recorded_eoc":sum(item["eoc"] for item in provenance["agent_evidence"]),
        "real_recorded_autonomous_eoc":sum(item["autonomous_eoc"] for item in provenance["agent_evidence"]),
        "real_recorded_runtime_assisted_eoc":sum(item["runtime_assisted_eoc"] for item in provenance["agent_evidence"]),
        "audited_recorded_model_calls":sum(item["model_calls"] for item in provenance["agent_evidence"]),
        "audited_recorded_tokens":sum(item["tokens"] for item in provenance["agent_evidence"]),
        "replay_tool_calls":sum(item["replay_tool_calls"] for item in provenance["agent_evidence"]),
        "engineering_registration_rejected":rejected,"learn_to_validation_rejected":heldout_guard,
        "new_model_calls":0,"new_tokens":0,"cpu_wall_seconds":time.perf_counter()-started,
        "program_admitted":False,"agent_admitted":False,"research_claim_passed":None,"isolated_activated":False,"deployed":False,
        "scope":"CPU acceptance and real recorded-response replay; engineering deprecation/rollback only; no new formal candidate"}
    publish(output / "report.json",report)
    return report


def audit(root):
    root = Path(root).resolve()
    report, sources = read(root / "report.json"),read(root / "source-index.json")
    if (fingerprint(sources) != report["source_index_hash"] or
            any(digest(root / "source-snapshot" / name) != expected or digest(ROOT / name) != expected for name,expected in sources.items())):
        raise ValueError("registry engineering source snapshot/version mismatch")
    declaration = read(root / "declaration.json")
    if declaration != hashed({"mode":"CPU engineering","compiler_run":report["compiler_run"],"sources_hash":fingerprint(sources),
        "operations":["legacy_import","retain_parent","engineering_deprecate","engineering_rollback"],
        "new_model_calls":0,"new_tokens":0,"formal_admission":False,"service_activation":False}):
        raise ValueError("registry engineering declaration mismatch")
    provenance = audit_compiler_run(ROOT / report["compiler_run"])
    if (provenance != read(root / "real-proposal-audit.json") or provenance["hash"] != report["provenance_hash"] or
            provenance["proposal"]["n_candidates"] or provenance["proposal"]["status"] != "NO_USEFUL_CANDIDATE"):
        raise ValueError("real no-update/compiler/evidence mismatch")
    registry = VersionedRegistry(root / "r")
    ids = report["snapshots"]
    base, catalog = registry.load(ids["baseline"])
    retained, kept = registry.load(ids["retained_parent"])
    deprecated, smaller = registry.load(ids["engineering_deprecated"])
    restored, restored_catalog = registry.load(ids["engineering_rollback"])
    expected_catalog = Catalog.load(ROOT / provenance["learn_run"] / "catalog.json")
    if (base["parent_snapshot"] is not None or base["operation"] != "LEGACY_IMPORT" or
            retained["parent_snapshot"] != ids["baseline"] or retained["operation"] != "RETAIN_PARENT" or retained["evidence"] != provenance or
            deprecated["parent_snapshot"] != ids["retained_parent"] or deprecated["operation"] != "DEPRECATED" or
            restored["parent_snapshot"] != ids["engineering_deprecated"] or restored["operation"] != "ROLLBACK" or restored["rollback_target"] != ids["baseline"] or
            any(item.hash != expected_catalog.hash for item in (catalog,kept,restored_catalog)) or len(smaller.entries()) != len(catalog.entries())-1):
        raise ValueError("registry selection/rollback lineage mismatch")
    if any(digest(root / name) != expected for name,expected in report["baseline_files"].items()):
        raise ValueError("original registry bytes changed")
    registration = read(ROOT / "results/skill-evolution/v1.2/development/p4-engineering-20261012-r3/program-admission.json")
    try:
        registry.register_program(ids["retained_parent"],engineering_entry(),program_admission=registration,
                                  compiler_run=ROOT / report["compiler_run"],reason="audit rejection guard")
    except ValueError as exc:
        if "formal program admission required" not in str(exc): raise
    else: raise ValueError("engineering receipt unexpectedly registered")
    expected = {"engineering_passed":True,"real_candidates":0,"no_update_reason":"NO_USEFUL_CANDIDATE",
        "retained_catalog_hash":expected_catalog.hash,"real_recorded_eoc":sum(item["eoc"] for item in provenance["agent_evidence"]),
        "real_recorded_autonomous_eoc":sum(item["autonomous_eoc"] for item in provenance["agent_evidence"]),
        "real_recorded_runtime_assisted_eoc":sum(item["runtime_assisted_eoc"] for item in provenance["agent_evidence"]),
        "audited_recorded_model_calls":sum(item["model_calls"] for item in provenance["agent_evidence"]),
        "audited_recorded_tokens":sum(item["tokens"] for item in provenance["agent_evidence"]),
        "replay_tool_calls":sum(item["replay_tool_calls"] for item in provenance["agent_evidence"]),
        "engineering_registration_rejected":True,"learn_to_validation_rejected":reject_learn_as_validation(provenance,catalog),
        "new_model_calls":0,"new_tokens":0,"program_admitted":False,"agent_admitted":False,"research_claim_passed":None,
        "isolated_activated":False,"deployed":False}
    if any(report[key] != value for key,value in expected.items()): raise ValueError("registry aggregate/disposition mismatch")
    receipt = {"passed":True,"generator_sha256":digest(__file__),"report_sha256":digest(root / "report.json"),
        "source_index_hash":fingerprint(sources),"retained_parent":True,"audit_replay_tool_calls":expected["replay_tool_calls"],
        "new_model_calls":0,"new_tokens":0,"scope":"real learn replay/proposal, immutable ancestor bytes, no-op/deprecation/rollback and admission guards"}
    publish(root / "evidence-audits" / (digest(__file__) + ".json"),receipt)
    return receipt


if __name__ == "__main__":
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output"); parser.add_argument("--compiler-run"); parser.add_argument("--run")
    args = parser.parse_args()
    if not args.run and not (args.output and args.compiler_run): parser.error("provide --run or --compiler-run and --output")
    result = audit(args.run) if args.run else run(args.output,args.compiler_run)
    print(json.dumps(result,ensure_ascii=False))
