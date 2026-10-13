"""Fetch only the official ZIP's CLI entry so model download can overlap libraries."""
import io
import json
import zipfile
from pathlib import Path

import httpx

from download_ollama import URL, ROOT


class RemoteZip(io.RawIOBase):
    def __init__(self, size):
        self.size, self.position = size, 0
        self.client = httpx.Client(follow_redirects=True, trust_env=False, timeout=120)

    def seekable(self):
        return True

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        return self.position

    def tell(self):
        return self.position

    def read(self, size=-1):
        if size < 0:
            size = self.size - self.position
        size = min(size, self.size - self.position)
        if size <= 0:
            return b''
        start, end = self.position, self.position + size - 1
        response = self.client.get(URL, headers={'Range': f'bytes={start}-{end}'})
        if response.status_code != 206 or len(response.content) != size:
            raise ValueError('Invalid ZIP range')
        self.position += size
        return response.content


def main():
    manifest = json.loads((ROOT / 'ollama-release.json').read_text(encoding='utf-8-sig'))
    stream = RemoteZip(manifest['size'])
    try:
        with zipfile.ZipFile(stream) as archive:
            info = archive.getinfo('ollama.exe')
            print(json.dumps({'entry': info.filename, 'download_bytes': info.compress_size}), flush=True)
            data = archive.read(info)  # zipfile verifies CRC for the full entry.
        out = ROOT / 'bootstrap'
        out.mkdir(exist_ok=True)
        (out / 'ollama.exe').write_bytes(data)
        print(json.dumps({'ready': True, 'path': str(out / 'ollama.exe')}), flush=True)
    finally:
        stream.client.close()


if __name__ == '__main__':
    main()
