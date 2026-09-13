"""Policy administration used by the adjuster portal."""

import math
import uuid
from datetime import date, datetime, timezone

from .storage import get_store

# These keys are also used by the agent's coverage checks.
KNOWN_EXCLUSIONS = ["racing", "commercial_use", "unlisted_driver"]


class PolicyValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class PolicyAlreadyExists(Exception):
    def __init__(self, policy_number: str):
        self.policy_number = policy_number
        super().__init__(policy_number)


def create_policy(
    policyholder_name: str,
    vin: str,
    listed_drivers: list[str],
    collision: bool,
    comprehensive: bool,
    deductible: float,
    limits: float,
    effective_date: str,
    expiration_date: str,
    exclusions: list[str],
) -> dict:
    """Create a validated policy without overwriting an existing policy number."""
    policyholder_name = (policyholder_name or "").strip()
    vin = (vin or "").strip().upper()
    listed_drivers = [driver.strip() for driver in listed_drivers if driver.strip()]
    unknown_exclusions = [value for value in exclusions if value not in KNOWN_EXCLUSIONS]

    if not policyholder_name:
        raise PolicyValidationError("Policyholder name is required.")
    if not vin:
        raise PolicyValidationError("VIN is required.")
    if not listed_drivers:
        raise PolicyValidationError("At least one listed driver is required.")
    if not math.isfinite(deductible) or deductible < 0:
        raise PolicyValidationError("Deductible must be finite and cannot be negative.")
    if not math.isfinite(limits) or limits <= 0:
        raise PolicyValidationError("Coverage limit must be finite and positive.")
    try:
        effective = date.fromisoformat(effective_date)
        expiration = date.fromisoformat(expiration_date)
    except ValueError as exc:
        raise PolicyValidationError("Coverage dates must use YYYY-MM-DD format.") from exc
    if expiration <= effective:
        raise PolicyValidationError("Expiration date must be after the effective date.")
    if unknown_exclusions:
        raise PolicyValidationError(f"Unknown exclusion(s): {', '.join(unknown_exclusions)}.")

    policy_number = f"POL-{uuid.uuid4().hex[:8].upper()}"
    record = {
        "policyholder_id": f"CUST-{uuid.uuid4().hex[:8].upper()}",
        "policyholder_name": policyholder_name,
        "vin": vin,
        "listed_drivers": listed_drivers,
        "coverage": {
            "collision": collision,
            "comprehensive": comprehensive,
            "deductible": deductible,
            "limits": limits,
        },
        "effective_date": effective.isoformat(),
        "expiration_date": expiration.isoformat(),
        "exclusions": exclusions,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    def insert(transaction):
        if transaction.get("policies", policy_number) is not None:
            raise PolicyAlreadyExists(policy_number)
        transaction.set("policies", policy_number, record)

    get_store().atomic(insert)
    return {"policy_number": policy_number, **record}


def list_policies() -> list[dict]:
    """Return newest policies first, followed by seeds without a creation date."""
    policies = [
        {"policy_number": policy_number, **fields}
        for policy_number, fields in get_store().collection("policies").list_all().items()
    ]
    policies.sort(key=lambda policy: policy.get("created_at") or "", reverse=True)
    return policies
