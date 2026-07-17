"""
memory/memory_provider.py
=========================
Storage abstraction. The Memory Manager depends on the MemoryProvider INTERFACE,
never a concrete store, so backends are interchangeable and the Brain Manager
(which talks only to the Memory Manager) is fully insulated from storage.

Providers:
    * InMemoryProvider - thread-safe dict; default, and used in tests.
    * JSONProvider     - file-backed via a single JSON document (lazy, atomic
                         writes); good for a laptop deployment.
    * SQLiteProvider   - file/`:memory:` sqlite3 backend (lazy import); scales
                         better and supports indexed queries.
    * VectorProvider   - stub for a future vector DB (semantic search); raises a
                         clear NotImplementedError until wired.

All providers store/return MemoryRecord objects and are safe for concurrent use.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Protocol, runtime_checkable

from core.logger import get_logger

from .memory_exceptions import ProviderError
from .memory_record import Importance, MemoryRecord, MemoryType

log = get_logger("memory.provider")


@runtime_checkable
class MemoryProvider(Protocol):
    """Common interface every storage backend implements."""
    name: str
    def put(self, record: MemoryRecord) -> None: ...
    def get(self, memory_id: str) -> MemoryRecord | None: ...
    def delete(self, memory_id: str) -> bool: ...
    def all(self) -> list[MemoryRecord]: ...
    def clear(self) -> None: ...


class InMemoryProvider:
    """Thread-safe in-memory store (dict keyed by memory_id)."""

    name = "in_memory"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, MemoryRecord] = {}

    def put(self, record: MemoryRecord) -> None:
        with self._lock:
            self._data[record.memory_id] = record

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self._lock:
            return self._data.get(memory_id)

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            return self._data.pop(memory_id, None) is not None

    def all(self) -> list[MemoryRecord]:
        with self._lock:
            return list(self._data.values())

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


class JSONProvider:
    """File-backed provider using a single JSON document. Writes are atomic
    (temp file + os.replace). Thread-safe. Suitable for modest laptop use."""

    name = "json"

    def __init__(self, path: str, autosave: bool = True) -> None:
        self._path = path
        self._autosave = autosave
        self._lock = threading.RLock()
        self._data: dict[str, MemoryRecord] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            with self._lock:
                self._data = {rid: MemoryRecord.from_dict(rec)
                              for rid, rec in raw.items()}
        except Exception as exc:                        # noqa: BLE001
            raise ProviderError(f"failed to load JSON store: {exc}") from exc

    def _save(self) -> None:
        try:
            with self._lock:
                raw = {rid: rec.to_dict() for rid, rec in self._data.items()}
            directory = os.path.dirname(os.path.abspath(self._path)) or "."
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(raw, fh)
            os.replace(tmp, self._path)                 # atomic
        except Exception as exc:                        # noqa: BLE001
            raise ProviderError(f"failed to save JSON store: {exc}") from exc

    def put(self, record: MemoryRecord) -> None:
        with self._lock:
            self._data[record.memory_id] = record
        if self._autosave:
            self._save()

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self._lock:
            return self._data.get(memory_id)

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            existed = self._data.pop(memory_id, None) is not None
        if existed and self._autosave:
            self._save()
        return existed

    def all(self) -> list[MemoryRecord]:
        with self._lock:
            return list(self._data.values())

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
        if self._autosave:
            self._save()

    def flush(self) -> None:
        """Force a save (useful when autosave is disabled)."""
        self._save()


class SQLiteProvider:
    """sqlite3-backed provider (lazy import). Uses one row per memory with the
    JSON payload plus indexed columns for type/importance/expiry so queries can
    be pushed down later. Thread-safe (per-connection lock; check_same_thread
    disabled with a guarding lock)."""

    name = "sqlite"

    def __init__(self, path: str = ":memory:") -> None:
        try:
            import sqlite3
        except Exception as exc:                        # noqa: BLE001
            raise ProviderError(f"sqlite3 unavailable: {exc}") from exc
        self._sqlite3 = sqlite3
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS memories ("
                " memory_id TEXT PRIMARY KEY,"
                " memory_type TEXT NOT NULL,"
                " importance TEXT NOT NULL,"
                " expires_at REAL,"
                " payload TEXT NOT NULL)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_type ON memories(memory_type)")
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_expires ON memories(expires_at)")
            self._conn.commit()

    def put(self, record: MemoryRecord) -> None:
        payload = json.dumps(record.to_dict())
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO memories"
                " (memory_id, memory_type, importance, expires_at, payload)"
                " VALUES (?,?,?,?,?)",
                (record.memory_id, record.memory_type.value,
                 record.importance.name, record.expires_at, payload))
            self._conn.commit()

    def get(self, memory_id: str) -> MemoryRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM memories WHERE memory_id=?",
                (memory_id,)).fetchone()
        return MemoryRecord.from_dict(json.loads(row[0])) if row else None

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM memories WHERE memory_id=?", (memory_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def all(self) -> list[MemoryRecord]:
        with self._lock:
            rows = self._conn.execute("SELECT payload FROM memories").fetchall()
        return [MemoryRecord.from_dict(json.loads(r[0])) for r in rows]

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM memories")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class VectorProvider:
    """Placeholder for a future vector-database backend enabling semantic search.
    It satisfies the interface but raises until a real vector store is wired, so
    the rest of the system can target it without existing yet."""

    name = "vector"

    def __init__(self, backend: object | None = None) -> None:
        self._backend = backend

    def _unavailable(self) -> ProviderError:
        return ProviderError(
            "VectorProvider is a future backend and is not yet implemented; "
            "inject a concrete vector store to enable semantic memory")

    def put(self, record: MemoryRecord) -> None:
        raise self._unavailable()

    def get(self, memory_id: str) -> MemoryRecord | None:
        raise self._unavailable()

    def delete(self, memory_id: str) -> bool:
        raise self._unavailable()

    def all(self) -> list[MemoryRecord]:
        raise self._unavailable()

    def clear(self) -> None:
        raise self._unavailable()
