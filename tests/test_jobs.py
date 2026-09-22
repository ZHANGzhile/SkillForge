import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from skillforge.jobs import JobStore, Worker


def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError("worker did not reach expected state")


def test_concurrent_idempotency_and_conflicting_payload(tmp_path):
    store = JobStore(tmp_path)
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = list(pool.map(lambda _: store.submit({"amount": 100}, "refund-request"), range(12)))
    assert len({j[0]["id"] for j in jobs}) == 1
    assert sum(j[1] for j in jobs) == 1
    with pytest.raises(ValueError, match="different request"):
        store.submit({"amount": 101}, "refund-request")


def test_recovery_preserves_events_queued_and_isolates_retry(tmp_path):
    store = JobStore(tmp_path)
    old, _ = store.submit({"amount": 100})
    assert store.claim()["id"] == old["id"]
    store.event(old["id"], "tool", {"committed": True, "refund_id": "one"})
    queued, _ = store.submit({"amount": 200})
    restarted = JobStore(tmp_path)
    restarted.recover()
    assert restarted.get(old["id"])["status"] == "interrupted"
    assert restarted.get(queued["id"])["status"] == "queued"
    assert restarted.events(old["id"])[2]["payload"]["committed"]
    retry, _ = restarted.retry(old["id"], "retry-key")
    assert retry["id"] != old["id"] and retry["retry_of"] == old["id"]
    assert restarted.retry(old["id"], "retry-key")[0]["id"] == retry["id"]
    assert restarted.directory(retry["id"]) != restarted.directory(old["id"])
    assert restarted.claim()["id"] == queued["id"]
    assert restarted.get(old["id"])["status"] == "interrupted"


def test_cancel_queued_and_worker_cooperative_cancel(tmp_path):
    store = JobStore(tmp_path)
    queued, _ = store.submit({})
    assert store.cancel(queued["id"])["status"] == "cancelled"
    assert store.claim() is None
    entered = threading.Event()
    def execute(job, emit, cancelled):
        entered.set()
        wait_for(cancelled)
        emit("checkpoint", {"preserved": True})
        return {"outcome": "cancelled"}
    worker = Worker(store, execute)
    worker.start()
    try:
        job, _ = store.submit({})
        worker.wake.set()
        assert entered.wait(5)
        assert store.cancel(job["id"])["status"] == "running"
        wait_for(lambda: store.get(job["id"])["status"] == "cancelled")
        assert store.events(job["id"])[-2]["kind"] == "checkpoint"
        with pytest.raises(RuntimeError, match="Another"):
            Worker(JobStore(tmp_path), execute).start()
        with pytest.raises(ValueError, match="running"):
            store.finish(job["id"], "succeeded")
    finally:
        worker.close()


def test_event_cursor_and_worker_failure_are_durable(tmp_path):
    store = JobStore(tmp_path)
    def fail(job, emit, cancelled):
        emit("tool", {"committed": True})
        raise ConnectionError("Student unavailable")
    worker = Worker(store, fail)
    worker.start()
    try:
        job, _ = store.submit({})
        worker.wake.set()
        wait_for(lambda: store.get(job["id"])["status"] == "failed")
        assert store.get(job["id"])["error"]["type"] == "ConnectionError"
        first = store.events(job["id"], limit=2)
        second = store.events(job["id"], after=first[-1]["seq"])
        assert [e["kind"] for e in first + second] == ["queued", "running", "tool", "failed"]
    finally:
        worker.close()
