"""Download the pinned official release with checked byte ranges and SHA-256."""
import concurrent.futures
import hashlib
import json
import shutil
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1] / '.runtime'
URL = 'https://github.com/ollama/ollama/releases/download/v0.34.0/ollama-windows-amd64.zip'


def main():
    manifest = json.loads((ROOT / 'ollama-release.json').read_text(encoding='utf-8-sig'))
    total = manifest['size']
    parts = ROOT / 'download-parts'
    parts.mkdir(exist_ok=True)
    prior = ROOT / 'ollama-windows-amd64.zip'
    prefix = prior.stat().st_size if prior.exists() else 0
    if prefix > total:
        raise ValueError('Unexpected prior file size')
    jobs = []
    step = 4 * 1024 * 1024
    for index, start in enumerate(range(prefix, total, step)):
        jobs.append((index, start, min(total - 1, start + step - 1)))
    def fetch(job):
        index, start, end = job
        path = parts / f'part-{start}-{end}'
        length = end - start + 1
        if path.exists() and path.stat().st_size == length:
            return path
        for attempt in range(4):
            try:
                with httpx.Client(follow_redirects=True, trust_env=False, timeout=60) as client:
                    with client.stream('GET', URL, headers={'Range': f'bytes={start}-{end}'}) as response:
                        if response.status_code != 206 or response.headers.get('content-range') != f'bytes {start}-{end}/{total}':
                            raise ValueError('Server did not honor requested range')
                        with path.open('wb') as out:
                            for data in response.iter_bytes(1024 * 1024):
                                out.write(data)
                if path.stat().st_size != length:
                    raise ValueError('Incomplete range')
                if index % 20 == 0 or index == len(jobs) - 1:
                    print(json.dumps({'part': index, 'parts': len(jobs), 'status': 'complete'}), flush=True)
                return path
            except (httpx.HTTPError, ValueError):
                if attempt == 3:
                    raise
                time.sleep(2)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        downloaded = list(pool.map(fetch, jobs))
    target = ROOT / 'ollama-verified.zip'
    with target.open('wb') as out:
        if prefix:
            with prior.open('rb') as source:
                shutil.copyfileobj(source, out, 1024 * 1024)
        for part in downloaded:
            with part.open('rb') as source:
                shutil.copyfileobj(source, out, 1024 * 1024)
    sha = hashlib.sha256()
    with target.open('rb') as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b''):
            sha.update(block)
    if target.stat().st_size != total or 'sha256:' + sha.hexdigest() != manifest['digest']:
        raise ValueError('Release checksum mismatch')
    print(json.dumps({'verified': True, 'sha256': sha.hexdigest(), 'path': str(target)}), flush=True)


if __name__ == '__main__':
    main()
