"""Controller-side admission at the frozen worker's pre-inference ACK barrier.

No Runtime or model-message changes. A durable approval precedes ACK; a crash
after approval conservatively charges the reservation. A denied, never-ACKed
request is explicitly distinguishable from an unknown in-flight request.
"""
from skillforge.evolution_schemas import fingerprint


class CheckpointAdmission:
    def __init__(self, prior_tokens, max_tokens, prior_wall, max_wall, close_grace=10):
        self.prior_tokens = prior_tokens
        self.max_tokens = max_tokens
        self.prior_wall = prior_wall
        self.max_wall = max_wall
        self.close_grace = close_grace
        self.approved = set()
        self.last = None

    def inspect(self, checkpoint, elapsed):
        if elapsed < 0:
            raise ValueError("negative elapsed time")
        requests = checkpoint["model_requests"]
        if any(r["status"] not in {"pending", "completed", "failed"} or
               r["reserved_tokens"] != 16384 or
               (r["status"] != "pending" and not 0 <= r["charged_tokens"] <= 16384)
               for r in requests):
            raise ValueError("invalid request reservation/settlement")
        pending = [i for i, r in enumerate(requests) if r["status"] == "pending"]
        if len(pending) > 1 or (pending and pending != [len(requests) - 1]):
            raise ValueError("invalid pending request sequence")
        total = sum(r["reserved_tokens"] if r["status"] == "pending" else r["charged_tokens"] for r in requests)
        if total != checkpoint["budget"]["used"].get("tokens", 0):
            raise ValueError("request and checkpoint budget disagree")
        # A settled request without an approval cannot have run through this
        # controller. Do not accidentally resume a foreign/pending checkpoint.
        if any(i not in self.approved for i, r in enumerate(requests) if r["status"] != "pending"):
            raise ValueError("unapproved completed inference")
        self.last = checkpoint
        if not pending or pending[0] in self.approved:
            return None
        i = pending[0]
        reason = ("token_budget" if self.prior_tokens + total > self.max_tokens else
                  "wall_budget" if self.remaining(elapsed) <= 0 else None)
        receipt = {"schema": "checkpoint-inference-admission-v1", "request_index": i,
                   "runtime_identity": checkpoint["identity"], "checkpoint_hash": fingerprint(checkpoint),
                   "context_hash": requests[i]["context_hash"], "reserved_tokens": requests[i]["reserved_tokens"],
                   "prior_tokens": self.prior_tokens, "project_tokens_with_reservation": self.prior_tokens + total,
                   "max_tokens": self.max_tokens, "elapsed_seconds": elapsed,
                   "prior_wall_seconds": self.prior_wall, "max_wall_seconds": self.max_wall,
                   "close_grace_seconds": self.close_grace, "approved": reason is None, "reason": reason}
        return receipt

    def record_approval(self, receipt):
        """Call only AFTER persisting the receipt, BEFORE sending worker ACK."""
        if not receipt["approved"] or self.last is None or receipt["checkpoint_hash"] != fingerprint(self.last):
            raise ValueError("approval does not bind current checkpoint")
        self.approved.add(receipt["request_index"])

    def charged_tokens(self):
        if self.last is None:
            return 0
        return sum(r["charged_tokens"] if r["status"] != "pending" else
                   (r["reserved_tokens"] if i in self.approved else 0)
                   for i, r in enumerate(self.last["model_requests"]))

    def remaining(self, elapsed):
        return self.max_wall - self.prior_wall - elapsed - self.close_grace
