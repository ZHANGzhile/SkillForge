"""Development acceptance of isolated four-arm protocol; no formal score claims."""
import argparse
import json
from pathlib import Path

from scripts.active_evolution_dataset import write_dataset
from scripts.evaluate_active_evolution import run_method
from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--config",default="configs/active-evolution-v1.json")
    parser.add_argument("--output",default="results/active-evolution/v1/development/protocol-v2")
    parser.add_argument("--worlds",nargs="+",default=["W3"])
    parser.add_argument("--methods",nargs="+",default=["no_adapt","passive","random","active"])
    parser.add_argument("--seed",type=int,default=701)
    parser.add_argument("--prepare-only",action="store_true")
    parser.add_argument("--coverage-smoke",action="store_true",help="Use the declared CPU counts and query budget, still development-only")
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding="utf-8"))
    if not set(args.worlds)<=set(config["worlds"]) or not set(args.methods)<=set(config["methods"]):
        parser.error("undeclared world or method")
    root=Path(args.output)
    bundle_path=Path("results/real-v2-frozen/frozen.json")
    bundle=json.loads(bundle_path.read_text(encoding="utf-8"))
    contracts={s["family"]:s for s in bundle["skills"]}
    counts={"seed":6,"explore":12,"validation":8,"stable_validation":8,"test":8,"stable_test":8}
    learning={**config["learning"],"max_queries":4}
    if args.coverage_smoke:
        counts=dict(config["splits"])
        learning=dict(config["learning"])
    source_paths=list(Path("skillforge").glob("*evolution*.py"))+[Path("skillforge")/name for name in ("belief.py","hypothesis.py","active_learning.py","gap_detection.py","sandbox_probe.py")]+list(Path("scripts").glob("*active_evolution*.py"))
    identity={"development_only":True,"coverage_smoke":args.coverage_smoke,"seed":args.seed,"worlds":args.worlds,"methods":args.methods,
        "counts":counts,"learning":learning,"parent_bundle_hash":file_hash(bundle_path),
        "source_hash":fingerprint({p.as_posix():file_hash(p) for p in sorted(source_paths)}),
        "formal_test_enabled":False,"scope":"small four-method integration, held-out files generated but never read"}
    immutable_json(root/"identity.json",identity)
    results=[]
    for world in args.worlds:
        dataset=root/"datasets"/world
        write_dataset(dataset,world,args.seed,counts,contracts["modify_address" if world=="W6" else "refund"])
        if args.prepare_only:
            continue
        for method in args.methods:
            print(json.dumps({"world":world,"method":method,"stage":"started"}),flush=True)
            result=run_method(dataset,root/"runs"/world/method,method,learning,args.seed,evaluate_test=False)
            results.append({"world":world,**result})
            print(json.dumps({"world":world,"method":method,"stage":"finished","status":result["status"],"queries":result["queries"]}),flush=True)
    if not args.prepare_only:
        immutable_json(root/"summary.json",{"identity":identity,"runs":results})


if __name__=="__main__":
    main()
