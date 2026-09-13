"""Claim review endpoints; synchronous handlers keep storage I/O off the event loop."""

import mimetypes

from claims_core import decisions, policies
from claims_core.evidence import load_photo
from claims_core.storage import get_store
from fastapi import APIRouter, HTTPException, Response
from google.api_core.exceptions import NotFound

from .schemas import DecisionRequest, PolicyCreateRequest

router = APIRouter(prefix="/api")


@router.get("/queue")
def get_queue(priority: str | None = None, q: str | None = None):
    items = []
    pending = (
        get_store().collection("escalations").query(filters=[("status", "==", "pending_review")])
    )
    for claim_id, doc in pending.items():
        doc_priority = (doc.get("priority_result") or {}).get("priority")
        if priority and doc_priority != priority:
            continue
        policy = doc.get("policy") or {}
        haystack = " ".join(
            str(x)
            for x in [claim_id, doc.get("policy_number"), policy.get("policyholder_name")]
            if x
        ).lower()
        if q and q.lower() not in haystack:
            continue
        cost = doc.get("cost_estimate")
        coverage = doc.get("coverage_result") or {}
        items.append(
            {
                "claim_id": claim_id,
                "priority": doc_priority,
                "priority_reason": (doc.get("priority_result") or {}).get("reason"),
                "policyholder_name": policy.get("policyholder_name"),
                "policy_number": doc.get("policy_number"),
                "incident_date": (doc.get("incident") or {}).get("incident_date"),
                "incident_description": (doc.get("incident") or {}).get("description"),
                "cost_low": cost.get("estimated_cost_low") if cost else None,
                "cost_high": cost.get("estimated_cost_high") if cost else None,
                "cost_not_assessed_reason": (
                    None
                    if cost
                    else f"Not assessed — coverage {coverage.get('status', 'not_covered')}"
                ),
                "queued_at": doc.get("queued_at"),
            }
        )
    items.sort(key=lambda it: it["queued_at"] or "", reverse=True)
    return items


@router.get("/claims/{claim_id}")
def get_claim(claim_id: str):
    snapshot = get_store().collection("escalations").document(claim_id).get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="claim not found")
    doc = snapshot.to_dict()
    doc["is_auto_approved"] = doc.get("status") == "auto_approved"
    doc["is_auto_denied"] = doc.get("status") == "auto_denied"
    doc["is_resolved"] = doc.get("status") == "resolved"
    return doc


@router.get("/claims/{claim_id}/photos/{index}")
def get_claim_photo(claim_id: str, index: int):
    snapshot = get_store().collection("escalations").document(claim_id).get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="claim not found")
    refs = ((snapshot.to_dict().get("evidence") or {}).get("photo_refs")) or []
    if index < 0 or index >= len(refs):
        raise HTTPException(status_code=404, detail="photo not found")
    ref = refs[index]
    try:
        data = load_photo(ref)
    except (FileNotFoundError, ValueError, NotFound) as exc:
        raise HTTPException(status_code=404, detail="photo not found") from exc
    mime_type = mimetypes.guess_type(ref)[0] or "image/jpeg"
    return Response(content=data, media_type=mime_type)


@router.post("/claims/{claim_id}/decision")
def post_decision(claim_id: str, body: DecisionRequest):
    try:
        return decisions.submit_decision(claim_id, body.action, body.amount, body.reason)
    except decisions.ClaimNotFound:
        raise HTTPException(status_code=404, detail="claim not found")
    except decisions.ClaimAlreadyResolved as e:
        raise HTTPException(status_code=409, detail=f"claim is already {e.status}")
    except decisions.DecisionValidationError as e:
        raise HTTPException(status_code=400, detail=e.message)


@router.get("/policies")
def get_policies():
    return policies.list_policies()


@router.post("/policies")
def post_policy(body: PolicyCreateRequest):
    try:
        return policies.create_policy(**body.model_dump())
    except policies.PolicyValidationError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except policies.PolicyAlreadyExists as e:
        raise HTTPException(
            status_code=409, detail=f"policy number {e.policy_number} already exists"
        )


@router.get("/history")
def get_history(
    date_from: str | None = None, date_to: str | None = None, override_only: bool = False
):
    escalations = (
        get_store()
        .collection("escalations")
        .query(filters=[("status", "in", ["resolved", "auto_approved", "auto_denied"])])
    )
    logs = get_store().collection("claims_log").list_all()
    rows = []
    for claim_id, doc in escalations.items():
        log = logs.get(claim_id, {})
        resolved_at = doc.get("resolved_at") or log.get("logged_at") or ""
        if date_from and resolved_at < date_from:
            continue
        if date_to and resolved_at > date_to:
            continue
        matched = log.get("matched_system_suggestion", True)
        if override_only and matched:
            continue
        policy = doc.get("policy") or {}
        rows.append(
            {
                "claim_id": claim_id,
                "policyholder_name": policy.get("policyholder_name"),
                "policy_number": doc.get("policy_number"),
                "priority": (doc.get("priority_result") or {}).get("priority"),
                "final_decision": log.get("final_decision"),
                "matched_system_suggestion": matched,
                "override_reason": log.get("override_reason", ""),
                "adjuster_notes": log.get("adjuster_notes", ""),
                "resolved_at": resolved_at,
                "is_auto_approved": doc.get("status") == "auto_approved",
                "is_auto_denied": doc.get("status") == "auto_denied",
            }
        )
    rows.sort(key=lambda r: r["resolved_at"], reverse=True)
    return rows
