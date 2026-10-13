"""Bind the independent nine-arm audit to the zero-inference snapshot extension."""
import argparse
from pathlib import Path
import json
from scripts import continue_skill_invocation as extension
from scripts import audit_skill_invocation as original
from scripts import run_interview_sprint as base
from scripts.run_skill_evolution import digest_file
from skillforge.evolution_schemas import fingerprint


def audit(root):
    root=Path(root).resolve();p=base.read(root/'protocol.json');extension.check(root,p)
    registration=base.read(root/'audit-registration.json')
    for name,h in registration['sources'].items():
        if digest_file(extension.study.ROOT/name)!=h or digest_file(root/'audit-source-snapshot'/name)!=h:
            raise ValueError('pre-inference auditor/test/plan source changed')
    if not base.read(root/'extension-cpu-tests.json')['passed']:raise ValueError('snapshot CPU regression failed')
    result=original.audit(root)
    extension.check(root,p)
    m=base.read(root/'controller-extension.json')
    body={'passed':result['passed'],'extension_hash':m['hash'],'protocol_hash':p['hash'],
        'independent_audit_sha256':digest_file(root/'independent-audit.json'),
        'auditor_sha256':digest_file(__file__),'parent_failed_run_unchanged':True,'reused_model_tokens':0,
        'prior_failed_gpu_load_wall_seconds':m['prior_gpu_load_wall_seconds'],'prior_failed_cpu_tools':m['prior_cpu_coverage_tools'],
        'model_calls':0,'tokens':0,'agent_admitted':False,'activated':False}
    proof={**body,'hash':fingerprint(body)};base.publish(root/'continuation-independent-audit.json',proof)
    return {'extension_audit':proof,'core_audit':result}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path,default=extension.DEFAULT)
    print(json.dumps(audit(parser.parse_args().run),ensure_ascii=False))
