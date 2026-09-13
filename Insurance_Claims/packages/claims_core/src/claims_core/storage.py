"""Document storage with atomic claim updates: SQLite locally, Firestore in GCP."""

import copy
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, TypeVar

from .config import load_environment, local_data_dir

T = TypeVar("T")


@dataclass(frozen=True)
class ArrayUnion:
    """Append unique values to an array field during a write."""

    values: list


@dataclass
class Snapshot:
    id: str
    _fields: dict | None

    @property
    def exists(self) -> bool:
        return self._fields is not None

    def to_dict(self) -> dict | None:
        return copy.deepcopy(self._fields)


def _name(value: str) -> str:
    if not isinstance(value, str) or not value or "/" in value or value in (".", ".."):
        raise ValueError(f"Invalid collection or document ID: {value!r}")
    return value


def _merge(existing: dict, data: dict, merge: bool) -> dict:
    result = copy.deepcopy(existing) if merge else {}
    for key, value in data.items():
        if isinstance(value, ArrayUnion):
            values = copy.deepcopy(existing.get(key) or [])
            for item in value.values:
                if item not in values:
                    values.append(copy.deepcopy(item))
            result[key] = values
        elif isinstance(value, dict):
            result[key] = _merge(existing.get(key) or {}, value, merge)
        else:
            result[key] = copy.deepcopy(value)
    return result


class Document:
    def __init__(self, store, collection: str, doc_id: str):
        self.store, self.collection, self.id = store, _name(collection), _name(doc_id)

    def get(self) -> Snapshot:
        return Snapshot(self.id, self.store.read(self.collection, self.id))

    def set(self, data: dict, merge: bool = False) -> None:
        self.store.atomic(lambda tx: tx.set(self.collection, self.id, data, merge=merge))


class Collection:
    def __init__(self, store, name: str):
        self.store, self.name = store, _name(name)

    def document(self, doc_id: str) -> Document:
        return Document(self.store, self.name, doc_id)

    def list_all(self) -> dict[str, dict]:
        return self.query()

    def query(self, filters=(), order_by: str | None = None, limit: int | None = None) -> dict:
        """Filter on dotted field names; a leading '-' sorts descending."""
        return self.store.query(self.name, filters, order_by, limit)


class _Store:
    def collection(self, name: str) -> Collection:
        return Collection(self, name)

    def get_all(self, refs) -> list[Snapshot]:
        return [ref.get() for ref in refs]


class _LocalTransaction:
    def __init__(self, connection):
        self.connection = connection

    def get(self, collection: str, doc_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT data FROM documents WHERE collection = ? AND id = ?",
            (_name(collection), _name(doc_id)),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, collection: str, doc_id: str, data: dict, merge: bool = False) -> None:
        fields = _merge(self.get(collection, doc_id) or {}, data, merge)
        self.connection.execute(
            "INSERT INTO documents (collection, id, data) VALUES (?, ?, ?) "
            "ON CONFLICT(collection, id) DO UPDATE SET data = excluded.data",
            (_name(collection), _name(doc_id), json.dumps(fields, allow_nan=False)),
        )


class LocalStore(_Store):
    """A single SQLite file gives both local portals atomic, concurrent-safe writes."""

    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "claims.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS documents ("
                "collection TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, "
                "PRIMARY KEY (collection, id))"
            )

    def _connect(self):
        return sqlite3.connect(self.path, timeout=30, isolation_level=None)

    def atomic(self, callback: Callable[[Any], T]) -> T:
        """Commit the callback's writes together, or roll everything back."""
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                result = callback(_LocalTransaction(connection))
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise

    def read(self, collection: str, doc_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            return _LocalTransaction(connection).get(collection, doc_id)

    def query(self, collection: str, filters=(), order_by=None, limit=None) -> dict:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, data FROM documents WHERE collection = ? ORDER BY id",
                (_name(collection),),
            ).fetchall()
        rows = [(doc_id, json.loads(data)) for doc_id, data in rows]
        for field, operator, expected in filters:
            if operator not in ("==", "!=", "<", "<=", ">", ">=", "in"):
                raise ValueError(f"Unsupported query operator: {operator}")
            rows = [(key, data) for key, data in rows if _matches(data, field, operator, expected)]
        if order_by:
            rows = [
                (key, data) for key, data in rows if _field(data, order_by.lstrip("-")) is not None
            ]
            rows.sort(
                key=lambda row: _field(row[1], order_by.lstrip("-")),
                reverse=order_by.startswith("-"),
            )
        if limit is not None:
            if limit < 1:
                raise ValueError("Query limit must be positive")
            rows = rows[:limit]
        return dict(rows)


