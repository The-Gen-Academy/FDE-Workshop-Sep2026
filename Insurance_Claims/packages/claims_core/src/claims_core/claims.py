"""Claims rules shared by the ADK agent and local applications.

Thresholds implement the project's demonstration policy in
``docs/claims_handling_policy.md``; they are not validated underwriting rules.
"""

import math
import uuid
from collections.abc import MutableMapping
from datetime import date, datetime, timezone
from typing import Any

from .storage import ArrayUnion, get_store

ClaimState = MutableMapping[str, Any]

LABOR_RATE_PER_HOUR = 120
LOW_PRIORITY_LIMIT_PCT = 0.10
HIGH_PRIORITY_LIMIT_PCT = 0.50
RECENT_CLAIM_WINDOW_DAYS = 365
RECENT_CLAIM_COUNT_THRESHOLD = 2
NEW_POLICY_WINDOW_DAYS = 30
EXCLUSION_CONFIDENCE_THRESHOLD = 0.5
PHOTO_CONFIRMED_SCORE = 1.0
CONSISTENCY_SCORE_THRESHOLD = 0.7
MIN_REQUIRED_PHOTOS = 2


def start_claim_intake(
    incident_date: str,
    incident_time: str,
    location: str,
    description: str,
    driver_name: str,
    is_drivable: bool,
    anyone_injured: bool,
    other_party_involved: bool,
    other_party_info: str,
    police_report_filed: bool,
    state: ClaimState,
) -> dict:
    """Open a claim and retain the reported incident."""
    claim_id = f"CLM-{uuid.uuid4().hex[:8].upper()}"
    incident = {
        "incident_date": incident_date,
        "incident_time": incident_time,
        "location": location,
        "description": description,
        "driver_name": driver_name,
        "is_drivable": is_drivable,
        "anyone_injured": anyone_injured,
        "other_party_involved": other_party_involved,
        "other_party_info": other_party_info,
        "police_report_filed": police_report_filed,
    }
    state["claim_id"] = claim_id
    state["incident"] = incident
    return {"claim_id": claim_id, "incident": incident}


def identify_policy(policy_number: str, state: ClaimState) -> dict:
    """Load the policy for later coverage and history checks."""
    doc = get_store().collection("policies").document(policy_number).get()
    policy = doc.to_dict() if doc.exists else None
    if policy is None:
        return {"status": "not_found", "policy_number": policy_number}
    state["policy_number"] = policy_number
    state["policy"] = policy
    return {"status": "found", "policy_number": policy_number, "policy": policy}


def record_damage_evidence(
    photo_descriptions: list[str],
    customer_damage_description: str,
    consistency_score: float,
    consistency_note: str,
    vin: str,
    photo_refs: list[str],
    state: ClaimState,
) -> dict:
    """Record actual photo references and the model’s evidence assessment."""
    if len(photo_refs) < MIN_REQUIRED_PHOTOS:
        return {
            "error": f"At least {MIN_REQUIRED_PHOTOS} photos are required. Only {len(photo_refs)} actual uploaded photo(s) were found — ask the customer to attach more."
        }
    if not isinstance(consistency_score, (int, float)) or not math.isfinite(consistency_score):
        return {"error": "consistency_score must be a finite number between 0.0 and 1.0."}
    if not 0.0 <= consistency_score <= 1.0:
        return {"error": "consistency_score must be between 0.0 and 1.0."}
    policy = state.get("policy") or {}
    vin_match = policy.get("vin") == vin if policy else None
    evidence = {
        "photo_descriptions": photo_descriptions,
        "customer_damage_description": customer_damage_description,
        "photo_refs": photo_refs,
        "consistency_score": consistency_score,
        "consistency_note": consistency_note,
        "vin": vin,
        "vin_match": vin_match,
    }
    state["evidence"] = evidence
    if vin and policy:
        get_store().collection("vin_claims").document(vin).set(
            {
                "claims": ArrayUnion(
                    [
                        {
                            "claim_id": state.get("claim_id"),
                            "policyholder_id": policy.get("policyholder_id"),
                            "date": (state.get("incident") or {}).get("incident_date"),
                        }
                    ]
                )
            },
            merge=True,
        )
    return evidence


