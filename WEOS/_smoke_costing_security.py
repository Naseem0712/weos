"""Smoke: public surfaces never expose engineering cost internals; tenant guards."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_cost_sec_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
os.environ["WEOS_UNIVERSAL_CANVAS"] = "1"

ROOT = Path(__file__).resolve().parents[1]

_FORBIDDEN = (
    "totalCost",
    "categoryTotals",
    "grossProfit",
    "grossMarginPct",
    "markupPct",
    "targetMarginPct",
    "unitCost",
    "extendedCost",
    "costBasisValue",
    "originalUnitCost",
    "overrideUnitCost",
    "purchaseRate",
    "effectiveMarkupPct",
)


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def _assert_no_internal(obj: object, path: str = "root") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k)
            if kl in _FORBIDDEN:
                raise SystemExit(f"FAIL: forbidden key {kl} at {path}")
            if "markup" in kl.lower() or "profit" in kl.lower():
                if kl not in ("costingId",):
                    raise SystemExit(f"FAIL: forbidden-ish key {kl} at {path}")
            if "cost" in kl.lower() and kl not in ("costingId",):
                raise SystemExit(f"FAIL: cost key {kl} at {path}")
            _assert_no_internal(v, f"{path}.{kl}")
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            _assert_no_internal(x, f"{path}[{i}]")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))

    from WEOS.db.engine import init_db
    from WEOS.factory import cost_rules as cr
    from WEOS.factory import customer_line_view as clv
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory import design_scene as ds
    from WEOS.factory import engineering_bom as eb
    from WEOS.factory import engineering_costing as ec
    from WEOS.factory import engineering_masters as em
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.project_store import empty_project, load_project, save_project
    from WEOS.factory.quote_share import build_public_quote_record, ensure_project_share_token

    init_db()
    gst = "22SECUR0000S1Z5"
    em.seed_default_window_masters(company_gst=gst)
    cr.seed_safe_sample_cost_rules(company_gst=gst)

    cust = create_customer(gst, display_name="Sec Cust", mobile="9000888999")
    proj = upsert_project(
        project_id="PRJ-2026-CSEC",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Security Cost",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Security Cost", customer="Sec Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerId"] = cust["customerId"]
    doc["lines"] = [
        {
            "id": "L1",
            "type": "sliding",
            "width": 1200,
            "height": 1400,
            "qty": 1,
            "sellingRate": 450,
            "amount": 6750,
            "location": "Hall",
        }
    ]
    save_project(doc, bump_version=False, action="smoke")
    doc = load_project(pid) or doc
    share = ensure_project_share_token(doc, persist=True)
    _ok(bool(share), "share token obtained")

    des = dh.ensure_design_document(pid, company_gst=gst)
    asm = ds.create_assembly(design_document_id=des["designDocumentId"], company_gst=gst)
    series = em.resolve_series_ref("29mm_sliding", company_gst=gst)
    el = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1200,
        height_mm=1400,
        display_code="W-SEC",
        config_payload={"seriesId": series["seriesId"], "seriesCode": "29mm_sliding"},
    )
    eid = el["elementId"]
    eb.generate_element_bom(eid, company_gst=gst, persist=True, force=True)
    costing = ec.generate_element_costing(
        eid,
        company_gst=gst,
        persist=True,
        force=True,
        selling={"method": "COST_PLUS_MARKUP", "markupPct": 25, "commercialUnit": "SFT"},
    )
    _ok(costing.get("totalCost", 0) > 0, "internal costing has totalCost")
    _ok(costing.get("usesQuoteSellingRateAsCost") is False, "quote sellingRate not used as cost")

    # Public commercial view
    pub = ec.public_commercial_view(costing)
    _assert_no_internal(pub)
    _ok("sellingSubtotal" in pub, "public has commercial selling")
    _ok(pub.get("batch") == "ENG-COST-PUBLIC", "public batch tag")

    stripped = ec.strip_internal_cost_fields(costing)
    _assert_no_internal(stripped)

    # customer_line_view — selling only, no engineering cost
    amt = clv.customer_line_amount(doc["lines"][0])
    _ok(amt is None or isinstance(amt, (int, float)), "customer line amount")
    row = clv.public_product_row(1, doc["lines"][0])
    _assert_no_internal(row)
    _ok(True, "customer_line_view public_product_row clean")
    src = Path(clv.__file__).read_text(encoding="utf-8")
    _ok("totalCost" not in src and "grossProfit" not in src, "customer_line_view source has no cost internals")

    # Public quote record (/q /scan /api/public/quote)
    rec = build_public_quote_record(share)
    _ok(rec is not None, "public quote record builds")
    _assert_no_internal(rec)
    blob = str(rec).lower().replace(" ", "")
    _ok("grossprofit" not in blob, "public quote string has no grossProfit")
    _ok("markuppct" not in blob, "public quote string has no markupPct")
    _ok("costbasis" not in blob, "public quote string has no costBasis")
    _ok("totalcost" not in blob, "public quote string has no totalCost")

    # Cross-tenant: wrong gst cannot read costing
    other = ec.get_current_costing(element_id=eid, company_gst="22OTHER0000O1Z5")
    _ok(other is None, "wrong gst cannot read costing")

    # Rollup is internalOnly (API gates with require_owned_project)
    roll = ec.rollup_project_costing(project_id=pid, company_gst=gst)
    _ok(roll.get("internalOnly") is True, "project rollup marked internalOnly")
    _ok("totalCost" in roll, "internal rollup includes cost (auth-gated at API)")

    # Alias surface exists
    _ok(callable(ec.calculate_bom_line_cost), "calculate_bom_line_cost alias")
    _ok(callable(ec.resolve_cost_rules), "resolve_cost_rules alias")
    _ok(callable(ec.calculate_selling_price), "calculate_selling_price alias")

    print("PASS _smoke_costing_security")


if __name__ == "__main__":
    main()
