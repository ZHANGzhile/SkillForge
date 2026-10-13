import json
import time

import pytest

from scripts.execution_aware_formal import H0
from scripts.execution_aware_protocol import design
from scripts.execution_resource_accounting import AMENDMENT, sleep_accounting, verified_interval, timestamp
from scripts.prepare_active_evolution import file_hash
from scripts.resume_execution_after_sleep import SleepReconciledLedger
from skillforge.evolution_schemas import fingerprint


def setup_amendment(root):
    events = root/'power.xml'
    events.write_text('''<Events>
    <Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System><Provider Name="Microsoft-Windows-Kernel-Power"/><EventID>42</EventID><TimeCreated SystemTime="2026-10-05T01:00:01Z"/></System></Event>
    <Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event"><System><Provider Name="Microsoft-Windows-Power-Troubleshooter"/><EventID>1</EventID></System><EventData><Data Name="SleepTime">2026-10-05T01:00:00Z</Data><Data Name="WakeTime">2026-10-05T10:00:00Z</Data></EventData></Event>
    </Events>''')
    protocol = {'config': {'limits': design()['limits']}, 'model_settings': {},
                'prior_charged_tokens': 100, 'prior_invocation_seconds': 100}
    start, end = 1791154800, 1791200000
    interval = verified_interval(events, start, end)
    assert interval['excluded_seconds'] == 9*3600-61
    inv = root/'model-layer/invocations'; inv.mkdir(parents=True)
    (inv/'old.start.json').write_text('{}')
    (inv/'old.final.json').write_text(json.dumps({'seconds': 47000}))
    amendment = {'protocol_hash': fingerprint(protocol), 'power_events': 'power.xml',
                 'invocation_start_unix': start, 'invocation_end_unix': end,
                 'interval': interval, 'evidence_hashes': {'power.xml': file_hash(events)}}
    target = root/AMENDMENT; target.parent.mkdir(parents=True)
    target.write_text(json.dumps({'amendment': amendment, 'amendment_hash': fingerprint(amendment)}))
    return protocol, events


def test_sleep_credit_is_evidence_bound_and_only_applied_once(tmp_path):
    protocol, events = setup_amendment(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    a = sleep_accounting(tmp_path, protocol)
    b = sleep_accounting(tmp_path, protocol)
    assert a == b and a['raw_closed_seconds'] == 47100
    assert a['reconciled_closed_seconds'] == 14761
    assert a['original_wall_budget_exceeded']
    assert before == {p: p.read_bytes() for p in before}
    (tmp_path/'model-layer/invocations/next.final.json').write_text('{"seconds": 10}')
    assert sleep_accounting(tmp_path, protocol)['reconciled_closed_seconds'] == 14771
    events.write_text(events.read_text().replace('10:00:00', '11:00:00'))
    with pytest.raises(ValueError, match='integrity'):
        sleep_accounting(tmp_path, protocol)


def test_sleep_outside_invocation_cannot_supply_credit(tmp_path):
    _, events = setup_amendment(tmp_path)
    with pytest.raises(ValueError, match='exactly one'):
        verified_interval(events, 0, 1)


def test_windows_seven_digit_event_timestamps():
    assert timestamp('2026-10-05T01:01:05.3238006Z') == timestamp('2026-10-05T01:01:05.323800Z')


def test_resume_keeps_reservations_and_frozen_retry_limit(tmp_path):
    protocol, _ = setup_amendment(tmp_path)
    failure_dir = tmp_path/'model-layer/failures'; failure_dir.mkdir()
    identity = {'task_hash': fingerprint({'task_id': 't'}), 'world': 'W3', 'contract': fingerprint({}),
                'patch': H0, 'runtime': 'new', 'decision_only': False, 'protocol_hash': fingerprint(protocol),
                'model': fingerprint(protocol['model_settings'])}
    key = fingerprint(identity)
    for attempt in (0, 1):
        (failure_dir/(key+'-'+str(attempt)+'.json')).write_text(json.dumps({'reserved_tokens': 262144}))
    ledger = SleepReconciledLedger(tmp_path, protocol)
    assert ledger.charged_tokens == 524388 and ledger.retries == 2
    assert ledger.prior_seconds == 14761
    ledger.invocation_start = time.perf_counter()
    with pytest.raises(RuntimeError, match='retry limit'):
        ledger.evaluate({'task_id': 't'}, 'W3', {}, H0, 'new')


def test_new_elapsed_cost_still_hits_budget_without_model_dispatch(tmp_path):
    protocol, _ = setup_amendment(tmp_path)
    ledger = SleepReconciledLedger(tmp_path, protocol)
    ledger.invocation_start = time.perf_counter()-43200
    with pytest.raises(RuntimeError, match='budget exhausted'):
        ledger.evaluate({'task_id': 't'}, 'W3', {}, H0, 'new')
