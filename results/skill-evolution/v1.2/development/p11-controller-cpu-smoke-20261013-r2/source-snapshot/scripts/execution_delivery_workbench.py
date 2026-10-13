"""Read-only A/B reporting extension; frozen research modules remain untouched."""
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from scripts.execution_aware_formal import read
from scripts.prepare_active_evolution import file_hash
from skillforge.evolution_schemas import fingerprint
from skillforge.execution_workbench.app import app


BASE = Path(__file__).resolve().parents[1]/'results/active-evolution/v1.1'


class AcquisitionView:
    def __init__(self, root=BASE/'formal-B-v1'):
        self.root = Path(root)

    def protocol(self):
        record = read(self.root/'protocol.json')
        if fingerprint(record['protocol']) != record['protocol_hash']:
            raise ValueError('B protocol identity mismatch')
        return record

    def index(self):
        if not (self.root/'protocol.json').exists():
            return {'status':'not_frozen','complete':False,'completed_runs':0,'planned_runs':150,
                    'rows':[],'aggregate':None,'protocol_hash':None,'selected_variant':None,'audit_passed':False}
        record = self.protocol(); config = record['protocol']['config']; rows = []
        for world in config['worlds']:
            for seed in config['paired_seeds']:
                for method in config['methods']:
                    path = self.root/'cpu'/world/str(seed)/method/'metrics.json'
                    if path.exists():
                        row = read(path)
                        if (row['world'],row['seed'],row['method']) != (world,seed,method):
                            raise ValueError('B row identity mismatch')
                        rows.append({k:row[k] for k in ('world','seed','method','queries','status',
                            'belief_converged','raw_belief_converged','boundary_admitted','h0_false_convergence','effective_test')})
        opened = [p for p in (self.root/'invocations').glob('*.start.json')
                  if not p.with_name(p.name.replace('.start.json','.final.json')).exists()]
        report_path = self.root/'cpu-report.json'
        report = read(report_path) if report_path.exists() else None
        if report and report['protocol_hash'] != record['protocol_hash']:
            raise ValueError('B report identity mismatch')
        audit_path = self.root/'audits/evidence.json'
        receipt = read(audit_path) if audit_path.exists() else None
        audited = bool(report and receipt and receipt['passed'] and receipt['report_hash']==file_hash(report_path))
        if receipt and not audited:
            raise ValueError('B audit report binding mismatch')
        status = ('complete' if audited and not opened else ('auditing' if opened else 'audit_incomplete')) if report else ('running' if opened else 'stopped')
        return {'status':status,'complete':status=='complete','completed_runs':len(rows),
            'planned_runs':len(config['worlds'])*len(config['paired_seeds'])*len(config['methods']),
            'protocol_hash':record['protocol_hash'],'selected_variant':record['protocol']['selected_variant'],
            'rows':rows,'aggregate':report['aggregate'] if report else None,'audit_passed':audited,
            'additional_gpu_seconds':0,'additional_model_tokens':0,
            'scope':'CPU Boundary only; no Agent admission or activation inferred'}

    def trace(self, world, seed, method):
        config = self.protocol()['protocol']['config']
        if world not in config['worlds'] or seed not in config['paired_seeds'] or method not in config['methods']:
            raise KeyError('unknown B run')
        directory = self.root/'cpu'/world/str(seed)/method
        if not (directory/'metrics.json').exists():
            raise KeyError('B run not complete')
        summary = read(directory/'metrics.json')
        queries = []
        for path in sorted((directory/'learner/queries').glob('query_*.json')):
            row = read(path)
            if row['row_hash'] != fingerprint({k:v for k,v in row.items() if k!='row_hash'}):
                raise ValueError('B query evidence mismatch')
            gate = row.get('h0_challenge_before')
            queries.append({'index':row['index'],'candidate_id':row['candidate_id'],
                'evidence_hash':row['evidence_hash'],'label':row['evidence']['label'],
                'selected_eig':row['selected_eig'],'learned':row['learned'],
                'h0_challenge':{k:gate[k] for k in ('status','required','completed','queries_charged')} if gate else None})
        effective = read(directory/'effective-version.json'); freeze = read(directory/'evaluation-freeze.json')
        if freeze['candidate_hash'] != fingerprint(effective):
            raise ValueError('B effective version freeze mismatch')
        return {'world':world,'seed':seed,'method':method,'summary':summary,'queries':queries,
                'effective_version':effective,'scope':'human evidence view; no execution capabilities'}


b_view = AcquisitionView()


@app.get('/api/acquisition-evolution/index')
def acquisition_index():
    try:
        return JSONResponse(b_view.index(),headers={'Cache-Control':'no-store'})
    except (ValueError,KeyError,FileNotFoundError) as exc:
        raise HTTPException(409,'Recorded B evidence unavailable: '+str(exc)) from exc


@app.get('/api/acquisition-evolution/trace')
def acquisition_trace(world: str, seed: int, method: str):
    try:
        return JSONResponse(b_view.trace(world,seed,method),headers={'Cache-Control':'no-store'})
    except KeyError as exc:
        raise HTTPException(404,'Unknown or incomplete B run') from exc
    except (ValueError,FileNotFoundError) as exc:
        raise HTTPException(409,'Recorded B trace unavailable: '+str(exc)) from exc


@app.get('/api/execution-evolution/continual-attribution')
def continual_attribution():
    try:
        value = read(BASE/'formal-A-v2/posthoc/continual-attribution.json')
        return {'counts':value['counts'],'stable_regressions':value['stable_regressions'],'scope':value['scope']}
    except (ValueError,FileNotFoundError) as exc:
        raise HTTPException(409,'Attribution not available') from exc
