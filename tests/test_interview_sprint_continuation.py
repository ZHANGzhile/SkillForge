"""Expected-denial CPU coverage must not interrupt real Agent collection."""
import json
from pathlib import Path
import pytest

from scripts.continue_interview_sprint import safe_coverage
from skillforge.skill_evolution.catalog import Catalog
from skillforge.interview_sprint.workflows import make_case


@pytest.mark.parametrize('variant,denial',[('unauthorized','permission_denied'),('missing','not_found')])
def test_cpu_coverage_preserves_actual_denial_without_positive_labels(variant,denial):
    root=Path(__file__).resolve().parents[1]/'results/interview-sprint/20261013-v3'
    catalog=Catalog(json.loads((root/'candidate-catalog.json').read_text()))
    rows=safe_coverage(make_case(139100,'dev',variant),catalog)
    assert len(rows)==4 and not any(r['covers_goal'] for r in rows)
    audit=[e for r in rows for e in r['tool_audit']]
    assert audit and all(e['error']==denial and not e['state_diff'] and e['result'] is None for e in audit)
