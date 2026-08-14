"""Smoke: GST session reopen, hub dashboard KPIs, mobile search, ledger PDF sections."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_gst_hub_smoke_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)


def main() -> int:
    fails: list[str] = []
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from WEOS.db.engine import init_db
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.customer_store import find_customers, save_customer_profile
    from WEOS.factory.ledger_pdf import render_ledger_pdf
    from WEOS.factory.ledger_store import add_advance, build_ledger
    from WEOS.factory.project_store import empty_project, save_project, set_project_status

    res = init_db()
    if not res.get("ok"):
        fails.append(f"init_db failed: {res}")
        _report(fails)
        return 1

    gst = "27BBBBB0000B1Z5"
    mobile = "9876501234"
    cust = "Hub Persist Customer"

    # ── 1) Open workspace + persist-style reopen (refresh restore API analog) ─
    ws1 = open_workspace(gst, profile={"companyName": "Hub Persist Co", "phone": "9111100000"})
    if not ws1.get("ok") or ws1.get("gstNo") != gst:
        fails.append("workspace open failed")

    save_customer_profile(cust, {"name": cust, "phone": mobile, "companyGst": gst})
    p = empty_project(name="Running Quote", customer=cust)
    p["companyGst"] = gst
    p["customerMobile"] = mobile
    p["quotationId"] = "QT-HUB-1"
    p["lastCalculation"] = {"price": {"total": 200000.0}}
    p = save_project(p, action="smoke")
    add_advance(
        cust,
        {
            "amount": 50000,
            "paymentMode": "upi",
            "reference": "HUB-UTR",
            "projectId": p["projectId"],
            "quoteId": "QT-HUB-1",
            "quoteVersion": int(p.get("version") or 1),
        },
    )

    # Draft (even with value) must not inflate year turnover.
    draft = empty_project(name="Test Draft Quote", customer=cust)
    draft["companyGst"] = gst
    draft["quotationId"] = "QT-HUB-DRAFT"
    draft["lastCalculation"] = {"price": {"total": 999999.0}}
    draft = save_project(draft, action="smoke")

    ws_draft = open_workspace(gst, create=True)
    dash_draft = ws_draft.get("dashboard") or {}
    if abs(float(dash_draft.get("yearTaxable") or 0)) > 0.01:
        fails.append(f"draft quotes must not count toward yearTaxable got {dash_draft.get('yearTaxable')}")

    set_project_status(p["projectId"], "approved")

    # Re-open as if page refreshed with saved GSTIN.
    ws2 = open_workspace(gst, create=True)
    if ws2.get("created"):
        fails.append("reopen incorrectly marked created")
    names = [c.get("name") for c in ws2.get("customers") or []]
    if cust not in names:
        fails.append(f"refresh restore missing customer: {names}")
    pids = [x.get("projectId") for x in ws2.get("projects") or []]
    if p["projectId"] not in pids:
        fails.append("refresh restore missing project list")

    # ── 2) Dashboard aggregates ────────────────────────────────────────────
    dash = ws2.get("dashboard") or {}
    if int(dash.get("projectsRunning") or 0) < 1:
        fails.append(f"projectsRunning expected >=1 got {dash.get('projectsRunning')}")
    if abs(float(dash.get("totalAdvances") or 0) - 50000) > 0.01:
        fails.append(f"totalAdvances expected 50000 got {dash.get('totalAdvances')}")
    if abs(float(dash.get("balanceOutstanding") or 0) - 150000) > 0.01:
        fails.append(f"balanceOutstanding expected 150000 got {dash.get('balanceOutstanding')}")
    if abs(float(dash.get("yearValueGenerated") or 0) - 200000) > 0.01:
        fails.append(f"yearValueGenerated expected 200000 got {dash.get('yearValueGenerated')}")
    if abs(float(dash.get("yearTaxable") or 0) - 200000) > 0.01:
        fails.append(f"yearTaxable expected 200000 got {dash.get('yearTaxable')}")
    if abs(float(dash.get("yearGrand") or 0) - 236000) > 0.01:
        fails.append(f"yearGrand expected 236000 got {dash.get('yearGrand')}")
    if abs(float(dash.get("totalTaxable") or 0) - 200000) > 0.01:
        fails.append(f"totalTaxable expected 200000 got {dash.get('totalTaxable')}")
    if abs(float(dash.get("totalGrand") or 0) - 236000) > 0.01:
        fails.append(f"totalGrand expected 236000 got {dash.get('totalGrand')}")
    if int(dash.get("ordersConfirmed") or 0) < 1:
        fails.append(f"ordersConfirmed expected >=1 after approve got {dash.get('ordersConfirmed')}")

    led0 = build_ledger(cust, company_gst=gst)
    t0 = led0.get("totals") or {}
    if abs(float(t0.get("totalTaxable") or 0) - 200000) > 0.01:
        fails.append(f"ledger totalTaxable expected 200000 got {t0.get('totalTaxable')}")
    if abs(float(t0.get("totalGrand") or 0) - 236000) > 0.01:
        fails.append(f"ledger totalGrand expected 236000 got {t0.get('totalGrand')}")
    if abs(float(dash.get("totalTaxable") or 0) - float(t0.get("totalTaxable") or 0)) > 0.01:
        fails.append("hub totalTaxable must match sum of customer ledgers")
    if abs(float(dash.get("totalGrand") or 0) - float(t0.get("totalGrand") or 0)) > 0.01:
        fails.append("hub totalGrand must match sum of customer ledgers")

    set_project_status(p["projectId"], "confirmed")
    ws3 = open_workspace(gst)
    dash3 = ws3.get("dashboard") or {}
    if int(dash3.get("ordersConfirmed") or 0) < 1:
        fails.append(f"ordersConfirmed after confirm expected >=1 got {dash3.get('ordersConfirmed')}")

    # ── 3) Search by mobile ────────────────────────────────────────────────
    hits = find_customers(mobile, company_gst=gst)
    if not any(str(h.get("name") or "") == cust for h in hits):
        fails.append(f"mobile search missed customer: {hits}")
    hits2 = find_customers("987650", company_gst=gst)
    if not any(str(h.get("name") or "") == cust for h in hits2):
        fails.append("partial mobile search missed customer")

    # ── 4) Ledger PDF sections ─────────────────────────────────────────────
    led = build_ledger(cust, company_gst=gst)
    adv0 = (led.get("advances") or [{}])[0]
    if adv0.get("quoteVersion") is None and not (adv0.get("linkedQuote") or {}).get("version"):
        fails.append("advance missing quote/version linkage")
    pdf = render_ledger_pdf(led, ws3.get("company") or {})
    if not pdf.startswith(b"%PDF"):
        fails.append("ledger PDF not valid")
    text = _pdf_plain_text(pdf).upper()
    for needle in (
        "CUSTOMER ACCOUNT LEDGER",
        "RUNNING QUOTES",
        "ADVANCES",
        "TAXABLE",
        "WITH GST",
        "BALANCE",
        "HUB PERSIST CO",
    ):
        if needle not in text:
            fails.append(f"ledger PDF missing section/marker: {needle!r}")

    _report(fails)
    return 1 if fails else 0


def _pdf_plain_text(raw: bytes) -> str:
    """Best-effort extract of literal PDF content (ASCII85 + FlateDecode)."""
    import base64
    import re
    import zlib

    def _decode_stream(data: bytes) -> bytes:
        data = data.strip()
        if data.startswith(b"\r\n"):
            data = data[2:]
        elif data.startswith(b"\n"):
            data = data[1:]
        # ReportLab often uses /ASCII85Decode /FlateDecode
        if b"~>" in data:
            try:
                decoded = base64.a85decode(data, adobe=True)
                try:
                    return zlib.decompress(decoded)
                except Exception:
                    return decoded
            except Exception:
                pass
        try:
            return zlib.decompress(data)
        except Exception:
            return data

    chunks: list[str] = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        try:
            payload = _decode_stream(m.group(1))
            chunks.append(payload.decode("latin-1", errors="ignore"))
        except Exception:
            continue
    chunks.append(raw.decode("latin-1", errors="ignore"))
    return "\n".join(chunks)


def _report(fails: list[str]) -> None:
    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
    else:
        print("OK gst hub persist + dashboard + mobile search + ledger PDF smoke passed")


if __name__ == "__main__":
    raise SystemExit(main())
