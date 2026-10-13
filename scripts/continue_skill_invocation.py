"""Zero-inference continuation: extend snapshot field validation, nothing else."""
import argparse
from pathlib import Path
from types import SimpleNamespace
import json

from scripts import run_skill_invocation as study
from scripts import run_interview_sprint as base
from scripts.run_skill_evolution import digest_file
from skillforge.evolution_common import snapshot
from skillforge.interview_sprint import adapters as old
from skillforge.evolution_schemas import fingerprint

DEFAULT=study.ROOT/'results/skill-invocation/20261013-v2'

# Same atomic SQL backup/envelope code, independently versioned accepted runtime
# field set. The extension fields carry their own mode and invocation-v1 schema.
# No legacy restore compatibility is claimed by this dev adapter.
save_snapshot=old.bind(snapshot.save_snapshot,{'REQUIRED':snapshot.REQUIRED|{'invocation_adapter','invocation_mode'}})
prepare=old.bind(base.original_prepare,{'save_snapshot':save_snapshot})
collection=old.bind(base.old_collection.collect_one,{'save_snapshot':save_snapshot})
proxy=SimpleNamespace(**{**vars(base),'original_prepare':prepare,
    'old_collection':SimpleNamespace(**{**vars(base.old_collection),'collect_one':collection})})


def declare(root):
    root=root.resolve();root.mkdir(parents=True,exist_ok=False)
    parent=study.DEFAULT;p=base.read(parent/'protocol.json');failed=base.read(parent/'report.json');study.check(p,inference=True)
    if failed['complete'] or failed['charged_tokens']!=0 or failed['statuses'] or failed['failure']!='ValueError: complete runtime checkpoint required':
        raise ValueError('only known pre-inference snapshot failure supported')
    if list(parent.glob('dev/**/admissions/*.json')) or list(parent.glob('dev/**/checkpoints/*/snapshot.json')):
        raise ValueError('unexpected inference/checkpoint evidence; do not implicitly retry')
    cpu=sum(len(e['tool_audit']) for f in parent.glob('dev/**/static-coverage.json') for e in base.read(f))
    source_files=['scripts/continue_skill_invocation.py','tests/test_skill_invocation_snapshot.py']
    sources={n:digest_file(study.ROOT/n) for n in source_files}
    old_files={f.relative_to(parent).as_posix():digest_file(f) for f in parent.rglob('*') if f.is_file()}
    body={'schema':'invocation-snapshot-continuation-v1','parent':parent.relative_to(study.ROOT).as_posix(),
        'core_protocol_hash':p['hash'],'parent_report_sha256':digest_file(parent/'report.json'),
        'parent_files':old_files,'sources':sources,'reused_model_tokens':0,'prior_cpu_coverage_tools':cpu,
        'prior_gpu_load_wall_seconds':failed['wall_seconds'],'deadline_utc':p['deadline_utc'],
        'change':'snapshot REQUIRED field set includes invocation_adapter and invocation_mode; same SQL/atomic publication code',
        'model_runtime_interface_cases_budget_gates_unchanged':True}
    manifest={**body,'hash':fingerprint(body)}
    for n,h in sources.items():
        dest=root/'extension-source-snapshot'/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((study.ROOT/n).read_bytes())
    for sub in ['source-snapshot','source-ledger','audit-source-snapshot']:
        for f in (parent/sub).rglob('*'):
            if f.is_file():
                dest=root/sub/f.relative_to(parent/sub);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(f.read_bytes())
    for name in ['protocol.json','ci-baseline.json','cpu-tests.json','audit-registration.json','historical-integrity-before.json']:
        (root/name).write_bytes((parent/name).read_bytes())
    base.publish(root/'controller-extension.json',manifest)
    return manifest


def check(root,p,inference=False):
    study.check(p,inference=inference);m=base.read(root/'controller-extension.json')
    if fingerprint({k:v for k,v in m.items() if k!='hash'})!=m['hash'] or m['core_protocol_hash']!=p['hash']:raise ValueError('extension manifest changed')
    for n,h in m['sources'].items():
        if digest_file(study.ROOT/n)!=h or digest_file(root/'extension-source-snapshot'/n)!=h:raise ValueError('extension source differs')
    parent=study.ROOT/m['parent']
    if any(digest_file(parent/n)!=h for n,h in m['parent_files'].items()):raise ValueError('old failure evidence changed')


def run(root):
    root=root.resolve()
    return old.bind(study.run,{'base':proxy,'check':lambda p,inference=False:check(root,p,inference=inference)})(root)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['declare','run']);parser.add_argument('--output',type=Path,default=DEFAULT)
    args=parser.parse_args()
    if args.command=='declare':print(json.dumps({'extension_hash':declare(args.output)['hash']}))
    else:run(args.output)
