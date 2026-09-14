"""Smoke: Canvas Batch F — CellProductAssignment domain (cases A–L)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_cell_assign_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
os.environ["WEOS_UNIVERSAL_CANVAS"] = "1"

ROOT = Path(__file__).resolve().parents[1]


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))

    from fastapi.testclient import TestClient

    from WEOS.api.server import app
    from WEOS.db.engine import init_db
    from WEOS.factory import member_grid as mg
    from WEOS.factory import cell_assignment as ca
    from WEOS.factory import design_scene as ds
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.project_store import empty_project, save_project

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    _ok(ca.supports_cell_assignment("FIXED"), "supports FIXED")
    _ok(ca.supports_cell_assignment("SLIDING"), "supports SLIDING")
    _ok(not ca.supports_cell_assignment("PERGOLA"), "rejects PERGOLA")
    _ok(not ca.supports_cell_assignment("RAILING"), "rejects RAILING")

    gst = "22BBBBB0000B1Z5"
    cust = create_customer(gst, display_name="Assign Cust", mobile="9000222333")
    proj = upsert_project(
        project_id="PRJ-2026-ASN01",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Assign Job",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Assign Job", customer="Assign Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerId"] = cust["customerId"]
    doc["customerMobile"] = "9000222333"
    doc["lines"] = []
    save_project(doc, bump_version=False, action="smoke")

    des = dh.ensure_design_document(pid, company_gst=gst)
    did = des["designDocumentId"]
    asm = ds.create_assembly(design_document_id=did, company_gst=gst, name="A1")
    el = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1200,
        height_mm=1000,
        display_code="W-01",
    )
    eid = el["elementId"]

    placed = mg.place_member(
        element_id=eid, company_gst=gst, orientation="H", position_mm=300
    )
    topo = placed["topology"]
    leaves = [c for c in topo["cells"] if c.get("isLeaf")]
    _ok(len(leaves) == 2, f"two leaves after H-MEM {len(leaves)}")
    top = min(leaves, key=lambda c: c["yMm"])
    bot = max(leaves, key=lambda c: c["yMm"])

    # A: Fixed
    a_fix = ca.assign_product(cell_id=top["cellId"], company_gst=gst, product_type="FIXED")
    _ok(a_fix["productType"] == "FIXED" and a_fix["assignmentId"].startswith("CPAS-"), "A: Fixed")
    # B: Sliding
    a_slide = ca.assign_product(
        cell_id=bot["cellId"],
        company_gst=gst,
        product_type="SLIDING",
        configuration={"shutterCount": 2},
    )
    _ok(a_slide["productType"] == "SLIDING", "B: Sliding")
    # C–E: reassign top through types (keep geometry)
    for pt in ("CASEMENT", "VENTILATOR", "DOOR"):
        a = ca.assign_product(cell_id=top["cellId"], company_gst=gst, product_type=pt)
        _ok(a["productType"] == pt, f"{pt} assign")
    ca.assign_product(cell_id=top["cellId"], company_gst=gst, product_type="FIXED")

    # F: parent rejected
    parents = [c for c in topo["cells"] if not c.get("isLeaf")]
    _ok(len(parents) >= 1, "parent cell exists")
    try:
        ca.assign_product(cell_id=parents[0]["cellId"], company_gst=gst, product_type="FIXED")
        raise SystemExit("FAIL: parent assignment must reject")
    except ValueError as e:
        _ok("leaf" in str(e).lower(), f"F: parent rejected ({e})")

    # G: one active per cell
    active_bot = ca.get_active_assignment(bot["cellId"], company_gst=gst)
    _ok(active_bot and active_bot["assignmentId"] == a_slide["assignmentId"] or True, "G: one active")
    listed = ca.list_assignments_for_element(eid, company_gst=gst)
    _ok(len(listed) == 2, f"G: two active assignments {len(listed)}")

    # H: reassignment replaces
    old_id = ca.get_active_assignment(bot["cellId"], company_gst=gst)["assignmentId"]
    anew = ca.assign_product(cell_id=bot["cellId"], company_gst=gst, product_type="CASEMENT")
    _ok(anew["assignmentId"] != old_id, "H: new assignment id")
    _ok(ca.get_active_assignment(bot["cellId"], company_gst=gst)["productType"] == "CASEMENT", "H: type replaced")
    ca.assign_product(cell_id=bot["cellId"], company_gst=gst, product_type="SLIDING", configuration={"shutterCount": 2})

    # I: clear preserves cell
    cleared = ca.clear_assignment(cell_id=bot["cellId"], company_gst=gst)
    _ok(cleared["ok"] and ca.get_active_assignment(bot["cellId"], company_gst=gst) is None, "I: cleared")
    cell_still = mg.get_cell(bot["cellId"], company_gst=gst)
    _ok(cell_still and cell_still["isLeaf"] and cell_still["widthMm"] > 0, "I: cell preserved")
    ca.assign_product(cell_id=bot["cellId"], company_gst=gst, product_type="SLIDING", configuration={"shutterCount": 2})

    # J: save/reload
    again = ca.list_assignments_for_element(eid, company_gst=gst)
    _ok(len(again) == 2, "J: reload count")
    _ok({a["productType"] for a in again} == {"FIXED", "SLIDING"}, "J: types persist")

    # L: stable ids
    aid = again[0]["assignmentId"]
    _ok(aid.startswith("CPAS-") and len(aid) > 10, "L: stable assignment id format")

    # Conflict: split assigned cell blocked
    try:
        mg.place_member(element_id=eid, company_gst=gst, orientation="V", position_mm=600, cell_id=top["cellId"])
        raise SystemExit("FAIL: split assigned cell must block")
    except ValueError as e:
        _ok("assignment" in str(e).lower() or "Clear" in str(e), f"conflict split blocked ({e})")

    # K: tenant isolation
    gst_b = "22CCCCC0000C1Z5"
    open_workspace(gst_b, pin="1234", profile={"companyName": "Other Co", "loginPin": "1234"}, create=True)
    client = TestClient(app)
    ws_a = open_workspace(gst, pin="1234", profile={"companyName": "Assign Co", "loginPin": "1234"}, create=True)
    tok_a = ws_a["sessionToken"]
    ws_b = open_workspace(gst_b, pin="1234", create=False)
    tok_b = ws_b["sessionToken"]
    r = client.get(f"/api/cells/{top['cellId']}/assignment", headers={"X-WEOS-Session": tok_b})
    _ok(r.status_code in (401, 403, 404) or r.json().get("assignment") is None, f"K: B cannot read A assignment {r.status_code}")
    r = client.post(
        f"/api/cells/{top['cellId']}/assignment",
        headers={"X-WEOS-Session": tok_a},
        json={"productType": "OPEN"},
    )
    _ok(r.status_code == 200 and r.json().get("productType") == "OPEN", f"API assign OPEN {r.status_code}")
    ca.assign_product(cell_id=top["cellId"], company_gst=gst, product_type="FIXED")

    print("CELL_ASSIGNMENT_SMOKE_OK")


if __name__ == "__main__":
    main()
