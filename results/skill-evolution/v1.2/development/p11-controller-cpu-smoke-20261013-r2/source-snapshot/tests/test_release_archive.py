"""Release archives must preserve evidence and exclude machine-local state."""
import hashlib
import json
import zipfile

import pytest

from scripts import package_project


def test_archive_round_trip_retains_lineage_and_excludes_local_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(package_project, "ROOT", tmp_path)

    def write(name, content):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(content) if isinstance(content, (dict, list)) else content, encoding="utf-8")

    write("configs/training-runs.json", {
        "root": "results/train", "config": "configs/train.json", "evaluation_root": "results/eval",
        "validation_loss_data": "results/likelihood", "resume_checkpoints": {"sft": "results/parent/sft/checkpoint-10"},
    })
    write("configs/train.json", {"dataset": "data/frozen", "bundle": "results/frozen/frozen.json",
        "baseline": "results/baseline/comparison.json", "real_data": "results/real", "supervision": "results/supervision"})
    write("configs/evidence.json", [{"path": ".runtime/pipeline.json"}])
    write(".runtime/pipeline.json", {"stage": "test-only"})
    write(".runtime/machine-private.txt", "must-not-ship")
    write("README.md", "可复现研究交付\n")
    write("configs/model.local.json", {"private": "must-not-ship"})
    write("configs/deployment.local.json", {"machine": "must-not-ship"})
    write("results/train/sft/adapter/adapter_model.safetensors", "explicit-test-fixture-adapter")
    write("results/train/sft/checkpoint-90/optimizer.pt", "excluded-intermediate-checkpoint")
    write("results/parent/sft/checkpoint-10/optimizer.pt", "required-resume-lineage")
    write("results/parent/sft/run.json", {"parent": True})
    write("results/parent/training-source.py", "# historical parent source\n")
    write("results/eval/comparison.json", {"fixture": True})
    report = package_project.package("release/test.zip", {"ready": True, "explicit_test_fixture": True})
    target = tmp_path / "release/test.zip"
    assert report["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert not target.with_suffix(".partial").exists()
    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
        assert "SkillForge/configs/model.local.json" not in names
        assert "SkillForge/configs/deployment.local.json" not in names
        assert not any(name.startswith("SkillForge/.runtime/") for name in names)
        assert "SkillForge/results/train/sft/checkpoint-90/optimizer.pt" not in names
        assert archive.read("SkillForge/results/parent/sft/checkpoint-10/optimizer.pt") == b"required-resume-lineage"
        assert archive.read("SkillForge/README.md") == (tmp_path / "README.md").read_bytes()
        manifest = json.loads(archive.read("SkillForge/release-manifest.json"))
        assert report["files"] == len(manifest["files"])
        for name, expected in manifest["files"].items():
            content = archive.read("SkillForge/" + name)
            assert len(content) == expected["bytes"]
            assert hashlib.sha256(content).hexdigest() == expected["sha256"]
    with pytest.raises(ValueError, match="new release file"):
        package_project.package("release/test.zip", {"ready": True})
    with pytest.raises(ValueError, match="inside the project"):
        package_project.package(tmp_path.parent / "outside.zip", {"ready": True})
