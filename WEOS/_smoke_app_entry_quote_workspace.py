"""Smoke: Canvas D2 — App entry + Engineering / Quote Review separation."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_app_entry_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
os.environ.pop("WEOS_UNIVERSAL_CANVAS", None)

ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / "WEOS" / "website" / "canvas"
INDEX = ROOT / "WEOS" / "website" / "index.html"
FACTORY = ROOT / "WEOS" / "factory"


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))

    from WEOS.factory import quote_workspace as qw
    from WEOS.factory import canvas_activation as ca
    from fastapi.testclient import TestClient
    from WEOS.api.server import app

    index = INDEX.read_text(encoding="utf-8")
    ws_js = (CANVAS / "workspace.js").read_text(encoding="utf-8")
    qw_js = (CANVAS / "quote_workspace.js").read_text(encoding="utf-8")
    ws_css = (CANVAS / "workspace.css").read_text(encoding="utf-8")

    # A: UC still default ON (D1 preserved)
    _ok(ca.is_universal_canvas_enabled() is True, "A: UC default ON")

    # B: app entry plan — login required
    plan0 = qw.app_entry_plan(logged_in=False)
    _ok(plan0["action"] == "login" and plan0["createQuote"] is False, "B: login gate, no silent create")

    # C: no draft → new quote setup (no create flag)
    plan1 = qw.app_entry_plan(logged_in=True, active_draft=None)
    _ok(plan1["action"] == "new_quote_setup" and plan1["createQuote"] is False, "C: new quote setup without create")

    # D: draft restore plan
    plan2 = qw.app_entry_plan(
        logged_in=True,
        active_draft={"projectId": "PRJ-2026-0001", "quotationId": "Q-1", "name": "Demo", "customer": "Ada"},
    )
    _ok(plan2["action"] == "restore_draft" and plan2["projectId"] == "PRJ-2026-0001", "D: restore draft plan")
    _ok(plan2["createQuote"] is False, "D: restore does not create")

    # E: API app-entry route exists
    client = TestClient(app)
    r = client.get("/api/quote-workspace/app-entry")
    _ok(r.status_code in (200, 401, 403), f"E: app-entry responds ({r.status_code})")
    if r.status_code == 200:
        body = r.json()
        _ok(body.get("batch") == "CANVAS-D2", "E: batch tag")
        _ok(body.get("createQuote") is False, "E: no silent create on API")

    # F: frontend modules wired
    _ok("quote_workspace.js" in index and "design_cards.js" in index, "F: scripts linked")
    _ok("runAppEntry" in qw_js and "showQuoteReview" in qw_js, "F: app entry + quote review APIs")
    _ok("qwTopBar" in qw_js and "btnQwBarReview" in qw_js, "F: compact top bar")

    # G: engineering without quote list overlay
    _ok("qw-engineering" in ws_js or "qw-engineering" in ws_css, "G: engineering class")
    _ok("uc-show-quote" in ws_css and "display: none" in ws_css, "G: quote overlay suppressed in D2 CSS")
    _ok("Quote Review" in ws_js and "btnUcQuoteLines" in ws_js, "G: Quote Review control")
    _ok("uc-show-quote" not in ws_js.split("quoteBtn.onclick")[1][:180] if "quoteBtn.onclick" in ws_js else True, "G: quoteBtn does not toggle overlay")

    # H: neutral naming
    _ok("Continue to Engineering" in index, "H: Continue to Engineering")
    _ok("Window Cart stays product-only" not in index, "H: Window Cart setup copy removed")

    # I: Quote Setup before products
    _ok("btnSetupToCart" in index and "saveProject(true)" in index, "I: setup continues with durable save")
    _ok("Quote Setup" in index or "quote setup" in qw_js.lower(), "I: quote setup language")

    # J: modes separated
    _ok("view-quote-review" in qw_js and "view-quote-home" in qw_js, "J: dedicated views")
    _ok("quote-review" in index and "showQuoteReview" in index, "J: setView routes quote-review")

    # K: compact props / canvas largest
    _ok("minmax(240px, 280px)" in ws_css or "minmax(220px, 260px)" in ws_css, "K: compact props band")
    _ok("qw-compact-props" in ws_css or "qw-compact-props" in ws_js, "K: compact props class")

    # L: Add to Quote after server confirm
    _ok("btnUcAddToQuote" in ws_js and "saveProject" in ws_js, "L: Add to Quote uses save")

    # M: no FrameMember / Batch E leakage
    _ok("FrameMember" not in qw_js, "M: no member engine in D2")

    print("PASS: _smoke_app_entry_quote_workspace.py")


if __name__ == "__main__":
    main()
