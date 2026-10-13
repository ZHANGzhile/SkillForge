"""Verified resumable byte-range downloader for large official artifacts."""
import hashlib
import json
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx


def ranged_download(url, target, size, expected_hash=None, workers=32, max_range_seconds=180):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    parts = target.parent / (target.name + ".chunks")
    parts.mkdir(exist_ok=True)
    chunk_size = 8 * 1024 * 1024
    def fetch(start):
        end = min(size - 1, start + chunk_size - 1)
        path = parts / str(start)
        if path.exists() and path.stat().st_size == end - start + 1:
            return path
        for retry in range(5):
            try:
                started = time.monotonic()
                with httpx.Client(follow_redirects=True, trust_env=False, timeout=60) as client:
                    with client.stream("GET", url, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"}) as response:
                        if response.status_code != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{size}":
                            raise ValueError("server did not honor exact requested range")
                        with path.open("wb") as out:
                            for block in response.iter_bytes():
                                if time.monotonic() - started > max_range_seconds:
                                    raise ValueError("range exceeded total transfer deadline")
                                out.write(block)
                if path.stat().st_size != end - start + 1:
                    raise ValueError("incomplete range")
                return path
            except (httpx.HTTPError, ValueError):
                if retry == 4:
                    raise
                time.sleep(1 + retry)
    starts = list(range(0, size, chunk_size))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch, start) for start in starts]
        for completed, future in enumerate(as_completed(futures), 1):
            future.result()
            if completed % 16 == 0 or completed == len(starts):
                print(json.dumps({"file": target.name, "chunks": completed, "total": len(starts)}), flush=True)
    temporary = target.with_name(target.name + ".assembling")
    h = hashlib.sha256()
    with temporary.open("wb") as out:
        for start in starts:
            with (parts / str(start)).open("rb") as source:
                for block in iter(lambda: source.read(4 * 1024 * 1024), b""):
                    h.update(block)
                    out.write(block)
    if temporary.stat().st_size != size or expected_hash and h.hexdigest() != expected_hash:
        raise ValueError("assembled artifact failed size/SHA-256 validation")
    temporary.replace(target)
    return h.hexdigest()
