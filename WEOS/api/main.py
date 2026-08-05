"""Uvicorn entry module — ``uvicorn WEOS.api.main:app``."""

from __future__ import annotations

from WEOS.api.server import app

__all__ = ["app"]
