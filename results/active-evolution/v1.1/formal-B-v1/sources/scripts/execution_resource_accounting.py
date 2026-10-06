"""Explicit, evidence-backed sleep amendment; never rewrites the raw ledger."""
from datetime import datetime
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_schemas import fingerprint


AMENDMENT = 'recovery/sleep-20261005/accounting-amendment.json'
NS = {'e': 'http://schemas.microsoft.com/win/2004/08/events/event'}


def timestamp(value):
    # Windows emits seven fractional digits; Python 3.10 accepts microseconds.
    value = re.sub(r'(\.\d{6})\d+', r'\1', value)
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def verified_interval(path, invocation_start, invocation_end):
    """Require paired sleep/wake providers and bound interval to this invocation."""
    events = ET.parse(path).getroot().findall('e:Event', NS)
    sleeps, wakes = [], []
    for event in events:
        system = event.find('e:System', NS)
        provider = system.find('e:Provider', NS).attrib['Name']
        event_id = system.findtext('e:EventID', namespaces=NS)
        data = {d.attrib['Name']: d.text for d in event.findall('e:EventData/e:Data', NS)}
        if provider == 'Microsoft-Windows-Kernel-Power' and event_id == '42':
            sleeps.append(timestamp(system.find('e:TimeCreated', NS).attrib['SystemTime']))
        if provider == 'Microsoft-Windows-Power-Troubleshooter' and event_id == '1':
            wakes.append((timestamp(data['SleepTime']), timestamp(data['WakeTime'])))
    candidates = []
    for start, end in wakes:
        for sleep in sleeps:
            if abs(sleep-start) < 5 and invocation_start <= min(start, sleep) < end <= invocation_end:
                candidates.append((max(start, sleep), end))
    if len(candidates) != 1:
        raise ValueError('exactly one corroborated sleep interval inside invocation required')
    start, end = candidates[0]
    # Retain a full minute of transition time as charged, never credit uncertainty.
    if end-start <= 60:
        raise ValueError('sleep interval too short for conservative credit')
    return {'sleep_start_unix': start, 'wake_unix': end,
            'transition_margin_seconds': 60, 'excluded_seconds': end-start-60}


def sleep_accounting(root, protocol):
    import json
    root = Path(root)
    raw = protocol['prior_invocation_seconds'] + sum(
        json.loads(p.read_text(encoding='utf-8'))['seconds']
        for p in (root/'model-layer/invocations').glob('*.final.json'))
    result = {'raw_closed_seconds': raw, 'excluded_sleep_seconds': 0,
              'reconciled_closed_seconds': raw, 'amendment_hash': None,
              'original_wall_budget_exceeded': raw > protocol['config']['limits']['shared_gpu_seconds']}
    path = root/AMENDMENT
    if not path.exists():
        return result
    record = json.loads(path.read_text(encoding='utf-8')); amendment = record['amendment']
    if fingerprint(amendment) != record['amendment_hash'] or amendment['protocol_hash'] != fingerprint(protocol):
        raise ValueError('sleep amendment identity mismatch')
    for relative, digest in amendment['evidence_hashes'].items():
        target = (root/relative).resolve()
        if not target.is_relative_to(root.resolve()) or file_hash(target) != digest:
            raise ValueError('sleep evidence integrity mismatch')
    interval = verified_interval(root/amendment['power_events'], amendment['invocation_start_unix'], amendment['invocation_end_unix'])
    if interval != amendment['interval'] or raw < interval['excluded_seconds']:
        raise ValueError('invalid sleep accounting credit')
    result.update(excluded_sleep_seconds=interval['excluded_seconds'],
                  reconciled_closed_seconds=raw-interval['excluded_seconds'], amendment_hash=record['amendment_hash'])
    return result
