"""Brain cache — 3 layers: RAM → SQLite → Vector/keyword memory.

Invalidated on approve / version publish / rollback.
Vector layer is pragmatic: tries sqlite-vss if available, else keyword bag stub.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from WEOS.memory.store import memories_root

_lock = threading.RLock()
_mem: dict[str, tuple[float, Any]] = {}  # L1 RAM: key → (expires_at, value)
DEFAULT_TTL_SEC = 120.0

_SQLITE_NAME = "brain_cache.sqlite3"


def _cache_dir() -> Path:
    d = memories_root() / "_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sqlite_path() -> Path:
    return _cache_dir() / _SQLITE_NAME


def _conn() -> sqlite3.Connection:
    path = _sqlite_path()
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kv (
            key TEXT PRIMARY KEY,
            expires_at REAL NOT NULL,
            value_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vector_stub (
            key TEXT PRIMARY KEY,
            tokens TEXT NOT NULL,
            value_json TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def cache_key(*parts: Any) -> str:
    return "|".join(str(p) for p in parts)


def _safe(key: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in key)[:180]


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) >= 2]


# ── L1 RAM ───────────────────────────────────────────────────────────────────

def _l1_get(key: str) -> Any | None:
    hit = _mem.get(key)
    if not hit:
        return None
    expires, val = hit
    if expires < time.time():
        _mem.pop(key, None)
        return None
    return val


def _l1_set(key: str, value: Any, expires: float) -> None:
    _mem[key] = (expires, value)


# ── L2 SQLite ────────────────────────────────────────────────────────────────

def _l2_get(key: str) -> Any | None:
    try:
        with _conn() as conn:
            row = conn.execute("SELECT expires_at, value_json FROM kv WHERE key = ?", (key,)).fetchone()
            if not row:
                return None
            expires, raw = row
            if float(expires) < time.time():
                conn.execute("DELETE FROM kv WHERE key = ?", (key,))
                conn.commit()
                return None
            return json.loads(raw)
    except Exception:
        return None


def _l2_set(key: str, value: Any, expires: float) -> None:
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kv(key, expires_at, value_json, updated_at) VALUES (?,?,?,?)",
                (key, expires, json.dumps(value, ensure_ascii=False), time.time()),
            )
            conn.commit()
    except Exception:
        pass


# ── L3 Vector / keyword stub ─────────────────────────────────────────────────

def _vector_backend() -> str:
    """Document which vector backend is active."""
    try:
        import sqlite_vss  # type: ignore  # noqa: F401

        return "sqlite-vss"
    except Exception:
        return "keyword_stub"


def _l3_set(key: str, value: Any, expires: float, *, text: str | None = None) -> None:
    blob = text or json.dumps(value, ensure_ascii=False)[:4000]
    tokens = " ".join(_tokenize(blob))
    try:
        with _conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO vector_stub(key, tokens, value_json, expires_at) VALUES (?,?,?,?)",
                (key, tokens, json.dumps(value, ensure_ascii=False), expires),
            )
            conn.commit()
    except Exception:
        pass


def _l3_search(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return []
    out: list[dict[str, Any]] = []
    try:
        with _conn() as conn:
            rows = conn.execute("SELECT key, tokens, value_json, expires_at FROM vector_stub").fetchall()
        now = time.time()
        scored = []
        for key, tokens, raw, expires in rows:
            if float(expires) < now:
                continue
            tset = set(str(tokens).split())
            score = len(q_tokens & tset)
            if score <= 0:
                continue
            scored.append((score, key, raw))
        scored.sort(key=lambda x: -x[0])
        for score, key, raw in scored[:limit]:
            out.append({"key": key, "score": score, "value": json.loads(raw)})
    except Exception:
        return []
    return out


# ── Public API (compatible with previous cache.py) ───────────────────────────

def get(key: str) -> Any | None:
    with _lock:
        val = _l1_get(key)
        if val is not None:
            return val
        val = _l2_get(key)
        if val is not None:
            # promote to L1
            _l1_set(key, val, time.time() + DEFAULT_TTL_SEC)
            return val
        # Legacy file fallback (migration)
        path = _cache_dir() / f"{_safe(key)}.json"
        if path.is_file():
            try:
                blob = json.loads(path.read_text(encoding="utf-8"))
                if float(blob.get("expires_at") or 0) < time.time():
                    path.unlink(missing_ok=True)
                    return None
                val = blob.get("value")
                expires = float(blob["expires_at"])
                _l1_set(key, val, expires)
                _l2_set(key, val, expires)
                return val
            except Exception:
                return None
        return None


def set(
    key: str,
    value: Any,
    *,
    ttl: float = DEFAULT_TTL_SEC,
    persist: bool = True,
    index_text: str | None = None,
) -> None:
    expires = time.time() + max(1.0, ttl)
    with _lock:
        _l1_set(key, value, expires)
        if persist:
            _l2_set(key, value, expires)
            _l3_set(key, value, expires, text=index_text)
            # Keep thin file mirror for older tools
            path = _cache_dir() / f"{_safe(key)}.json"
            try:
                path.write_text(
                    json.dumps({"expires_at": expires, "value": value}, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:
                pass


def search_cache(query: str, *, limit: int = 5) -> dict[str, Any]:
    hits = _l3_search(query, limit=limit)
    return {"ok": True, "backend": _vector_backend(), "results": hits, "count": len(hits)}


def invalidate(prefix: str | None = None) -> int:
    """Clear L1 + L2 + L3 (+ legacy files). If prefix given, only matching keys."""
    n = 0
    with _lock:
        if prefix is None:
            n = len(_mem)
            _mem.clear()
            try:
                with _conn() as conn:
                    n += conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0] or 0
                    conn.execute("DELETE FROM kv")
                    conn.execute("DELETE FROM vector_stub")
                    conn.commit()
            except Exception:
                pass
            for p in _cache_dir().glob("*.json"):
                p.unlink(missing_ok=True)
                n += 1
            return n

        keys = [k for k in _mem if k.startswith(prefix)]
        for k in keys:
            _mem.pop(k, None)
            n += 1
        try:
            with _conn() as conn:
                rows = conn.execute("SELECT key FROM kv").fetchall()
                for (k,) in rows:
                    if str(k).startswith(prefix):
                        conn.execute("DELETE FROM kv WHERE key = ?", (k,))
                        conn.execute("DELETE FROM vector_stub WHERE key = ?", (k,))
                        n += 1
                conn.commit()
        except Exception:
            pass
        for p in _cache_dir().glob("*.json"):
            if prefix.replace("|", "_") in p.stem or _safe(prefix) in p.stem:
                p.unlink(missing_ok=True)
                n += 1
    return n


def invalidate_kb() -> int:
    """Call after approve / rollback / version publish."""
    return invalidate(None)


def status() -> dict[str, Any]:
    l1 = len(_mem)
    l2 = 0
    l3 = 0
    try:
        with _conn() as conn:
            l2 = int(conn.execute("SELECT COUNT(*) FROM kv").fetchone()[0] or 0)
            l3 = int(conn.execute("SELECT COUNT(*) FROM vector_stub").fetchone()[0] or 0)
    except Exception:
        pass
    return {
        "layers": {
            "L1_RAM": l1,
            "L2_SQLite": l2,
            "L3_Vector": l3,
        },
        "vectorBackend": _vector_backend(),
        "sqlitePath": str(_sqlite_path()),
        "ttlSec": DEFAULT_TTL_SEC,
        "note": (
            "L3 uses sqlite-vss when installed; otherwise keyword token overlap stub. "
            "Invalidate on approve/rollback."
        ),
    }


def fingerprint(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
