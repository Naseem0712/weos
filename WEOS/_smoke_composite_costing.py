"""Smoke: composite window costing — no double outer frame; cell/element rollup."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_comp_cost_"))
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
    from WEOS.db.models import COST_BREAKDOWN_CATEGORIES, COST_RULE_DOMAINS
    from WEOS.factory import cell_assignment as ca
    from WEOS.factory import cost_rules as cr
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory import design_scene as ds
    from WEOS.factory import engineering_bom as eb
    from WEOS.factory import engineering_costing as ec
    from WEOS.factory import engineering_masters as em
    from WEOS.factory import member_grid as mg
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.project_store import empty_project, save_project

    init_db()
    gst = "22DDDDD0000D1Z5"
    em.seed_default_window_masters(company_gst=gst)
    cr.seed_safe_sample_cost_rules(company_gst=gst)
    series = em.resolve_series_ref("29mm_sliding", company_gst=gst)

    cust = create_customer(gst, display_name="Comp Cost", mobile="9000444555")
    proj = upsert_project(
        project_id="PRJ-2026-CCOST",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Composite Cost Fixture",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Composite Cost", customer="Comp Cost")
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
        product_type="SLIDING_WINDOW",
        width_mm=1800,
        height_mm=1500,
        display_code="W-CCOST",
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
    outer_bom = [ln for ln in (bom.get("lines") or []) if (ln.get("meta") or {}).get("outerFrame")]
    _ok(len(outer_bom) == 4, "BOM outer frame 4 pieces once")

    costing = ec.generate_element_costing(
        eid,
        company_gst=gst,
        persist=True,
        force=True,
        selling={"method": "COST_PLUS_MARKUP", "markupPct": 20, "commercialUnit": "SFT"},
    )
    _ok(costing["totalCost"] > 0, "composite total cost")
    _ok(costing.get("usesQuoteSellingRateAsCost") is False, "not from selling rate")

    mat = [ln for ln in costing["lines"] if ln.get("breakdownCategory") == "MATERIAL"]
    outer_cost = [ln for ln in mat if (ln.get("meta") or {}).get("outerFrame")]
    _ok(len(outer_cost) == 4, "outer frame cost lines match BOM (no double)")

    cell_lines = [ln for ln in costing["lines"] if ln.get("cellId")]
    _ok(len(cell_lines) >= 1, "cell-level cost trace")

    _ok("FABRICATION" in COST_RULE_DOMAINS, "fab domain ready for railing/pergola later")
    _ok("MATERIAL" in COST_BREAKDOWN_CATEGORIES, "breakdown categories ready")

    roll = ec.rollup_project_costing(project_id=pid, company_gst=gst)
    _ok(roll.get("totalCost", 0) > 0, "project cost rollup")
    _ok(len(roll.get("designs") or []) >= 1, "design in rollup")

    print("PASS _smoke_composite_costing")


if __name__ == "__main__":
    main()
