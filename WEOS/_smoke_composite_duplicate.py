"""Smoke: Canvas Batch G — composite deep-copy duplicate (cases A–I)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_comp_dup_"))
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
    from WEOS.factory import composite_duplicate as cd
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory import design_scene as ds
    from WEOS.factory import member_grid as mg
    from WEOS.factory import quote_workspace as qw
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.project_store import empty_project, load_project, save_project

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    gst = "22CCCCC0000C1Z5"
    cust = create_customer(gst, display_name="Dup Comp Cust", mobile="9000333444")
    proj = upsert_project(
        project_id="PRJ-2026-CDUP",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Composite Dup Job",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Composite Dup Job", customer="Dup Comp Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerId"] = cust["customerId"]
    doc["lines"] = []
    save_project(doc, bump_version=False, action="smoke")

    des = dh.ensure_design_document(pid, company_gst=gst)
    asm = ds.create_assembly(design_document_id=des["designDocumentId"], company_gst=gst, name="A1")
    el = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1800,
        height_mm=1500,
        display_code="W-01",
        legacy_line_id="line_src01",
    )
    eid = el["elementId"]
    placed = mg.place_member(element_id=eid, company_gst=gst, orientation="H", position_mm=500)
    leaves = [c for c in placed["topology"]["cells"] if c.get("isLeaf")]
    top = min(leaves, key=lambda c: c["yMm"])
    bot = max(leaves, key=lambda c: c["yMm"])
    ca.assign_product(cell_id=top["cellId"], company_gst=gst, product_type="FIXED")
    ca.assign_product(
        cell_id=bot["cellId"],
        company_gst=gst,
        product_type="SLIDING",
        configuration={"shutterCount": 2},
    )

    src_topo = mg.get_element_topology(eid, company_gst=gst)
    src_assigns = ca.list_assignments_for_element(eid, company_gst=gst)
    src_member_ids = {m["memberId"] for m in src_topo["members"]}
    src_cell_ids = {c["cellId"] for c in src_topo["cells"]}
    src_asg_ids = {a["assignmentId"] for a in src_assigns}

    # Attach quote line
    doc = load_project(pid)
    doc["lines"] = [
        {
            "lineId": "line_src01",
            "product": "sliding_stub",
            "productType": "SLIDING_WINDOW",
            "displayName": "Combination Window",
            "width": 1800,
            "height": 1500,
            "qty": 1,
            "sellingRate": 1850,
            "saleUnit": "sqft",
            "mark": "W-01",
            "description": "Top Fixed + Bottom Sliding",
            "glass": "5mm_clear",
            "elementId": eid,
        }
    ]
    save_project(doc, action="smoke_attach")

    # A: same-size composite duplicate
    dup = cd.duplicate_composite_element(
        source_element_id=eid,
        company_gst=gst,
        new_legacy_line_id="line_dup01",
        width_mm=1800,
        height_mm=1500,
    )
    _ok(dup["ok"], "A: same-size duplicate ok")
    new_eid = dup["element"]["elementId"]
    _ok(new_eid != eid, "B: new element id")
    _ok(dup["assembly"]["assemblyId"] != asm["assemblyId"], "B: new assembly id")

    # B: new IDs for member/cell/assignment
    new_topo = dup["topology"]
    new_assigns = dup["assignments"]
    new_member_ids = {m["memberId"] for m in new_topo["members"]}
    new_cell_ids = {c["cellId"] for c in new_topo["cells"]}
    new_asg_ids = {a["assignmentId"] for a in new_assigns}
    _ok(not (src_member_ids & new_member_ids), "B: member ids remapped")
    _ok(not (src_cell_ids & new_cell_ids), "B: cell ids remapped")
    _ok(not (src_asg_ids & new_asg_ids), "B: assignment ids remapped")

    # C: exact topology copied (counts + display codes)
    _ok(new_topo["memberCount"] == src_topo["memberCount"], "C: member count")
    _ok(new_topo["leafCellCount"] == src_topo["leafCellCount"], "C: leaf count")
    src_codes = sorted(c["displayCode"] for c in src_topo["cells"] if c.get("isLeaf"))
    new_codes = sorted(c["displayCode"] for c in new_topo["cells"] if c.get("isLeaf"))
    _ok(src_codes == new_codes, f"C: leaf codes {src_codes}=={new_codes}")

    # D: assignments copied
    by_code = {}
    cells_by_id = {c["cellId"]: c for c in new_topo["cells"]}
    for a in new_assigns:
        code = (cells_by_id.get(a["cellId"]) or {}).get("displayCode")
        by_code[code] = a["productType"]
    top_code = (min([c for c in new_topo["cells"] if c.get("isLeaf")], key=lambda c: c["yMm"]))["displayCode"]
    bot_code = (max([c for c in new_topo["cells"] if c.get("isLeaf")], key=lambda c: c["yMm"]))["displayCode"]
    _ok(by_code.get(top_code) == "FIXED", "D: top Fixed")
    _ok(by_code.get(bot_code) == "SLIDING", "D: bottom Sliding")

    # E: source unchanged
    src_after = mg.get_element_topology(eid, company_gst=gst)
    _ok(src_after["memberCount"] == src_topo["memberCount"], "E: source members unchanged")
    _ok(set(m["memberId"] for m in src_after["members"]) == src_member_ids, "E: source member ids stable")

    # F/G: via quote_workspace + persist
    doc = load_project(pid)
    result = qw.duplicate_design_rows(
        doc,
        source_line_id="line_src01",
        rows=[{"width": 1800, "height": 1500, "qty": 2, "floor": "1F", "location": "Bed", "mark": "W-02", "sellingRate": 1850}],
        company_gst=gst,
        idempotency_key="IDEM-SMOKE-1",
    )
    _ok(result["createdCount"] == 1, "G: quote card created")
    saved = save_project(result["doc"], action="dup_smoke")
    reloaded = load_project(saved["projectId"])
    lids = [ln.get("lineId") for ln in reloaded["lines"]]
    _ok("line_src01" in lids and result["createdLineIds"][0] in lids, "F: refresh restores ids")

    # H: preview regenerated
    created_ln = next(ln for ln in reloaded["lines"] if ln["lineId"] == result["createdLineIds"][0])
    prev = created_ln.get("preview") or {}
    _ok(bool(prev.get("svg")) or prev.get("needsRegen") is True, "H: preview regenerated or marked")
    _ok(created_ln.get("elementId") != eid, "H: new element on line")

    # I: tenant isolation
    try:
        cd.duplicate_composite_element(
            source_element_id=eid,
            company_gst="99ZZZZZ9999Z9Z9",
            new_legacy_line_id="x",
        )
        raise SystemExit("FAIL: I tenant isolation")
    except PermissionError:
        _ok(True, "I: tenant isolation")

    # Idempotency
    again = qw.duplicate_design_rows(
        reloaded,
        source_line_id="line_src01",
        rows=[{"width": 1800, "height": 1500, "qty": 1}],
        company_gst=gst,
        idempotency_key="IDEM-SMOKE-1",
    )
    _ok(again.get("idempotentReplay") is True, "idempotent replay")
    _ok(again["createdLineIds"] == result["createdLineIds"], "idempotent same ids")

    print("PASS: _smoke_composite_duplicate")


if __name__ == "__main__":
    main()
