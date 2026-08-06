"""In-process + file cache for Engineering Brain loads.

TTL-based; invalidated on KB version change / rollback.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from WEOS.memory.store import memories_root

_lock = threading.RLock()
_mem: dict[str, tuple[float, Any]] = {}  # key → (expires_at, value)
DEFAULT_TTL_SEC = 120.0


def _cache_dir() -> Path:
    d = memories_root() / "_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_key(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)


def get(key: str) -> Any | None:
    with _lock:
        hit = _mem.get(key)
        if not hit:
            # file fallback
            path = _cache_dir() / f"{_safe(key)}.json"
            if not path.is_file():
                return None
            try:
                blob = json.loads(path.read_text(encoding="utf-8"))
                if float(blob.get("expires_at") or 0) < time.time():
                    path.unlink(missing_ok=True)
                    return None
                val = blob.get("value")
                _mem[key] = (float(blob["expires_at"]), val)
                return val
            except Exception:
                return None
        expires, val = hit
        if expires < time.time():
            _mem.pop(key, None)
            return None
        return val


def set(key: str, value: Any, *, ttl: float = DEFAULT_TTL_SEC, persist: bool = True) -> None:
    expires = time.time() + max(1.0, ttl)
    with _lock:
        _mem[key] = (expires, value)
        if persist:
            path = _cache_dir() / f"{_safe(key)}.json"
            path.write_text(
                json.dumps({"expires_at": expires, "value": value}, ensure_ascii=False),
                encoding="utf-8",
            )


def invalidate(prefix: str | None = None) -> int:
    """Clear in-process + file cache. If prefix given, only matching keys."""
    n = 0
    with _lock:
        if prefix is None:
            n = len(_mem)
            _mem.clear()
            for p in _cache_dir().glob("*.json"):
                p.unlink(missing_ok=True)
                n += 1
            return n
        keys = [k for k in _mem if k.startswith(prefix)]
        for k in keys:
            _mem.pop(k, None)
            n += 1
        for p in _cache_dir().glob("*.json"):
            if prefix.replace("|", "_") in p.stem or _safe(prefix) in p.stem:
                p.unlink(missing_ok=True)
                n += 1
    return n


def invalidate_kb() -> int:
    """Call after approve / rollback / version publish."""
    return invalidate(None)


def _safe(key: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:180]
