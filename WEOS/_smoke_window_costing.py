"""Smoke: window costing pipeline — BOM→cost→selling, stale, override, billing qty."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_win_cost_"))
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
    from WEOS.factory import cost_rules as cr
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory import design_scene as ds
    from WEOS.factory import engineering_bom as eb
    from WEOS.factory import engineering_costing as ec
    from WEOS.factory import engineering_masters as em
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.project_store import empty_project, save_project

    init_db()
    gst = "22CCCCC0000C1Z5"
    em.seed_default_window_masters(company_gst=gst)
    cr.seed_safe_sample_cost_rules(company_gst=gst)

    cust = create_customer(gst, display_name="Cost Cust", mobile="9000222333")
    proj = upsert_project(
        project_id="PRJ-2026-COST1",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Cost Window",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Cost Window", customer="Cost Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerId"] = cust["customerId"]
    doc["lines"] = []
    save_project(doc, bump_version=False, action="smoke")

    des = dh.ensure_design_document(pid, company_gst=gst)
    asm = ds.create_assembly(design_document_id=des["designDocumentId"], company_gst=gst)
    series = em.resolve_series_ref("29mm_sliding", company_gst=gst)
    el = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1200,
        height_mm=1400,
        display_code="W-COST",
        config_payload={"seriesId": series["seriesId"], "seriesCode": "29mm_sliding", "shutterCount": 2},
    )
    eid = el["elementId"]

    bom = eb.generate_element_bom(eid, company_gst=gst, persist=True, force=True)
    _ok(bom.get("usesQuoteSellingRate") is False, "BOM not from selling")

    costing = ec.generate_element_costing(
        eid,
        company_gst=gst,
        persist=True,
        force=True,
        selling={"method": "COST_PLUS_MARKUP", "markupPct": 25, "commercialUnit": "SFT"},
    )
    _ok(costing["costingId"].startswith("ECOST-"), "costing id")
    _ok(costing.get("usesQuoteSellingRateAsCost") is False, "cost not from quote rate")
    _ok(costing["totalCost"] > 0, "total cost > 0")
    _ok("MATERIAL" in (costing.get("categoryTotals") or {}), "material category")
    _ok("WASTAGE" in (costing.get("categoryTotals") or {}), "wastage applied")
    _ok(costing.get("suggestedSelling") and costing["suggestedSelling"] > costing["totalCost"], "markup sell > cost")
    _ok(costing.get("grossProfit") is not None, "gross profit")
    _ok(costing.get("calculatedQty") and costing["calculatedQty"] > 0, "calculated billing qty")
    _ok(abs(float(costing["billingQty"]) - float(costing["calculatedQty"])) < 1e-6, "billing=calculated default")

    # Piece-level trace to BOM / member
    mat = [ln for ln in costing["lines"] if ln.get("breakdownCategory") == "MATERIAL"]
    _ok(len(mat) >= 1, "material lines")
    _ok(any(ln.get("bomLineId") for ln in mat), "BOM line traceability")
    outer = [ln for ln in mat if (ln.get("meta") or {}).get("outerFrame")]
    _ok(len(outer) == 4, "no double outer-frame cost (4 pieces)")

    # NOMINAL glass → ESTIMATED
    glass_lines = [ln for ln in costing["lines"] if ln.get("breakdownCategory") == "GLASS"]
    _ok(len(glass_lines) >= 1, "glass cost lines")
    _ok(all(ln.get("precisionMode") == "ESTIMATED" for ln in glass_lines), "glass ESTIMATED")

    # Billing override does not change cost / geometry
    cost_before = costing["totalCost"]
    updated = ec.update_selling(
        costing["costingId"],
        company_gst=gst,
        selling={"method": "COST_PLUS_MARKUP", "markupPct": 25, "billingQtyOverride": 20.0},
    )
    _ok(abs(updated["totalCost"] - cost_before) < 1e-6, "selling change does not alter cost")
    _ok(abs(float(updated["billingQty"]) - 20.0) < 1e-6, "billing override applied")
    _ok(abs(float(updated["calculatedQty"]) - float(costing["calculatedQty"])) < 1e-6, "calculated qty preserved")

    # Manual override preserves original
    line0 = next(ln for ln in updated["lines"] if ln.get("breakdownCategory") == "MATERIAL" and ln.get("unitCost"))
    over = ec.apply_line_override(
        updated["costingId"],
        line0["lineId"],
        company_gst=gst,
        override_unit_cost=float(line0["unitCost"]) * 1.1,
        reason="smoke_override",
        user="tester",
    )
    ol = next(ln for ln in over["lines"] if ln.get("lineId") == line0["lineId"] or ln.get("bomLineId") == line0.get("bomLineId"))
    # After supersede, find overridden line by bomLineId
    ol = next(ln for ln in over["lines"] if ln.get("bomLineId") == line0.get("bomLineId") and ln.get("overrideReason"))
    _ok(ol.get("originalUnitCost") is not None, "original unit cost preserved")
    _ok(ol.get("overrideReason") == "smoke_override", "override reason")
    _ok((ol.get("meta") or {}).get("masterSourcePreserved") is True, "master source preserved")

    # BOM STALE → Cost STALE
    eb.mark_stale_for_element(eid, company_gst=gst, reason="design_change")
    stale = ec.get_current_costing(element_id=eid, company_gst=gst)
    _ok(stale and (stale.get("status") == "STALE" or stale.get("calcStatus") == "STALE" or stale.get("freshness") == "STALE"), "cost stale with BOM")

    regen = ec.regenerate_costing(
        eid, company_gst=gst, selling={"method": "COST_PLUS_MARKUP", "markupPct": 30}
    )
    _ok(regen["costingId"] != (stale or {}).get("costingId"), "regenerate supersedes")
    _ok(regen.get("isCurrent") is True, "new costing current")
    _ok(regen.get("calcStatus") in ("READY", "PARTIAL"), f"regen status {regen.get('calcStatus')}")

    # Master cost change → stale
    profiles = em.list_profiles(company_gst=gst)
    p0 = profiles[0]
    em.update_profile(p0["profileId"], company_gst=gst, costBasisValue=float(p0.get("costBasisValue") or 100) + 1)
    cur = ec.get_current_costing(element_id=eid, company_gst=gst)
    _ok(cur and (cur.get("freshness") == "STALE" or cur.get("status") == "STALE"), "master cost change → costing stale")

    # Public strip
    pub = ec.public_commercial_view(regen)
    _ok("totalCost" not in pub and "grossProfit" not in pub, "public view hides cost/profit")
    stripped = ec.strip_internal_cost_fields(regen)
    _ok("totalCost" not in stripped, "audit strip removes totalCost")
    _ok("markupPct" not in stripped, "audit strip removes markup")

    # Project rollup
    roll = ec.rollup_project_costing(project_id=pid, company_gst=gst)
    _ok(roll.get("totalCost", 0) >= 0, "project rollup")
    _ok(roll.get("hierarchy") == ["DESIGN", "FLOOR", "LOCATION", "PROJECT"], "rollup hierarchy")

    # Legacy import: selling keys → manualReview
    imp = cr.import_legacy_cost_semantics(
        {"wastage_pct": 4, "selling_rate": 999, "unknown_thing": 1},
        company_gst=gst,
    )
    _ok(len(imp["imported"]) >= 1, "known legacy imported")
    _ok(any(x.get("manualReview") for x in imp["manualReview"]), "unknown/selling → manualReview")
    _ok(imp.get("zeroSilentLoss") is True, "zeroSilentLoss")

    print("PASS _smoke_window_costing")


if __name__ == "__main__":
    main()
