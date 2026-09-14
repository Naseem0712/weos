"""Smoke: Canvas Batch G — design card management (SQL reconstruct / edit / delete)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_cards_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
os.environ["WEOS_UNIVERSAL_CANVAS"] = "1"

ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / "WEOS" / "website" / "canvas"


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
    gst = "22FFFFF0000F1Z5"
    cust = create_customer(gst, display_name="Card Cust", mobile="9000666777")
    proj = upsert_project(
        project_id="PRJ-2026-CARDS",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Cards Job",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Cards Job", customer="Card Cust")
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
        width_mm=1200,
        height_mm=1000,
        legacy_line_id="card_line1",
        display_code="W-01",
    )
    eid = el["elementId"]
    placed = mg.place_member(element_id=eid, company_gst=gst, orientation="H", position_mm=300)
    leaves = [c for c in placed["topology"]["cells"] if c.get("isLeaf")]
    top = min(leaves, key=lambda c: c["yMm"])
    bot = max(leaves, key=lambda c: c["yMm"])
    ca.assign_product(cell_id=top["cellId"], company_gst=gst, product_type="FIXED")
    ca.assign_product(cell_id=bot["cellId"], company_gst=gst, product_type="SLIDING")
    pre = ca.pdf_preflight_composite(eid, company_gst=gst)

    doc = load_project(pid)
    doc["lines"] = [
        {
            "lineId": "card_line1",
            "product": "sliding_stub",
            "productType": "SLIDING_WINDOW",
            "displayName": "Combination Window",
            "width": 1200,
            "height": 1000,
            "qty": 2,
            "sellingRate": 1850,
            "saleUnit": "sqft",
            "mark": "W-01",
            "locationName": "Floor 1",
            "positionName": "Bedroom",
            "elementId": eid,
            "assemblyId": asm["assemblyId"],
            "compositionSummary": pre.get("compositionSummary"),
            "preview": {"svg": pre.get("svg") or "", "key": "c1"},
        }
    ]
    save_project(doc, action="attach")

    # Reconstruct cards from SQL/FS
    ws = qw.build_quote_workspace(load_project(pid))
    _ok(len(ws["cards"]) == 1, "one card")
    card = ws["cards"][0]
    _ok(card["lineId"] == "card_line1", "stable id")
    _ok(card["mark"] == "W-01", "mark")
    _ok("Fixed" in (card.get("composition") or "") or "FIXED" in (card.get("composition") or "").upper()
        or "C-" in (card.get("composition") or ""), f"composition={card.get('composition')}")
    _ok(card["amount"] > 0, "amount")
    _ok(card.get("hasDurablePreview") or bool(card.get("previewSvg")), "preview")

    # UI surface files present
    cards_js = (CANVAS / "design_cards.js").read_text(encoding="utf-8")
    dup_js = (CANVAS / "design_duplicate.js").read_text(encoding="utf-8")
    _ok("data-qw-del" in cards_js, "delete action on card")
    _ok("data-qw-tpl" in cards_js, "template action on card")
    _ok("KEEP_OFFSETS" in dup_js and "SCALE" in dup_js, "size rule UI")
    _ok("idempotencyKey" in dup_js, "idempotency in UI")
    _ok("qwFilterFloor" in cards_js, "floor filter")

    # Duplicate flow creates second card
    result = qw.duplicate_design_rows(
        load_project(pid),
        source_line_id="card_line1",
        rows=[{"width": 1200, "height": 1000, "qty": 1, "mark": "W-02", "sellingRate": 1850}],
        company_gst=gst,
    )
    saved = save_project(result["doc"], action="dup")
    ws2 = qw.build_quote_workspace(saved)
    _ok(len(ws2["cards"]) == 2, "two cards after dup")

    # Edit same design = same line id (no new QuoteItem)
    edit_line = next(ln for ln in saved["lines"] if ln["lineId"] == "card_line1")
    edit_line["width"] = 1250
    saved["lines"] = [
        edit_line if ln["lineId"] == "card_line1" else ln for ln in saved["lines"]
    ]
    saved2 = save_project(saved, action="edit_same")
    lids = [ln["lineId"] for ln in saved2["lines"]]
    _ok(lids.count("card_line1") == 1, "edit keeps same line id")
    _ok(len(lids) == 2, "no extra quote item on edit")

    # Delete targets correct design
    deleted = qw.delete_design_line(saved2, line_id=result["createdLineIds"][0], company_gst=gst)
    saved3 = save_project(deleted["doc"], action="delete")
    _ok(len(saved3["lines"]) == 1, "one line after delete")
    _ok(saved3["lines"][0]["lineId"] == "card_line1", "source remains")
    _ok(deleted.get("retired") is not None, "SQL retired")

    # Canvas size independence noted in UI copy
    _ok("independent of card count" in cards_js.lower() or "CANVAS-G" in cards_js, "canvas independence copy")

    print("PASS: _smoke_design_card_management")


if __name__ == "__main__":
    main()
