import hashlib
import json
import sqlite3
import time
import uuid

from .policies import MUTATIONS, TOOLS, eligibility, valid_address
from .tool_schemas import INPUTS, ValidationError


class ToolError(Exception):
    def __init__(self, code, message=""):
        self.code = code
        super().__init__(message or code)


class Environment:
    """One isolated SQLite environment per task. Money is integer minor units."""

    def __init__(self, path=":memory:", fixture=None, faults=None):
        f = fixture or {}
        self.order_id = f.get("order_id", "O1")
        self.db = sqlite3.connect(path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.audit = []
        self.faults = {k: list(v) for k, v in (faults or {}).items()}
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS customers(customer_id TEXT PRIMARY KEY, risk_level TEXT);
        CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY, customer_id TEXT, status TEXT, shipping_address TEXT);
        CREATE TABLE IF NOT EXISTS payments(order_id TEXT PRIMARY KEY, status TEXT, captured_amount INTEGER, refunded_amount INTEGER);
        CREATE TABLE IF NOT EXISTS shipments(order_id TEXT PRIMARY KEY, status TEXT);
        CREATE TABLE IF NOT EXISTS refunds(refund_id TEXT PRIMARY KEY, order_id TEXT, amount INTEGER, status TEXT, transaction_id TEXT);
        CREATE TABLE IF NOT EXISTS tickets(ticket_id TEXT PRIMARY KEY, order_id TEXT, customer_id TEXT, description TEXT);
        CREATE TABLE IF NOT EXISTS addresses(address_id TEXT PRIMARY KEY, customer_id TEXT, street TEXT, is_valid INTEGER);
        CREATE TABLE IF NOT EXISTS order_items(item_id TEXT PRIMARY KEY, order_id TEXT, product_id TEXT, quantity INTEGER, unit_price INTEGER, status TEXT);
        CREATE TABLE IF NOT EXISTS idempotency(key TEXT PRIMARY KEY, signature TEXT, response TEXT);
        """)
        if not self.db.execute("SELECT 1 FROM customers").fetchone():
            cid = f.get("customer_id", "C1")
            address = f.get("address", "Original address 100")
            self.db.execute("INSERT INTO customers VALUES (?,?)", (cid, f.get("risk", "LOW")))
            self.db.execute("INSERT INTO orders VALUES (?,?,?,?)", (self.order_id, cid, f.get("order", "CONFIRMED"), address))
            self.db.execute("INSERT INTO payments VALUES (?,?,?,?)", (self.order_id, f.get("payment", "CAPTURED"), f.get("captured", 10000), f.get("refunded", 0)))
            self.db.execute("INSERT INTO shipments VALUES (?,?)", (self.order_id, f.get("shipment", "NOT_STARTED")))
            self.db.execute("INSERT INTO addresses VALUES ('A1',?,?,1)", (cid, address))
            self.db.execute("INSERT INTO order_items VALUES ('I1',?,'P1',1,?,'CONFIRMED')", (self.order_id, f.get("captured", 10000)))

    def close(self):
        self.db.close()

    def snapshot(self, order_id=None):
        order_id = self.order_id if order_id is None else order_id
        state = {}
        for table, prefix in [("orders", "order"), ("payments", "payment"), ("shipments", "shipment")]:
            row = self.db.execute(f"SELECT * FROM {table} WHERE order_id=?", (order_id,)).fetchone()
            if row:
                state.update({f"{prefix}.{k}": row[k] for k in row.keys()})
        row = self.db.execute("SELECT * FROM customers WHERE customer_id=?", (state.get("order.customer_id"),)).fetchone()
        if row:
            state.update({f"customer.{k}": row[k] for k in row.keys()})
        state["refunds"] = [dict(r) for r in self.db.execute("SELECT * FROM refunds WHERE order_id=?", (order_id,))]
        state["tickets"] = [dict(r) for r in self.db.execute("SELECT * FROM tickets WHERE order_id=?", (order_id,))]
        return state

    def call(self, name, arguments, customer_id="C1", request_id=None):
        start = time.perf_counter()
        args = dict(arguments)
        order_id = args.get("order_id", "O1")
        before = self.snapshot(order_id)
        error, result = None, None
        committed = False
        try:
            if name not in TOOLS:
                raise ToolError("invalid_tool")
            try:
                args = INPUTS[name].model_validate(args).model_dump()
            except ValidationError as exc:
                raise ToolError("invalid_arguments", "arguments do not match tool schema") from exc
            self.db.execute("BEGIN IMMEDIATE")
            state = self.snapshot(order_id)
            if not state.get("order.order_id"):
                raise ToolError("not_found")
            if state["order.customer_id"] != customer_id:
                raise ToolError("permission_denied")
            signature = hashlib.sha256(json.dumps([name, args, customer_id], sort_keys=True).encode()).hexdigest()
            cached = None
            if name in MUTATIONS:
                if not request_id:
                    raise ToolError("missing_idempotency_key")
                cached = self.db.execute("SELECT * FROM idempotency WHERE key=?", (request_id,)).fetchone()
                if cached and cached["signature"] != signature:
                    raise ToolError("idempotency_conflict")
            fault = self.faults.get(name, []).pop(0) if self.faults.get(name) else None
            if fault and fault != "response_lost":
                raise ToolError(fault)
            if cached:
                result = json.loads(cached["response"])
            else:
                if name in MUTATIONS:
                    decision = eligibility(name, state, args)
                    if decision != "allow":
                        raise ToolError("business_rule_rejected", decision)
                result = self._execute(name, args, state, customer_id)
                if name in MUTATIONS:
                    self.db.execute("INSERT INTO idempotency VALUES (?,?,?)", (request_id, signature, json.dumps(result)))
            self.db.execute("COMMIT")
            committed = True
            if fault == "response_lost":
                raise ToolError("timeout", "response lost after commit")
            return result
        except ToolError as exc:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            error = exc.code
            raise
        except Exception:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            error = "unexpected_error"
            raise
        finally:
            after = self.snapshot(order_id)
            self.audit.append({"tool_name": name, "arguments": args, "result": result if not error else None,
                "authenticated_customer_id": customer_id,
                "error": error, "committed": committed, "request_id": request_id,
                "latency_ms": (time.perf_counter() - start) * 1000,
                "before_state": before, "after_state": after,
                "state_diff": {k: {"before": before.get(k), "after": v} for k, v in after.items() if before.get(k) != v},
                "attempted_policy_violation": error in {"permission_denied", "business_rule_rejected"}})

    def _execute(self, name, args, state, customer_id):
        oid = state["order.order_id"]
        prefixes = {"get_order": "order.", "get_customer": "customer.", "get_payment": "payment.", "get_shipment": "shipment."}
        if name in prefixes:
            return {k: v for k, v in state.items() if k.startswith(prefixes[name])}
        if name == "get_order_items":
            return {"items": [dict(row) for row in self.db.execute("SELECT * FROM order_items WHERE order_id=?", (oid,))]}
        if name == "validate_address":
            return {"address.valid": valid_address(args.get("new_address"))}
        if name == "update_shipping_address":
            self.db.execute("UPDATE orders SET shipping_address=? WHERE order_id=?", (args["new_address"], oid))
            self.db.execute("INSERT INTO addresses VALUES (?,?,?,1)", (str(uuid.uuid4()), customer_id, args["new_address"]))
        elif name == "cancel_order":
            self.db.execute("UPDATE orders SET status='CANCELLED' WHERE order_id=?", (oid,))
        elif name == "issue_refund":
            amount = args["amount"]
            total = state["payment.refunded_amount"] + amount
            status = "REFUNDED" if total == state["payment.captured_amount"] else "PARTIALLY_REFUNDED"
            self.db.execute("UPDATE payments SET refunded_amount=?,status=? WHERE order_id=?", (total, status, oid))
            transaction = str(uuid.uuid4())
            self.db.execute("INSERT INTO refunds VALUES (?,?,?,?,?)", (str(uuid.uuid4()), oid, amount, "COMPLETED", transaction))
            return {"ok": True, "transaction_id": transaction}
        elif name in {"create_ticket", "escalate_to_human"}:
            tid = str(uuid.uuid4())
            self.db.execute("INSERT INTO tickets VALUES (?,?,?,?)", (tid, oid, customer_id, args.get("reason", "manual review")))
            return {"ok": True, "ticket_id": tid}
        return {"ok": True}
