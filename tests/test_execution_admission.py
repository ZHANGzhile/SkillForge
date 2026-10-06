from dataclasses import replace

import pytest

from skillforge.execution_aware.admission import AdmissionEvidence, admission_funnel


def test_h0_failure_and_partial_agent_coverage_remain_visible():
    rows = [AdmissionEvidence("h0", "active", True, False, True, False),
            AdmissionEvidence("cpu-only", "active", True, True, True, True),
            AdmissionEvidence("rejected", "active", True, True, True, True, True, False),
            AdmissionEvidence("passed", "active", True, True, True, True, True, True, True),
            AdmissionEvidence("interrupted", "active", False, False, False)]
    result = admission_funnel(rows)
    assert result["counts"] == {"planned": 5, "complete": 4, "belief_converged": 4, "boundary_admitted": 3,
                                "agent_admitted": 1, "activated": 1, "deployed": 0}
    assert result["branches"]["h0_validation_failed"] == 1
    assert result["branches"]["agent_not_scheduled"] == 1
    assert result["conditional_rates"]["agent_admission_rate"] == .5
    assert result["fixed_cohort_rates"]["agent_admitted"] == .2


def test_no_adapt_self_comparison_is_not_update_success():
    row = AdmissionEvidence("control", "no_adapt", True, False, True, True, True, True)
    result = admission_funnel([row])
    assert result["counts"]["agent_admitted"] == 0
    assert result["conditional_rates"]["boundary_admission_rate"] is None
    with pytest.raises(ValueError, match="activation"):
        admission_funnel([replace(row, activated=True)])


def test_pending_agent_evaluation_stays_in_fixed_denominator():
    rows = [AdmissionEvidence("pending", "active", True, True, True, True, True)]
    result = admission_funnel(rows)
    assert result["conditional_rates"]["agent_admission_rate"] == 0
    assert result["branches"]["agent_pending"] == 1
