"""Slash quote numbers in QR URLs must load the commercial quote, not 404 empty."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_scan_slash_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    fails: list[str] = []
    html = (Path(__file__).resolve().parents[1] / "WEOS" / "website" / "index.html").read_text(encoding="utf-8")
    for needle in (
        "ledger-entry",
        "btnCpApproveQuote",
        "approveQuote",
        "preview-roomy",
        "syncPreviewRoomy",
    ):
        if needle not in html:
            fails.append("index missing " + needle)
    if 'id="cpLedgerEntry"' not in html:
        fails.append("ledger form id missing")
    form = html.split('id="cpLedgerEntry"', 1)[-1].split("</div>\n          <p class=\"muted\"", 1)[0]
    if "width:110px" in form or "width:140px" in form:
        fails.append("ledger fields still use fixed widths that collide")
    if "ledger-entry" not in html.split("cpLedgerEntry", 1)[0][-400:]:
        fails.append("ledger form is not on the grid layout")

    from fastapi.testclient import TestClient

    from WEOS.api.server import app
    from WEOS.factory.project_store import load_project, save_project
    from WEOS.factory.quote_share import clean_public_ref, resolve_public_ref

    if clean_public_ref("AK-26%2F00026%2FA1") != "AK-26/00026/A1":
        fails.append("clean_public_ref did not decode %2F")

    doc = {
        "projectId": "PRJ-SCANFIX",
        "quotationId": "AK-26/00026/A1",
        "customer": "INDIVISUM ARCHITECTS",
        "name": "WEOS Project",
        "status": "draft",
        "shareToken": "tokscanfix",
        "version": 2,
        "lines": [
            {
                "lineId": "l1",
                "product": "casement_window",
                "displayName": "Casement Window",
                "productType": "casement",
                "width": 1336,
                "height": 1031,
                "qty": 1,
                "locationName": "W01",
                "sellingRate": 1049.33,
                "saleUnit": "sqft",
                "commercialTotal": 15000,
            }
        ],
    }
    save_project(doc, bump_version=False)
    loaded = resolve_public_ref("AK-26/00026/A1")
    if not loaded or loaded.get("customer") != "INDIVISUM ARCHITECTS":
        fails.append("resolve_public_ref missed slash quote number")
    if not (loaded or {}).get("lines"):
        fails.append("resolved quote has no lines")

    client = TestClient(app)
    page = client.get("/q/AK-26/00026/A1")
    body = page.text or ""
    if page.status_code != 200:
        fails.append(f"slash HTML status {page.status_code}: {body[:240]}")
    elif "INDIVISUM ARCHITECTS" not in body or "W01" not in body:
        fails.append("slash scan HTML missing customer or line")
    if "Not Found" == (page.json().get("detail") if page.headers.get("content-type", "").startswith("application/json") else ""):
        fails.append("slash URL still missed the route")

    api = client.get("/api/public/quote/AK-26/00026/A1")
    if api.status_code != 200:
        fails.append(f"slash JSON status {api.status_code}: {api.text[:240]}")
    else:
        payload = api.json()
        products = payload.get("products") or []
        if payload.get("customer", {}).get("name") != "INDIVISUM ARCHITECTS":
            fails.append("slash JSON customer empty")
        if not products:
            fails.append("slash JSON products empty")
        elif "W01" not in str(products[0].get("location") or "") and "W1" not in str(products[0].get("serial") or ""):
            fails.append(f"slash JSON product not the quote line: {products[0]}")

    token_page = client.get("/q/tokscanfix")
    if token_page.status_code != 200 or "INDIVISUM ARCHITECTS" not in (token_page.text or ""):
        fails.append("share-token scan page failed")

    missing = client.get("/api/public/quote/tokscanfix/pack/files/no-such-file")
    if missing.status_code == 200 and "products" in (missing.text or ""):
        fails.append("path route stole the pack file download")

    live = load_project("PRJ-SCANFIX")
    approved = client.post("/api/projects/PRJ-SCANFIX/approve", json={"quoteVersion": 1, "note": "Approved AK-26/00026/A1 v1"})
    if approved.status_code != 200:
        fails.append(f"approve status {approved.status_code}: {approved.text[:240]}")
    else:
        live = load_project("PRJ-SCANFIX")
        if str(live.get("status") or "").lower() != "approved":
            fails.append("approve did not set status")
        if int(live.get("approvedVersion") or 0) != 1:
            fails.append(f"approvedVersion not stored: {live.get('approvedVersion')}")

    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
        return 1
    print("OK public quote slash scan + approve version")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
