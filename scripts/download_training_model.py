"""Download a pinned public Qwen snapshot; resume shards and verify LFS SHA-256."""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

REPO = "Qwen/Qwen3-4B"
REVISION = "1cfa9a7208912126459214e8b04321603b3df60c"
ROOT = Path(".runtime/hf-models/Qwen3-4B")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(entry):
    name = entry["rfilename"]
    if "/" in name or "\\" in name:
        raise ValueError("unexpected nested snapshot filename")
    target, partial = ROOT / name, ROOT / (name + ".part")
    expected_size, expected_hash = entry.get("size"), entry.get("lfs", {}).get("sha256")
    if target.exists():
        current_hash = sha256(target)
        if expected_size is not None and target.stat().st_size != expected_size or expected_hash and current_hash != expected_hash:
            raise ValueError("existing file failed verification: " + name)
        return {"file": name, "bytes": target.stat().st_size, "sha256": current_hash}
    url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}"
    if expected_size and expected_size > 8 * 1024 * 1024:
        from ranged_download import ranged_download
        actual_hash = ranged_download(url, target, expected_size, expected_hash, workers=16)
        return {"file": name, "bytes": target.stat().st_size, "sha256": actual_hash}
    for attempt in range(5):
        start = partial.stat().st_size if partial.exists() else 0
        try:
            with httpx.Client(follow_redirects=True, timeout=120, trust_env=False) as client:
                with client.stream("GET", url, headers={"Range": f"bytes={start}-"} if start else {}) as response:
                    response.raise_for_status()
                    append = start > 0 and response.status_code == 206
                    if append and not response.headers.get("Content-Range", "").startswith(f"bytes {start}-"):
                        raise ValueError("range response does not match requested offset")
                    with partial.open("ab" if append else "wb") as stream:
                        progress = start if append else 0
                        announced = progress // (128 * 1024 * 1024)
                        for chunk in response.iter_bytes(1024 * 1024):
                            stream.write(chunk)
                            progress += len(chunk)
                            if progress // (128 * 1024 * 1024) > announced:
                                announced = progress // (128 * 1024 * 1024)
                                print(json.dumps({"file": name, "downloaded_mib": progress // 1048576}), flush=True)
            break
        except (httpx.HTTPError, OSError):
            if attempt == 4:
                raise
            time.sleep(2 ** attempt)
    actual_hash = sha256(partial)
    if expected_size is not None and partial.stat().st_size != expected_size:
        raise ValueError("download size mismatch: " + name)
    if expected_hash and actual_hash != expected_hash:
        raise ValueError("download hash mismatch: " + name)
    partial.replace(target)
    print(json.dumps({"verified": name, "bytes": target.stat().st_size}), flush=True)
    return {"file": name, "bytes": target.stat().st_size, "sha256": actual_hash}


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30, trust_env=False) as client:
        response = client.get(f"https://huggingface.co/api/models/{REPO}/revision/{REVISION}?blobs=true")
        response.raise_for_status()
        info = response.json()
    if info["sha"] != REVISION:
        raise ValueError("model revision mismatch")
    entries = [e for e in info["siblings"] if e["rfilename"].endswith((".json", ".safetensors")) or e["rfilename"] in {"merges.txt"}]
    with ThreadPoolExecutor(max_workers=3) as pool:
        files = list(pool.map(download, entries))
    report = {"repo": REPO, "revision": REVISION, "files": files, "trust_remote_code": False}
    (ROOT / "download_manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"complete": True, "files": len(files), "bytes": sum(f["bytes"] for f in files)}), flush=True)
