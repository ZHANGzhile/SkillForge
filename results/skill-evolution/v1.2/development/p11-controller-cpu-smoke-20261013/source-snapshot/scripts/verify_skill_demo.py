"""Run the real-model demo acceptance cases; never selects the test split."""
import argparse
import json
from pathlib import Path
import uuid
from skillforge.skill_demo import FAMILIES, CASES, select_tasks, run_case


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--split', choices=['train','validation'], default='train')
    p.add_argument('--all-instances', action='store_true')
    args = p.parse_args()
    root = Path('results/skill-demo-acceptance') / str(uuid.uuid4())
    root.mkdir(parents=True)
    rows = []
    for family in FAMILIES:
        for case in CASES:
            for task in select_tasks(family, case, args.split, args.all_instances):
                r = run_case(family, case, args.split, task=task)
                row = {'family':family, 'case':case, 'task_id':task.task_id, 'passed':r['demo_passed'],
                    'outcome':r['outcome'], 'skill_calls':r['metrics']['skill_calls'],
                    'attempted_violation':r['verification']['attempted_policy_violation'],
                    'actual_violation':r['verification']['actual_policy_violation'], 'artifact_dir':r['artifact_dir']}
                rows.append(row)
                (root/'progress.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
                print(json.dumps(row),flush=True)
    summary = {'split':args.split, 'passed':sum(r['passed'] for r in rows), 'total':len(rows), 'cases':rows,
        'scope':'bounded action catalog + gate + executor; real model chooses; not unrestricted B3', 'artifact_dir':str(root.resolve())}
    (root/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)
    if summary['passed'] != summary['total']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
