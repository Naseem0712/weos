"""Smoke: Window engineering BOM — piece cuts, weight, glass, hardware, stale."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_win_bom_"))
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
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory import design_scene as ds
    from WEOS.factory import engineering_bom as eb
    from WEOS.factory import engineering_masters as em
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.project_store import empty_project, save_project

    init_db()
    gst = "22BBBBB0000B1Z5"
    em.seed_default_window_masters(company_gst=gst)

    cust = create_customer(gst, display_name="BOM Cust", mobile="9000111222")
    proj = upsert_project(
        project_id="PRJ-2026-BOM1",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="BOM Window",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="BOM Window", customer="BOM Cust")
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
        display_code="W-BOM",
        config_payload={"seriesId": series["seriesId"], "seriesCode": "29mm_sliding", "shutterCount": 2},
    )
    eid = el["elementId"]

    bom = eb.generate_element_bom(eid, company_gst=gst, persist=True, force=True)
    _ok(bom["bomId"].startswith("EBOM-"), "bom id")
    _ok(bom.get("usesQuoteSellingRate") is False, "no quote selling rate")
    _ok(bom.get("editableSource") is False, "derived not editable source")
    _ok(bom.get("generatorVersion") == eb.GENERATOR_VERSION, "generator version")
    _ok(bom.get("masterRevisionToken"), "master rev token")
    _ok(bom.get("status") in ("READY", "PARTIAL"), f"status {bom.get('status')}")

    lines = bom.get("lines") or []
    _ok(len(lines) >= 4, "has piece lines")
    outer = [ln for ln in lines if ln.get("meta", {}).get("outerFrame")]
    _ok(len(outer) == 4, "outer frame 4 pieces once")
    # weight = length_m × weight_per_rmt
    sample = next(ln for ln in outer if ln.get("profileRole") == "OUTER_FRAME_VERTICAL")
    _ok(sample.get("requiredLengthMm") == 1400, "required length = height")
    _ok(sample.get("stockConsumptionMm") is not None, "stock consumption distinct")
    _ok(sample.get("weightKg") is not None and sample["weightKg"] > 0, "weight calculated")
    expected_wt = (1400 / 1000.0) * float(sample["weightPerRmt"])
    _ok(abs(sample["weightKg"] - expected_wt) < 1e-6, "weight = length_m * weight_per_rmt")

    glass = [ln for ln in lines if ln.get("category") == "GLASS"]
    _ok(len(glass) >= 1, "glass BOM present")
    g0 = glass[0]
    _ok(g0.get("widthMm") and g0.get("heightMm"), "glass W×H")
    _ok(g0.get("areaSqm") is not None, "glass area")
    _ok(g0.get("deductionMode") == "NOMINAL", "NOMINAL glass deductions")

    hw = [ln for ln in lines if ln.get("category") == "HARDWARE"]
    _ok(len(hw) >= 1, "hardware from rules")

    # Stale + regenerate (before mutating masters)
    cur = eb.get_current_bom(element_id=eid, company_gst=gst)
    _ok(cur is not None, "current bom exists")
    _ok(cur.get("status") in ("READY", "PARTIAL"), f"current status {cur.get('status')}")
    _ok(cur.get("freshness") in ("CURRENT", "READY", "PARTIAL") or cur.get("isCurrent") is True, "freshness current")
    n = eb.mark_stale_for_element(eid, company_gst=gst, reason="test_design_change")
    _ok(n >= 1, "marked stale")
    stale = eb.get_current_bom(element_id=eid, company_gst=gst)
    _ok(stale and stale.get("status") == "STALE", "status STALE")
    regen = eb.regenerate_bom(eid, company_gst=gst)
    _ok(regen["bomId"] != (stale or {}).get("bomId"), "regenerate supersedes")
    _ok(regen.get("status") in ("READY", "PARTIAL"), "regenerated fresh")
    _ok(regen.get("isCurrent") is True, "new bom current")

    # Missing mapping → explicit issue path
    bad = em.create_series(code="orphan_series", name="Orphan", company_gst=gst, family="WINDOW")
    el2 = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="FIXED_WINDOW",
        width_mm=800,
        height_mm=900,
        display_code="W-MISS",
        config_payload={"seriesId": bad["seriesId"]},
    )
    bom2 = eb.generate_element_bom(el2["elementId"], company_gst=gst, persist=True, force=True)
    _ok(bom2["status"] in ("PARTIAL", "ERROR"), "missing mapping → PARTIAL/ERROR")
    _ok(any(i.get("code") == "MISSING_PROFILE_MAPPING" for i in (bom2.get("issues") or [])), "explicit missing mapping issue")

    # Master change makes prior BOM stale
    after = eb.get_current_bom(element_id=eid, company_gst=gst)
    _ok(after is not None, "eid bom still retrievable")
    if after.get("masterRevisionToken") != em.master_revision_token(gst):
        _ok(after.get("status") == "STALE" or after.get("freshness") == "STALE", "master change → stale")

    print("PASS: window bom")


if __name__ == "__main__":
    main()