def verify_coverage(
    incident_type: str,
    cause_covered: bool,
    coverage_confidence: float,
    coverage_reasoning: str,
    state: ClaimState,
) -> dict:
    """Apply policy checks and the supplied exclusion assessment."""
    policy = state.get("policy")
    incident = state.get("incident")
    if not policy or not incident:
        return {"status": "needs_review", "reason": "Missing policy or incident data."}
    state["incident_type"] = incident_type
    loss_date = date.fromisoformat(incident["incident_date"])
    effective = date.fromisoformat(policy["effective_date"])
    expiration = date.fromisoformat(policy["expiration_date"])
    if not effective <= loss_date <= expiration:
        result = {
            "status": "not_covered",
            "reason": f"Policy is not active on {loss_date.isoformat()} (active {effective.isoformat()} to {expiration.isoformat()}).",
            "deductible": policy["coverage"]["deductible"],
        }
        state["coverage_result"] = result
        return result
    if not policy["coverage"].get(incident_type, False):
        result = {
            "status": "not_covered",
            "reason": f"Policy does not include {incident_type} coverage.",
            "deductible": policy["coverage"]["deductible"],
        }
        state["coverage_result"] = result
        return result
    if "unlisted_driver" in policy.get("exclusions", []):
        driver_name = incident.get("driver_name", "")
        listed_drivers = policy.get("listed_drivers", [])
        if driver_name and driver_name not in listed_drivers:
            result = {
                "status": "needs_review",
                "reason": f"'{driver_name}' is not on the policy's list of drivers ({', '.join(listed_drivers) or 'none listed'}).",
                "deductible": policy["coverage"]["deductible"],
            }
            state["coverage_result"] = result
            return result
    if coverage_confidence < EXCLUSION_CONFIDENCE_THRESHOLD:
        result = {
            "status": "needs_review",
            "reason": f"Exclusion assessment inconclusive (confidence {coverage_confidence:.0%}): {coverage_reasoning}",
            "deductible": policy["coverage"]["deductible"],
            "cause_covered": cause_covered,
            "coverage_confidence": coverage_confidence,
        }
        state["coverage_result"] = result
        return result
    if not cause_covered:
        result = {
            "status": "not_covered",
            "reason": coverage_reasoning,
            "deductible": policy["coverage"]["deductible"],
            "cause_covered": cause_covered,
            "coverage_confidence": coverage_confidence,
        }
        state["coverage_result"] = result
        return result
    evidence = state.get("evidence") or {}
    if evidence.get("vin_match") is False:
        result = {
            "status": "needs_review",
            "reason": "VIN on submitted evidence does not match the VIN on the policy.",
            "deductible": policy["coverage"]["deductible"],
            "cause_covered": cause_covered,
            "coverage_confidence": coverage_confidence,
        }
        state["coverage_result"] = result
        return result
    result = {
        "status": "covered",
        "reason": f"{incident_type.capitalize()} coverage applies; policy active on date of loss; no exclusions triggered ({coverage_reasoning}).",
        "deductible": policy["coverage"]["deductible"],
        "cause_covered": cause_covered,
        "coverage_confidence": coverage_confidence,
    }
    state["coverage_result"] = result
    return result


