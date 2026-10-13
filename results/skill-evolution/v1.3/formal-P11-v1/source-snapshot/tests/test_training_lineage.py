import json
import pytest

from skillforge.dataset import digest
from skillforge.training_lineage import audit_parent_checkpoint


def test_kernel_migration_preserves_recipe_and_all_checkpoint_state(tmp_path):
    root = tmp_path / "sft"
    checkpoint = root / "checkpoint-10"
    checkpoint.mkdir(parents=True)
    config = {"sft_epochs": 2, "learning_rate": 0.0001}
    audit = {"corpus_hash": "frozen-corpus"}
    run = {"config": config, "stage": "sft", "smoke_only": False, "corpus_audit": audit,
        "sft_adapter_hash": None, "trainer_source_hash": "original-source"}
    run["run_hash"] = digest(run)
    (root / "run.json").write_text(json.dumps(run))
    for name in ("adapter_model.safetensors", "adapter_config.json", "optimizer.pt", "scheduler.pt", "rng_state.pth", "training_args.bin"):
        (checkpoint / name).write_bytes(b"test metadata fixture; never deserialized")
    (checkpoint / "trainer_state.json").write_text(json.dumps({"global_step": 10, "max_steps": 90}))
    new_config = {**config, "sdpa_backend": "cudnn"}
    lineage = audit_parent_checkpoint(checkpoint, new_config, "sft", audit)
    assert lineage["global_step"] == 10 and lineage["parent_run_hash"] == run["run_hash"]
    with pytest.raises(ValueError, match="same recipe"):
        audit_parent_checkpoint(checkpoint, {**new_config, "sft_epochs": 1}, "sft", audit)
    with pytest.raises(ValueError, match="same recipe"):
        audit_parent_checkpoint(checkpoint, new_config, "sft", {"corpus_hash": "changed"})
    (checkpoint / "optimizer.pt").write_bytes(b"altered optimizer")
    assert audit_parent_checkpoint(checkpoint, new_config, "sft", audit) != lineage
    (checkpoint / "rng_state.pth").unlink()
    with pytest.raises(ValueError, match="missing"):
        audit_parent_checkpoint(checkpoint, new_config, "sft", audit)
