"""ADK tool schemas and adapters for the shared claims rules."""

from claims_core import claims
from google.adk.tools import ToolContext

from .evidence import collect_customer_photos


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
    tool_context: ToolContext,
) -> dict:
    """Open a claim after collecting the incident details.

    Args:
        incident_date: Date of loss as YYYY-MM-DD.
        incident_time: Reported time, such as "14:30" or "afternoon".
        location: Where the incident occurred.
        description: The customer's account of what happened.
        driver_name: Name of the person driving at the time.
        is_drivable: Whether the vehicle is currently drivable.
        anyone_injured: Whether anyone was injured.
        other_party_involved: Whether another party was involved.
        other_party_info: Their details, or an empty string if not applicable.
        police_report_filed: Whether a police report was filed.
        tool_context: Injected session context.
    """
    return claims.start_claim_intake(
        incident_date,
        incident_time,
        location,
        description,
        driver_name,
        is_drivable,
        anyone_injured,
        other_party_involved,
        other_party_info,
        police_report_filed,
        tool_context.state,
    )


def identify_policy(policy_number: str, tool_context: ToolContext) -> dict:
    """Find and retain the customer's policy; ask again if not found.

    Args:
        policy_number: Customer-provided policy number, e.g. POL-100234.
        tool_context: Injected session context.
    """
    return claims.identify_policy(policy_number, tool_context.state)


def record_damage_evidence(
    photo_descriptions: list[str],
    customer_damage_description: str,
    consistency_score: float,
    consistency_note: str,
    vin: str,
    tool_context: ToolContext,
) -> dict:
    """Record at least two real photos and an independent assessment of them.

    Args:
        photo_descriptions: Your visual description of each actual attached photo.
        customer_damage_description: The customer's damage description verbatim;
            keep it separate from your visual assessment.
        consistency_score: Honest confidence from 0 to 1 that visible damage fits
            the incident. Lower for material contradictions, not hidden damage.
            Below 0.7 triggers review and lowers claimed-only confidence.
        consistency_note: Neutral explanation when the score is below 0.7;
            otherwise an empty string. Do not accuse the customer.
        vin: VIN supplied by the customer, never inferred from a photo.
        tool_context: Injected session context; supplies actual photo references.
    """
    return claims.record_damage_evidence(
        photo_descriptions,
        customer_damage_description,
        consistency_score,
        consistency_note,
        vin,
        [ref for ref, _ in collect_customer_photos(tool_context)],
        tool_context.state,
    )


def verify_coverage(
    incident_type: str,
    cause_covered: bool,
    coverage_confidence: float,
    coverage_reasoning: str,
    tool_context: ToolContext,
) -> dict:
    """Check coverage using policy data and your exclusion assessment.

    Args:
        incident_type: "collision" or "comprehensive", based on the incident.
        cause_covered: Whether the cause avoids the policy's exclusions, except
            unlisted_driver, which the tool checks against listed drivers.
        coverage_confidence: Honest confidence from 0 to 1. Below 0.5 requires
            human review regardless of the direction of your assessment.
        coverage_reasoning: Specific exclusion considered and supporting facts.
        tool_context: Injected session context.
    """
    return claims.verify_coverage(
        incident_type, cause_covered, coverage_confidence, coverage_reasoning, tool_context.state
    )


def check_claim_history(tool_context: ToolContext) -> dict:
    """Check frequency, policy age, VIN reuse, and photo consistency.

    Args:
        tool_context: Injected session context.
    """
    return claims.check_claim_history(tool_context.state)


def estimate_repair_cost(
    photo_confirmed_parts: list[str], claimed_only_parts: list[str], tool_context: ToolContext
) -> dict:
    """Price all reported damage and compute confidence from its provenance.

    Args:
        photo_confirmed_parts: Part keys independently visible as damaged in photos.
        claimed_only_parts: Additional parts reported by the customer but unseen
            in photos. Include hidden damage; put each part in only one list.
        tool_context: Injected session context.
    """
    return claims.estimate_repair_cost(
        photo_confirmed_parts, claimed_only_parts, tool_context.state
    )


def classify_claim_priority(tool_context: ToolContext) -> dict:
    """Classify priority from coverage, risk, and policy-relative repair cost.

    Args:
        tool_context: Injected session context.
    """
    return claims.classify_claim_priority(tool_context.state)


def recommend_decision(tool_context: ToolContext) -> dict:
    """Suggest an outcome for packaging; pending recommendations stay internal.

    Args:
        tool_context: Injected session context.
    """
    return claims.recommend_decision(tool_context.state)


def package_for_adjuster(tool_context: ToolContext) -> dict:
    """Queue the claim or execute the demo policy's automatic outcome.

    Low-priority approvals and hard-signal denials execute here. Other outcomes,
    including coverage denials, await an adjuster. Return flags identify which
    outcome actually occurred; do not present a pending recommendation as final.

    Args:
        tool_context: Injected session context.
    """
    return claims.package_for_adjuster(tool_context.state)


def log_outcome(
    final_decision: str,
    matched_system_suggestion: bool,
    override_reason: str,
    tool_context: ToolContext,
) -> dict:
    """Log a later human decision; automatic outcomes are already logged.

    Args:
        final_decision: Actual adjuster outcome, e.g. "approved:1800" or "denied".
        matched_system_suggestion: Whether it agrees with the system suggestion.
        override_reason: Explanation for an override, otherwise an empty string.
        tool_context: Injected session context.
    """
    return claims.log_outcome(
        final_decision, matched_system_suggestion, override_reason, tool_context.state
    )
