"""Validate adjuster decisions and atomically resolve their claims."""

import math
from datetime import datetime, timezone

from .storage import get_store


class ClaimNotFound(Exception):
    def __init__(self, claim_id: str):
        self.claim_id = claim_id
        super().__init__(claim_id)


class ClaimAlreadyResolved(Exception):
    def __init__(self, claim_id: str, status: str):
        self.claim_id = claim_id
        self.status = status
        super().__init__(f"Claim {claim_id} is already {status}.")


class DecisionValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def submit_decision(claim_id: str, action: str, amount: float | None, reason: str) -> dict:
    """Resolve a pending claim once, keeping its decision and status together."""
    if action not in {"approve", "deny"}:
        raise DecisionValidationError("Action must be approve or deny.")

    def resolve(transaction):
        doc = transaction.get("escalations", claim_id)
        if doc is None:
            raise ClaimNotFound(claim_id)
        if doc.get("status") != "pending_review":
            raise ClaimAlreadyResolved(claim_id, doc.get("status", "unknown"))

        _validate_amount(doc, action, amount)
        recommended_action = (doc.get("recommendation") or {}).get("recommended_action")
        matched = recommended_action in (None, "needs_manual_review", action)
        logged_at = datetime.now(timezone.utc).isoformat()
        record = {
            "claim_id": claim_id,
            "policy_number": doc.get("policy_number"),
            "system_priority": (doc.get("priority_result") or {}).get("priority"),
            "final_decision": f"approved:{amount}" if action == "approve" else "denied",
            "matched_system_suggestion": matched,
            "override_reason": "" if matched else (reason or ""),
            "adjuster_notes": reason or "",
            "logged_at": logged_at,
        }
        transaction.set("claims_log", claim_id, record)
        transaction.set(
            "escalations", claim_id, {"status": "resolved", "resolved_at": logged_at}, merge=True
        )
        return record

    return get_store().atomic(resolve)


def _validate_amount(doc: dict, action: str, amount: float | None) -> None:
    if action != "approve":
        return
    if amount is None or not math.isfinite(amount):
        raise DecisionValidationError("An approval amount is required and must be finite.")
    if amount < 0:
        raise DecisionValidationError("Approval amount cannot be negative.")
    policy_limit = ((doc.get("policy") or {}).get("coverage") or {}).get("limits")
    if policy_limit is not None and amount > policy_limit:
        raise DecisionValidationError(
            f"Approval amount cannot exceed the policy limit of {policy_limit:.2f}."
        )
