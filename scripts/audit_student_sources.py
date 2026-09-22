"""Audit real train evidence and report compiler readiness without touching test."""
import argparse
import json
from pathlib import Path
from skillforge.dataset import load_dataset
from skillforge.experiment import read_sources
from skillforge.provenance import audit_sources
from skillforge.skills import compile_skill
from skillforge.benchmark import summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('sources', nargs='+')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    records = [r for source in args.sources for r in read_sources(source)]
    _, tasks = load_dataset('data/experiment-v1')
    report = {'sources': args.sources, 'audit': audit_sources(records, tasks),
              'summary': summarize(records), 'families': {}}
    for family in ['modify_address', 'cancel_order', 'refund']:
        selected = [r for r in records if r['task_family'] == family]
        item = {'tasks': len(selected), 'clean_completed': sum(r['outcome'] == 'completed'
            and r['verification']['task_success'] and not r['verification']['attempted_policy_violation'] for r in selected)}
        item['failed_business_counterexamples'] = sum(not r['verification']['task_success']
            and any(e.get('error') in {'business_rule_rejected', 'permission_denied'} for e in r['tool_audit']) for r in selected)
        ordered, excluded = [], []
        mutation = {'modify_address': 'update_shipping_address', 'cancel_order': 'cancel_order', 'refund': 'issue_refund'}[family]
        before_read = 'get_payment' if family == 'refund' else 'get_shipment'
        after_read = 'get_payment' if family == 'refund' else 'get_order'
        for record in selected:
            if record['outcome'] != 'completed' or not record['verification']['task_success'] or record['verification']['attempted_policy_violation']:
                continue
            names = [e['tool_name'] for e in record['tool_audit'] if not e['error']]
            write = names.index(mutation) if mutation in names else -1
            valid = write >= 0 and 'get_order' in names[:write] and before_read in names[:write] and after_read in names[write + 1:]
            (ordered if valid else excluded).append(record['trajectory_id'])
        item['ordered_execution_evidence'] = ordered
        item['clean_outcomes_missing_execution_evidence'] = excluded
        try:
            candidate = compile_skill(records, family)
            item.update(ready=True, candidate=candidate.model_dump())
        except ValueError as exc:
            item.update(ready=False, reason=str(exc))
        report['families'][family] = item
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise ValueError('Choose a new audit output to preserve history')
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'sources'}, indent=2))


if __name__ == '__main__':
    main()