def check_claim_history(state: ClaimState) -> dict:
    """Evaluate the demo policy’s history, VIN, and consistency signals."""
    policy = state.get("policy")
    if not policy:
        result = {
            "risk_flag": "needs_closer_look",
            "reason": "No policy on file to check history against.",
            "hard_fraud_signals": [],
        }
        state["risk_result"] = result
        return result
    incident = state.get("incident") or {}
    reasons = []
    hard_fraud_signals = []
    doc = get_store().collection("claim_history").document(policy["policyholder_id"]).get()
    claims = doc.to_dict().get("claims", []) if doc.exists else []
    recent_claims = claims
    loss_date = None
    if incident.get("incident_date"):
        loss_date = date.fromisoformat(incident["incident_date"])
        recent_claims = [
            c
            for c in claims
            if abs((loss_date - date.fromisoformat(c["date"])).days) <= RECENT_CLAIM_WINDOW_DAYS
        ]
    if len(recent_claims) >= RECENT_CLAIM_COUNT_THRESHOLD:
        reasons.append(
            f"{len(recent_claims)} claims filed by this policyholder within the last {RECENT_CLAIM_WINDOW_DAYS} days: {[c['claim_id'] for c in recent_claims]}."
        )
        hard_fraud_signals.append("claim_frequency")
    if loss_date and policy.get("effective_date"):
        policy_age_days = (loss_date - date.fromisoformat(policy["effective_date"])).days
        if 0 <= policy_age_days < NEW_POLICY_WINDOW_DAYS:
            reasons.append(
                f"Policy was only {policy_age_days} day(s) old on the date of loss (effective {policy['effective_date']})."
            )
            hard_fraud_signals.append("new_policy")
    vin = (state.get("evidence") or {}).get("vin")
    if vin:
        vin_doc = get_store().collection("vin_claims").document(vin).get()
        vin_claims = vin_doc.to_dict().get("claims", []) if vin_doc.exists else []
        other_holder_claims = [
            c for c in vin_claims if c.get("policyholder_id") != policy["policyholder_id"]
        ]
        if other_holder_claims:
            reasons.append(
                f"VIN {vin} has prior claim(s) under a different policyholder: {[c['claim_id'] for c in other_holder_claims]}."
            )
            hard_fraud_signals.append("vin_reuse")
    evidence = state.get("evidence") or {}
    consistency_score = evidence.get("consistency_score")
    if consistency_score is not None and consistency_score < CONSISTENCY_SCORE_THRESHOLD:
        reasons.append(
            f"Visible damage doesn't clearly match the incident description (consistency score {consistency_score:.0%}): {evidence.get('consistency_note') or 'no further detail given'}."
        )
    if reasons:
        result = {
            "risk_flag": "needs_closer_look",
            "reason": " ".join(reasons),
            "hard_fraud_signals": hard_fraud_signals,
        }
    else:
        result = {
            "risk_flag": "clean",
            "reason": "No unusual claim frequency or pattern found.",
            "hard_fraud_signals": [],
        }
    state["risk_result"] = result
    return result


def estimate_repair_cost(
    photo_confirmed_parts: list[str], claimed_only_parts: list[str], state: ClaimState
) -> dict:
    """Price reported parts and retain their evidence provenance."""
    consistency_score = (state.get("evidence") or {}).get("consistency_score", 1.0)
    claimed_only_score = (
        PHOTO_CONFIRMED_SCORE
        if consistency_score >= CONSISTENCY_SCORE_THRESHOLD
        else consistency_score
    )
    part_provenance = {}
    for part in photo_confirmed_parts:
        part_provenance[part] = {"provenance": "photo_confirmed", "score": PHOTO_CONFIRMED_SCORE}
    for part in claimed_only_parts:
        if part in part_provenance:
            continue
        part_provenance[part] = {"provenance": "claimed_only", "score": claimed_only_score}
    all_parts = list(part_provenance.keys())
    collection = get_store().collection("parts_pricing")
    refs = [collection.document(part) for part in all_parts]
    pricing = {doc.id: doc.to_dict() for doc in get_store().get_all(refs) if doc.exists}
    low_total = 0.0
    high_total = 0.0
    priced_parts = []
    unknown_parts = []
    for part in all_parts:
        entry = pricing.get(part)
        if entry is None:
            unknown_parts.append(part)
            continue
        subtotal = entry["part_cost"] + entry["labor_hours"] * LABOR_RATE_PER_HOUR
        part_low = subtotal * 0.9
        part_high = subtotal * 1.25
        part_provenance[part]["estimated_cost_low"] = round(part_low, 2)
        part_provenance[part]["estimated_cost_high"] = round(part_high, 2)
        low_total += part_low
        high_total += part_high
        priced_parts.append(part)
    policy = state.get("policy") or {}
    policy_limit = policy.get("coverage", {}).get("limits")
    exceeds_limit = policy_limit is not None and high_total > policy_limit
    insurable_amount = (
        min(round(high_total, 2), policy_limit)
        if policy_limit is not None
        else round(high_total, 2)
    )
    result = {
        "priced_parts": priced_parts,
        "unknown_parts": unknown_parts,
        "part_provenance": part_provenance,
        "estimated_cost_low": round(low_total, 2),
        "estimated_cost_high": round(high_total, 2),
        "policy_limit": policy_limit,
        "exceeds_limit": exceeds_limit,
        "insurable_amount": insurable_amount,
    }
    state["cost_estimate"] = result
    return result


