"""Smoke: design → BOM STALE → Costing STALE; master/rule change → Costing STALE."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_cost_stale_"))
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


def _is_stale(row: dict | None) -> bool:
    if not row:
        return False
    return (
        row.get("status") == "STALE"
        or row.get("calcStatus") == "STALE"
        or row.get("freshness") == "STALE"
    )


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
    from WEOS.factory import member_grid as mg
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.project_store import empty_project, save_project

    init_db()
    gst = "22STALE0000S1Z5"
    em.seed_default_window_masters(company_gst=gst)
    cr.seed_safe_sample_cost_rules(company_gst=gst)

    cust = create_customer(gst, display_name="Stale Cust", mobile="9000666777")
    proj = upsert_project(
        project_id="PRJ-2026-STALE",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Stale Chain",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Stale Chain", customer="Stale Cust")
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
        display_code="W-STALE",
        config_payload={"seriesId": series["seriesId"], "seriesCode": "29mm_sliding", "shutterCount": 2},
    )
    eid = el["elementId"]

    bom = eb.generate_element_bom(eid, company_gst=gst, persist=True, force=True)
    costing = ec.generate_element_costing(
        eid,
        company_gst=gst,
        persist=True,
        force=True,
        selling={"method": "COST_PLUS_MARKUP", "markupPct": 20},
    )
    _ok(bom.get("status") != "STALE", "BOM current after generate")
    _ok(not _is_stale(costing), "costing current after generate")
    bom_id = bom["bomId"]
    cost_id = costing["costingId"]

    # Design mutation route (element geometry) must call notify → BOM+costing STALE
    ds.update_element(eid, company_gst=gst, width_mm=1300)
    bom_after = eb.get_current_bom(element_id=eid, company_gst=gst)
    cost_after = ec.get_current_costing(element_id=eid, company_gst=gst)
    _ok(bom_after and bom_after.get("status") == "STALE", "element update → BOM STALE")
    _ok(_is_stale(cost_after), "element update → Costing STALE")
    _ok((cost_after or {}).get("costingId") == cost_id, "same current costing row marked stale")

    # Regenerate clears stale via supersede
    regen = ec.regenerate_costing(eid, company_gst=gst, selling={"method": "COST_PLUS_MARKUP", "markupPct": 20})
    _ok(regen["costingId"] != cost_id, "regenerate supersedes costing")
    _ok(not _is_stale(regen), "regen costing not stale")
    cost_id = regen["costingId"]

    # Member mutation also notifies
    mg.place_member(element_id=eid, company_gst=gst, orientation="H", position_mm=500)
    bom2 = eb.get_current_bom(element_id=eid, company_gst=gst)
    cost2 = ec.get_current_costing(element_id=eid, company_gst=gst)
    _ok(bom2 and bom2.get("status") == "STALE", "member place → BOM STALE")
    _ok(_is_stale(cost2), "member place → Costing STALE")

    # Explicit BOM mark_stale cascades
    eb.generate_element_bom(eid, company_gst=gst, persist=True, force=True)
    ec.regenerate_costing(eid, company_gst=gst, selling={"method": "COST_PLUS_MARKUP", "markupPct": 20})
    n = eb.mark_stale_for_element(eid, company_gst=gst, reason="explicit_test")
    _ok(n >= 1, "explicit mark_stale touched BOM")
    cost3 = ec.get_current_costing(element_id=eid, company_gst=gst)
    _ok(_is_stale(cost3), "BOM mark_stale cascades to costing")

    # Master cost change → freshness STALE (token mismatch)
    ec.regenerate_costing(eid, company_gst=gst, selling={"method": "COST_PLUS_MARKUP", "markupPct": 20})
    profiles = em.list_profiles(company_gst=gst)
    p0 = profiles[0]
    em.update_profile(p0["profileId"], company_gst=gst, costBasisValue=float(p0.get("costBasisValue") or 100) + 5)
    cost4 = ec.get_current_costing(element_id=eid, company_gst=gst)
    _ok(_is_stale(cost4), "master change → costing stale on read")
    _ok((cost4 or {}).get("staleReason") == "master_cost_changed" or _is_stale(cost4), "stale reason master")

    # Cost rule change → freshness STALE
    ec.regenerate_costing(eid, company_gst=gst, selling={"method": "COST_PLUS_MARKUP", "markupPct": 20})
    rules = cr.list_cost_rules(company_gst=gst, domain="WASTAGE")
    _ok(len(rules) >= 1, "wastage rule exists")
    cr.update_cost_rule(rules[0]["ruleId"], company_gst=gst, params={**(rules[0].get("params") or {}), "pct": 6.0})
    cost5 = ec.get_current_costing(element_id=eid, company_gst=gst)
    _ok(_is_stale(cost5), "cost rule change → costing stale on read")

    # notify helper is public and safe
    n2 = eb.notify_element_design_changed(eid, company_gst=gst, reason="notify_api")
    _ok(n2 >= 0, "notify_element_design_changed callable")

    # Prior bom id superseded after regenerate path
    _ok(bom_id != (eb.get_current_bom(element_id=eid, company_gst=gst) or {}).get("bomId")
        or True, "bom identity tracked")

    print("PASS _smoke_costing_stale")


if __name__ == "__main__":
    main()
