"""Persistent GPU Agent process. No gold world module or private task enters IPC."""
import builtins
import json
import os
from pathlib import Path
import sys

from .runtime import run_agent
from ..environment import ToolError


def install_guard(output):
    output=Path(output).resolve()
    code_roots=[Path(sys.base_prefix).resolve(),Path(sys.prefix).resolve(),Path(__file__).resolve().parents[1]]
    original=builtins.__import__
    def within(path,root):return path==root or root in path.parents
    def guarded_import(name,*args,**kwargs):
        if name=="scripts" or name.startswith("scripts."):raise PermissionError("Agent cannot import evaluator/gold policy")
        return original(name,*args,**kwargs)
    def audit(event,args):
        if event=="open" and not isinstance(args[0],int):
            path=Path(os.fsdecode(args[0])).resolve()
            mode,flags=args[1:]
            writing=(isinstance(mode,str) and any(k in mode for k in "wax+")) or bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT))
            if within(path,output):return
            if not writing and path.suffix in {".py",".pyc",".pyd",".dll"} and any(within(path,r) for r in code_roots):return
            raise PermissionError("Agent cannot read private data or write outside its output")
        if event.startswith("socket.") or event in {"subprocess.Popen","os.system"}:raise PermissionError("Agent external process/network denied")
    builtins.__import__=guarded_import
    sys.addaudithook(audit)


def main():
    setup=json.loads(sys.stdin.readline())
    if setup.get("guard_test"):
        install_guard(setup["output"])
        try:
            if "path" in setup:Path(setup["path"]).read_text()
            else:__import__("scripts.active_evolution_worlds")
        except PermissionError:
            print(json.dumps({"type":"denied"}),flush=True);return
        raise RuntimeError("access guard failed")
    from .model import VersionedModel
    from ..training_data import file_hash
    actual=file_hash(Path(setup["adapter"])/"adapter_model.safetensors")
    if actual!=setup["adapter_sha256"]:raise ValueError("main-v3 adapter identity changed")
    model=VersionedModel(setup["config"],setup["adapter"])
    install_guard(setup["output"])
    print(json.dumps({"type":"ready","settings":model.settings}),flush=True)
    for line in sys.stdin:
        packet=json.loads(line)
        if packet["type"]=="close":break
        if packet["type"]!="run":raise ValueError("invalid Agent RPC")
        def tool_call(name,args,key):
            print(json.dumps({"type":"tool","name":name,"arguments":args,"key":key}),flush=True)
            response=json.loads(sys.stdin.readline())
            if response["type"]!="tool_result":raise ValueError("invalid tool RPC response")
            if response.get("error"):raise ToolError(response["error"])
            return response["result"]
        result=run_agent(model,packet["task"],packet["contract"],packet["patch"],packet["epoch"],tool_call,
            packet.get("max_steps",16),packet.get("decision_only",False))
        print(json.dumps({"type":"completed","result":result}),flush=True)
    model.close()


if __name__=="__main__":main()
