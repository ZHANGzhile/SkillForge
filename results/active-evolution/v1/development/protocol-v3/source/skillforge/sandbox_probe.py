"""Spawn-only SQLite probes. Hidden policy exists only in the child process."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

from .evolution_schemas import fingerprint


def database_hash(path):
    with closing(sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)) as db:
        return fingerprint(list(db.iterdump()))


def _probe_child(spec, world, clone_path, faults):
    try:
        # Private process: this hook can never affect the deployed environment.
        import skillforge.environment as module
        from scripts.active_evolution_worlds import policy
        module.eligibility = lambda name, state, args: policy(world,name,state,args)
        env=module.Environment(path=clone_path,fixture=spec["fixture"],faults=faults)
        oid=spec["parameters"]["order_id"]
        cid=spec["fixture"]["customer_id"]
        initial=env.snapshot(oid)
        observations={}
        successful=False
        try:
            for name in ("get_customer","get_order","get_shipment","get_payment"):
                observations.update(env.call(name,{"order_id":oid},cid,spec["task_id"]+":"+name))
            if spec["family"]=="modify_address":
                observations.update(env.call("validate_address",{"order_id":oid,"new_address":spec["parameters"]["new_address"]},cid,spec["task_id"]+":address"))
            mutation={"refund":"issue_refund","modify_address":"update_shipping_address","cancel_order":"cancel_order"}[spec["family"]]
            env.call(mutation,spec["parameters"],cid,spec["task_id"]+":mutation")
            after=env.call("get_payment" if spec["family"]=="refund" else "get_order",{"order_id":oid},cid,spec["task_id"]+":verify")
            if spec["family"]=="refund":
                successful=after["payment.refunded_amount"]==initial["payment.refunded_amount"]+spec["parameters"]["amount"]
            elif spec["family"]=="modify_address":
                successful=after["order.shipping_address"]==spec["parameters"]["new_address"]
            else:
                successful=after["order.status"]=="CANCELLED"
        except module.ToolError:
            pass
        final=env.snapshot(oid)
        result={"trajectory_id":fingerprint([spec["task_id"],spec["policy_epoch"]]),"task_id":spec["task_id"],
            "policy_epoch":spec["policy_epoch"],"origin":"controlled_procedure", "procedure_success":successful,
            "initial_state":initial,"final_state":final,"tool_audit":env.audit,"remaining_faults":env.faults,
            "actual_violations":sum(bool(e["state_diff"]) and e["committed"] and e["tool_name"] in module.MUTATIONS and policy(world,e["tool_name"],e["before_state"],e["arguments"])!="allow" for e in env.audit)}
        env.close()
        return {"result":result}
    except Exception as exc:
        if "env" in locals():
            env.close()
        return {"error":type(exc).__name__+": "+str(exc)}


def run_probe(spec, world, source_database=None, faults=None, timeout=30):
    before=database_hash(source_database) if source_database else None
    with tempfile.TemporaryDirectory(prefix="skillforge-probe-") as tmp:
        clone=str(Path(tmp)/"probe.sqlite")
        if source_database:
            with closing(sqlite3.connect(f"file:{Path(source_database).resolve().as_posix()}?mode=ro",uri=True)) as source, closing(sqlite3.connect(clone)) as target:
                source.backup(target)
        request=Path(tmp)/"request.json"
        response=Path(tmp)/"response.json"
        request.write_text(json.dumps({"spec":spec,"world":world,"clone_path":clone,"faults":faults or {}}),encoding="utf-8")
        # File IPC avoids named-pipe restrictions on Windows. No shell interpolation.
        subprocess.run([sys.executable,"-m","skillforge.sandbox_probe",str(request),str(response)],
            check=True,timeout=timeout,capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=="win32" else 0)
        payload=json.loads(response.read_text(encoding="utf-8"))
        if source_database and database_hash(source_database)!=before:
            raise ValueError("probe modified source database")
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return payload["result"]


if __name__ == "__main__":
    request=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path(sys.argv[2]).write_text(json.dumps(_probe_child(**request)),encoding="utf-8")
