"""Durable Product Library store — mirrors the Product Library JSON files into
PostgreSQL so imported/edited products survive Railway redeploys.

Pattern (mirrors the quote store):
* The database is the SOURCE OF TRUTH for the Product Library.
* The container filesystem (``products_dir()``) is a fast local cache.
* On boot the app calls :func:`bootstrap` which rehydrates the filesystem from
  the DB (or, on first run with an empty table, seeds the DB from the files that
  ship with the image).
* Every create / update / delete / Excel-import writes through to the DB.

Everything degrades gracefully when the DB is unavailable (local dev without
``DATABASE_URL``): the functions become no-ops and the existing file-based code
continues to work unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable

from WEOS.db.engine import db_available, init_db, session_scope
from WEOS.paths import products_dir

_log = logging.getLogger("weos.product_store")


def db_ready() -> bool:
    """True when a live DB connection is available."""
    try:
        return bool(db_available())
    except Exception:
        return False


def _root() -> Path:
    return products_dir()


def _rel(path: Path) -> str:
    """Path relative to products_dir(), using forward slashes for portability."""
    return path.resolve().relative_to(_root().resolve()).as_posix()


def _product_id_for(rel_path: str) -> str | None:
    parts = rel_path.split("/")
    if not parts:
        return None
    if parts[0] == "sections":
        return None
    return parts[0]


def _kind_for(rel_path: str) -> str:
    return "sections" if rel_path.split("/")[0] == "sections" else "product"


# ── write-through ─────────────────────────────────────────────────────────────

def snapshot_file(abs_path: str | Path) -> bool:
    """Mirror a single JSON file into the DB (upsert by rel path)."""
    if not db_ready():
        return False
    p = Path(abs_path)
    if not p.is_file():
        return False
    try:
        rel = _rel(p)
    except ValueError:
        return False  # outside products_dir — ignore
    try:
        text = p.read_text(encoding="utf-8-sig")
    except Exception:
        return False
    init_db()
    from sqlalchemy import select

    from WEOS.db.models import LibraryFile

    try:
        with session_scope() as s:
            row = s.execute(select(LibraryFile).where(LibraryFile.rel_path == rel)).scalar_one_or_none()
            if row is None:
                row = LibraryFile(rel_path=rel)
                s.add(row)
            row.product_id = _product_id_for(rel)
            row.kind = _kind_for(rel)
            row.content = text
        return True
    except Exception:
        _log.exception("snapshot_file failed for %s", rel)
        return False


def _iter_json(base: Path) -> Iterable[Path]:
    if base.is_dir():
        yield from base.rglob("*.json")


def snapshot_product(product_id: str) -> int:
    """Mirror every JSON file for one product folder. Returns files written."""
    if not db_ready():
        return 0
    n = 0
    for jf in _iter_json(_root() / product_id):
        if snapshot_file(jf):
            n += 1
    return n


def snapshot_dir(subdir: str) -> int:
    """Mirror every JSON file under products_dir()/subdir (e.g. 'sections')."""
    if not db_ready():
        return 0
    n = 0
    for jf in _iter_json(_root() / subdir):
        if snapshot_file(jf):
            n += 1
    return n


def snapshot_all() -> int:
    """Mirror the entire Product Library (all product folders + sections)."""
    if not db_ready():
        return 0
    n = 0
    for jf in _iter_json(_root()):
        if snapshot_file(jf):
            n += 1
    _log.info("Product Library snapshot → DB: %d files", n)
    return n


def delete_product(product_id: str) -> int:
    """Remove all DB rows for a product folder (hard delete mirror)."""
    if not db_ready():
        return 0
    init_db()
    from sqlalchemy import delete, or_

    from WEOS.db.models import LibraryFile

    prefix = f"{product_id}/"
    try:
        with session_scope() as s:
            res = s.execute(
                delete(LibraryFile).where(
                    or_(LibraryFile.product_id == product_id, LibraryFile.rel_path.like(prefix + "%"))
                )
            )
            return int(res.rowcount or 0)
    except Exception:
        _log.exception("delete_product mirror failed for %s", product_id)
        return 0


# ── rehydrate ───────────────────────────────────────────────────────────────

def count() -> int:
    if not db_ready():
        return 0
    init_db()
    from sqlalchemy import func, select

    from WEOS.db.models import LibraryFile

    try:
        with session_scope() as s:
            return int(s.execute(select(func.count()).select_from(LibraryFile)).scalar_one())
    except Exception:
        return 0


def restore_all(*, overwrite: bool = True) -> int:
    """Write every mirrored file back to the filesystem. Returns files written."""
    if not db_ready():
        return 0
    init_db()
    from sqlalchemy import select

    from WEOS.db.models import LibraryFile

    written = 0
    try:
        with session_scope() as s:
            rows = s.execute(select(LibraryFile)).scalars().all()
            root = _root()
            for row in rows:
                dest = root / row.rel_path
                if dest.exists() and not overwrite:
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(row.content, encoding="utf-8")
                written += 1
    except Exception:
        _log.exception("restore_all failed")
    if written:
        _log.info("Product Library rehydrated from DB: %d files", written)
    return written


def bootstrap() -> dict[str, int | str | bool]:
    """Boot-time sync: DB→filesystem when the DB has data, else seed DB from files.

    Returns a small diagnostic dict. Never raises (best-effort)."""
    if not db_ready():
        return {"ok": False, "reason": "db_unavailable"}
    try:
        existing = count()
        if existing > 0:
            restored = restore_all(overwrite=True)
            return {"ok": True, "mode": "restore", "files": restored, "rows": existing}
        seeded = snapshot_all()
        return {"ok": True, "mode": "seed", "files": seeded}
    except Exception as exc:  # pragma: no cover - defensive
        _log.exception("product_store.bootstrap failed")
        return {"ok": False, "error": str(exc)}
