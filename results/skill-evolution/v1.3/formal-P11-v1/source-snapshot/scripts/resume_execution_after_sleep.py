"""Resume frozen A through an explicitly recorded infrastructure amendment."""
import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from scripts import execution_aware_formal as formal
from scripts.execution_resource_accounting import AMENDMENT, sleep_accounting, verified_interval
from scripts.prepare_active_evolution import file_hash
from scripts.recover_execution_interruption import verify_no_runner
from skillforge.evolution_registry import immutable_json
from skillforge.evolution_schemas import fingerprint


ROOT = Path('results/active-evolution/v1.1/formal-A-v2')
INTERRUPTED = '1bdc3caed371406fb28ba95b7cc7e2c4'
FAILURE = '9272e31ad597bae113251a87515d28c4c657ce7a7e3858416e584d0c90853a92-0.json'


class PreventIdleSleep:
    """Thread-scoped Windows request, restored on exit; no global power edits."""
    def __enter__(self):
        if os.name != 'nt':
            raise RuntimeError('this recovery requires Windows power evidence')
        self.api = ctypes.WinDLL('kernel32', use_last_error=True).SetThreadExecutionState
        self.api.argtypes = [ctypes.c_uint32]; self.api.restype = ctypes.c_uint32
        self.previous = self.api(0x80000001)  # CONTINUOUS | SYSTEM_REQUIRED, display can turn off
        if not self.previous:
            raise ctypes.WinError(ctypes.get_last_error())
        return self

    def __exit__(self, *args):
        if not self.api(self.previous):
            raise ctypes.WinError(ctypes.get_last_error())


def prepare(root):
    root = Path(root); protocol = formal.load(root)
    target = root/AMENDMENT
    if target.exists():
        sleep_accounting(root, protocol)
        return formal.read(target)
    start = root/'model-layer/invocations'/(INTERRUPTED+'.start.json')
    final = start.with_name(INTERRUPTED+'.final.json')
    failure = root/'model-layer/failures'/FAILURE
    events = target.parent/'power-events.xml'
    closed, failed = formal.read(final), formal.read(failure)
    if closed['status'] != 'incomplete' or failed['error_type'] != 'TimeoutError':
        raise ValueError('unexpected interrupted invocation')
    interval = verified_interval(events, start.stat().st_mtime, final.stat().st_mtime)
    # This credit may only explain the failed dispatch, not successful-task cost.
    failed_end = failure.stat().st_mtime
    if not (failed_end-failed['seconds'] <= interval['sleep_start_unix']
            < interval['wake_unix'] <= failed_end):
        raise ValueError('sleep interval is outside failed dispatch')
    raw = sleep_accounting(root, protocol)
    amendment = {
        'protocol_hash': fingerprint(protocol), 'interrupted_invocation': INTERRUPTED,
        'authorization': 'User: 检查后找到问题解决，继续运行',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'kind': 'post-freeze infrastructure accounting amendment',
        'invocation_start_unix': start.stat().st_mtime, 'invocation_end_unix': final.stat().st_mtime,
        'power_events': events.relative_to(root).as_posix(), 'interval': interval,
        'evidence_hashes': {p.relative_to(root).as_posix(): file_hash(p) for p in (start, final, failure, events)},
        'continuation_sources': {p: file_hash(p) for p in ('scripts/resume_execution_after_sleep.py',
                                                        'scripts/execution_resource_accounting.py')},
        'raw_closed_seconds_at_reconciliation': raw['raw_closed_seconds'],
        'reconciled_closed_seconds_at_reconciliation': raw['raw_closed_seconds']-interval['excluded_seconds'],
        'preserved': ['all cached results and original records', '20M token cap and failed token reservations',
                      '12h cap after verified sleep exclusion', 'global and per-task retry caps',
                      'frozen model, data, admission, ordering and estimands'],
        'limitation': 'Original inclusive wall-clock cap was exceeded. Completion uses this disclosed amendment; not original-budget compliance. No claim of measured GPU utilization.'}
    record = {'amendment': amendment, 'amendment_hash': fingerprint(amendment)}
    immutable_json(target, record)
    return record


class SleepReconciledLedger(formal.ModelLedger):
    def __init__(self, root, protocol):
        super().__init__(root, protocol)
        self.accounting = sleep_accounting(root, protocol)
        if not self.accounting['amendment_hash']:
            raise RuntimeError('explicit amendment required before continuation')
        self.prior_seconds = self.accounting['reconciled_closed_seconds']
        # Fail before loading the GPU model if even one full attempt cannot fit.
        if (self.prior_seconds+self.limits['task_wall_seconds'] > self.limits['shared_gpu_seconds']
                or self.charged_tokens+16*16384 > self.limits['shared_tokens']):
            raise RuntimeError('reconciled budget exhausted')

    def open(self):
        opens = [p for p in (self.root/'invocations').glob('*.start.json')
                 if not p.with_name(p.name.replace('.start.json', '.final.json')).exists()]
        if len(opens) != 1:
            raise RuntimeError('exactly one active continuation invocation required')
        invocation = opens[0].name.removesuffix('.start.json')
        binding = self.root.parent/'recovery/sleep-20261005'/('binding-'+invocation+'.json')
        # open() may run again for an already permitted infrastructure retry.
        if not binding.exists():
            immutable_json(binding, {'invocation': invocation, 'protocol_hash': self.protocol_hash,
                'amendment_hash': self.accounting['amendment_hash'], 'accounting_at_start': self.accounting,
                'idle_sleep_prevention': 'SetThreadExecutionState SYSTEM_REQUIRED held by runner main thread'})
        super().open()


def run(root):
    root = Path(root)
    lock = Path('.runtime/execution-sleep-continuation.lock')
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('x', encoding='utf-8') as stream:
        json.dump({'pid': os.getpid(), 'root': str(root.resolve())}, stream)
    try:
        return run_owned(root)
    finally:
        lock.unlink()


def run_owned(root):
    verify_no_runner(); record = prepare(root)
    for path, digest in record['amendment']['continuation_sources'].items():
        if file_hash(path) != digest:
            raise ValueError('amended continuation source changed')
    before = set((root/'model-layer/invocations').glob('*.start.json'))
    original = formal.ModelLedger
    try:
        with PreventIdleSleep():
            # Narrow explicit adapter: only the prior resource total differs.
            # Frozen source files, task identities and evaluation code stay intact.
            formal.ModelLedger = SleepReconciledLedger
            print(json.dumps({'stage': 'sleep-reconciled-resume', **sleep_accounting(root, formal.load(root))}), flush=True)
            formal.run_models(root)
    finally:
        formal.ModelLedger = original
        created = set((root/'model-layer/invocations').glob('*.start.json'))-before
        for path in created:
            invocation = path.name.removesuffix('.start.json')
            if path.with_name(invocation+'.final.json').exists():
                from scripts.finalize_execution_aware import finalize
                print(json.dumps(finalize(root, invocation)), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.run:
        run(args.root)
    else:
        print(json.dumps(prepare(args.root), ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
