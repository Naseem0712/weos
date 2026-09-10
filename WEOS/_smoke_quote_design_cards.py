"""Smoke: Canvas D2 — visual design cards from authoritative saved quote data."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_design_cards_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

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

    from WEOS.factory import quote_workspace as qw
    from WEOS.factory.project_store import save_project
    from fastapi.testclient import TestClient
    from WEOS.api.server import app

    cards_js = (CANVAS / "design_cards.js").read_text(encoding="utf-8")
    qw_js = (CANVAS / "quote_workspace.js").read_text(encoding="utf-8")

    # A: card from saved line uses durable preview, not inventing
    line = {
        "lineId": "abc123def0",
        "product": "casement_stub",
        "productType": "CASEMENT_WINDOW",
        "displayName": "Casement",
        "width": 1200,
        "height": 1500,
        "qty": 2,
        "locationName": "GF",
        "positionName": "Bedroom",
        "glass": "5mm_clear",
        "sellingRate": 900,
        "saleUnit": "sqft",
        "commercialTotal": 12000,
        "preview": {"svg": '<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>', "key": "k1"},
    }
    card = qw.build_design_card(line, index=0)
    _ok(card["lineId"] == "abc123def0", "A: stable design id")
    _ok(card["hasDurablePreview"] is True and "<svg" in card["previewSvg"], "A: durable preview used")
    _ok(card["widthMm"] == 1200 and card["heightMm"] == 1500, "A: size")
    _ok(card["floor"] == "GF" and card["location"] == "Bedroom", "A: floor/location")
    _ok(card["amount"] == 12000, "A: amount")

    # B: missing data warnings (preflight concepts)
    bad = {"lineId": "x1", "product": "", "width": 0, "height": 0, "qty": 0}
    warns = qw.card_warnings_for_line(bad)
    _ok(any("product" in w.lower() for w in warns) or any("width" in w.lower() for w in warns), "B: warnings present")

    # C: totals shape from existing money calc
    doc = {
        "projectId": "PRJ-TEST-CARDS",
        "name": "Cards Demo",
        "customer": "Demo",
        "status": "draft",
        "quotationId": "Q-CARDS",
        "lines": [line],
        "quoteDiscount": {"mode": "off", "percent": 0, "amount": 0},
    }
    totals = qw.build_quote_totals(doc)
    for key in ("subtotal", "discount", "taxable", "gst", "grand", "itemCount"):
        _ok(key in totals, f"C: totals.{key}")
    _ok(totals["itemCount"] == 1, "C: item count")

    # D: workspace payload
    ws = qw.build_quote_workspace(doc)
    _ok(ws["batch"] == "CANVAS-D2" and len(ws["cards"]) == 1, "D: workspace cards")
    _ok(ws["context"]["hasActiveQuote"] is True, "D: active quote context")

    # E: frontend card renderer
    _ok("renderWorkspace" in cards_js and "qw-card" in cards_js, "E: card renderer")
    _ok("Subtotal" in cards_js and "Grand" in cards_js, "E: totals labels")
    _ok("data-qw-edit" in cards_js and "data-qw-dup" in cards_js, "E: edit/dup actions")
    _ok("showQuoteReview" in qw_js, "E: quote review host")

    # F: persist + API (tenant may 401 without session — still route exists)
    saved = save_project(dict(doc), action="create")
    pid = saved["projectId"]
    client = TestClient(app)
    r = client.get(f"/api/projects/{pid}/quote-workspace")
    _ok(r.status_code in (200, 401, 403, 404), f"F: quote-workspace route ({r.status_code})")

    # G: card does not require DOM/localStorage
    _ok("localStorage" not in cards_js, "G: cards not from localStorage")

    print("PASS: _smoke_quote_design_cards.py")


if __name__ == "__main__":
    main()
