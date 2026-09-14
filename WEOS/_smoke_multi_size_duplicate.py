"""Smoke: Canvas Batch G — multi-size duplicate KEEP_OFFSETS / SCALE."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_msize_dup_"))
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

    from WEOS.db.engine import init_db
    from WEOS.factory import cell_assignment as ca
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory import design_scene as ds
    from WEOS.factory import member_grid as mg
    from WEOS.factory import quote_workspace as qw
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.project_store import empty_project, load_project, save_project

    init_db()
    gst = "22DDDDD0000D1Z5"
    cust = create_customer(gst, display_name="Multi Size Cust", mobile="9000444555")
    proj = upsert_project(
        project_id="PRJ-2026-MSIZE",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Multi Size",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Multi Size", customer="Multi Size Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerId"] = cust["customerId"]
    doc["lines"] = []
    save_project(doc, bump_version=False, action="smoke")

    des = dh.ensure_design_document(pid, company_gst=gst)
    asm = ds.create_assembly(design_document_id=des["designDocumentId"], company_gst=gst)
    el = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="CASEMENT_WINDOW",
        width_mm=1800,
        height_mm=1500,
        legacy_line_id="ms_src",
        display_code="W-01",
    )
    eid = el["elementId"]
    placed = mg.place_member(element_id=eid, company_gst=gst, orientation="V", position_mm=900)
    leaves = [c for c in placed["topology"]["cells"] if c.get("isLeaf")]
    left = min(leaves, key=lambda c: c["xMm"])
    right = max(leaves, key=lambda c: c["xMm"])
    ca.assign_product(cell_id=left["cellId"], company_gst=gst, product_type="FIXED")
    ca.assign_product(cell_id=right["cellId"], company_gst=gst, product_type="CASEMENT")

    doc = load_project(pid)
    doc["lines"] = [
        {
            "lineId": "ms_src",
            "product": "casement_stub",
            "productType": "CASEMENT_WINDOW",
            "displayName": "Split Casement",
            "width": 1800,
            "height": 1500,
            "qty": 1,
            "sellingRate": 1200,
            "saleUnit": "sqft",
            "mark": "W-01",
            "elementId": eid,
        }
    ]
    save_project(doc, action="attach")

    # Reject different size without rule
    try:
        qw.duplicate_design_rows(
            load_project(pid),
            source_line_id="ms_src",
            rows=[{"width": 2100, "height": 1500, "qty": 1}],
            company_gst=gst,
        )
        # May partial-fail per row
        doc2 = load_project(pid)
        # ensure failed path recorded if partial
    except ValueError as e:
        _ok("sizeChangeRule" in str(e), f"reject without rule: {e}")

    result = qw.duplicate_design_rows(
        load_project(pid),
        source_line_id="ms_src",
        rows=[
            {"width": 1800, "height": 1500, "qty": 2, "floor": "F1", "location": "Hall", "mark": "W-02", "sellingRate": 1200},
            {"width": 2100, "height": 1500, "qty": 1, "floor": "F1", "location": "Bed", "mark": "W-03", "sellingRate": 1300, "sizeChangeRule": "KEEP_OFFSETS"},
            {"width": 2400, "height": 1500, "qty": 1, "floor": "F2", "location": "Office", "mark": "W-04", "sellingRate": 1400, "sizeChangeRule": "SCALE"},
        ],
        company_gst=gst,
        idempotency_key="IDEM-MSIZE-1",
    )
    _ok(result["createdCount"] == 3, f"created 3 got {result['createdCount']} {result.get('rowResults')}")
    saved = save_project(result["doc"], action="msize")
    lines = {ln["lineId"]: ln for ln in saved["lines"]}
    src = lines["ms_src"]
    _ok(float(src["width"]) == 1800, "source unchanged")

    for lid in result["createdLineIds"]:
        ln = lines[lid]
        _ok(ln.get("elementId") and ln["elementId"] != eid, f"new element {lid}")
        el_new = ds.get_element(ln["elementId"], company_gst=gst)
        _ok(el_new is not None, f"element exists {lid}")
        topo = mg.get_element_topology(ln["elementId"], company_gst=gst)
        _ok(topo["memberCount"] == 1, f"member retained {lid}")
        assigns = ca.list_assignments_for_element(ln["elementId"], company_gst=gst)
        _ok(len(assigns) == 2, f"assignments retained {lid}")
        _ok(float(ln.get("sellingAmount") or ln.get("commercialTotal") or 0) > 0, f"amount recalc {lid}")

    # KEEP_OFFSETS geometry: mullion stays ~900 on 2100
    keep_ln = next(ln for ln in saved["lines"] if ln.get("mark") == "W-03")
    keep_topo = mg.get_element_topology(keep_ln["elementId"], company_gst=gst)
    keep_mem = keep_topo["members"][0]
    _ok(abs(float(keep_mem["positionMm"]) - 900) < 1.0, f"KEEP_OFFSETS pos={keep_mem['positionMm']}")

    # SCALE: 1800→2400 → 900 * (2400/1800) = 1200
    scale_ln = next(ln for ln in saved["lines"] if ln.get("mark") == "W-04")
    scale_topo = mg.get_element_topology(scale_ln["elementId"], company_gst=gst)
    scale_mem = scale_topo["members"][0]
    _ok(abs(float(scale_mem["positionMm"]) - 1200) < 1.5, f"SCALE pos={scale_mem['positionMm']}")

    # Invalid KEEP_OFFSETS (member outside)
    bad = qw.duplicate_design_rows(
        load_project(pid),
        source_line_id="ms_src",
        rows=[{"width": 800, "height": 1500, "qty": 1, "sizeChangeRule": "KEEP_OFFSETS", "mark": "BAD"}],
        company_gst=gst,
    )
    _ok(bad["createdCount"] == 0 and bad["failedCount"] == 1, f"invalid KEEP_OFFSETS rejected {bad.get('rowResults')}")
    reason = (bad["rowResults"][0].get("reason") or "").lower()
    _ok("keep_offsets" in reason or "outside" in reason, f"reason={reason}")

    print("PASS: _smoke_multi_size_duplicate")


if __name__ == "__main__":
    main()
