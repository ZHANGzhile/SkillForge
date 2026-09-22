"""Write a live, read-only-derived evaluation progress document."""
import json
from datetime import datetime
from pathlib import Path


def main():
    root = max(Path('results/real-v2-comparisons').iterdir(), key=lambda p: p.stat().st_mtime)
    complete = (root / 'comparison.json').exists()
    lines = ['# 真实对照评测实时进度', '', f'更新：{datetime.now().astimezone().isoformat()}', '',
             f'状态：{"全部完成" if complete else "运行中；以下为部分结果，不能作为最终比较"}',
             f'运行目录：`{root}`', '', '| 组别 | 已完成/78 | 结局合格 | 违规尝试 | 实际违规 |', '|---|---|---|---|---|']
    counters = {}
    for label in ['B0', 'B1', 'B2', 'B3', 'B3-no-gate']:
        rows = []
        for journal in (root / label).glob('*/task_results.jsonl'):
            for line in journal.read_text(encoding='utf-8').splitlines():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # The writer may be in the middle of its final line.
        counts = [sum(r['verification'][key] for r in rows) for key in
                  ['task_success', 'attempted_policy_violation', 'actual_policy_violation']]
        lines.append(f'| {label} | {len(rows)}/78 | {counts[0]} | {counts[1]} | {counts[2]} |')
        counters[label] = {'completed': len(rows), 'success': counts[0], 'attempts': counts[1], 'actual': counts[2]}
    lines += ['', '五组完成后执行三类固定候选Decision-level探针。所有组使用同一冻结提示与Skill来源；不根据test结果修改提示。',
              '日志：`.runtime/real-comparison.log`；正式训练尚未开始。']
    Path('docs/EVAL_LIVE.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'complete': complete, 'variants': counters}))


if __name__ == '__main__':
    main()
