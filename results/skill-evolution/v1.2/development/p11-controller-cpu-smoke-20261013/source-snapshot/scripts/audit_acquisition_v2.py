"""Independent evidence replay for B; no new probes, labels or model calls."""
import argparse
from pathlib import Path

from scripts.acquisition_v2_protocol import DEV, ROOT, aggregate, error_counts, load, select_variant, verify_sources
from scripts.evaluate_challenge_evolution import Evaluator
from scripts.active_evolution_dataset import public_candidate
from scripts.execution_aware_formal import H0, read
from scripts.prepare_active_evolution import file_hash
from skillforge.belief import BeliefState
from skillforge.evolution_config import LearningOptions
from skillforge.evolution_registry import EvolutionRegistry, boundary_admission, immutable_json
from skillforge.evolution_schemas import Candidate, EvidenceView, Hypothesis, fingerprint
from skillforge.execution_aware.challenge import ChallengeOptions, challenge_gate


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_run(dataset, directory, cache, row, config, formal, acquisition):
    packet = read(directory/'learner-packet.json'); summary = read(directory/'summary.json')
    learner = read(directory/'learner/summary.json'); signature = read(directory/'learner/identity.json')
    require(all(row[k] == v for k,v in summary.items()), 'aggregate differs from run summary')
    require(packet['method'] == row['method'] and packet['learning'] == config['learning'], 'method/learning identity differs')
    require(packet['acquisition']==acquisition and packet['challenge']==config['challenge'], 'acquisition identity differs')
    evaluator = Evaluator(dataset, cache); store = evaluator.store
    require(packet['identity']['dataset_hash'] == fingerprint(store.manifest), 'learner dataset identity differs')
    specs = {s['task_id']:s for split in ('seed','explore','validation','stable_validation') for s in store.read(split)}
    effective = read(directory/'effective-version.json'); freeze = read(directory/'evaluation-freeze.json')
    if formal:
        specs.update({s['task_id']:s for split in ('test','stable_test') for s in store.read(split,effective,freeze)})
    queries = [read(p) for p in sorted((directory/'learner/queries').glob('query_*.json'))]
    required_ids = {k for k,s in specs.items() if s['split'] != 'explore'} | {q['candidate_id'] for q in queries}
    require(all((cache/'private-probes'/(k+'.json')).exists() for k in required_ids), 'missing raw probe: audit refuses to execute new probes')
    expected_seed = [evaluator.evidence(s).model_dump() for s in store.read('seed')]
    require(packet['seed_evidence'] == expected_seed, 'seed evidence differs from raw probes')
    options = LearningOptions.model_validate(config['learning'])
    belief = BeliefState([Hypothesis.model_validate(h) for h in packet['hypotheses']],packet['identity']['policy_epoch'],
                        options.accuracy,options.other_prior,options.complexity_lambda)
    candidates = [Candidate.model_validate(c) for c in packet['candidates']]
    require(packet['candidates']==[public_candidate(s,evaluator.contract).model_dump() for s in store.read('explore')], 'public candidate pool differs')
    for evidence in expected_seed:
        belief.update(EvidenceView.model_validate(evidence))
    used = set()
    require(len(queries) == summary['queries'] <= options.max_queries, 'query budget/charging differs')
    for i,q in enumerate(queries):
        require(q['index'] == i and q['candidate_id'] not in used, 'query order or uniqueness differs')
        require(q['row_hash'] == fingerprint({k:v for k,v in q.items() if k!='row_hash'}), 'query hash differs')
        require(q['identity_hash'] == fingerprint(signature), 'query signature differs')
        spec = specs[q['candidate_id']]
        require(spec['split']=='explore' and evaluator.evidence(spec).model_dump()==q['evidence'], 'query evidence differs from executed raw probe')
        require(q['evidence_hash']==fingerprint(q['evidence']), 'evidence hash differs')
        learned = row['method']!='passive' or q['evidence']['label']=='not_executable'
        require(q['learned']==learned,'passive update policy differs')
        if learned:
            belief.update(EvidenceView.model_validate(q['evidence']))
        used.add(q['candidate_id'])
    raw = belief.convergence(candidates,**options.convergence_args()); gate = None
    top = next(h for h in belief.hypotheses if h.hypothesis_id==raw['hypothesis_id'])
    if packet['method']=='active_v2' and raw['converged'] and top.kind=='no_change':
        gate = challenge_gate(belief,candidates,{q['candidate_id']:q['evidence'] for q in queries},ChallengeOptions(**config['challenge']))
    certified = raw['converged'] and (gate is None or gate['passed'])
    require(summary['raw_belief_converged']==raw['converged'] and summary['belief_converged']==certified and summary['h0_challenge']==gate,
            'belief/challenge certification differs')
    require(summary['convergence']=={**raw,'converged':certified},'posterior convergence differs')
    require(summary['queries_to_convergence']==(len(queries) if certified and row['method']!='no_adapt' else None),'convergence censoring differs')
    candidate_path = directory/'learner/candidate.json'; passed = False; nontrivial = False
    expected_effective = H0
    if candidate_path.exists():
        candidate = read(candidate_path)
        require(candidate['belief_hash']==fingerprint(belief.snapshot()),'candidate belief binding differs')
        validation = read(directory/'validation.json')
        require(evaluator.validate(candidate)==validation,'validation not supported by raw probes')
        proposed = Hypothesis.model_validate(candidate['hypothesis'])
        nontrivial = any(proposed.predict(c.observations,c.baseline_prediction,c.guard_prediction) is not None
            and proposed.predict(c.observations,c.baseline_prediction,c.guard_prediction)!=c.baseline_prediction for c in candidates)
        passed = boundary_admission(candidate,validation) and validation['stable_regressions']==0
        require(summary['boundary_validation_passed']==passed,'Boundary validation differs')
        if passed and nontrivial and row['method']!='no_adapt':
            expected_effective = proposed.model_dump(mode='json')
            EvolutionRegistry(directory/'registry').load(summary['registry_version'])
    else:
        require(not certified and row['method']!='no_adapt','missing frozen candidate')
    require(summary['nontrivial']==nontrivial and summary['boundary_admitted']==bool(passed and nontrivial and row['method']!='no_adapt'),'Boundary admission differs')
    require(effective['effective_hypothesis']==expected_effective,'effective fallback differs')
    diagnostic = read(directory/'diagnostic-freeze.json')
    require(diagnostic['candidate']=={'top_hypothesis':top.model_dump(mode='json'),'learner_summary_hash':fingerprint(learner)},'diagnostic not frozen after learning')
    splits = ('test','stable_test') if formal else ('validation','stable_validation')
    cases = evaluator.measure(top,splits,diagnostic['candidate'],diagnostic['freeze'])
    require(read(directory/'top-diagnostic.json')['cases']==cases,'top diagnostic differs from raw probes')
    counts = error_counts(cases); require(row['top_diagnostic']==counts,'top diagnostic counters differ')
    for prefix, converged in (('raw_',raw['converged']),('',certified)):
        bad = bool(converged and counts['changed_errors'] and row['method']!='no_adapt')
        require(row[prefix+'false_convergence']==bad and row[prefix+'h0_false_convergence']==(bad and top.kind=='no_change'),'false convergence accounting differs')
    if formal:
        cases = evaluator.measure(Hypothesis.model_validate(expected_effective),splits,effective,freeze)
        require(read(directory/'test.json')['cases']==cases and row['effective_test']==error_counts(cases),'effective heldout evidence differs')
    return {'world':row['world'],'seed':row['seed'],'method':row['method'],
            'metrics_hash':file_hash(directory/'metrics.json'),'queries':len(queries),'passed':True}


