"""Smoke: Canvas Batch F — cell assignment UI / property panel schema switching."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_cell_ui_"))
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

    from WEOS.db.engine import init_db
    from WEOS.factory import member_grid as mg
    from WEOS.factory import cell_assignment as ca
    from WEOS.factory import design_scene as ds
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.project_store import empty_project, save_project

    init_db()

    # Frontend presence
    pp = (CANVAS / "property_panel.js").read_text(encoding="utf-8")
    _ok("assignCellProduct" in pp and "Clear Assignment" in pp, "UI: assign/clear wired")
    _ok("/api/cells/" in pp and "assignment" in pp, "UI: assignment API path")

    gst = "22EEEEE0000E1Z5"
    cust = create_customer(gst, display_name="UI Cust", mobile="9000444555")
    proj = upsert_project(
        project_id="PRJ-2026-UI01",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="UI Job",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="UI Job", customer="UI Cust")
    doc.update({"projectId": pid, "companyGst": gst, "customerId": cust["customerId"], "lines": []})
    save_project(doc, bump_version=False, action="smoke")
    des = dh.ensure_design_document(pid, company_gst=gst)
    asm = ds.create_assembly(design_document_id=des["designDocumentId"], company_gst=gst, name="A1")
    el = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="FIXED_WINDOW",
        width_mm=1200,
        height_mm=1000,
        display_code="W-UI",
    )
    eid = el["elementId"]
    mg.place_member(element_id=eid, company_gst=gst, orientation="H", position_mm=400)
    topo = mg.get_element_topology(eid, company_gst=gst)
    leaves = [c for c in topo["cells"] if c["isLeaf"]]
    c1 = leaves[0]

    # Unassigned schema
    panel0 = mg.panel_for_cell({**c1, "companyGst": gst})
    _ok(panel0.get("supportsCellAssignment"), "panel supports assign")
    _ok(not panel0.get("forbidProductAssignment"), "leaf not forbidden")
    keys0 = [f["key"] for g in panel0["schema"]["groups"] for f in g["fields"]]
    _ok("productType" in keys0, "unassigned shows productType assign field")

    ca.assign_product(cell_id=c1["cellId"], company_gst=gst, product_type="SLIDING")
    panel_s = mg.panel_for_cell({**mg.get_cell(c1["cellId"], company_gst=gst), "companyGst": gst})
    _ok(panel_s.get("assignment", {}).get("productType") == "SLIDING", "sliding assignment on panel")
    field_blob = str(panel_s["schema"])
    _ok("shutterCount" in field_blob or "Shutter" in field_blob, "sliding schema fields")
    _ok("hinge" not in field_blob.lower() or "Handle" in field_blob, "no casement-only leak check soft")

    ca.assign_product(cell_id=c1["cellId"], company_gst=gst, product_type="FIXED")
    panel_f = mg.panel_for_cell({**mg.get_cell(c1["cellId"], company_gst=gst), "companyGst": gst})
    blob_f = str(panel_f["schema"])
    _ok("shutterCount" not in blob_f and "FIXED" in str(panel_f.get("assignment")), "fixed schema no shutter")

    # Member panel still distinct
    mem = (topo.get("members") or [None])[0]
    if mem:
        mp = mg.panel_for_member(mem)
        _ok(mp["kind"] == "member" and "Cell" not in (mp.get("title") or ""), "member panel distinct")

    print("CELL_ASSIGNMENT_UI_SMOKE_OK")


if __name__ == "__main__":
    main()
