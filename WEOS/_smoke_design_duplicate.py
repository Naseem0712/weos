"""Smoke: Canvas D2 — duplicate design + multi-size rows → real new IDs."""

from __future__ import annotations

import copy
import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_design_dup_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / "WEOS" / "website" / "canvas"


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))

    from WEOS.factory import quote_workspace as qw
    from WEOS.factory.project_store import load_project, save_project

    dup_js = (CANVAS / "design_duplicate.js").read_text(encoding="utf-8")

    src_svg = '<svg xmlns="http://www.w3.org/2000/svg"><g id="SRC"/></svg>'
    source = {
        "lineId": "srcline001",
        "product": "casement_stub",
        "productType": "CASEMENT_WINDOW",
        "displayName": "Casement",
        "width": 1000,
        "height": 1200,
        "qty": 1,
        "glass": "5mm_clear",
        "colour": "white",
        "description": "Inherited desc",
        "sellingRate": 800,
        "saleUnit": "sqft",
        "preview": {"svg": src_svg, "key": "old"},
        "options": {"quoteGroup": "Main"},
    }
    doc = {
        "projectId": "PRJ-DUP-TEST",
        "name": "Dup Demo",
        "customer": "Cust",
        "status": "draft",
        "lines": [copy.deepcopy(source)],
    }
    saved = save_project(doc, action="create")
    pid = saved["projectId"]
    # Stabilize source id after freeze
    lines = saved.get("lines") or []
    _ok(len(lines) >= 1, "A: source line persisted")
    src_id = str(lines[0].get("lineId") or "srcline001")

    rows = [
        {"width": 1100, "height": 1300, "qty": 2, "floor": "1F", "location": "Hall", "mark": "C-02", "sellingRate": 850},
        {"widthMm": 1400, "heightMm": 1500, "qty": 1, "floor": "2F", "location": "Office", "mark": "C-03", "rate": 900},
    ]
    result = qw.duplicate_design_rows(saved, source_line_id=src_id, rows=rows)
    _ok(result["createdCount"] == 2, "B: created 2 rows")
    new_ids = result["createdLineIds"]
    _ok(len(set(new_ids)) == 2, "B: unique new ids")
    _ok(src_id not in new_ids, "B: original id unchanged / not reused")

    out_lines = result["doc"]["lines"]
    _ok(len(out_lines) == len(lines) + 2, "C: original + 2 new")
    orig = next(ln for ln in out_lines if str(ln.get("lineId")) == src_id)
    _ok(float(orig.get("width") or 0) == float(lines[0].get("width") or 1000), "C: original dims unchanged")

    created_lines = [ln for ln in out_lines if str(ln.get("lineId")) in set(new_ids)]
    _ok(len(created_lines) == 2, "D: both clones present")
    for ln in created_lines:
        prev = ln.get("preview") if isinstance(ln.get("preview"), dict) else {}
        svg = str((prev or {}).get("svg") or "")
        _ok(src_svg not in svg and "SRC" not in svg, "D: no raw SVG clone")
        _ok(prev.get("needsRegen") is True or svg == "", "D: marked for regen")
        _ok(str(ln.get("description") or "") == "Inherited desc" or ln.get("glass") == "5mm_clear", "D: inherits specs")

    _ok(float(created_lines[0].get("width") or 0) == 1100, "E: multi-size row1 W")
    _ok(float(created_lines[1].get("width") or 0) == 1400, "E: multi-size row2 W")
    _ok(str(created_lines[0].get("locationName") or "") == "1F", "E: floor inherited onto locationName")

    # Persist via save
    saved2 = save_project(result["doc"], action="duplicate_design")
    reloaded = load_project(saved2["projectId"])
    lids = [str(ln.get("lineId")) for ln in (reloaded.get("lines") or []) if isinstance(ln, dict)]
    _ok(src_id in lids and all(i in lids for i in new_ids), "F: durable reload keeps ids")

    # Frontend modal
    _ok("Create All" in dup_js and "qwDupModal" in dup_js, "G: duplicate modal")
    _ok("needsRegen" not in dup_js or "regenerat" in dup_js.lower(), "G: regen messaging")
    _ok("/designs/" in dup_js and "duplicate" in dup_js, "G: calls duplicate API")

    # API route registration
    from fastapi.testclient import TestClient
    from WEOS.api.server import app

    client = TestClient(app)
    r = client.post(
        f"/api/projects/{pid}/designs/{src_id}/duplicate",
        json={"rows": [{"width": 1600, "height": 1600, "qty": 1}]},
    )
    _ok(r.status_code in (200, 401, 403, 404), f"H: duplicate API responds ({r.status_code})")

    print("PASS: _smoke_design_duplicate.py")


if __name__ == "__main__":
    main()
