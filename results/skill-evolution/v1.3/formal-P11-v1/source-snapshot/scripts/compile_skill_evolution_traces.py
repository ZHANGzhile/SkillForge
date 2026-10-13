"""Compile only independently audited learn opportunities; never admit/publish."""
import argparse
from pathlib import Path
import shutil

from scripts.collect_skill_evolution_learn import audit, read
from scripts.continue_skill_evolution_selection import publish
from scripts.run_skill_evolution import ROOT, digest_file
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.compiler import compile_screen
from skillforge.skill_evolution.experience import mine_opportunities


def compile_run(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    receipt = audit(root)
    if not receipt["run_completed"]:
        raise ValueError("complete audited learn collection required")
    registration = read(root / "registration.json")
    config = registration["config"]["opportunity_screen"]
    if config["skill_search_load_execute_stop_decisions"] != 4:
        raise ValueError("unsupported utility model")
    rows = [read(path) for path in sorted(root.glob("*/result.json"))]
    screen = mine_opportunities(rows, read(root / "model-identity.json"), min_sources=config["min_sources"],
                                min_model_call_saving=config["min_model_call_saving"])
    result = compile_screen(screen)
    output.mkdir(parents=True, exist_ok=False)
    sources = {}
    for name in ("skillforge/skill_evolution/compiler.py", "skillforge/skill_evolution/experience.py", __file__):
        source = Path(name) if Path(name).is_absolute() else ROOT / name
        target = output / ("source-" + source.name)
        sources[source.relative_to(ROOT).as_posix()] = digest_file(source)
        shutil.copyfile(source, target)
        if digest_file(target) != sources[source.relative_to(ROOT).as_posix()]:
            raise ValueError("compiler source changed during snapshot")
    binding = {"learn_protocol_hash": registration["protocol_hash"], "learn_report_sha256": receipt["report_sha256"],
               "learn_run": root.relative_to(ROOT).as_posix(), "collection_audit": receipt,
               "opportunity_screen_hash": fingerprint(screen), "sources": sources,
               "scope": "deterministic learn-only proposal, no formal validation, catalog registration or inference"}
    publish(output / "binding.json", {**binding, "hash": fingerprint(binding)})
    publish(output / "opportunity-screen.json", screen)
    publish(output / "report.json", result)
    return {"status": result["status"], "n_candidates": result["n_candidates"], "binding_hash": fingerprint(binding)}


if __name__ == "__main__":
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True); parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(compile_run(args.run, args.output), ensure_ascii=False))
