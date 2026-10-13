import copy
import json

import pytest

from skillforge.environment import ToolError
from skillforge.schemas import SkillContract, SkillStep, Condition
from skillforge.skill_evolution.catalog import Catalog, LoadedSkills, revision


def entry(version=1, status="VERIFIED"):
    skill = SkillContract(skill_id="cancel_demo", version=version, family="cancel_order", inputs=["order_id"],
        preconditions=[Condition(field="order.status", value="CONFIRMED", evidence=["private-train-source"])],
        forbidden_conditions=[Condition(field="customer.risk_level", value="HIGH", evidence=["private-boundary-source"])],
        procedure=[SkillStep(kind="call", tool="cancel_order", arguments={"order_id": "$input.order_id"}),
                   SkillStep(kind="call", tool="get_order", arguments={"order_id": "$input.order_id"}),
                   SkillStep(kind="finish")], postconditions={"order.status": "CANCELLED"},
        source_trajectory_ids=["private-trajectory"], policy_version="v1.1", status=status,
        statistics={"validation": {"secret": 123}})
    return revision(skill.model_dump(), name="Cancel order", description="cancel stop order fulfillment",
                    support_domain={"scope": "test fixture"})


def test_public_search_load_has_no_private_evidence_or_full_program_in_search():
    e = entry(); catalog = Catalog([e])
    found = catalog.search("cancel order")
    assert len(found) == 1 and "program" not in found[0]
    loaded = catalog.public_load(e["skill_id"], e["revision"])
    text = json.dumps([found, loaded])
    assert "private-" not in text and "statistics" not in text and "validation" not in text
    assert "program" in loaded and "postconditions" in loaded
    assert catalog.search("unrelated pineapple") == []


def test_tampering_version_conflict_and_unverified_use_are_rejected():
    a, b = entry(), entry(2)
    catalog = Catalog([a, b]); loaded = LoadedSkills(catalog)
    with pytest.raises(ToolError, match="skill_not_loaded"): loaded.contract("cancel_demo")
    loaded.load(a["skill_id"], a["revision"])
    with pytest.raises(ToolError, match="skill_revision_conflict"): loaded.load(b["skill_id"], b["revision"])
    assert loaded.contract("cancel_demo").version == 1
    bad = copy.deepcopy(a); bad["contract"]["procedure"][0]["tool"] = "issue_refund"
    with pytest.raises(ValueError, match="tampered"): Catalog([bad])
    candidate = entry(status="CANDIDATE"); c = Catalog([candidate])
    assert c.search("cancel") == []
    with pytest.raises(ToolError, match="not_verified"): c.public_load(candidate["skill_id"], candidate["revision"])


def test_catalog_snapshot_and_loaded_refs_restore_bind_exact_bytes(tmp_path):
    e = entry(); c = Catalog([e]); c.save(tmp_path / "catalog.json")
    assert Catalog.load(tmp_path / "catalog.json").hash == c.hash
    refs = LoadedSkills(c); refs.load(e["skill_id"], e["revision"])
    assert LoadedSkills(c, refs.refs).refs == refs.refs
    altered = copy.deepcopy(refs.refs); altered[e["skill_id"]]["content_hash"] = "wrong"
    with pytest.raises(ValueError, match="identity"): LoadedSkills(c, altered)


@pytest.mark.parametrize("query,k", [("", 5), ("cancel", 0), ("cancel", True), ("cancel", 6)])
def test_invalid_search_does_not_escape_catalog(query, k):
    with pytest.raises(ToolError): Catalog([entry()]).search(query, k)


def test_thousand_entry_distractor_catalog_is_capacity_fixture_only():
    from skillforge.evolution_schemas import fingerprint
    target = entry()
    distractors = []
    for i in range(999):
        d = copy.deepcopy(target)
        d["skill_id"] = d["contract"]["skill_id"] = "synthetic_" + str(i)
        d["name"] = "Synthetic shipping tracking " + str(i)
        d["description"] = "synthetic distractor; catalog capacity only"
        d["revision"] = fingerprint({k: v for k, v in d.items() if k != "revision"})
        distractors.append(d)
    results = Catalog([target, *distractors]).search("cancel order fulfillment")
    assert results[0]["skill_id"] == target["skill_id"]
    assert len(results) <= 5
