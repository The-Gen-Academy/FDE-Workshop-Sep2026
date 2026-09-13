from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from claims_core.storage import ArrayUnion, FirestoreStore, LocalStore


def test_atomic_rolls_back_all_documents(tmp_path):
    store = LocalStore(tmp_path)
    store.collection("escalations").document("C1").set({"status": "pending_review"})

    def broken(tx):
        tx.set("escalations", "C1", {"status": "resolved"})
        tx.set("claims_log", "C1", {"decision": "approve"})
        raise RuntimeError("failure before commit")

    with pytest.raises(RuntimeError):
        store.atomic(broken)
    assert store.read("escalations", "C1") == {"status": "pending_review"}
    assert store.read("claims_log", "C1") is None


def test_concurrent_updates_do_not_lose_values(tmp_path):
    store = LocalStore(tmp_path)
    store.collection("counts").document("C1").set({"count": 0})

    def increment(_):
        def apply(tx):
            count = tx.get("counts", "C1")["count"]
            tx.set("counts", "C1", {"count": count + 1})

        store.atomic(apply)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(increment, range(30)))
    assert store.read("counts", "C1")["count"] == 30


def test_union_and_nested_merge(tmp_path):
    document = LocalStore(tmp_path).collection("history").document("P1")
    document.set({"claims": [{"id": "C1"}], "policy": {"limit": 10, "deductible": 1}})
    document.set(
        {"claims": ArrayUnion([{"id": "C1"}, {"id": "C2"}]), "policy": {"limit": 20}}, merge=True
    )
    assert document.get().to_dict() == {
        "claims": [{"id": "C1"}, {"id": "C2"}],
        "policy": {"limit": 20, "deductible": 1},
    }


def test_query_supports_queue_and_priority(tmp_path):
    collection = LocalStore(tmp_path).collection("escalations")
    for key, status, priority in (
        ("C1", "resolved", "high"),
        ("C2", "pending_review", "high"),
        ("C3", "pending_review", "low"),
    ):
        collection.document(key).set({"status": status, "priority_result": {"priority": priority}})
    assert list(
        collection.query(
            filters=[("status", "==", "pending_review"), ("priority_result.priority", "==", "high")]
        )
    ) == ["C2"]


def test_firestore_adapter_translates_writes_and_queries():
    from google.cloud import firestore

    client = MagicMock()
    store = FirestoreStore("test-project", client=client)
    reference = client.collection.return_value.document.return_value
    reference.get.return_value.to_dict.return_value = {"status": "pending_review"}
    transaction = client.transaction.return_value
    # Exercise our callback against the SDK-shaped transaction without RPCs.
    with patch.object(firestore, "transactional", side_effect=lambda function: function):

        def resolve(tx):
            assert tx.get("escalations", "C1")["status"] == "pending_review"
            tx.set("history", "P1", {"claims": ArrayUnion(["C1"])}, merge=True)

        store.atomic(resolve)
    reference.get.assert_called_once_with(transaction=transaction)
    args, kwargs = transaction.set.call_args
    assert isinstance(args[1]["claims"], firestore.ArrayUnion)
    assert kwargs == {"merge": True}

    result = MagicMock(id="C1")
    result.to_dict.return_value = {"status": "pending_review"}
    client.collection.return_value.where.return_value.stream.return_value = [result]
    assert store.collection("escalations").query(filters=[("status", "==", "pending_review")]) == {
        "C1": {"status": "pending_review"}
    }
    query_filter = client.collection.return_value.where.call_args.kwargs["filter"]
    assert (query_filter.field_path, query_filter.op_string, query_filter.value) == (
        "status",
        "==",
        "pending_review",
    )
