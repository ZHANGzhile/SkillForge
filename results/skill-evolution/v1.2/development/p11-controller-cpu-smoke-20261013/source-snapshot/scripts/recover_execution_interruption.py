"""Reconcile an externally terminated serial A invocation without changing its protocol."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from scripts.active_evolution_dataset import EvaluationStore
from scripts.execution_aware_formal import H0, load, read
from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint


def identity_for(protocol, spec, world, contract, patch, runtime, decision):
    return {'task_hash': fingerprint(spec), 'world': world, 'contract': fingerprint(contract), 'patch': patch,
            'runtime': runtime, 'decision_only': decision, 'protocol_hash': fingerprint(protocol),
            'model': fingerprint(protocol['model_settings'])}


def first_uncached(root, protocol):
    """Replay only frozen dispatch ordering, using cache evidence; never call models."""
    root = Path(root); cpu = read(root/'cpu-report.json'); parents = {'old': H0, 'new': H0}
    groups = [(r, Path(protocol['data_root'])/r['world']/str(r['seed']),
               root/'model-layer/independent'/r['world']/str(r['seed']), False) for r in cpu['independent']]
    groups += [(r, root/'continuous/datasets'/str(r['epoch']), root/'model-layer/continuous'/str(r['epoch']), True)
               for r in cpu['continuous']]
    for boundary, dataset, output, continuous in groups:
        store = EvaluationStore(dataset); contract = read(dataset/'parent-skill.json')
        actual = parents if continuous else {'old': H0, 'new': H0}
        patches = {runtime: {'old': boundary['before'], 'proposal': boundary['effective'], 'agent_parent': actual[runtime]}
                   for runtime in ('old', 'new')}
        def missing(specs, runtime, phase, decision=False):
            for spec in specs:
                identity = identity_for(protocol, spec, boundary['world'], contract, patches[runtime][phase], runtime, decision)
                target = root/'model-layer/cache'/(fingerprint(identity)+'.json')
                if not target.exists():
                    return identity
                record = read(target)
                if record['identity'] != identity or record['result_hash'] != fingerprint(record['result']):
                    raise ValueError('cache evidence changed during dispatch reconstruction')
        valid = store.read('model_validation'); stable = store.read('model_stable_validation')
        for runtime in ('old', 'new'):
            for phase, decision in (('agent_parent', False), ('proposal', False), ('agent_parent', True), ('proposal', True)):
                pending = missing(valid if decision else valid+stable, runtime, phase, decision)
                if pending:
                    return pending
        if not (output/'evaluation-freeze.json').exists():
            # Held-out model dispatch is impossible before this durable freeze.
            return None
        activation = read(output/'activation.json'); freeze = read(output/'evaluation-freeze.json')
        if activation['actual_agent_parents'] != actual:
            raise ValueError('actual Agent parent chain differs')
        test = store.read('model_test', activation, freeze); stable_test = store.read('model_stable_test', activation, freeze)
        for runtime in ('old', 'new'):
            for decision in (False, True):
                for phase in ('old', 'proposal', 'agent_parent'):
                    pending = missing(test if decision else test+stable_test, runtime, phase, decision)
                    if pending:
                        return pending
        if not (output/'report.json').exists():
            return None
        if continuous:
            if not (output/'lineage.json').exists():
                return None
            report = read(output/'report.json')
            parents = {runtime: report['runtime_results'][runtime]['effective_patch'] for runtime in ('old', 'new')}
    return None


def verify_no_runner():
    import psutil
    names = {'scripts.execution_aware_formal', 'skillforge.execution_aware.worker'}
    found = []
    for process in psutil.process_iter(['name', 'cmdline']):
        if process.info['name'] and process.info['name'].lower() == 'python.exe' and process.info['cmdline'] is None:
            raise RuntimeError('a Python process is not inspectable; host-level verification required')
        if names.intersection(process.info['cmdline'] or []):
            found.append(process.pid)
    if found:
        raise RuntimeError('A runner or worker still exists: '+str(found))
    return {'matching_live_processes': [], 'checked_utc': datetime.now(timezone.utc).isoformat()}


def plan(root, invocation):
    root = Path(root); protocol = load(root)
    start = root/'model-layer/invocations'/(invocation+'.start.json')
    final = start.with_name(invocation+'.final.json')
    if not start.exists() or final.exists():
        raise ValueError('exactly one unreconciled invocation start is required')
    opens = [p for p in start.parent.glob('*.start.json') if not p.with_name(p.name.replace('.start.json', '.final.json')).exists()]
    if opens != [start]:
        raise ValueError('multiple unreconciled invocations require separate investigation')
    if read(start)['protocol_hash'] != fingerprint(protocol):
        raise ValueError('invocation protocol differs')
    cache = list((root/'model-layer/cache').glob('*.json'))
    for path in cache:
        record = read(path)
        if (path.stem != fingerprint(record['identity']) or record['result_hash'] != fingerprint(record['result'])
                or record['identity']['protocol_hash'] != fingerprint(protocol)):
            raise ValueError('cached execution identity mismatch')
    pending = first_uncached(root, protocol)
    return {'protocol_hash': fingerprint(protocol), 'invocation': invocation, 'completed_cache_entries': len(cache),
            'cache_tokens': sum(read(p)['result']['agent']['metrics']['tokens'] for p in cache),
            'possible_unrecorded_dispatch': pending,
            'reserved_tokens': ((1 if pending['decision_only'] else 16)*16384) if pending else 0,
            'start_file_sha256': file_hash(start), 'start_file_mtime_utc': datetime.fromtimestamp(start.stat().st_mtime, timezone.utc).isoformat(),
            'scope': 'first possible unfinished serial dispatch; reservation does not assert it actually ran'}


def reserve_unfinished(root, proposal, limits):
    pending = proposal['possible_unrecorded_dispatch']
    if pending is None:
        return
    root = Path(root); key = fingerprint(pending)
    same = list((root/'model-layer/failures').glob(key+'-*.json'))
    existing = [read(p) for p in same if read(p).get('invocation') == proposal['invocation']]
    if existing:
        if len(existing) != 1 or existing[0]['identity'] != pending or existing[0]['reserved_tokens'] != proposal['reserved_tokens']:
            raise ValueError('existing interruption reservation differs')
        return
    immutable_json(root/'model-layer/failures'/(key+'-'+str(len(same))+'.json'), {
        'identity': pending, 'reserved_tokens': proposal['reserved_tokens'],
        'seconds': limits['task_wall_seconds'], 'error_type': 'ExternalInvocationInterrupted',
        'invocation': proposal['invocation'], 'scope': 'conservative reservation for at most one unfinished serial task; fresh environment retry only'})


def recover(root, invocation):
    root = Path(root); verified = verify_no_runner(); proposal = plan(root, invocation); protocol = load(root)
    recovery = root/'recovery'/invocation
    immutable_json(recovery/'reconciliation-plan.json', proposal)
    lock = Path('.runtime/active-evolution-gpu-lease.json')
    if lock.exists():
        lease = read(lock)
        if lease.get('scope') != 'serial active-evolution GPU evaluation' or not set(lease['services']) <= {'project-web.pid', 'trained-student.pid'}:
            raise ValueError('unknown GPU lease owner')
        immutable_json(recovery/'orphaned-lease.json', {'lease': lease, 'sha256': file_hash(lock), 'process_verification': verified})
        verify_no_runner()
        lock.unlink()
    elif not (recovery/'orphaned-lease.json').exists():
        raise ValueError('missing GPU lease evidence; inspect before recovery')
    # Restore the formerly leased services so the resumed frozen lease can
    # capture and restore their exact live commands/environment normally.
    from scripts.start_active_evolution_workbench import start as restore_services
    restored = restore_services()
    verify_no_runner()
    reserve_unfinished(root, proposal, protocol['config']['limits'])
    failures = list((root/'model-layer/failures').glob('*.json'))
    total_tokens = protocol['prior_charged_tokens']+proposal['cache_tokens']+sum(read(p)['reserved_tokens'] for p in failures)
    start = root/'model-layer/invocations'/(invocation+'.start.json')
    # Includes the dead interval, service restoration, and a 60-second margin
    # preceding the durable start file. This is deliberately not exact GPU time.
    seconds = max(0, time.time()-start.stat().st_mtime)+60
    record = {'protocol_hash': fingerprint(protocol), 'status': 'incomplete', 'seconds': seconds,
        'charged_tokens_all_v11': total_tokens, 'infrastructure_failures': len(failures),
        'reconciled_external_interruption': True, 'clock_basis': 'wall clock through verified process absence and service restoration plus 60s margin',
        'reconciliation_plan_hash': fingerprint(proposal), 'recovery_script_sha256': file_hash(__file__), 'services_restored': restored,
        'process_verification': verified, 'completed_cache_entries': len(list((root/'model-layer/cache').glob('*.json')))}
    immutable_json(start.with_name(invocation+'.final.json'), record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('results/active-evolution/v1.1/formal-A-v2'))
    parser.add_argument('--invocation', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if len(args.invocation) != 32 or any(c not in '0123456789abcdef' for c in args.invocation):
        raise ValueError('invalid invocation ID')
    value = recover(args.root, args.invocation) if args.apply else plan(args.root, args.invocation)
    print(json.dumps(value, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
