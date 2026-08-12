"""Durable JSON/blob mirror — survives Railway redeploys.

Company setup, customer profiles, and project documents historically lived under
``data_dir()`` / ``projects_dir()``. Those paths are ephemeral on Railway, so
saves looked successful until the next refresh/redeploy wiped the container.

This module is the write-through / rehydrate layer (same idea as
``product_store``): DB is source of truth when available; filesystem is a cache.
"""

from __future__ import annotations

import logging
from typing import Any

from WEOS.db.engine import db_available, init_db, session_scope

_log = logging.getLogger("weos.durable_store")


def db_ready() -> bool:
    try:
        return bool(db_available())
    except Exception:
        return False


def put_json(key: str, kind: str, payload: dict[str, Any] | list[Any] | None) -> bool:
    """Upsert a JSON payload under ``key``. Returns False if DB unavailable."""
    if not db_ready() or not (key or "").strip():
        return False
    init_db()
    from sqlalchemy import select

    from WEOS.db.models import DurableRecord

    try:
        with session_scope() as s:
            row = s.execute(
                select(DurableRecord).where(DurableRecord.key == key)
            ).scalar_one_or_none()
            if row is None:
                row = DurableRecord(key=key)
                s.add(row)
            row.kind = kind or "json"
            row.payload = payload
        return True
    except Exception:
        _log.exception("durable put_json failed for %s", key)
        return False


def get_json(key: str) -> dict[str, Any] | list[Any] | None:
    if not db_ready() or not (key or "").strip():
        return None
    init_db()
    from sqlalchemy import select

    from WEOS.db.models import DurableRecord

    try:
        with session_scope() as s:
            row = s.execute(
                select(DurableRecord).where(DurableRecord.key == key)
            ).scalar_one_or_none()
            if row is None:
                return None
            return row.payload
    except Exception:
        _log.exception("durable get_json failed for %s", key)
        return None


def put_blob(
    key: str,
    *,
    kind: str = "blob",
    raw: bytes,
    content_type: str | None = None,
    filename: str | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    if not db_ready() or not (key or "").strip():
        return False
    init_db()
    from sqlalchemy import select

    from WEOS.db.models import DurableRecord

    try:
        with session_scope() as s:
            row = s.execute(
                select(DurableRecord).where(DurableRecord.key == key)
            ).scalar_one_or_none()
            if row is None:
                row = DurableRecord(key=key)
                s.add(row)
            row.kind = kind or "blob"
            row.blob = raw
            row.blob_content_type = content_type
            row.blob_filename = filename
            if payload is not None:
                row.payload = payload
        return True
    except Exception:
        _log.exception("durable put_blob failed for %s", key)
        return False


def get_blob(key: str) -> tuple[bytes | None, str | None, str | None]:
    """Return ``(bytes, content_type, filename)`` or ``(None, None, None)``."""
    if not db_ready() or not (key or "").strip():
        return None, None, None
    init_db()
    from sqlalchemy import select

    from WEOS.db.models import DurableRecord

    try:
        with session_scope() as s:
            row = s.execute(
                select(DurableRecord).where(DurableRecord.key == key)
            ).scalar_one_or_none()
            if row is None or row.blob is None:
                return None, None, None
            return bytes(row.blob), row.blob_content_type, row.blob_filename
    except Exception:
        _log.exception("durable get_blob failed for %s", key)
        return None, None, None


def delete_key(key: str) -> bool:
    if not db_ready() or not (key or "").strip():
        return False
    init_db()
    from sqlalchemy import delete

    from WEOS.db.models import DurableRecord

    try:
        with session_scope() as s:
            s.execute(delete(DurableRecord).where(DurableRecord.key == key))
        return True
    except Exception:
        _log.exception("durable delete failed for %s", key)
        return False


def list_keys(kind: str | None = None, *, prefix: str | None = None) -> list[str]:
    if not db_ready():
        return []
    init_db()
    from sqlalchemy import select

    from WEOS.db.models import DurableRecord

    try:
        with session_scope() as s:
            q = select(DurableRecord.key)
            if kind:
                q = q.where(DurableRecord.kind == kind)
            if prefix:
                q = q.where(DurableRecord.key.like(prefix + "%"))
            return [str(r[0]) for r in s.execute(q).all()]
    except Exception:
        _log.exception("durable list_keys failed")
        return []


def list_payloads(kind: str | None = None, *, prefix: str | None = None) -> list[dict[str, Any]]:
    """Return ``[{key, kind, payload, updatedAt}, ...]``."""
    if not db_ready():
        return []
    init_db()
    from sqlalchemy import select

    from WEOS.db.models import DurableRecord

    try:
        with session_scope() as s:
            q = select(DurableRecord)
            if kind:
                q = q.where(DurableRecord.kind == kind)
            if prefix:
                q = q.where(DurableRecord.key.like(prefix + "%"))
            rows = s.execute(q).scalars().all()
            return [
                {
                    "key": r.key,
                    "kind": r.kind,
                    "payload": r.payload,
                    "updatedAt": r.to_dict().get("updatedAt"),
                }
                for r in rows
            ]
    except Exception:
        _log.exception("durable list_payloads failed")
        return []
