import argparse
import json
from skillforge.supervision import prepare_supervision

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare_supervision(args.dataset, args.bundle, args.output), ensure_ascii=False, indent=2))
