import json
import os
from pathlib import Path


def load_config():
    path = Path(os.getenv("SKILLFORGE_CONFIG", "configs/default.json"))
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"max_steps": 16, "retry_budget": 1, "retrieval_top_k": 3}