def audit(development=False):
    if development:
        registration = read(DEV/'registration.json'); verify_sources(registration['sources'])
        report = read(DEV/'report.json'); config = registration['config']; root = DEV
        require(report['selection']==select_variant(report['runs'],config),'development selection differs')
    else:
        protocol = load(); report = read(ROOT/'cpu-report.json'); config = protocol['config']; root = ROOT
        require(report['protocol_hash']==fingerprint(protocol),'formal report protocol differs')
        require(report['aggregate']==aggregate(report['runs'],config),'formal aggregate differs')
    checked = []
    for row in report['runs']:
        directory = root/('runs' if development else 'cpu')/row['world']
        directory = directory/row['variant'] if development else directory/str(row['seed'])/row['method']
        cache = root/'private-probes'/row['world']
        if not development:
            cache = cache/str(row['seed'])
        acquisition = config['variants'][row['variant']]['acquisition'] if development else (protocol['selected_acquisition'] if row['method']=='active_v2' else {})
        checked.append(check_run(root/'datasets'/row['world']/str(row['seed']),directory,cache,row,config,not development,acquisition))
        print({'audited_runs':len(checked),'total':len(report['runs'])},flush=True)
    receipt = {'passed':True,'complete':True,'runs':checked,'report_hash':file_hash(root/('report.json' if development else 'cpu-report.json')),
               'auditor_sha256':file_hash(__file__),
               'scope':'read-only raw-probe, posterior, challenge, admission, heldout and aggregate replay; no new queries; acquisition ranking is source-bound, not independently recomputed'}
    immutable_json(root/'audits/evidence.json',receipt)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--development',action='store_true');args=parser.parse_args()
    audit(args.development)