def classify_claim_priority(state: ClaimState) -> dict:
    """Combine coverage, risk, and policy-relative cost thresholds."""
    coverage = state.get("coverage_result")
    if not coverage:
        result = {"priority": "high", "reason": "Missing coverage result."}
        state["priority_result"] = result
        return result
    if coverage["status"] == "not_covered":
        result = {"priority": "high", "reason": f"Coverage is not covered: {coverage['reason']}"}
        state["priority_result"] = result
        return result
    risk = state.get("risk_result")
    cost = state.get("cost_estimate")
    if not risk or not cost:
        result = {"priority": "high", "reason": "Missing one or more of risk/cost results."}
        state["priority_result"] = result
        return result
    policy_limit = cost.get("policy_limit")
    high_threshold = policy_limit * HIGH_PRIORITY_LIMIT_PCT if policy_limit else None
    low_threshold = policy_limit * LOW_PRIORITY_LIMIT_PCT if policy_limit else None
    high_reasons = []
    if coverage["status"] != "covered":
        high_reasons.append(f"coverage status is '{coverage['status']}'")
    if risk["risk_flag"] != "clean":
        high_reasons.append("risk flag is not clean")
    if high_threshold is not None and cost["estimated_cost_high"] > high_threshold:
        high_reasons.append(
            f"estimated cost high end (${cost['estimated_cost_high']}) exceeds {HIGH_PRIORITY_LIMIT_PCT:.0%} of the policy limit (${high_threshold:,.2f})"
        )
    if cost.get("exceeds_limit"):
        high_reasons.append(
            f"estimated cost high end (${cost['estimated_cost_high']}) exceeds the policy's coverage limit (${policy_limit})"
        )
    if high_reasons:
        result = {"priority": "high", "reason": "; ".join(high_reasons)}
    elif low_threshold is not None and cost["estimated_cost_high"] > low_threshold:
        result = {
            "priority": "medium",
            "reason": f"Coverage is clear and risk is clean, but estimated cost high end (${cost['estimated_cost_high']}) exceeds {LOW_PRIORITY_LIMIT_PCT:.0%} of the policy limit (${low_threshold:,.2f}).",
        }
    else:
        result = {
            "priority": "low",
            "reason": "Coverage is clear, no risk flags, and cost is within the low-priority range.",
        }
    state["priority_result"] = result
    return result


def recommend_decision(state: ClaimState) -> dict:
    """Recommend a decision; packaging determines whether it is executed."""
    coverage = state.get("coverage_result")
    cost = state.get("cost_estimate")
    priority = state.get("priority_result")
    if not coverage or not priority:
        result = {
            "recommended_action": "needs_manual_review",
            "recommended_amount": None,
            "reason": "Missing one or more of coverage/priority results.",
        }
        state["recommendation"] = result
        return result
    if priority["priority"] != "high":
        if not cost:
            result = {
                "recommended_action": "needs_manual_review",
                "recommended_amount": None,
                "reason": "Missing cost estimate.",
            }
            state["recommendation"] = result
            return result
        midpoint = (cost["estimated_cost_low"] + cost["estimated_cost_high"]) / 2
        capped_midpoint = min(midpoint, cost.get("insurable_amount", midpoint))
        deductible = coverage.get("deductible") or 0
        result = {
            "recommended_action": "approve",
            "recommended_amount": round(max(0, capped_midpoint - deductible), 2),
            "reason": f"Coverage is covered and risk is clean (priority: {priority['priority']}).",
        }
    elif coverage["status"] == "not_covered":
        result = {
            "recommended_action": "deny",
            "recommended_amount": None,
            "reason": coverage["reason"],
        }
    elif (state.get("risk_result") or {}).get("hard_fraud_signals"):
        risk = state.get("risk_result") or {}
        result = {
            "recommended_action": "deny",
            "recommended_amount": None,
            "reason": f"Hard fraud signal(s) {risk['hard_fraud_signals']}: {risk['reason']}",
        }
    else:
        result = {
            "recommended_action": "needs_manual_review",
            "recommended_amount": None,
            "reason": priority["reason"],
        }
    state["recommendation"] = result
    return result


