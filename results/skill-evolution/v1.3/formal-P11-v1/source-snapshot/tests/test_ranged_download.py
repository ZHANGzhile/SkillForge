import hashlib
import httpx
import pytest

from scripts import ranged_download as downloader


def test_verified_download_reuses_complete_chunks_and_rejects_wrong_hash(monkeypatch, tmp_path):
    data = b"official artifact bytes"
    calls = []
    def handle(request):
        calls.append(request)
        assert request.headers["Range"] == f"bytes=0-{len(data)-1}"
        return httpx.Response(206, headers={"Content-Range": f"bytes 0-{len(data)-1}/{len(data)}"}, content=data)
    client = httpx.Client
    monkeypatch.setattr(downloader.httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handle)))
    path = tmp_path / "weights"
    expected = hashlib.sha256(data).hexdigest()
    assert downloader.ranged_download("https://official.invalid/weights", path, len(data), expected) == expected
    assert path.read_bytes() == data
    downloader.ranged_download("https://official.invalid/weights", path, len(data), expected)
    assert len(calls) == 1
    with pytest.raises(ValueError, match="SHA-256"):
        downloader.ranged_download("https://official.invalid/weights", path, len(data), "wrong-hash")
    assert path.read_bytes() == data


def test_slow_trickle_retries_instead_of_hanging_forever(monkeypatch, tmp_path):
    clock = [0.0]
    calls = []
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            clock[0] += 181
            yield b"slow"
    def handle(request):
        calls.append(request)
        return httpx.Response(206, headers={"Content-Range": "bytes 0-3/4"}, stream=Stream())
    client = httpx.Client
    monkeypatch.setattr(downloader.httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(downloader.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(downloader.time, "sleep", lambda _: None)
    path = tmp_path / "weights"
    with pytest.raises(ValueError, match="deadline"):
        downloader.ranged_download("https://official.invalid/weights", path, 4)
    assert len(calls) == 5 and not path.exists()
