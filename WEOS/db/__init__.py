"""WEOS cloud-first database layer (PostgreSQL in production, sqlite dev fallback).

This package is the persistent source of truth for customers, quotes, quote
versions, calculations, BOM, agent events and suggestions. The browser never
owns this data.
"""

from WEOS.db.engine import (
    db_available,
    get_engine,
    get_session,
    health,
    init_db,
    resolve_database_url,
    session_scope,
    sqlalchemy_available,
)

__all__ = [
    "db_available",
    "get_engine",
    "get_session",
    "health",
    "init_db",
    "resolve_database_url",
    "session_scope",
    "sqlalchemy_available",
]
