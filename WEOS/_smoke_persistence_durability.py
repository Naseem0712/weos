"""Smoke: project save durability — SQL is authoritative; fail closed on SQL write failure."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

_tmp = Path(tempfile.mkdtemp(prefix="weos_persist_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from WEOS.db.engine import init_db
    from WEOS.factory.project_store import (
        DurableSaveError,
        load_project,
        project_path,
        save_project,
    )

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    doc = {
        "name": "Persist Job",
        "customer": "Persist Cust",
        "customerMobile": "9123456780",
        "status": "draft",
        "companyGst": "22PERSIST000A1Z5",
        "lines": [
            {
                "lineId": "L1",
                "product": "29mm_sliding",
                "displayName": "Sliding",
                "width": 1200,
                "height": 1400,
                "qty": 1,
            }
        ],
    }
    saved = save_project(doc, action="create")
    pid = saved.get("projectId")
    _ok(bool(pid), f"projectId allocated: {pid}")
    _ok(saved.get("persisted") is True, f"persisted True got {saved.get('persisted')}")
    _ok(saved.get("durable") is True, f"durable True got {saved.get('durable')}")
    _ok(saved.get("saveKind") == "server_draft", f"saveKind {saved.get('saveKind')}")

    # Reload from store (DB preferred via load_project)
    loaded = load_project(pid)
    _ok(loaded.get("customer") == "Persist Cust", "reload customer")
    _ok(len(loaded.get("lines") or []) == 1, "reload lines")
    _ok(int(loaded.get("version") or 0) >= 1, f"version >=1 got {loaded.get('version')}")

    # Update + reopen
    loaded["name"] = "Persist Job v2"
    loaded["lines"].append(
        {
            "lineId": "L2",
            "product": "29mm_sliding",
            "displayName": "Sliding 2",
            "width": 900,
            "height": 1200,
            "qty": 2,
        }
    )
    updated = save_project(loaded, action="update")
    _ok(updated.get("durable") is True, "update durable")
    again = load_project(pid)
    _ok(again.get("name") == "Persist Job v2", "reopen name")
    _ok(len(again.get("lines") or []) == 2, f"reopen lines got {len(again.get('lines') or [])}")

    # Simulate SQL write failure while DB is ready → must raise, must NOT claim durable success
    before = load_project(pid)
    before_ver = int(before.get("version") or 0)
    before_name = before.get("name")
    fs_mtime_before = project_path(pid).stat().st_mtime if project_path(pid).is_file() else None

    with mock.patch("WEOS.factory.project_store._db_put_project", return_value=False):
        failed = False
        try:
            boom = dict(before)
            boom["name"] = "SHOULD_NOT_PERSIST"
            save_project(boom, action="update")
        except DurableSaveError as exc:
            failed = True
            _ok("Durable database save failed" in str(exc), f"error message: {exc}")
        _ok(failed, "SQL failure raises DurableSaveError")

    after = load_project(pid)
    _ok(after.get("name") == before_name, f"name unchanged after failed save got {after.get('name')}")
    _ok(int(after.get("version") or 0) == before_ver, "version unchanged after failed save")
    # FS must not have become the sole "success" path for the failed write
    if fs_mtime_before is not None and project_path(pid).is_file():
        # Content check is stronger than mtime
        disk = __import__("json").loads(project_path(pid).read_text(encoding="utf-8"))
        _ok(disk.get("name") != "SHOULD_NOT_PERSIST", "FS cache must not hold failed durable write")

    print("OK persistence durability smoke")


if __name__ == "__main__":
    main()
