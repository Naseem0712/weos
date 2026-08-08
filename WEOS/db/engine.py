"""Cloud-first database engine for WEOS (Part 9).

Source of truth is a real database:

* **Production (Railway):** PostgreSQL via the ``DATABASE_URL`` env var.
* **Local dev / dead shell:** the *same* SQLAlchemy layer degrades to a
  clearly-labelled sqlite file under ``data_dir()``. This is a dev fallback
  only — the browser is never the source of truth.

The module is import-safe even when SQLAlchemy (or a DB driver) is missing:
importing WEOS must never crash. In that case ``db_available()`` is False and
the health endpoint reports the reason, while the legacy JSON project store
keeps working.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

_log = logging.getLogger("weos.db")

# ── Optional SQLAlchemy import (never crash WEOS import) ─────────────────────
try:  # pragma: no cover - exercised at runtime
    import sqlalchemy as _sa
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    _SA_IMPORT_ERROR: str | None = None
except Exception as exc:  # pragma: no cover - only when dependency missing
    _sa = None  # type: ignore[assignment]
    create_engine = None  # type: ignore[assignment]
    Session = object  # type: ignore[assignment,misc]
    sessionmaker = None  # type: ignore[assignment]
    _SA_IMPORT_ERROR = f"SQLAlchemy unavailable: {exc}"

_lock = threading.RLock()
_engine: Any = None
_SessionFactory: Any = None
_initialised = False
_last_error: str | None = _SA_IMPORT_ERROR
_resolved_url: str | None = None
_backend: str = "unavailable"
# Which env var (if any) supplied the DATABASE_URL at engine-build time.
_url_source: str | None = None

# Env vars checked, in priority order, for a Postgres connection string.
_DB_URL_KEYS = ("DATABASE_URL", "WEOS_DATABASE_URL", "POSTGRES_URL")


def _database_url_source() -> tuple[str, str | None]:
    """Return ``(raw_url, env_key)`` from the current process environment.

    Read live from ``os.environ`` — on Railway the value is only injected at
    process start, so this reflects exactly what the running process can see.
    """
    for key in _DB_URL_KEYS:
        val = (os.environ.get(key) or "").strip()
        if val:
            return val, key
    return "", None


def _require_postgres() -> bool:
    """When truthy, refuse the sqlite dev fallback (fail loudly instead)."""
    return (os.environ.get("WEOS_REQUIRE_POSTGRES") or "").strip().lower() in ("1", "true", "yes", "on")


def on_railway() -> bool:
    return bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("RAILWAY_PROJECT_ID")
        or os.environ.get("RAILWAY_SERVICE_ID")
    )


def _normalise_url(raw: str) -> str:
    """Railway / Heroku hand out ``postgres://`` which SQLAlchemy rejects.

    Normalise to the psycopg2 dialect. Handles both ``postgres://`` and
    ``postgresql://`` (incl. Railway's private ``*.railway.internal`` host).
    TLS is left to libpq / ``PGSSLMODE`` (Railway's private network does not
    require sslmode); we no longer silently rewrite it here.
    """
    url = raw.strip()
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://") :]
    elif url.startswith("postgresql://") and "+psycopg" not in url:
        url = "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


def resolve_database_url() -> tuple[str, str]:
    """Return ``(url, backend)``.

    Rule: **if DATABASE_URL (or an alias) is present and non-empty, ALWAYS use
    Postgres.** sqlite is only ever chosen when no URL is configured. If the
    Postgres connection later fails, that surfaces as a real error in the health
    check — we never silently swap a failed Postgres for sqlite.
    """
    global _url_source
    raw, source = _database_url_source()
    _url_source = source
    if raw:
        url = _normalise_url(raw)
        return url, ("postgresql" if url.startswith("postgresql") else "external")

    # No connection string configured.
    if _require_postgres():
        raise RuntimeError(
            "DATABASE_URL is not set in this process but WEOS_REQUIRE_POSTGRES is on. "
            "Set DATABASE_URL on the web service (e.g. ${{Postgres.DATABASE_URL}}) and redeploy. "
            "Refusing the sqlite dev fallback in production."
        )

    # Dev fallback — sqlite file through the SAME abstraction (clearly labelled).
    from WEOS.paths import data_dir

    db_path = data_dir() / "weos.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}", "sqlite"


def sqlalchemy_available() -> bool:
    return _sa is not None


def get_engine() -> Any:
    """Lazily build (and cache) the SQLAlchemy engine.

    Raises RuntimeError if SQLAlchemy isn't installed so callers can degrade.
    """
    global _engine, _SessionFactory, _resolved_url, _backend, _last_error
    if _sa is None:
        raise RuntimeError(_SA_IMPORT_ERROR or "SQLAlchemy not installed")
    with _lock:
        if _engine is not None:
            return _engine
        url, backend = resolve_database_url()
        connect_args: dict[str, Any] = {}
        engine_kwargs: dict[str, Any] = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        else:
            # Recycle connections so Railway's idle Postgres timeouts don't bite.
            engine_kwargs["pool_recycle"] = 1800
        try:
            _engine = create_engine(url, connect_args=connect_args, **engine_kwargs)
            _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, class_=Session)
            _resolved_url = url
            _backend = backend
            _last_error = None
        except Exception as exc:  # pragma: no cover
            _last_error = f"engine create failed: {exc}"
            _log.exception("WEOS DB engine creation failed")
            raise
        return _engine


def get_session() -> Any:
    """Return a new Session. Caller is responsible for closing it.

    Prefer :func:`session_scope` for automatic commit/rollback/close.
    """
    get_engine()
    return _SessionFactory()


class session_scope:  # noqa: N801 - used as a context manager
    """``with session_scope() as s:`` — commit on success, rollback on error."""

    def __enter__(self) -> Any:
        self.session = get_session()
        return self.session

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()


def init_db() -> dict[str, Any]:
    """Create all tables (idempotent). Safe to call on every startup."""
    global _initialised, _last_error
    if _sa is None:
        return {"ok": False, "error": _SA_IMPORT_ERROR, "backend": "unavailable"}
    try:
        from WEOS.db.models import Base

        engine = get_engine()
        Base.metadata.create_all(engine)
        _initialised = True
        _last_error = None
        return {"ok": True, "backend": _backend, "url": _safe_url(), "initialised": True}
    except Exception as exc:
        _last_error = str(exc)
        _log.exception("WEOS init_db failed")
        return {"ok": False, "error": str(exc), "backend": _backend}


def _safe_url() -> str | None:
    """URL with credentials stripped, for diagnostics."""
    if not _resolved_url:
        return None
    url = _resolved_url
    if "@" in url and "//" in url:
        head, tail = url.split("//", 1)
        if "@" in tail:
            tail = tail.split("@", 1)[1]
        return f"{head}//***@{tail}"
    return url


def db_available() -> bool:
    """True when a live connection can be opened right now."""
    if _sa is None:
        return False
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(_sa.text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover
        global _last_error
        _last_error = str(exc)
        return False


def health() -> dict[str, Any]:
    """Diagnostic snapshot for the admin health endpoint (Part 10).

    Explains *why* a backend was chosen so a silent sqlite fallback on Railway is
    obvious: reports whether the process actually sees DATABASE_URL, which env key
    supplied it, and flags a misconfiguration when Postgres was expected.
    """
    if _sa is None:
        return {
            "status": "ERROR",
            "backend": "unavailable",
            "error": _SA_IMPORT_ERROR,
            "detail": "Install SQLAlchemy + psycopg2-binary and set DATABASE_URL.",
        }

    raw, source = _database_url_source()
    url_present = bool(raw)
    railway = on_railway()

    # Try to open the engine so we can surface a genuine Postgres connection error
    # (missing driver, bad host, auth) instead of hiding it.
    connected = db_available()

    info: dict[str, Any] = {
        "status": "CONNECTED" if connected else "ERROR",
        "backend": _backend,
        "url": _safe_url(),
        "initialised": _initialised,
        "error": None if connected else _last_error,
        "isProduction": _backend == "postgresql",
        "devFallback": _backend == "sqlite",
        # Diagnostics for the sqlite-vs-postgres decision:
        "databaseUrlPresent": url_present,
        "databaseUrlSource": source,
        "onRailway": railway,
        "requirePostgres": _require_postgres(),
    }

    # Misconfiguration: we fell back to sqlite even though we clearly should be
    # on Postgres (running on Railway, or an operator forced strict mode).
    if _backend == "sqlite" and (railway or _require_postgres()) and not url_present:
        info["status"] = "MISCONFIGURED"
        info["misconfigured"] = True
        info["reason"] = (
            "DATABASE_URL is NOT present in this running process, so WEOS used the "
            "sqlite dev fallback. On Railway, variables are injected at container "
            "start — set DATABASE_URL=${{Postgres.DATABASE_URL}} on THIS (web) "
            "service, remove any stray/empty DATABASE_URL, then trigger a fresh "
            "redeploy so the new process sees it. Re-check /api/admin/health for "
            'backend: "postgresql".'
        )
    return info
