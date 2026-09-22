import argparse
import json
from skillforge.training import train

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/training.json")
    parser.add_argument("--stage", choices=["sft", "dpo"], required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--sft-adapter")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--resume-checkpoint", help="Explicit audited migration from an earlier run; preserves optimizer/scheduler/RNG")
    args = parser.parse_args()
    print(json.dumps(train(args.config, args.stage, args.output, args.sft_adapter, args.resume, args.smoke, args.resume_checkpoint), indent=2))
