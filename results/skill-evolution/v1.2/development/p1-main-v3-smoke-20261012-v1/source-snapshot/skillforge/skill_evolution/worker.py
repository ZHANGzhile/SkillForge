"""Gold-isolated model worker. Only public catalog/task and tool RPC enter."""
import json
from pathlib import Path
import sys

from ..environment import ToolError
from ..execution_aware.worker import install_guard
from ..training_data import file_hash
from .catalog import Catalog
from .runtime import run_agent


def main():
    setup = json.loads(sys.stdin.readline())
    from .model import CatalogModel
    if file_hash(Path(setup["adapter"]) / "adapter_model.safetensors") != setup["adapter_sha256"]:
        raise ValueError("execution adapter identity mismatch")
    model = CatalogModel(setup["config"], setup["adapter"])
    install_guard(setup["output"])
    print(json.dumps({"type": "ready", "settings": model.settings}), flush=True)
    for line in sys.stdin:
        packet = json.loads(line)
        if packet["type"] == "close":
            break
        if packet["type"] != "run" or set(packet["task"]) != {"task_id", "family", "request", "parameters"}:
            raise ValueError("invalid public Agent RPC")
        def tool(name, args, key, source):
            print(json.dumps({"type": "tool", "name": name, "arguments": args, "key": key, "source": source}), flush=True)
            response = json.loads(sys.stdin.readline())
            if response["type"] != "tool_result":
                raise ValueError("invalid tool RPC response")
            if response.get("error"):
                raise ToolError(response["error"])
            return response["result"]
        def persist(value):
            print(json.dumps({"type": "checkpoint", "value": value}), flush=True)
            if json.loads(sys.stdin.readline()).get("type") != "checkpoint_saved":
                raise ValueError("checkpoint not durably acknowledged")
        result = run_agent(model, packet["task"], Catalog(packet["catalog"]), tool,
                           persist=persist, **packet["limits"])
        print(json.dumps({"type": "completed", "result": result}), flush=True)
    model.close()


if __name__ == "__main__":
    main()
