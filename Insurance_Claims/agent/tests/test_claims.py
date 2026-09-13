"""Offline regression coverage for the existing demonstration policy."""

from types import SimpleNamespace

import pytest
from claims_core import claims
from claims_core.storage import LocalStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = LocalStore(tmp_path)
    monkeypatch.setattr(claims, "get_store", lambda: store)
    store.collection("parts_pricing").document("front_bumper").set(
        {"part_cost": 200, "labor_hours": 1}
    )
    return store


@pytest.fixture
def state():
    return {
        "claim_id": "CLM-TEST",
        "policy_number": "POL-TEST",
        "policy": {
            "policyholder_id": "CUSTOMER-1",
            "vin": "VIN-1",
            "effective_date": "2026-01-01",
            "expiration_date": "2026-12-31",
            "listed_drivers": ["Alex"],
            "exclusions": ["racing", "unlisted_driver"],
            "coverage": {
                "collision": True,
                "comprehensive": True,
                "deductible": 100,
                "limits": 10000,
            },
        },
        "incident": {"incident_date": "2026-09-01", "driver_name": "Alex"},
        "evidence": {"vin": "VIN-1", "vin_match": True, "consistency_score": 1.0},
    }


def assess(state):
    claims.verify_coverage("collision", True, 1.0, "No excluded cause.", state)
    claims.check_claim_history(state)
    claims.estimate_repair_cost(["front_bumper"], [], state)
    claims.classify_claim_priority(state)
    claims.recommend_decision(state)
    return claims.package_for_adjuster(state)


@pytest.mark.parametrize(
    ("part_cost", "priority", "action", "status"),
    [
        (200, "low", "approve", "auto_approved"),
        (2000, "medium", "approve", "pending_review"),
        (4500, "high", "needs_manual_review", "pending_review"),
    ],
)
def test_cost_priority_and_outcome(store, state, part_cost, priority, action, status):
    store.collection("parts_pricing").document("front_bumper").set(
        {"part_cost": part_cost, "labor_hours": 1}
    )
    package = assess(state)
    assert package["status"] == status
    assert state["priority_result"]["priority"] == priority
    assert state["recommendation"]["recommended_action"] == action
    outcome = store.collection("claims_log").document("CLM-TEST").get()
    assert outcome.exists is (status == "auto_approved")
    if outcome.exists:
        assert package["approved_amount"] == 244.0
        assert outcome.to_dict()["final_decision"] == "approved:244.0"


@pytest.mark.parametrize("signal", ["claim_frequency", "new_policy", "vin_reuse"])
def test_existing_hard_signals_auto_deny(store, state, signal):
    if signal == "claim_frequency":
        store.collection("claim_history").document("CUSTOMER-1").set(
            {
                "claims": [
                    {"claim_id": "OLD-1", "date": "2026-08-01"},
                    {"claim_id": "OLD-2", "date": "2026-08-15"},
                ]
            }
        )
    elif signal == "new_policy":
        state["policy"]["effective_date"] = "2026-08-25"
    else:
        store.collection("vin_claims").document("VIN-1").set(
            {
                "claims": [
                    {"claim_id": "OLD-1", "policyholder_id": "CUSTOMER-2"},
                ]
            }
        )
    package = assess(state)
    assert package["status"] == "auto_denied"
    assert state["risk_result"]["hard_fraud_signals"] == [signal]
    assert (
        store.collection("claims_log").document("CLM-TEST").get().to_dict()["final_decision"]
        == "denied"
    )


def test_soft_photo_signal_keeps_human_review(store, state):
    state["evidence"].update(consistency_score=0.4, consistency_note="Visible impact differs.")
    package = assess(state)
    assert package["status"] == "pending_review"
    assert state["risk_result"]["hard_fraud_signals"] == []
    assert state["recommendation"]["recommended_action"] == "needs_manual_review"


def test_coverage_denial_does_not_require_risk_or_cost(store, state):
    claims.verify_coverage("collision", False, 0.9, "Racing is excluded.", state)
    assert claims.classify_claim_priority(state)["priority"] == "high"
    assert claims.recommend_decision(state)["recommended_action"] == "deny"
    package = claims.package_for_adjuster(state)
    assert package["status"] == "pending_review"
    assert package["risk_result"] is None
    assert package["cost_estimate"] is None
    assert not store.collection("claims_log").document("CLM-TEST").get().exists


def test_low_confidence_and_unlisted_driver_require_review(store, state):
    assert (
        claims.verify_coverage("collision", True, 0.49, "Unclear cause.", state)["status"]
        == "needs_review"
    )
    state["incident"]["driver_name"] = "Unlisted Driver"
    assert (
        claims.verify_coverage("collision", True, 1.0, "Covered cause.", state)["status"]
        == "needs_review"
    )


def test_provenance_preserves_full_pricing_and_policy_cap(store, state):
    state["evidence"]["consistency_score"] = 0.4
    state["policy"]["coverage"]["limits"] = 500
    store.collection("parts_pricing").document("engine").set({"part_cost": 1000, "labor_hours": 0})
    estimate = claims.estimate_repair_cost(
        ["front_bumper"],
        ["front_bumper", "engine", "unknown_part"],
        state,
    )
    assert estimate["part_provenance"]["front_bumper"]["score"] == 1.0
    assert estimate["part_provenance"]["engine"]["score"] == 0.4
    assert estimate["estimated_cost_high"] == 1650
    assert estimate["insurable_amount"] == 500
    assert estimate["exceeds_limit"] is True
    assert estimate["unknown_parts"] == ["unknown_part"]


def test_packaging_is_idempotent_and_does_not_reopen_resolved_claims(store, state):
    state["evidence"]["consistency_score"] = 0.4
    original = assess(state)
    assert claims.package_for_adjuster(state) == original
    history = store.collection("claim_history").document("CUSTOMER-1")
    assert len(history.get().to_dict()["claims"]) == 1
    record = claims.log_outcome("approved:300", False, "Reviewed additional evidence.", state)
    assert store.collection("claims_log").document("CLM-TEST").get().to_dict() == record
    assert claims.package_for_adjuster(state)["status"] == "resolved"
    assert len(history.get().to_dict()["claims"]) == 1


def test_packaging_rolls_back_history_and_queue_if_outcome_write_fails(store, state, monkeypatch):
    atomic = store.atomic

    def fail_audit_write(callback):
        def run(transaction):
            def write(collection, doc_id, data, merge=False):
                if collection == "claims_log":
                    raise RuntimeError("Audit write failed")
                transaction.set(collection, doc_id, data, merge=merge)

            return callback(SimpleNamespace(get=transaction.get, set=write))

        return atomic(run)

    monkeypatch.setattr(store, "atomic", fail_audit_write)
    with pytest.raises(RuntimeError, match="Audit write failed"):
        assess(state)
    assert store.collection("claim_history").list_all() == {}
    assert store.collection("escalations").list_all() == {}
    assert store.collection("claims_log").list_all() == {}


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_evidence_score_is_not_recorded(store, state, score):
    result = claims.record_damage_evidence(
        ["bumper", "wheel"],
        "My bumper and wheel are damaged.",
        score,
        "",
        "VIN-1",
        ["photo-1", "photo-2"],
        state,
    )
    assert "error" in result
    assert store.collection("vin_claims").list_all() == {}
