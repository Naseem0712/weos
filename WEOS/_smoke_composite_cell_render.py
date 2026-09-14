"""Smoke: Canvas Batch F — composite cell render (no double frames)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_composite_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

ROOT = Path(__file__).resolve().parents[1]


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
    gst = "22DDDDD0000D1Z5"
    cust = create_customer(gst, display_name="Comp Cust", mobile="9000333444")
    proj = upsert_project(
        project_id="PRJ-2026-CMP01",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Comp Job",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Comp Job", customer="Comp Cust")
    doc.update({"projectId": pid, "companyGst": gst, "customerId": cust["customerId"], "lines": []})
    save_project(doc, bump_version=False, action="smoke")
    des = dh.ensure_design_document(pid, company_gst=gst)
    asm = ds.create_assembly(design_document_id=des["designDocumentId"], company_gst=gst, name="A1")

    # Top Fixed / Bottom Sliding — 1200×1000
    el = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1200,
        height_mm=1000,
        display_code="W-CMP",
    )
    eid = el["elementId"]
    mg.place_member(element_id=eid, company_gst=gst, orientation="H", position_mm=300)
    topo = mg.get_element_topology(eid, company_gst=gst)
    leaves = [c for c in topo["cells"] if c["isLeaf"]]
    top = min(leaves, key=lambda c: c["yMm"])
    bot = max(leaves, key=lambda c: c["yMm"])
    ca.assign_product(cell_id=top["cellId"], company_gst=gst, product_type="FIXED")
    ca.assign_product(
        cell_id=bot["cellId"], company_gst=gst, product_type="SLIDING", configuration={"shutterCount": 2}
    )
    assignments = ca.list_assignments_for_element(eid, company_gst=gst)
    svg = ca.render_composite_svg(topo, assignments, width_mm=1200, height_mm=1000)
    _ok('data-weos-composite="1"' in svg, "composite marker")
    _ok('data-weos-structural="1"' in svg, "structural marker")
    _ok(svg.count('stroke="#1f2937" stroke-width="8"') == 1, "exactly one outer frame")
    _ok("FIXED" in svg and "SLIDING" in svg, "infills present")
    _ok(svg.count("data-weos-cell-infill") == 2, "two CELL infills")
    _ok("background:transparent" in svg or "transparent" in svg, "transparent bg")
    _ok(len([m for m in topo["members"] if m.get("orientation") == "H"]) >= 1, "transom present")

    pdf = mg.pdf_drawing_for_element(eid, company_gst=gst)
    _ok(pdf["mode"] == "composite" and pdf.get("svg"), f"pdf composite mode={pdf['mode']}")

    # Unassigned fail-closed
    ca.clear_assignment(cell_id=bot["cellId"], company_gst=gst)
    pre = ca.pdf_preflight_composite(eid, company_gst=gst)
    _ok(not pre["ok"] and pre.get("missing"), f"unassigned fail-closed {pre}")
    ca.assign_product(cell_id=bot["cellId"], company_gst=gst, product_type="OPEN")
    pre2 = ca.pdf_preflight_composite(eid, company_gst=gst)
    _ok(pre2["ok"], "OPEN is valid for PDF")

    # Mixed Fixed + Casement + Ventilator — 1800×1500
    el2 = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="CASEMENT_WINDOW",
        width_mm=1800,
        height_mm=1500,
        display_code="W-MIX",
    )
    e2 = el2["elementId"]
    mg.place_member(element_id=e2, company_gst=gst, orientation="H", position_mm=500)
    t2 = mg.get_element_topology(e2, company_gst=gst)
    leaves2 = [c for c in t2["cells"] if c["isLeaf"]]
    top2 = min(leaves2, key=lambda c: c["yMm"])
    bot2 = max(leaves2, key=lambda c: c["yMm"])
    # split bottom vertically
    mid_x = float(bot2["xMm"]) + float(bot2["widthMm"]) / 2
    mg.place_member(element_id=e2, company_gst=gst, orientation="V", position_mm=mid_x, cell_id=bot2["cellId"])
    t3 = mg.get_element_topology(e2, company_gst=gst)
    leaves3 = [c for c in t3["cells"] if c["isLeaf"]]
    _ok(len(leaves3) == 3, f"three leaves {len(leaves3)}")
    top3 = min(leaves3, key=lambda c: c["yMm"])
    bottom_leaves = [c for c in leaves3 if c["cellId"] != top3["cellId"]]
    left = min(bottom_leaves, key=lambda c: c["xMm"])
    right = max(bottom_leaves, key=lambda c: c["xMm"])
    ca.assign_product(cell_id=top3["cellId"], company_gst=gst, product_type="FIXED")
    ca.assign_product(cell_id=left["cellId"], company_gst=gst, product_type="CASEMENT")
    ca.assign_product(cell_id=right["cellId"], company_gst=gst, product_type="VENTILATOR")
    asg = ca.list_assignments_for_element(e2, company_gst=gst)
    svg2 = ca.render_composite_svg(t3, asg, width_mm=1800, height_mm=1500)
    _ok(svg2.count('stroke="#1f2937" stroke-width="8"') == 1, "mixed: one outer frame")
    _ok("FIXED" in svg2 and "CASEMENT" in svg2 and "VENT" in svg2, "mixed labels")
    _ok(svg2.count("data-weos-cell-infill") == 3, "three infills")
    summary = ca.composition_summary(asg, t3["cells"])
    _ok("Fixed" in summary or "FIXED" in summary.upper(), f"summary {summary}")

    print("COMPOSITE_CELL_RENDER_SMOKE_OK")


if __name__ == "__main__":
    main()
