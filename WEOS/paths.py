"""Portable filesystem roots for local + Railway.

All writable runtime paths resolve via pathlib relative to the package or
``WEOS_DATA_DIR``. No Windows drive letters or absolute OS roots are assumed.
"""

from __future__ import annotations

import os
from pathlib import Path

# WEOS package directory (contains products/, website/, stock/, …)
PACKAGE_ROOT = Path(__file__).resolve().parent
# Repo / workspace root (parent of WEOS/)
WORKSPACE_ROOT = PACKAGE_ROOT.parent


def _env_path(name: str, default: Path) -> Path:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    return Path(raw).expanduser().resolve()


def data_dir() -> Path:
    """Writable data root. Defaults to the WEOS package (local parity)."""
    return _env_path("WEOS_DATA_DIR", PACKAGE_ROOT)


def projects_dir() -> Path:
    override = (os.environ.get("WEOS_PROJECTS_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return data_dir() / "projects"


def output_dir() -> Path:
    override = (os.environ.get("WEOS_OUTPUT_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return data_dir() / "output"


def stock_dir() -> Path:
    """Stock inventory (ships with package; overridable)."""
    return _env_path("WEOS_STOCK_DIR", PACKAGE_ROOT / "stock")


def knowledge_base_dir() -> Path:
    return _env_path("WEOS_KB_DIR", WORKSPACE_ROOT / "knowledge_base")


def website_dir() -> Path:
    return PACKAGE_ROOT / "website"


def products_dir() -> Path:
    return PACKAGE_ROOT / "products"


def host_from_env(default: str = "127.0.0.1") -> str:
    return (os.environ.get("WEOS_HOST") or os.environ.get("HOST") or default).strip() or default


def port_from_env(default: int = 8000) -> int:
    raw = (os.environ.get("PORT") or os.environ.get("WEOS_PORT") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default
