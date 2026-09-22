"""Pull Qwen3 from the local Ollama service and preserve download status."""
import json
import time
from pathlib import Path

import httpx


def main():
    last = 0
    root = Path(__file__).resolve().parents[1] / '.runtime'
    with httpx.Client(trust_env=False, timeout=httpx.Timeout(600, connect=10)) as client:
        with client.stream('POST', 'http://127.0.0.1:11434/api/pull', json={'model': 'qwen3:4b', 'stream': True}) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                item = json.loads(line)
                status_path = root / 'model-download-status.json'
                temporary = status_path.with_suffix('.tmp')
                temporary.write_text(json.dumps(item), encoding='utf-8')
                temporary.replace(status_path)
                if item.get('error'):
                    raise RuntimeError(item['error'])
                if time.monotonic() - last > 20 or item.get('status') == 'success':
                    print(json.dumps(item), flush=True)
                    last = time.monotonic()


if __name__ == '__main__':
    main()
