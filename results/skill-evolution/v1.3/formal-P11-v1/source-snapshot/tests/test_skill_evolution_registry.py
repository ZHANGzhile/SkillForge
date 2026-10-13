"""Catalog selection engineering only; no fabricated formal registration."""
import copy
import json

import pytest

from scripts.verify_skill_evolution_p4 import engineering_entry
from skillforge.evolution_common.artifacts import record
from skillforge.evolution_schemas import fingerprint
from skillforge.skill_evolution.catalog import Catalog, revision
from skillforge.skill_evolution.registry import VersionedRegistry, verified_publication


def receipt(**fields):
    return {**fields, "hash": fingerprint(fields)}


def bootstrap(tmp_path):
    registry = VersionedRegistry(tmp_path / "registry")
    entry = verified_publication(engineering_entry())
    catalog = Catalog([entry])
    root = registry.bootstrap(catalog, reason="explicit unit-only legacy import", evidence=receipt(catalog_hash=catalog.hash, scope="unit-only"))
    return registry, root, catalog


def test_publication_has_new_hash_without_mutating_candidate():
    original = engineering_entry(); unchanged = copy.deepcopy(original)
    published = verified_publication(original)
    assert original == unchanged and published["revision"] != original["revision"]
    assert original["contract"]["status"] == "CANDIDATE" and published["contract"]["status"] == "VERIFIED"
    assert {**original["contract"], "status": "VERIFIED"} == published["contract"]
    with pytest.raises(ValueError, match="candidate"): verified_publication(published)


def test_retain_deprecate_rollback_preserves_every_ancestor(tmp_path):
    registry, root, catalog = bootstrap(tmp_path)
    original_files = {path: path.read_bytes() for path in (tmp_path / "registry").rglob("*.json")}
    kept = registry.retain(root, reason="NO_USEFUL_CANDIDATE", evidence=receipt(n_candidates=0))
    deprecated = registry.deprecate(kept, catalog.entries()[0]["revision"], reason="unit safety check", evidence=receipt(scope="unit-only"))
    restored = registry.rollback(deprecated, root, reason="restore explicit baseline", evidence=receipt(scope="unit-only"))
    assert registry.load(root)[1].hash == registry.load(kept)[1].hash == registry.load(restored)[1].hash == catalog.hash
    assert registry.load(deprecated)[1].entries() == []
    assert registry.load(restored)[0]["parent_snapshot"] == deprecated
    assert registry.load(restored)[0]["rollback_target"] == root
    assert all(path.read_bytes() == data for path, data in original_files.items())
    assert not registry.load(restored)[0]["isolated_activated"] and not registry.load(restored)[0]["deployed"]


def test_rollback_rejects_nonancestor_and_current_snapshot(tmp_path):
    registry, root, _ = bootstrap(tmp_path)
    branch = registry.retain(root, reason="branch", evidence=receipt(unit=True))
    other = registry.retain(root, reason="other branch", evidence=receipt(unit=True))
    for target in (branch, other):
        with pytest.raises(ValueError, match="prior.*ancestor"):
            registry.rollback(branch, target, reason="unit", evidence=receipt(unit=True))


def test_catalog_rejects_conflicting_versions_and_unverified_import(tmp_path):
    registry, _, catalog = bootstrap(tmp_path)
    entry = catalog.entries()[0]; contract = copy.deepcopy(entry["contract"]); contract["version"] += 1
    second = revision(contract, name=entry["name"], description=entry["description"], support_domain=entry["support_domain"], parent_revision=entry["revision"])
    for entries in ([entry, second], [engineering_entry()]):
        conflicting = Catalog(entries)
        with pytest.raises(ValueError, match="one VERIFIED"):
            registry.bootstrap(conflicting, reason="invalid", evidence=receipt(catalog_hash=conflicting.hash))


def test_deprecation_cannot_break_dependency_closure(tmp_path):
    registry = VersionedRegistry(tmp_path / "registry")
    parent = verified_publication(engineering_entry()); child = copy.deepcopy(parent["contract"]); child["skill_id"] = "dependent-unit"
    dependent = revision(child, name="dependent", description="unit", support_domain=parent["support_domain"], dependencies=[{"skill_id":parent["skill_id"],"revision":parent["revision"]}])
    catalog = Catalog([parent, dependent]); root = registry.bootstrap(catalog, reason="unit", evidence=receipt(catalog_hash=catalog.hash))
    before = set((tmp_path / "registry" / "snapshots").glob("*.json"))
    with pytest.raises(ValueError, match="dependency"):
        registry.deprecate(root, parent["revision"], reason="invalid", evidence=receipt(unit=True))
    assert set((tmp_path / "registry" / "snapshots").glob("*.json")) == before


def test_tampered_or_rehashed_catalog_cannot_bypass_registration(tmp_path):
    registry, root, _ = bootstrap(tmp_path)
    body, _ = registry.load(root)
    altered = copy.deepcopy(body); altered["entries"] = [verified_publication(engineering_entry(["get_order_items", "get_order", "get_shipment"]))]
    altered["catalog_hash"] = Catalog(altered["entries"]).hash
    forged = record(registry.root, "snapshots", altered)
    with pytest.raises(ValueError, match="registration"): registry.load(forged)
    path = registry.root / "snapshots" / (root + ".json")
    value = json.loads(path.read_text()); value["body"]["deployed"] = True; path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="integrity"): registry.load(root)


def test_engineering_receipt_cannot_publish_even_with_rehashed_metadata():
    entry = engineering_entry()
    with pytest.raises((ValueError, KeyError)):
        VersionedRegistry._audit_registration({"program_admission": receipt(decision="ADMITTED", catalog_revision=entry["revision"]),
            "proposal_entry": entry, "published_entry": verified_publication(entry)})


def test_empty_reason_and_unbound_import_are_rejected(tmp_path):
    registry, root, catalog = bootstrap(tmp_path)
    with pytest.raises(ValueError, match="reason"):
        registry.retain(root, reason="", evidence=receipt(unit=True))
    with pytest.raises(ValueError, match="bind"):
        registry.bootstrap(catalog, reason="unit", evidence=receipt(catalog_hash="wrong"))
    with pytest.raises(ValueError, match="active exact"):
        registry.deprecate(root, "missing", reason="unit", evidence=receipt(unit=True))
