"""Smoke: Composite assembly BOM — outer frame once + cell products + member profiles."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_comp_bom_"))
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
    from WEOS.factory import engineering_bom as eb
    from WEOS.factory import engineering_masters as em
    from WEOS.factory import member_grid as mg
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.project_store import empty_project, save_project

    init_db()
    gst = "22CCCCC0000C1Z5"
    em.seed_default_window_masters(company_gst=gst)
    series = em.resolve_series_ref("29mm_sliding", company_gst=gst)

    cust = create_customer(gst, display_name="Comp BOM", mobile="9000333444")
    proj = upsert_project(
        project_id="PRJ-2026-CBOM",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Composite BOM Fixture",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Composite BOM", customer="Comp BOM")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerId"] = cust["customerId"]
    doc["lines"] = []
    save_project(doc, bump_version=False, action="smoke")

    des = dh.ensure_design_document(pid, company_gst=gst)
    asm = ds.create_assembly(design_document_id=des["designDocumentId"], company_gst=gst)
    # Known fixture: 1800×1500, H member @ 500 → top FIXED + bottom SLIDING
    el = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1800,
        height_mm=1500,
        display_code="W-COMP",
        config_payload={"seriesId": series["seriesId"], "seriesCode": "29mm_sliding"},
    )
    eid = el["elementId"]
    placed = mg.place_member(element_id=eid, company_gst=gst, orientation="H", position_mm=500)
    leaves = [c for c in placed["topology"]["cells"] if c.get("isLeaf")]
    top = min(leaves, key=lambda c: c["yMm"])
    bot = max(leaves, key=lambda c: c["yMm"])
    ca.assign_product(
        cell_id=top["cellId"],
        company_gst=gst,
        product_type="FIXED",
        series_id=series["seriesId"],
        series_code="29mm_sliding",
    )
    ca.assign_product(
        cell_id=bot["cellId"],
        company_gst=gst,
        product_type="SLIDING",
        series_id=series["seriesId"],
        series_code="29mm_sliding",
        configuration={"shutterCount": 2, "mesh": True},
    )

    bom = eb.generate_composite_fixture_bom(company_gst=gst, element_id=eid)
    lines = bom.get("lines") or []
    _ok(bom.get("status") in ("READY", "PARTIAL"), f"composite status {bom.get('status')}")

    outer = [ln for ln in lines if (ln.get("meta") or {}).get("outerFrame")]
    _ok(len(outer) == 4, "outer frame counted once (4 pieces)")

    # Member (transom) profile — not outer frame
    members = [ln for ln in lines if ln.get("memberId")]
    _ok(len(members) >= 1, "frame member profile BOM")
    _ok(all(ln.get("profileRole") not in ("OUTER_FRAME", "OUTER_FRAME_VERTICAL", "OUTER_FRAME_HORIZONTAL") for ln in members), "members not outer frame roles")

    glass = [ln for ln in lines if ln.get("category") == "GLASS"]
    _ok(len(glass) >= 2, "glass per cell (fixed + sliding)")
    cell_ids = {ln.get("cellId") for ln in glass}
    _ok(top["cellId"] in cell_ids and bot["cellId"] in cell_ids, "glass tagged to cell ids")

    mesh = [ln for ln in lines if ln.get("category") == "MESH"]
    _ok(len(mesh) >= 1, "mesh on sliding cell")

    hw = [ln for ln in lines if ln.get("category") == "HARDWARE"]
    _ok(len(hw) >= 1, "sliding hardware rules")

    # Expected: no double-count — outer vertical length total required = 2 * 1500
    vert_req = sum(
        float(ln.get("requiredLengthMm") or 0)
        for ln in outer
        if ln.get("profileRole") == "OUTER_FRAME_VERTICAL"
    )
    _ok(abs(vert_req - 3000) < 0.1, f"outer vertical required total 3000 got {vert_req}")

    print("PASS: composite bom")


if __name__ == "__main__":
    main()
