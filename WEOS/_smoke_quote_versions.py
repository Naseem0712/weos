"""Empty cart projects recover version lines; approve, ledger, and diff flags."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_quote_ver_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _line(product: str, loc: str, amount: float, **extra):
    row = {
        "lineId": extra.pop("lineId", product + loc),
        "product": product,
        "productType": "casements",
        "locationName": loc,
        "width": extra.pop("width", 1200),
        "height": extra.pop("height", 1400),
        "qty": extra.pop("qty", 1),
        "amount": amount,
    }
    row.update(extra)
    return row


def main() -> int:
    fails: list[str] = []
    html = (Path(__file__).resolve().parents[1] / "WEOS" / "website" / "index.html").read_text(encoding="utf-8")
    for needle in ("btnMlApprove", 'id="mlAdvEntry"', "changeFlag", "saveProject(true)"):
        if needle not in html:
            fails.append("index missing " + needle)
    form = html.split('id="mlAdvEntry"', 1)[-1].split("</div>", 1)[0]
    if "width:110px" in form or "width:140px" in form:
        fails.append("master ledger advance fields still use fixed widths")

    from WEOS.factory.master_ledger import build_master_ledger
    from WEOS.factory.project_store import load_project, save_project
    from WEOS.factory.quote_share import build_public_quote_record

    doc = {
        "projectId": "PRJ-VER-1",
        "name": "30NF Arch. Dhiraj Reddy ji",
        "customer": "INDIVISUM ARCHITECTS",
        "customerMobile": "918050967162",
        "quotationId": "AK-26/00025/A1",
        "status": "draft",
        "lines": [
            _line("casement", "W01", 10000),
            _line("sliding", "W02", 20000),
        ],
    }
    save_project(doc, action="create")
    doc["lines"] = [
        _line("casement", "W01", 10000),
        _line("fold", "F01", 451792),
    ]
    saved = save_project(doc, action="update")
    loaded = load_project("PRJ-VER-1")
    flags = {ln.get("locationName"): ln.get("changeFlag") for ln in loaded.get("lines") or []}
    if flags.get("F01") != "added":
        fails.append(f"added flag missing: {flags}")
    if flags.get("W02") == "added":
        fails.append("unchanged-removed line still on cart as added")
    removed_locs = [ln.get("locationName") for ln in loaded.get("removedLines") or []]
    if "W02" not in removed_locs:
        fails.append(f"removed flag missing: {removed_locs}")
    if int(saved.get("version") or 0) < 2:
        fails.append("version did not advance on correction")

    approved = save_project  # keep lint quiet
    from WEOS.factory.project_store import set_project_status

    approved = set_project_status("PRJ-VER-1", "approved", note="Approved version", approved_version=int(loaded.get("version") or 2))
    if str(approved.get("status")) != "approved":
        fails.append("approve did not stick")
    if not approved.get("approvedVersion"):
        fails.append("approvedVersion missing")

    # Wipe lines the way a bad save did. Undo / quoteVersions must bring them back.
    wiped = load_project("PRJ-VER-1")
    wiped["lines"] = []
    save_project(wiped, bump_version=True, action="wipe")
    recovered = load_project("PRJ-VER-1")
    if not recovered.get("lines"):
        fails.append("empty project did not recover version lines")
    led = build_master_ledger(project_id="PRJ-VER-1")
    ledger = led.get("ledger") or {}
    if not ledger.get("quoteCount"):
        fails.append("ledger still shows 0 quotes")
    totals = ledger.get("totals") or {}
    if float(totals.get("projectValue") or 0) <= 0:
        fails.append(f"ledger value still zero: {totals}")
    statuses = [str(p.get("status") or "") for p in ledger.get("projects") or []]
    if "approved" not in statuses:
        fails.append(f"ledger project not approved: {statuses}")

    shell = {
        "projectId": "PRJ-VER-EMPTY",
        "name": "draft shell",
        "customer": "INDIVISUM ARCHITECTS",
        "quotationId": "AK-26/00099/A1",
        "status": "draft",
        "lines": [],
    }
    save_project(shell, action="create")
    shell_led = build_master_ledger(project_id="PRJ-VER-EMPTY")
    shell_quotes = (shell_led.get("ledger") or {}).get("quotes") or []
    if not shell_quotes:
        fails.append("quotation id with no lines is hidden from the ledger")

    pub = build_public_quote_record("AK-26/00025/A1")
    products = (pub or {}).get("products") or []
    locs = [p.get("location") for p in products]
    if "F01" not in locs and "W01" not in locs:
        fails.append(f"scanner missing recovered products: {locs}")
    if not (pub or {}).get("approved"):
        fails.append("scanner did not show approved")

    if fails:
        print("FAIL")
        for row in fails:
            print(" -", row)
        return 1
    print("OK quote versions recover, approve, ledger, flags")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