def _package_result(package: dict) -> dict:
    """Expose only executed outcomes as customer-facing decision fields."""
    result = {
        **package,
        "auto_approved": package["status"] == "auto_approved",
        "auto_denied": package["status"] == "auto_denied",
    }
    recommendation = package.get("recommendation") or {}
    if result["auto_approved"]:
        result["approved_amount"] = recommendation.get("recommended_amount")
        result["deductible"] = (package.get("coverage_result") or {}).get("deductible")
    elif result["auto_denied"]:
        result["denial_reason"] = recommendation.get("reason")
    return result


def package_for_adjuster(state: ClaimState) -> dict:
    """Persist the handoff, history, and any automatic outcome together.

    Repeated calls return the existing package without reopening a resolved
    claim or duplicating its history.
    """
    claim_id = state.get("claim_id")
    if not claim_id:
        raise ValueError("Open a claim before packaging it.")
    priority = state.get("priority_result") or {}
    recommendation = state.get("recommendation") or {}
    risk = state.get("risk_result") or {}
    auto_approved = (
        priority.get("priority") == "low" and recommendation.get("recommended_action") == "approve"
    )
    # Preserve the demo policy: only recorded hard signals allow auto-denial.
    auto_denied = recommendation.get("recommended_action") == "deny" and bool(
        risk.get("hard_fraud_signals")
    )
    status = (
        "auto_approved" if auto_approved else "auto_denied" if auto_denied else "pending_review"
    )
    package = {
        key: state.get(key)
        for key in (
            "claim_id",
            "incident",
            "policy_number",
            "policy",
            "evidence",
            "coverage_result",
            "risk_result",
            "cost_estimate",
            "priority_result",
            "recommendation",
        )
    }
    package.update(status=status, queued_at=datetime.now(timezone.utc).isoformat())
    if auto_approved or auto_denied:
        package["resolved_at"] = package["queued_at"]

    def persist(transaction):
        existing = transaction.get("escalations", claim_id)
        if existing:
            return _package_result(existing)
        policyholder_id = (state.get("policy") or {}).get("policyholder_id")
        history = transaction.get("claim_history", policyholder_id) if policyholder_id else None
        if policyholder_id:
            incident = state.get("incident") or {}
            cost = state.get("cost_estimate") or {}
            entries = list((history or {}).get("claims", []))
            if not any(entry.get("claim_id") == claim_id for entry in entries):
                entries.append(
                    {
                        "claim_id": claim_id,
                        "date": incident.get("incident_date"),
                        "type": state.get("incident_type"),
                        "amount": cost.get("insurable_amount", 0),
                    }
                )
            transaction.set("claim_history", policyholder_id, {"claims": entries}, merge=True)
        transaction.set("escalations", claim_id, package)
        if auto_approved or auto_denied:
            record = {
                "claim_id": claim_id,
                "policy_number": package["policy_number"],
                "system_priority": priority.get("priority"),
                "final_decision": (
                    f"approved:{recommendation.get('recommended_amount')}"
                    if auto_approved
                    else "denied"
                ),
                "matched_system_suggestion": True,
                "override_reason": "",
                "logged_at": package["queued_at"],
                "auto_approved" if auto_approved else "auto_denied": True,
            }
            transaction.set("claims_log", claim_id, record)
        return _package_result(package)

    return get_store().atomic(persist)


def log_outcome(
    final_decision: str,
    matched_system_suggestion: bool,
    override_reason: str,
    state: ClaimState,
) -> dict:
    """Record a human decision and resolve its queue entry together."""
    claim_id = state.get("claim_id")
    if not claim_id:
        raise ValueError("A claim ID is required to log an outcome.")
    record = {
        "claim_id": claim_id,
        "policy_number": state.get("policy_number"),
        "system_priority": (state.get("priority_result") or {}).get("priority"),
        "final_decision": final_decision,
        "matched_system_suggestion": matched_system_suggestion,
        "override_reason": override_reason,
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }

    def persist(transaction):
        transaction.set("claims_log", claim_id, record)
        transaction.set(
            "escalations",
            claim_id,
            {"status": "resolved", "resolved_at": record["logged_at"]},
            merge=True,
        )

    get_store().atomic(persist)
    return record
