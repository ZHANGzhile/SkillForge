"""Isolated learner RPC worker, with cooperative fail-closed filesystem audit.

This protects against accidental dataset/oracle reads. It is not an OS sandbox
for hostile native extensions. The supervisor never sends held-out rows here.
"""
import builtins
import json
import os
from pathlib import Path
import sys

from .controller import ChallengeEvolutionController
from ..evolution_schemas import Candidate, EvidenceView, Hypothesis


def install_access_guard(output_root):
    output_root = Path(output_root).resolve()
    python_roots = [Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()]
    package = Path(__file__).resolve().parents[1]
    denied_modules = {"skillforge.environment", "skillforge.policies", "skillforge.skills",
                      "skillforge.dataset", "skillforge.evolution_boundary"}
    # Needed imports are preloaded above, before installing the audit hook.
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        fromlist = kwargs.get("fromlist", args[2] if len(args)>2 else ()) or ()
        requested = {name} | {name+"."+part for part in fromlist if isinstance(part,str)}
        if name.startswith("scripts") or requested & denied_modules:
            raise PermissionError("learner cannot import oracle/environment modules")
        return original_import(name, *args, **kwargs)

    def within(path, root):
        return path == root or root in path.parents

    def audit(event, args):
        if event == "open":
            file, mode, flags = args
            if isinstance(file, int):
                return
            path = Path(os.fsdecode(file)).resolve()
            writing = (isinstance(mode, str) and any(x in mode for x in "wax+")) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT))
            if within(path, output_root):
                return
            code_read = not writing and path.suffix in {".py", ".pyc", ".pyd", ".dll"} and (
                any(within(path, root) for root in python_roots) or within(path, package))
            if code_read and path.stem.split(".")[0] not in {"environment", "policies", "skills", "dataset", "evolution_boundary"}:
                return
            raise PermissionError("learner filesystem access outside its output/code boundary")
        if event in {"sqlite3.connect"}:
            if not within(Path(os.fsdecode(args[0])).resolve(), output_root):
                raise PermissionError("learner database access outside output")
        if event.startswith("socket.") or event in {"subprocess.Popen", "os.system", "ctypes.dlopen"}:
            raise PermissionError("learner network/process/native loading forbidden")
        if event in {"os.remove", "os.rmdir", "os.mkdir", "os.rename", "os.link", "os.symlink"}:
            paths = args[:2] if event in {"os.rename", "os.link", "os.symlink"} else args[:1]
            if any(not within(Path(os.fsdecode(p)).resolve(),output_root) for p in paths):
                raise PermissionError("learner filesystem mutation outside output")

    builtins.__import__ = guarded_import
    sys.addaudithook(audit)


def main():
    packet = json.loads(sys.stdin.readline())
    root = Path(packet["output"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    install_access_guard(root)
    if "access_probe" in packet or "import_probe" in packet:
        try:
            if "access_probe" in packet:
                Path(packet["access_probe"]).read_text()
            else:
                __import__("skillforge",fromlist=[packet["import_probe"]])
        except PermissionError:
            print(json.dumps({"type": "access_denied"}), flush=True)
            return
        raise RuntimeError("guard failed")

    def probe(candidate_id):
        print(json.dumps({"type": "probe", "candidate_id": candidate_id}), flush=True)
        response = json.loads(sys.stdin.readline())
        if response.get("type") != "evidence":
            raise ValueError("unexpected supervisor response")
        return EvidenceView.model_validate(response["value"])

    def forbidden_validation(_):
        raise PermissionError("learner may not request validation labels")

    controller = ChallengeEvolutionController(root, packet["identity"],
        [Hypothesis.model_validate(h) for h in packet["hypotheses"]],
        [EvidenceView.model_validate(e) for e in packet["seed_evidence"]],
        [Candidate.model_validate(c) for c in packet["candidates"]], probe,
        forbidden_validation, root / "unused-registry", packet["learning"], packet["passive_order"], packet.get("challenge"))
    result = controller.run(method=packet["method"], random_seed=packet["random_seed"], defer_validation=True)
    print(json.dumps({"type": "completed", "result": result}), flush=True)


if __name__ == "__main__":
    main()
