"""Finish protocol A reporting after its frozen runner closes; never run models."""
import argparse
import json
from pathlib import Path
import time

from scripts.audit_execution_aware import audit
from scripts.execution_aware_formal import read, load
from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint


def finalize(root, invocation):
    root = Path(root); protocol = load(root)
    final = read(root/'model-layer/invocations'/(invocation+'.final.json'))
    receipt = audit(root)
    if not receipt['complete'] or final['status'] != 'complete':
        immutable_json(root/'audits'/('finalization-'+invocation+'.json'), {
            'status': 'incomplete', 'invocation': invocation, 'audit': receipt,
            'reason': 'Frozen model runner did not complete; no aggregate research conclusion emitted.'})
        return {'status': 'incomplete', 'invocation': invocation}
    model = read(root/'model-report.json'); cpu = read(root/'cpu-report.json')
    immutable_json(root/'execution-attribution.json', {
        'protocol_hash': fingerprint(protocol), 'groups': receipt['per_group_execution_attribution'],
        'scope': 'descriptive attribution only; original frozen estimands and admission are unchanged'})
    immutable_json(root/'audits'/('finalization-'+invocation+'.json'), {
        'status': 'complete', 'invocation': invocation, 'audit': receipt,
        'finalizer_sha256': file_hash(__file__)})
    report = ['# Execution-Aware Self-Evolution v1.1-A 正式结果', '',
              '协议：`'+fingerprint(protocol)+'`。固定 main-v3、原 Active 获取策略；Acquisition v2 不进入本实验。', '',
              '9 个独立 world-seed（W3/W5/W6 各 3 个 seed）；另有两个连续 epoch，后者不并入主要统计样本。', '',
              '## 固定分母漏斗', '', '| Runtime | Planned | Belief | Boundary | Agent | Activated | Deployed |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for runtime in ('old', 'new'):
        c = model['funnel'][runtime]['counts']
        report.append('| '+runtime+' | '+' | '.join(str(c[k]) for k in ('planned','belief_converged','boundary_admitted','agent_admitted','activated','deployed'))+' |')
    report += ['', 'Activated 仅为隔离评估中的 Bundle 生效。拒绝更新保留实际父 Bundle；不代表已部署。', '',
               '## 预注册 factorial 效应', '',
               '效应单位为 EOC 比例差；bootstrap 按世界分层重采样配对 seed，不把任务视为独立重复。每世界仅 3 个 seed，区间精度有限。', '',
               '| Bundle 口径 | Estimand | 点估计 | 95% 配对区间 |', '|---|---|---:|---|']
    for scope, values in model['factorial'].items():
        for name, value in values['point_estimates'].items():
            interval = values['paired_bootstrap_95'][name]
            report.append(f'| {scope} | {name} | {value:.4f} | [{interval[0]:.4f}, {interval[1]:.4f}] |')
    report += ['', 'candidate 为隔离候选诊断；effective 为 Runtime 各自准入后的有效 Bundle。test 不会追溯改变 validation 准入。', '',
               '## Runtime 贡献（同一旧 Bundle）', '',
               '| World / seed | N | autonomous EOC | assisted EOC | 干预任务 | 救援 | 强制读回 | 自动终止 |',
               '|---|---:|---:|---:|---:|---:|---:|---:|']
    for row in model['independent']:
        m = row['runtime_assistance']; c = m['counts']
        report.append('| '+row['world']+'/'+str(row['seed'])+' | '+str(m['n'])+' | '+' | '.join(str(c[k]) for k in
            ('autonomous_eoc','runtime_assisted_eoc','runtime_intervention_rate','rescued_by_runtime','forced_readback_count','auto_termination_count'))+' |')
    report += ['', '自主与辅助成功互斥；上述配对包括变化与 stable test。救援属于系统执行契约的贡献，不能解释为模型权重学习。', '',
               '## 新 Runtime 下更新 Bundle 的逐臂归因', '',
               '以下为变化test的描述性计数，各单元单列。candidate是CPU准入后的候选；effective按Agent准入回退。完整旧/新Runtime、变化/stable分区见`execution-attribution.json`，不新增主estimand。', '',
               '| World / seed | 口径 | Bundle | N | EOC | autonomous | assisted | 有干预任务 |',
               '|---|---|---|---:|---:|---:|---:|---:|']
    for row in receipt['per_group_execution_attribution']:
        if not row['independent']:
            continue
        for scope in ('candidate', 'effective'):
            for arm in ('old', 'proposal'):
                m = row[scope]['new_'+arm]['changed']; c = m['counts']
                report.append(f"| {row['world']}/{row['seed']} | {scope} | {arm} | {m['n']} | {c['eoc']} | {c['autonomous_eoc']} | {c['runtime_assisted_eoc']} | {c['runtime_intervention_rate']} |")
    report += ['',
               '## 有效 Bundle：Decision / Safety / Cost', '',
               '| World / seed | Runtime | 新世界 EOC 前→后 | Decision 正确 前→后 | FA / FB / UNKNOWN 后 | 实际违规 | stable 退步 | Tokens 前→后 |',
               '|---|---|---|---|---|---:|---:|---|']
    for row in model['independent']:
        for runtime, r in row['runtime_results'].items():
            report.append(f"| {row['world']}/{row['seed']} | {runtime} | {r['before_new_eoc']:.3f}→{r['after_new_eoc']:.3f} | "
                f"{r['before_decision_correct']}→{r['after_decision_correct']} / {r['decision_tasks']} | "
                f"{r['after_decision_false_allow']} / {r['after_decision_false_block']} / {r['after_decision_unknown']} | "
                f"{r['actual_violations']} | {r['stable_regressions']} | {r['before_tokens']}→{r['after_tokens']} |")
    report += ['', 'Decision 为独立首动作探针；UNKNOWN 单列，不能当作正确阻断。Tokens 为完整 test 的逻辑比较成本，跨臂缓存复用不重复计入实际资源账本。', '',
               '## 连续 epoch 与实际 Agent 父链', '',
               '| Epoch | World | CPU 更新 | Runtime | Agent 更新 | EOC 前→后 | stable 退步 | 实际违规 |',
               '|---:|---|---|---|---|---|---:|---:|']
    for boundary, row in zip(cpu['continuous'], model['continuous']):
        for runtime, r in row['runtime_results'].items():
            report.append(f"| {row['epoch']} | {row['world']} | {boundary['boundary_admitted']} | {runtime} | "
                f"{r['agent_admitted']} | {r['before_new_eoc']:.3f}→{r['after_new_eoc']:.3f} | {r['stable_regressions']} | {r['actual_violations']} |")
    report += ['', 'CPU 与每种 Runtime 的实际 Agent lineage 分开；被拒绝的提案不成为下一 epoch 的 Agent 父版本。', '',
               '## 审计与资源', '',
               f"独立审计通过 {receipt['totals']['executions']} 条实际模型执行与 {receipt['totals']['receipts']} 份 VerificationReceipt。",
               f"v1.1 开发及正式累计计费 {receipt['charged_tokens_all_v11']:,} tokens、{receipt['closed_invocation_seconds_all_v11']/3600:.3f} 小时（含失败预留与调用启动/关闭）。",
               f"基础设施失败 {receipt['infrastructure_failures']} 次，失败 token 保守预留 {receipt['reserved_failure_tokens']:,}。",
               '结论限于已声明的规则世界和有限代表场景；权重保持不变，未执行 Continual SFT。', '']
    accounting = receipt.get('resource_accounting', {})
    if accounting.get('amendment_hash'):
        report += ['## 睡眠中断与协议修正披露', '',
            '本轮在原冻结墙钟预算下中断，后依据 Windows 系统电源日志进行基础设施计时修正后续跑。原记录完整保留，不能声称满足未经修正的原墙钟预算。',
            f"修正记录：`{accounting['amendment_hash']}`。原始墙钟 {accounting['raw_closed_seconds']/3600:.3f} 小时；证实睡眠扣除 {accounting['excluded_sleep_seconds']/3600:.3f} 小时；修正后 {accounting['reconciled_closed_seconds']/3600:.3f} / 12 小时。",
            '扣除范围仅为日志证实的睡眠区间，并保留 60 秒过渡余量；这不是 GPU 利用率测量。失败 token 预留、重试限制、模型、数据、准入和统计规则未修改。', '']
    text = '\n'.join(report); target = root/'REPORT.md'
    if target.exists():
        if target.read_text(encoding='utf-8') != text:
            raise ValueError('existing final report differs')
    else:
        target.write_text(text, encoding='utf-8')
    return {'status': 'complete', 'report': target.as_posix(), 'tokens': receipt['charged_tokens_all_v11']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('results/active-evolution/v1.1/formal-A-v2'))
    parser.add_argument('--invocation', required=True)
    parser.add_argument('--wait', action='store_true')
    args = parser.parse_args()
    if len(args.invocation) != 32 or any(c not in '0123456789abcdef' for c in args.invocation):
        raise ValueError('invalid invocation ID')
    final = args.root/'model-layer/invocations'/(args.invocation+'.final.json')
    if not (final.with_name(args.invocation+'.start.json')).exists():
        raise ValueError('unknown invocation')
    sources = {str(Path(__file__).resolve()): file_hash(__file__),
               str(Path('scripts/audit_execution_aware.py').resolve()): file_hash('scripts/audit_execution_aware.py')}
    deadline = time.monotonic()+13*3600
    while args.wait and not final.exists() and time.monotonic() < deadline:
        time.sleep(10)
    if not final.exists():
        raise RuntimeError('invocation is still open; final report not generated')
    if any(file_hash(path) != digest for path, digest in sources.items()):
        raise RuntimeError('reporter source changed during wait; restart read-only finalizer before emitting provenance')
    # A close record can briefly be visible while its immutable JSON is being written.
    for attempt in range(3):
        try:
            print(json.dumps(finalize(args.root, args.invocation)), flush=True)
            return
        except json.JSONDecodeError:
            if attempt == 2:
                raise
            time.sleep(1)


if __name__ == '__main__':
    main()