def _field(data: dict, path: str):
    for key in path.split("."):
        if not isinstance(data, dict) or key not in data:
            return None
        data = data[key]
    return data


def _matches(data: dict, field: str, operator: str, expected) -> bool:
    value = _field(data, field)
    if value is None:
        return operator == "==" and expected is None
    match operator:
        case "==":
            return value == expected
        case "!=":
            return value != expected
        case "<":
            return value < expected
        case "<=":
            return value <= expected
        case ">":
            return value > expected
        case ">=":
            return value >= expected
        case "in":
            return value in expected
    return False


def _firestore_values(value):
    from google.cloud import firestore

    if isinstance(value, ArrayUnion):
        return firestore.ArrayUnion(value.values)
    if isinstance(value, dict):
        return {key: _firestore_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_firestore_values(item) for item in value]
    return value


class _FirestoreTransaction:
    def __init__(self, client, transaction):
        self.client, self.transaction = client, transaction

    def _ref(self, collection, doc_id):
        return self.client.collection(_name(collection)).document(_name(doc_id))

    def get(self, collection: str, doc_id: str) -> dict | None:
        snapshot = self._ref(collection, doc_id).get(transaction=self.transaction)
        return snapshot.to_dict() if snapshot.exists else None

    def set(self, collection: str, doc_id: str, data: dict, merge: bool = False) -> None:
        self.transaction.set(self._ref(collection, doc_id), _firestore_values(data), merge=merge)


class FirestoreStore(_Store):
    """Native Firestore documents; clients are created only when this store is selected."""

    def __init__(self, project: str, database: str = "(default)", *, client=None):
        from google.cloud import firestore

        self.client = (
            client if client is not None else firestore.Client(project=project, database=database)
        )

    def atomic(self, callback: Callable[[Any], T]) -> T:
        """Firestore may retry this callback. Read first; keep external side effects outside."""
        from google.cloud import firestore

        @firestore.transactional
        def execute(transaction):
            return callback(_FirestoreTransaction(self.client, transaction))

        return execute(self.client.transaction())

    def read(self, collection: str, doc_id: str) -> dict | None:
        snapshot = self.client.collection(_name(collection)).document(_name(doc_id)).get()
        return snapshot.to_dict() if snapshot.exists else None

    def query(self, collection: str, filters=(), order_by=None, limit=None) -> dict:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self.client.collection(_name(collection))
        for field, operator, expected in filters:
            query = query.where(filter=FieldFilter(field, operator, expected))
        if order_by:
            query = query.order_by(
                order_by.lstrip("-"),
                direction="DESCENDING" if order_by.startswith("-") else "ASCENDING",
            )
        if limit is not None:
            if limit < 1:
                raise ValueError("Query limit must be positive")
            query = query.limit(limit)
        return {doc.id: doc.to_dict() for doc in query.stream()}


@lru_cache(maxsize=1)
def get_store():
    load_environment()
    backend = os.environ.get("CLAIMS_STORE", "local").lower()
    if backend == "local":
        return LocalStore(local_data_dir())
    if backend == "firestore":
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise ValueError("GOOGLE_CLOUD_PROJECT is required for CLAIMS_STORE=firestore")
        return FirestoreStore(project, os.environ.get("CLAIMS_FIRESTORE_DATABASE", "(default)"))
    raise ValueError(
        "CLAIMS_STORE must be 'local' or 'firestore'; use claims-data import-gcs for legacy JSON"
    )
