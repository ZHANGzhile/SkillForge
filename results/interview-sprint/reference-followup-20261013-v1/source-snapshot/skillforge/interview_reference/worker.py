"""Original public-only RPC and unchanged file guard; explicit model adapter."""
import json
from pathlib import Path
import sys

from skillforge.environment import ToolError
from skillforge.execution_aware.worker import install_guard
from skillforge.training_data import file_hash
from skillforge.skill_evolution.catalog import Catalog
from skillforge.interview_sprint.adapters import bind
from .runtime import run_agent, sources


def main():
    setup = json.loads(sys.stdin.readline())
    from .model import ReferenceModel
    if file_hash(Path(setup["adapter"])/"adapter_model.safetensors") != setup["adapter_sha256"]:
        raise ValueError("fixed main-v3 adapter differs")
    frozen_sources = sources()
    model = ReferenceModel(setup["config"], setup["adapter"])
    runtime = bind(run_agent, {"runtime_sources": lambda: frozen_sources})
    install_guard(setup["output"])
    print(json.dumps({"type":"ready", "settings":model.settings}), flush=True)
    for line in sys.stdin:
        packet = json.loads(line)
        if packet["type"] == "close": break
        if packet["type"] != "run" or set(packet["task"]) != {"task_id","family","request","parameters"}:
            raise ValueError("invalid public task RPC")
        def tool(name, args, key, source):
            print(json.dumps({"type":"tool","name":name,"arguments":args,"key":key,"source":source}),flush=True)
            result = json.loads(sys.stdin.readline())
            if result["type"] != "tool_result": raise ValueError("invalid tool RPC")
            if result.get("error"): raise ToolError(result["error"])
            return result["result"]
        def persist(value):
            print(json.dumps({"type":"checkpoint","value":value}),flush=True)
            if json.loads(sys.stdin.readline()).get("type") != "checkpoint_saved": raise ValueError("checkpoint not acknowledged")
        result = runtime(model,packet["task"],Catalog(packet["catalog"]),tool,persist=persist,
                         public_start=packet.get("public_start"),**packet["limits"])
        print(json.dumps({"type":"completed","result":result}),flush=True)
    model.close()


if __name__ == "__main__": main()
