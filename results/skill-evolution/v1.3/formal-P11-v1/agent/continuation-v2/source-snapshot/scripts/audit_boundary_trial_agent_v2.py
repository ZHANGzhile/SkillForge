"""Versioned full audit of an exact frozen study plus auditor-only continuation."""
import argparse
from pathlib import Path
from unittest.mock import patch

from scripts import audit_boundary_trial_agent as original
from scripts.audit_boundary_stage2_arm_v2 import audit_arm
from scripts.continue_skill_evolution_selection import publish
from scripts.run_skill_evolution import ROOT, digest_file
from skillforge.skill_evolution.agent_evidence import read
from skillforge.boundary_lineage.proposal import checked, hashed


def audit(root):
    root = Path(root).resolve(); output = root / "agent"; continuation = output / "continuation-v2"
    manifest, report = read(continuation / "manifest.json"), read(continuation / "report.json")
    checked(manifest); checked(report)
    if digest_file(output / "report.json") != manifest["original_partial_report_sha256"]:
        raise ValueError("original partial report changed")
    for name, sha in manifest["auditor_extensions"].items():
        if digest_file(ROOT / name) != sha or digest_file(continuation / "source-snapshot" / name) != sha:
            raise ValueError("versioned continuation source changed")
    for name, sha in manifest["original_evidence_index"].items():
        if digest_file(root / name) != sha: raise ValueError("complete original physical evidence changed")
    def selected_read(path):
        return read(continuation / "report.json") if Path(path) == output / "report.json" else read(path)
    def save(path, value):
        if Path(path) == output / "independent-audit.json":
            value = hashed({**{k: v for k, v in value.items() if k != "hash"},
                "continuation_manifest_hash": manifest["hash"], "auditor_extensions": manifest["auditor_extensions"],
                "original_partial_report_hash": manifest["original_partial_report_hash"]})
            publish(continuation / "independent-audit.json", value)
        else: publish(path, value)
    with patch.object(original, "read", selected_read), patch.object(original, "audit_arm", audit_arm), patch.object(original, "publish", save):
        original.audit(root)
    return read(continuation / "independent-audit.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--run", required=True)
    print(audit(parser.parse_args().run))
