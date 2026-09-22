"""Summarize completed paired test runs without changing prompts or verdicts."""
import argparse
import json
from collections import Counter
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    args = parser.parse_args()
    root = Path(args.run)
    report = json.loads((root / 'comparison.json').read_text(encoding='utf-8'))
    rows = {}
    for summary in report['summary']:
        label = summary['label']
        rows[label] = [json.loads(line) for p in (root / label).glob('*/task_results.jsonl')
                       for line in p.read_text(encoding='utf-8').splitlines()]
        assert len(rows[label]) == 78 and len({r['task_id'] for r in rows[label]}) == 78
    lines = ['# 真实B0–B3与双评测报告', '', f'运行目录：`{root}`', '',
        '同一冻结Qwen3 4B配置、同一78任务test集合，每组一次；无正式后训练。本轮未根据test修改提示或Skill。', '',
        '| 组别 | 结局合格 | 合格且无违规尝试 | 违规尝试 | 实际违规 | 平均模型调用 | 平均工具调用 | 平均总token |',
        '|---|---|---|---|---|---|---|---|']
    details = {}
    for s in report['summary']:
        label = s['label']
        batch = rows[label]
        good = sum(r['verification']['task_success'] for r in batch)
        clean = sum(r['verification']['task_success'] and not r['verification']['attempted_policy_violation'] for r in batch)
        attempts = sum(r['verification']['attempted_policy_violation'] for r in batch)
        violations = sum(r['verification']['actual_policy_violation'] for r in batch)
        lines.append(f'| {label} | {good}/78 | {clean}/78 | {attempts}/78 | {violations}/78 | {s["average_llm_calls"]:.2f} | {s["average_tool_calls"]:.2f} | {s["average_tokens"]:.1f} |')
        details[label] = {'clean_success': clean, 'errors': dict(Counter(e for r in batch for e in r['error_categories'])),
            'tasks_with_primitive_policy_error': sum(any((step.get('action') or {}).get('type') == 'tool'
                and step.get('error') in {'business_rule_rejected', 'permission_denied'} for step in r['steps']) for r in batch),
            'tasks_with_skill_policy_error': sum(any(event.get('error') in {'business_rule_rejected', 'permission_denied'}
                for event in r['skill_events']) for r in batch),
            'actual_outcomes': dict(Counter(r['outcome'] for r in batch)),
            'by_family': {f: {'tasks': sum(r['task_family'] == f for r in batch),
                'success': sum(r['verification']['task_success'] for r in batch if r['task_family'] == f)}
                for f in sorted({r['task_family'] for r in batch})}}
    lines += ['', '## Decision-level', '',
        '固定候选在预先授权读取后交给模型；不适用候选也可见，Gate不能替模型掩盖选择错误。故障或无法完成授权读取的案例跳过。', '',
        '| 范围 | 正确/评测 | 跳过 |', '|---|---|---|']
    for d in report['decision_evaluation']:
        lines.append(f'| {d["scope"]} | {sum(r.get("correct", False) for r in d["cases"])}/{d["evaluated"]} | {d["skipped"]} |')
    lines += ['', '## 策略错误发生位置', '', '同一任务可以同时出现在两列；权限/业务拒绝按轨迹错误位置分类。', '',
              '| 组别 | 原子工具调用错误任务 | Skill内部错误任务 |', '|---|---|---|']
    for label, item in details.items():
        lines.append(f'| {label} | {item["tasks_with_primitive_policy_error"]} | {item["tasks_with_skill_policy_error"]} |')
    baseline = {r['task_id']: r for r in rows['B0']}
    paired = {}
    for label, batch in rows.items():
        if label == 'B0':
            continue
        assert {r['task_id'] for r in batch} == set(baseline)
        helped = [r['task_id'] for r in batch if r['verification']['task_success'] and not baseline[r['task_id']]['verification']['task_success']]
        hurt = [r['task_id'] for r in batch if not r['verification']['task_success'] and baseline[r['task_id']]['verification']['task_success']]
        paired[label] = {'helped': helped, 'hurt': hurt}
    lines += ['', '## 逐任务配对变化', '', '以下是相对B0的观察性变化，不能作为已识别的因果NTR。', '',
              '| 组别 | B0失败→本组成功 | B0成功→本组失败 |', '|---|---|---|']
    for label, pair in paired.items():
        lines.append(f'| {label} | {len(pair["helped"])} | {len(pair["hurt"])} |')
    lines += ['', '## 解读边界', '',
        '- 本轮所有组skill_reuse_attempts=0，B2/B3/去Gate组均没有实际Skill调用。组间变化不能解释为Skill执行复用收益，NTR相关分母为0。',
        '- Decision-level为0/48：47次选择原子tool，另1次refuse也不符合目标；15个案例跳过。当前模型未遵守固定候选选择协议。',
        '- B0无记忆/Skill，B1检索原始train经验，B2成功经验Naive Skill，B3成功＋失败＋policy且经验证Skill，最后一组去除Gate。',
        '- 系统成绩包含环境策略拦截、Gate读取和Skill executor能力；不能替代模型自身决策成绩。',
        '- 拒绝/转人工按Expected Outcome Contract判断，结局符合仍可能伴随违规尝试。',
        '- 单模型、单次、合成环境；不声称显著性、稳定性或真实业务泛化。',
        '- UNKNOWN、错误复用与成本原始指标在comparison.json/csv；causal_ntr保留null，未将UNKNOWN当作false。',
        '- 详细错误、领域分层和配对任务ID见analysis.json；模型/GPU/冻结配置见serving_snapshot.json。']
    (root / 'analysis.json').write_text(json.dumps({'variants': details, 'paired_vs_B0': paired}, indent=2), encoding='utf-8')
    Path('docs/REAL_EVAL_REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({'summary': report['summary'], 'decisions': [{k:v for k,v in d.items() if k != 'cases'} for d in report['decision_evaluation']],
        'paired': {k: {n:len(ids) for n,ids in v.items()} for k,v in paired.items()}}))


if __name__ == '__main__':
    main()
