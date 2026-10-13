import json
import re
from pathlib import Path
import httpx
from ranged_download import ranged_download

index = "https://download.pytorch.org/whl/cu128/torch/"
with httpx.Client(trust_env=False, follow_redirects=True, timeout=30) as client:
    response = client.get(index)
    response.raise_for_status()
matches = re.findall(r'href="([^"]*torch-2\.10\.0(?:%2B|\+)cu128-cp310-cp310-win_amd64\.whl)#sha256=([a-f0-9]+)"', response.text)
if len(matches) != 1:
    raise ValueError("could not uniquely resolve pinned official wheel")
url, expected = matches[0]
size = 2867370185
path = Path(".runtime/wheels/torch-2.10.0+cu128-cp310-cp310-win_amd64.whl")
sha = ranged_download(url, path, size, expected)
print(json.dumps({"verified": True, "sha256": sha, "path": str(path)}), flush=True)
