"""Controller-side audit of a learn-only compiler run before registration."""
from pathlib import Path

from ..evolution_schemas import fingerprint
from .agent_evidence import ROOT, read, digest, audit_trajectory
from .catalog import Catalog
from .compiler import compile_screen
from .experience import mine_opportunities
from .validation import checked_hash


def audit_compiler_run(compiler_root):
    # The existing collector audit owns the shared GPU ledger and archived
    # worker sources. The additional replay owns action/tool causality.
    from scripts.collect_skill_evolution_learn import audit

    compiler_root = Path(compiler_root).resolve()
    binding = read(compiler_root / "binding.json")
    checked_hash(binding)
    for name, expected in binding["sources"].items():
        if (digest(ROOT / name) != expected or digest(compiler_root / ("source-" + Path(name).name)) != expected):
            raise ValueError("compiler source version differs; use archived controller")
    learn_root = (ROOT / binding["learn_run"]).resolve()
    receipt = audit(learn_root)
    registration = read(learn_root / "registration.json")
    if (not receipt["run_completed"] or receipt["report_sha256"] != binding["learn_report_sha256"] or
            receipt["protocol_hash"] != binding["learn_protocol_hash"] or receipt != binding["collection_audit"]):
        raise ValueError("learn collection/compiler provenance mismatch")
    settings = read(learn_root / "model-identity.json")
    config, budget = registration["config"], registration["config"]["budget"]
    if settings.get("adapter_sha256") != config["adapter_sha256"]:
        raise ValueError("learn adapter differs from registered fixed weights")
    sources = {name.removeprefix("skillforge/"): value for name, value in registration["sources"].items() if name.startswith("skillforge/")}
    catalog = Catalog.load(learn_root / "catalog.json")
    rows, evidence, prior = [], [], registration["prior_tokens"]
    for case in read(learn_root / "private-learn-cases.json"):
        if case["split"] != "train": raise ValueError("proposal sources must be train only")
        folder = learn_root / case["task_id"]
        packet = audit_trajectory(folder, catalog, settings, sources, config["limits"], charge_context={
            "prior_tokens": prior, "max_tokens": budget["project_max_tokens"], "prior_wall": registration["prior_wall_seconds"],
            "max_wall": budget["project_max_wall_seconds"]})
        prior += packet["tokens"]
        evidence.append(packet)
        rows.append(read(folder / "result.json"))
    thresholds = config["opportunity_screen"]
    if thresholds["skill_search_load_execute_stop_decisions"] != 4:
        raise ValueError("unsupported opportunity cost model")
    # Compiler input order is the sorted result paths, not collection order.
    rows.sort(key=lambda row: row["case"]["task_id"])
    screen = mine_opportunities(rows, settings, min_sources=thresholds["min_sources"], min_model_call_saving=thresholds["min_model_call_saving"])
    report = compile_screen(screen)
    if (screen != read(compiler_root / "opportunity-screen.json") or fingerprint(screen) != binding["opportunity_screen_hash"] or
            report != read(compiler_root / "report.json")):
        raise ValueError("compiler proposal differs from independently audited real learn replay")
    body = {"schema": "audited-trace-proposal-v1", "binding_hash": binding["hash"],
            "compiler_run": compiler_root.relative_to(ROOT).as_posix(), "learn_run": binding["learn_run"],
            "compiler_report_sha256": digest(compiler_root / "report.json"), "collection_audit": receipt,
            "agent_evidence": evidence, "proposal": report, "catalog_hash": catalog.hash,
            "new_model_calls": 0, "new_tokens": 0, "scope": "real learn collection and recorded-response replay; no formal validation"}
    return {**body, "hash": fingerprint(body)}
