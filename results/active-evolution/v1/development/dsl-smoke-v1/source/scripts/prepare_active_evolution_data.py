"""Prepare immutable six-world/five-seed data packages, without executing learners."""
import argparse
import json
from pathlib import Path

from scripts.active_evolution_dataset import write_dataset
from scripts.active_evolution_worlds import difference_witnesses
from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",default="configs/active-evolution-v1.json")
    parser.add_argument("--output",default="results/active-evolution/v1/preparation/dataset-v1")
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding="utf-8"))
    root=Path(args.output)
    bundle_path=Path("results/real-v2-frozen/frozen.json")
    bundle=json.loads(bundle_path.read_text(encoding="utf-8"))
    contracts={s["family"]:s for s in bundle["skills"]}
    sources=[Path(args.config),Path(__file__),Path("scripts/active_evolution_dataset.py"),
             Path("scripts/active_evolution_worlds.py"),Path("scripts/active_evolution_model_design.py"),Path("skillforge/evolution_boundary.py")]
    identity={"format":"active-data-preparation-v1","config":config,
        "sources":{p.name:file_hash(p) for p in sources},"parent_bundle_sha256":file_hash(bundle_path),
        "scope":"Data-only preparation. No learner fit, no test scoring, no research success claim."}
    immutable_json(root/"identity.json",identity)
    receipts=[]
    for world in config["worlds"]:
        for seed in config["paired_seeds"]:
            counts=dict(config["splits"])
            model=config["model_layer"]
            if world in model["worlds"] and seed==model["paired_seed"]:
                counts.update({key:model[key] for key in ("model_validation","model_stable_validation","model_test","model_stable_test")})
            manifest=write_dataset(root/world/str(seed),world,seed,counts,
                                   contracts["modify_address" if world=="W6" else "refund"])
            receipts.append({"world":world,"seed":seed,"counts":manifest["counts"],"manifest_hash":fingerprint(manifest)})
        print(json.dumps({"world":world,"prepared":len(receipts)}),flush=True)
    immutable_json(root/"world-witnesses.json",difference_witnesses())
    result={"identity_hash":fingerprint(identity),"datasets":receipts,
            "total_tasks":sum(sum(r["counts"].values()) for r in receipts),"formal_experiment_frozen":False}
    immutable_json(root/"summary.json",result)
    print(json.dumps({"datasets":len(receipts),"tasks":result["total_tasks"],"formal_experiment_frozen":False}))


if __name__=="__main__":
    main()
