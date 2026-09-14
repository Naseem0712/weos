"""Smoke: Canvas Batch G — design templates (save / instantiate / no identity)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_tpl_"))
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
    from WEOS.factory import design_templates as dt
    from WEOS.factory import member_grid as mg
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.project_store import empty_project, save_project

    init_db()
    gst = "22EEEEE0000E1Z5"
    cust = create_customer(gst, display_name="Tpl Cust", mobile="9000555666")
    proj = upsert_project(
        project_id="PRJ-2026-TPL",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Template Job",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Template Job", customer="Tpl Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerId"] = cust["customerId"]
    doc["quotationId"] = "Q-SHOULD-NOT-LEAK"
    doc["lines"] = []
    save_project(doc, bump_version=False, action="smoke")

    des = dh.ensure_design_document(pid, company_gst=gst)
    asm = ds.create_assembly(design_document_id=des["designDocumentId"], company_gst=gst)
    el = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1800,
        height_mm=1500,
        display_code="W-01",
    )
    eid = el["elementId"]
    placed = mg.place_member(element_id=eid, company_gst=gst, orientation="H", position_mm=400)
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

    tpl = dt.save_element_as_template(
        element_id=eid,
        company_gst=gst,
        name="Top Fixed + Bottom Sliding",
        category="Combination",
        description="Starter combo",
    )
    _ok(tpl["templateId"].startswith("TPL-"), "template id")
    _ok(tpl.get("isQuoteItem") is False, "not a quote item")
    _ok(tpl.get("includeInPdf") is False, "not in PDF")
    snap = tpl.get("topologySnapshot") or {}
    blob = str(snap) + str(tpl.get("assignmentsSnapshot"))
    _ok("Q-SHOULD-NOT-LEAK" not in blob, "no quotation id in template")
    _ok("Tpl Cust" not in blob and "customerId" not in blob.lower(), "no customer identity")
    _ok(snap.get("gridActivated") is True, "topology preserved")
    _ok(len(tpl.get("assignmentsSnapshot") or []) == 2, "assignments preserved")

    listed = dt.list_templates(company_gst=gst)
    _ok(any(t["templateId"] == tpl["templateId"] for t in listed), "listed")

    # Instantiate at new size with SCALE
    des2 = dh.ensure_design_document(pid, company_gst=gst)
    inst = dt.instantiate_template(
        template_id=tpl["templateId"],
        company_gst=gst,
        design_document_id=des2["designDocumentId"],
        legacy_line_id="from_tpl_01",
        width_mm=2400,
        height_mm=1500,
        size_change_rule="SCALE",
    )
    _ok(inst["element"]["elementId"] != eid, "new element ids")
    _ok(inst["assembly"]["assemblyId"] != asm["assemblyId"], "new assembly")
    new_topo = inst["topology"]
    _ok(new_topo["memberCount"] == 1, "topology from template")
    _ok(len(inst["assignments"]) == 2, "assignments instantiated")
    mem = new_topo["members"][0]
    # 400 * (1500/1500) height scale=1, width 1800→2400 → H member y scales with sy=1 → still ~400
    _ok(abs(float(mem["positionMm"]) - 400) < 2.0, f"H member scaled pos={mem['positionMm']}")

    tpl_after = dt.get_template(tpl["templateId"], company_gst=gst)
    _ok(tpl_after["name"] == tpl["name"], "template unchanged")
    _ok(tpl_after["sourceElementId"] == eid, "source audit unchanged")

    # Require rule when dims differ
    try:
        dt.instantiate_template(
            template_id=tpl["templateId"],
            company_gst=gst,
            design_document_id=des2["designDocumentId"],
            legacy_line_id="bad",
            width_mm=2000,
            height_mm=1500,
            size_change_rule=None,
        )
        raise SystemExit("FAIL: should require size rule")
    except ValueError as e:
        _ok("sizeChangeRule" in str(e), f"rule required ({e})")

    print("PASS: _smoke_design_templates")


if __name__ == "__main__":
    main()
