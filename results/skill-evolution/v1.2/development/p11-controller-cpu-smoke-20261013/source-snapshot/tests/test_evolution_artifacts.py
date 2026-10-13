"""Durable immutable publications must survive interruption and competing writers."""
from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from skillforge import evolution_registry


def test_interrupted_publish_never_exposes_partial_destination(tmp_path, monkeypatch):
    target=tmp_path/"candidate.json"
    real_link=evolution_registry.os.link

    def interrupted(source, destination):
        assert json.loads(source.read_text(encoding="utf-8"))=={"version":1}
        assert not target.exists()
        raise OSError("simulated interruption before publication")

    monkeypatch.setattr(evolution_registry.os,"link",interrupted)
    with pytest.raises(OSError,match="simulated interruption"):
        evolution_registry.immutable_json(target,{"version":1})
    assert not target.exists()
    assert list(tmp_path.iterdir())==[]
    monkeypatch.setattr(evolution_registry.os,"link",real_link)
    evolution_registry.immutable_json(target,{"version":1})
    assert json.loads(target.read_text(encoding="utf-8"))=={"version":1}


def test_concurrent_publish_keeps_one_complete_winner(tmp_path, monkeypatch):
    target=tmp_path/"candidate.json"
    barrier=threading.Barrier(2)
    real_link=evolution_registry.os.link

    def competing_link(source, destination):
        barrier.wait(timeout=10)
        return real_link(source,destination)

    monkeypatch.setattr(evolution_registry.os,"link",competing_link)

    def publish(version):
        try:
            evolution_registry.immutable_json(target,{"version":version})
            return version
        except ValueError as error:
            assert str(error)=="immutable artifact differs"
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results=list(executor.map(publish,(1,2)))
    winner=json.loads(target.read_text(encoding="utf-8"))["version"]
    assert sorted(x for x in results if x is not None)==[winner]
    assert list(tmp_path.iterdir())==[target]
    evolution_registry.immutable_json(target,{"version":winner})
    with pytest.raises(ValueError,match="immutable artifact differs"):
        evolution_registry.immutable_json(target,{"version":3})
