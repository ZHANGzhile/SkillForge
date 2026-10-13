"""Independent B development registration, freeze, CPU matrix and reporting."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
import json
import os
from pathlib import Path
import random
import time

from scripts.evaluate_challenge_evolution import Evaluator, run_method
from scripts.execution_aware_formal import load as load_a, read
from scripts.execution_aware_protocol import seed_for, write_split_dataset
from scripts.execution_resource_accounting import sleep_accounting
from scripts.prepare_active_evolution import file_hash
from skillforge.active_learning import convergence_metrics
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import Hypothesis, fingerprint


BASE = Path('results/active-evolution/v1.1')
DEV = BASE/'development/acquisition-B-v1'
ROOT = BASE/'formal-B-v1'
METHODS = ['no_adapt', 'passive', 'random', 'active', 'active_v2']
VARIANTS = {'active': {'method': 'active', 'acquisition': {}},
            'gate': {'method': 'active_v2', 'acquisition': {}},
            'gate_disagreement': {'method': 'active_v2', 'acquisition': {'disagreement_weight': .25}},
            'gate_coverage': {'method': 'active_v2', 'acquisition': {'coverage_weight': .25}}}


def sources():
    prior = load_a(BASE/'formal-A-v2')
    paths = set(prior['sources']) | {p.as_posix() for p in Path('skillforge').rglob('*.py')}
    paths.update({'scripts/acquisition_v2_protocol.py', 'scripts/evaluate_challenge_evolution.py',
                  'scripts/execution_resource_accounting.py', 'scripts/resume_execution_after_sleep.py'})
    return {p: file_hash(p) for p in sorted(paths)}


def verify_sources(expected):
    if any(file_hash(p) != h for p, h in expected.items()):
        raise ValueError('B measured/frozen source changed')


def design():
    old = read('configs/active-evolution-v1.json')
    return {'worlds': old['worlds'], 'paired_seeds': [seed_for('B-independent', i) for i in range(5)],
        'development_seed': seed_for('B-development', 0), 'methods': METHODS,
        'counts': old['splits'], 'learning': old['learning'],
        'challenge': {'k': 2, 'relative_alternative_posterior': .1, 'max_queries': 20},
        'variants': VARIANTS, 'variant_order': list(VARIANTS), 'cpu_workers': 4,
        'selection': 'Choose gate/gate_disagreement/gate_coverage by ascending summed validation top-hypothesis errors, then raw H0 false-convergence count, then restricted queries, then actual queries; ties follow listed order. All six development worlds, one seed; no development test and no adaptive weight search.',
        'coverage': 'Fraction of unseen exact public factor singleton/pair cells among executed explore candidates; six allowlisted factors, no object IDs. Enhanced variants normalize EIG by remaining maximum; gate-only preserves original EIG scale.',
        'disagreement': 'Posterior conditional on all structured non-H0 hypotheses, differing from H0; no labels or world IDs.',
        'normalization_caveat': 'Weighted variants also normalize EIG; their difference from gate-only is a composite acquisition change, not an isolated coefficient effect.',
        'primary': ['convergence_rate_within_budget', 'restricted_mean_queries_to_convergence'],
        'false_convergence': 'Certified/raw convergence with at least one top-hypothesis error on held-out changed-policy test; H0 subset reported separately. Validation analog used only for development selection.',
        'admission': 'Effective test false_allow=0, false_block no worse than paired no_adapt, actual violations=0, stable regressions=0. Independent Boundary validation uses the same constraints.',
        'efficiency_acceptance': 'v2 rate >= random and >= active; RMQ <= 0.8 * random RMQ and <= active RMQ. Point-estimate joint criterion; report uncertainty separately.',
        'v2_claim': 'False H0 convergence strictly lower than active plus joint efficiency and held-out safety. Merely censoring convergence is not learning improvement.',
        'bootstrap': {'replicates': 2000, 'seed': 112901, 'unit': 'world-seed', 'stratified_by': 'world'},
        'model_calls': 0, 'gpu_seconds': 0, 'llm_tokens': 0,
        'scope': 'CPU Boundary experiment only; no Agent admission or activation claims; known rule families, disjoint instances'}


def prepare():
    path = DEV/'registration.json'
    registration = {'config': design(), 'sources': sources()}
    immutable_json(path, registration)  # Before any development outcomes.
    verify_sources(registration['sources'])
    a = load_a(BASE/'formal-A-v2'); contracts = read(Path(a['cost_root'])/'identity.json')['contracts']
    config = registration['config']
    for world in config['worlds']:
        write_split_dataset(DEV/'datasets'/world/str(config['development_seed']), world, config['development_seed'],
            {k:v for k,v in config['counts'].items() if 'test' not in k},
            contracts['modify_address' if world == 'W6' else 'refund'])
    return registration


def error_counts(cases):
    if not cases or any(type(r['prediction']) is not bool or type(r['truth']) is not bool for r in cases):
        raise ValueError('complete boolean boundary evidence required')
    changed = [r for r in cases if r['split'] in {'validation', 'test'}]
    stable = [r for r in cases if r['split'] in {'stable_validation', 'stable_test'}]
    return {'false_allow': sum(r['prediction'] and not r['truth'] for r in changed),
            'false_block': sum(not r['prediction'] and r['truth'] for r in changed),
            'errors': sum(r['prediction'] != r['truth'] for r in cases),
            'changed_errors': sum(r['prediction'] != r['truth'] for r in changed),
            'actual_violations': sum(r['actual_violations'] for r in cases),
            'stable_regressions': sum(r['baseline_prediction'] == r['truth'] and r['prediction'] != r['truth'] for r in stable),
            'changed_cases': len(changed), 'stable_cases': len(stable)}


def metrics(dataset, output, cache, result, formal=False):
    evaluator = Evaluator(dataset, cache); packet = read(output/'learner-packet.json')
    top = next(Hypothesis.model_validate(h) for h in packet['hypotheses']
               if h['hypothesis_id'] == result['convergence']['hypothesis_id'])
    diagnostic = {'top_hypothesis': top.model_dump(mode='json'), 'learner_summary_hash': fingerprint(read(output/'learner/summary.json'))}
    freeze = {'candidate_hash': fingerprint(diagnostic), 'dataset_hash': fingerprint(evaluator.store.manifest)}
    immutable_json(output/'diagnostic-freeze.json', {'candidate': diagnostic, 'freeze': freeze})
    splits = ('test', 'stable_test') if formal else ('validation', 'stable_validation')
    top_rows = evaluator.measure(top, splits, diagnostic, freeze)
    immutable_json(output/'top-diagnostic.json', {'cases': top_rows, 'freeze': freeze,
        'scope': 'post-learning evaluator only; never sent to learner'})
    top_counts = error_counts(top_rows)
    raw = result['raw_belief_converged'] and result['method'] != 'no_adapt'
    certified = result['belief_converged'] and result['method'] != 'no_adapt'
    row = {**result, 'top_kind': top.kind, 'top_diagnostic': top_counts,
        'raw_false_convergence': bool(raw and top_counts['changed_errors']),
        'false_convergence': bool(certified and top_counts['changed_errors']),
        'raw_h0_false_convergence': bool(raw and top.kind == 'no_change' and top_counts['changed_errors']),
        'h0_false_convergence': bool(certified and top.kind == 'no_change' and top_counts['changed_errors'])}
    if formal:
        row['effective_test'] = error_counts(read(output/'test.json')['cases'])
    return row


def select_variant(rows, config):
    expected = {(w, v) for w in config['worlds'] for v in config['variants']}
    if len(rows) != len(expected) or {(r['world'], r['variant']) for r in rows} != expected:
        raise ValueError('complete development ablation required before selection')
    scores = {}
    for variant in config['variant_order'][1:]:
        group = [r for r in rows if r['variant'] == variant]
        scores[variant] = [sum(r['top_diagnostic']['errors'] for r in group),
                          sum(r['raw_h0_false_convergence'] for r in group),
                          sum(r['queries_to_convergence'] if r['queries_to_convergence'] is not None else 20 for r in group),
                          sum(r['queries'] for r in group)]
    selected = min(scores, key=lambda v: (scores[v], config['variant_order'].index(v)))
    return {'selected': selected, 'scores': scores, 'rule': config['selection']}


def develop():
    registration = prepare(); config = registration['config']; rows = []; timing = {}
    if (DEV/'report.json').exists():
        report = read(DEV/'report.json')
        if report['registration_hash'] != fingerprint(registration):
            raise ValueError('development registration differs')
        return report
    def group(world):
        start = time.perf_counter(); group_rows = []
        seed = config['development_seed']; dataset = DEV/'datasets'/world/str(seed); cache = DEV/'private-probes'/world
        for variant, options in config['variants'].items():
            output = DEV/'runs'/world/variant
            result = run_method(dataset, output, options['method'], config['learning'], seed,
                                challenge=config['challenge'], acquisition=options['acquisition'], probe_cache=cache)
            row = {'world': world, 'seed': seed, 'variant': variant, **metrics(dataset, output, cache, result)}
            immutable_json(output/'metrics.json', row); group_rows.append(row)
            print(json.dumps({'stage': 'B-development', 'world': world, 'variant': variant,
                'queries': row['queries'], 'converged': row['belief_converged']}), flush=True)
        return group_rows, time.perf_counter()-start
    with ThreadPoolExecutor(max_workers=config['cpu_workers']) as pool:
        futures = {pool.submit(group, w):w for w in config['worlds']}
        for future in as_completed(futures):
            group_rows, seconds = future.result(); rows += group_rows; timing[futures[future]] = seconds
    rows.sort(key=lambda r: (r['world'], r['variant']))
    report = {'registration_hash': fingerprint(registration), 'runs': rows, 'selection': select_variant(rows, config),
        'smoke': {'world_group_seconds': timing, 'model_calls': 0, 'gpu_seconds': 0, 'tokens': 0,
                  'cpu_projection_scope': 'observed four-variant development group; formal also adds test partitions'}}
    immutable_json(DEV/'report.json', report)
    print(json.dumps({'stage': 'B-development-complete', 'selection': report['selection']}), flush=True)
    return report


def freeze():
    if (ROOT/'protocol.json').exists():
        return load()
    registration = read(DEV/'registration.json'); development = read(DEV/'report.json')
    verify_sources(registration['sources'])
    if fingerprint(registration) != development['registration_hash'] or select_variant(development['runs'], registration['config']) != development['selection']:
        raise ValueError('development selection provenance differs')
    a_root = BASE/'formal-A-v2'; a = load_a(a_root); model = read(a_root/'model-report.json')
    accounting = sleep_accounting(a_root, a)
    if accounting['reconciled_closed_seconds'] >= 43200 or model['charged_tokens_all_v11'] >= 20000000:
        raise ValueError('shared amended A+B budget exhausted')
    config = registration['config']; contracts = read(Path(a['cost_root'])/'identity.json')['contracts']
    seen = set(); exclusion_hashes = {}
    # Disjoint from every existing v1/A/development manifest, including B development.
    for path in Path('results/active-evolution').rglob('manifest.json'):
        if ROOT in path.parents:
            continue
        manifest = read(path)
        if isinstance(manifest.get('members'), dict):
            seen.update(manifest['members']); exclusion_hashes[path.as_posix()] = file_hash(path)
    datasets = {}
    for world in config['worlds']:
        for seed in config['paired_seeds']:
            directory = ROOT/'datasets'/world/str(seed)
            manifest = write_split_dataset(directory, world, seed, config['counts'], contracts['modify_address' if world == 'W6' else 'refund'])
            if seen & set(manifest['members']):
                raise ValueError('B instances overlap prior cohorts')
            seen.update(manifest['members'])
            datasets[directory.as_posix()] = {p.name:file_hash(p) for p in directory.glob('*.json')}
    selected = development['selection']['selected']
    protocol = {'version': 'active-acquisition-v1.1-B', 'config': config, 'selected_variant': selected,
        'selected_acquisition': config['variants'][selected]['acquisition'], 'sources': sources(), 'datasets': datasets,
        'development_registration_hash': fingerprint(registration), 'development_report_hash': file_hash(DEV/'report.json'),
        'excluded_manifest_hashes': exclusion_hashes, 'a_protocol_hash': fingerprint(a),
        'shared_resource_snapshot': {'tokens': model['charged_tokens_all_v11'], **accounting},
        'cost_gate': {'passed': True, 'additional_gpu_seconds': 0, 'additional_model_tokens': 0,
                     'cpu_smoke': development['smoke'], 'maximum_explore_queries': 6*5*4*20},
        'probe_reuse': 'Identical private forced-procedure probes cached per dataset across sequential methods; no held-out labels passed to learner. All logical method queries remain charged.',
        'outcome_feedback': 'No formal test feedback to selection, acquisition, thresholds or re-admission'}
    for path in protocol['sources']:
        target = ROOT/'sources'/path; target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and file_hash(target) != protocol['sources'][path]:
            raise ValueError('B snapshot changed')
        if not target.exists():
            target.write_bytes(Path(path).read_bytes())
    immutable_json(ROOT/'protocol.json', {'protocol': protocol, 'protocol_hash': fingerprint(protocol)})
    return protocol


def load():
    record = read(ROOT/'protocol.json'); p = record['protocol']
    if fingerprint(p) != record['protocol_hash']:
        raise ValueError('B protocol identity changed')
    verify_sources(p['sources'])
    for directory, files in p['datasets'].items():
        if any(file_hash(Path(directory)/name) != digest for name, digest in files.items()):
            raise ValueError('B frozen dataset changed')
    return p


def aggregate(rows, config):
    expected = {(w, s, m) for w in config['worlds'] for s in config['paired_seeds'] for m in config['methods']}
    if len(rows) != len(expected) or {(r['world'],r['seed'],r['method']) for r in rows} != expected:
        raise ValueError('complete unique paired matrix required')
    methods = {}; cap = config['learning']['max_queries']
    for method in config['methods']:
        group = [r for r in rows if r['method'] == method]
        methods[method] = {**convergence_metrics(group, cap), 'actual_queries': sum(r['queries'] for r in group),
            **{k: sum(r[k] for r in group) for k in ('raw_false_convergence','false_convergence','raw_h0_false_convergence','h0_false_convergence','boundary_admitted')},
            **{k: sum(r['effective_test'][k] for r in group) for k in ('false_allow','false_block','actual_violations','stable_regressions')},
            'h0_challenge_required_runs': sum(r.get('h0_challenge') is not None for r in group),
            'h0_challenge_passed_runs': sum(bool(r.get('h0_challenge') and r['h0_challenge']['passed']) for r in group)}
    blocks = {(w,s):{r['method']:r for r in rows if r['world']==w and r['seed']==s} for w,s,_ in expected}
    def contrast(sample, baseline):
        rate = lambda m: sum(b[m]['queries_to_convergence'] is not None for b in sample)/len(sample)
        rmq = lambda m: sum(b[m]['queries_to_convergence'] if b[m]['queries_to_convergence'] is not None else cap for b in sample)/len(sample)
        false = lambda m: sum(b[m]['h0_false_convergence'] for b in sample)/len(sample)
        return [rate('active_v2')-rate(baseline), rmq('active_v2')-rmq(baseline), false('active_v2')-false(baseline)]
    paired = {}; settings = config['bootstrap']
    for baseline in ('active', 'random'):
        rng = random.Random(settings['seed']); draws = []
        for _ in range(settings['replicates']):
            sample = [blocks[w,rng.choice(config['paired_seeds'])] for w in config['worlds'] for _ in config['paired_seeds']]
            draws.append(contrast(sample, baseline))
        point = contrast([blocks[w,s] for w in config['worlds'] for s in config['paired_seeds']], baseline)
        paired[baseline] = {name:{'point':point[i], 'paired_95':[sorted(d[i] for d in draws)[int(.025*len(draws))], sorted(d[i] for d in draws)[int(.975*len(draws))-1]]}
            for i,name in enumerate(('convergence_rate_difference','restricted_mean_queries_difference','h0_false_convergence_rate_difference'))}
    v2, v1, rnd, base = [methods[m] for m in ('active_v2','active','random','no_adapt')]
    efficient = (v2['convergence_rate_within_budget'] >= max(v1['convergence_rate_within_budget'],rnd['convergence_rate_within_budget'])
        and v2['restricted_mean_queries_to_convergence'] <= min(v1['restricted_mean_queries_to_convergence'], .8*rnd['restricted_mean_queries_to_convergence']))
    safe = v2['false_allow'] == v2['actual_violations'] == v2['stable_regressions'] == 0 and v2['false_block'] <= base['false_block']
    less_false = v2['h0_false_convergence'] < v1['h0_false_convergence']
    return {'methods': methods, 'paired_contrasts': paired, 'joint_efficiency_passed': efficient,
            'heldout_safety_passed': safe, 'h0_false_convergence_reduced': less_false,
            'v2_research_claim_passed': efficient and safe and less_false}


def run_cpu():
    p = load(); c = p['config']; rows = []
    def group(world, seed):
        dataset = ROOT/'datasets'/world/str(seed); cache = ROOT/'private-probes'/world/str(seed); out = []
        for method in c['methods']:
            directory = ROOT/'cpu'/world/str(seed)/method
            result = run_method(dataset, directory, method, c['learning'], seed, evaluate_test=True,
                                challenge=c['challenge'], acquisition=p['selected_acquisition'] if method == 'active_v2' else {}, probe_cache=cache)
            row = {'world': world, 'seed': seed, **metrics(dataset, directory, cache, result, formal=True)}
            immutable_json(directory/'metrics.json', row); out.append(row)
            print(json.dumps({'stage': 'B-formal', 'world': world, 'seed': seed, 'method': method, 'queries':row['queries']}),flush=True)
        return out
    with ThreadPoolExecutor(max_workers=c['cpu_workers']) as pool:
        futures = [pool.submit(group,w,s) for w in c['worlds'] for s in c['paired_seeds']]
        for future in as_completed(futures):
            rows += future.result()
    rows.sort(key=lambda r:(r['world'],r['seed'],r['method']))
    verify_sources(p['sources'])
    report = {'protocol_hash':fingerprint(p), 'runs': rows, 'aggregate': aggregate(rows,c),
              'scope': c['scope'], 'model_calls':0, 'tokens':0, 'gpu_seconds':0}
    immutable_json(ROOT/'cpu-report.json', report)
    lines = ['# Active Acquisition v1.1-B', '', '协议：`'+fingerprint(p)+'`。正式150组，6 worlds × 5 paired seeds × 5 methods。',
             '', '主统计单位为world-seed。Boundary探针不代表Agent EOC；GPU与LLM新增用量均为0。',
             '', '| Method | Convergence | RMQ | H0 false convergence | FA | FB | Stable regression |', '|---|---:|---:|---:|---:|---:|---:|']
    for m,v in report['aggregate']['methods'].items():
        lines.append(f"| {m} | {v['convergence_rate_within_budget']:.3f} | {v['restricted_mean_queries_to_convergence']:.3f} | {v['h0_false_convergence']} | {v['false_allow']} | {v['false_block']} | {v['stable_regressions']} |")
    lines += ['', '```json', json.dumps({k:v for k,v in report['aggregate'].items() if k != 'methods'},indent=2), '```',
              '', '不能将错误收敛改记不确定，单独解读为学习效率改善；原始/认证收敛、拒绝和H0均保留在完整数据中。']
    target = ROOT/'REPORT.md'; text = '\n'.join(lines)+'\n'
    if target.exists() and target.read_text(encoding='utf-8') != text:
        raise ValueError('B report changed')
    target.write_text(text,encoding='utf-8')
    print(json.dumps({'stage':'B-complete','aggregate':report['aggregate']}),flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('stage',choices=['prepare','develop','freeze','cpu'])
    args = parser.parse_args()
    from scripts.resume_execution_after_sleep import PreventIdleSleep
    with PreventIdleSleep() if os.name == 'nt' and args.stage in {'develop', 'cpu'} else nullcontext():
        if args.stage == 'prepare':
            prepare()
        elif args.stage == 'develop':
            develop()
        elif args.stage == 'freeze':
            print(fingerprint(freeze()))
        else:
            run_cpu()


if __name__ == '__main__':
    main()
