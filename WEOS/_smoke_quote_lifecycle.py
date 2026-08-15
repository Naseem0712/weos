"""Smoke: approved-only turnover, reject/refund, PIN-gated delete."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_quote_lifecycle_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)


def main() -> int:
    fails: list[str] = []
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from WEOS.db.engine import init_db
    from WEOS.factory.company_quotes import delete_company_quote, require_delete_confirm
    from WEOS.factory.company_store import save_company_by_gst, verify_delete_pin
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.customer_store import save_customer_profile
    from WEOS.factory.ledger_store import add_advance, build_ledger
    from WEOS.factory.project_store import empty_project, load_project, save_project, set_project_status

    res = init_db()
    if not res.get("ok"):
        fails.append(f"init_db failed: {res}")
        _report(fails)
        return 1

    gst = "27LIFEC0000L1Z5"
    cust = "Lifecycle Customer"
    ws = open_workspace(gst, profile={"companyName": "Lifecycle Co"})
    if ws.get("company", {}).get("hasDeletePin"):
        fails.append("new company should not have delete PIN")
    if "deletePinHash" in (ws.get("company") or {}):
        fails.append("PIN hash leaked to workspace payload")

    save_customer_profile(cust, {"name": cust, "companyGst": gst})

    draft = empty_project(name="Test v160", customer=cust)
    draft["companyGst"] = gst
    draft["quotationId"] = "QT-LIFE-DRAFT"
    draft["lastCalculation"] = {"price": {"total": 160000.0}}
    draft = save_project(draft, action="smoke")

    real = empty_project(name="Production quote", customer=cust)
    real["companyGst"] = gst
    real["quotationId"] = "QT-LIFE-REAL"
    real["lastCalculation"] = {"price": {"total": 80000.0}}
    real = save_project(real, action="smoke")
    set_project_status(real["projectId"], "approved")

    led = build_ledger(cust, company_gst=gst)
    t = led.get("totals") or {}
    if abs(float(t.get("yearTaxable") or 0) - 80000) > 0.01:
        fails.append(f"yearTaxable must ignore draft, expected 80000 got {t.get('yearTaxable')}")
    if abs(float(t.get("totalTaxable") or 0) - 80000) > 0.01:
        fails.append(f"billed must ignore draft, expected 80000 got {t.get('totalTaxable')}")

    hub = open_workspace(gst)
    dash = hub.get("dashboard") or {}
    if abs(float(dash.get("yearTaxable") or 0) - 80000) > 0.01:
        fails.append(f"hub yearTaxable expected 80000 got {dash.get('yearTaxable')}")

    # Reject production quote — drop out of turnover; keep history.
    set_project_status(real["projectId"], "rejected")
    led_r = build_ledger(cust, company_gst=gst)
    if abs(float((led_r.get("totals") or {}).get("yearTaxable") or 0)) > 0.01:
        fails.append("rejected quote still in year turnover")
    rejected = load_project(real["projectId"])
    if str(rejected.get("status") or "") != "rejected":
        fails.append(f"status not rejected: {rejected.get('status')}")

    # Re-approve, then refund.
    set_project_status(real["projectId"], "approved")
    add_advance(cust, {"amount": 20000, "paymentMode": "upi", "projectId": real["projectId"], "quoteId": "QT-LIFE-REAL"})
    refund = add_advance(
        cust,
        {
            "amount": 20000,
            "entryType": "refund",
            "paymentMode": "upi",
            "projectId": real["projectId"],
            "quoteId": "QT-LIFE-REAL",
        },
    )
    if float(refund.get("amount") or 0) >= 0:
        fails.append(f"refund must be negative got {refund.get('amount')}")
    if str(refund.get("entryType") or "") != "refund":
        fails.append(f"refund entryType {refund.get('entryType')}")
    led_f = build_ledger(cust, company_gst=gst)
    adv_tot = float((led_f.get("totals") or {}).get("totalAdvances") or 0)
    if abs(adv_tot) > 0.01:
        fails.append(f"advance+refund should net 0 got {adv_tot}")

    # PIN unset: project ID required; one-click empty confirm fails.
    try:
        require_delete_confirm(draft["projectId"], company_gst=gst, pin=None, confirm=None)
        fails.append("delete without PIN/project id must fail")
    except PermissionError:
        pass

    require_delete_confirm(draft["projectId"], company_gst=gst, confirm=draft["projectId"])
    require_delete_confirm(draft["projectId"], company_gst=gst, confirm="DELETE")

    saved = save_company_by_gst(gst, {"deletePin": "2468"})
    if not saved.get("hasDeletePin"):
        fails.append("hasDeletePin not set after saving PIN")
    if saved.get("deletePinHash") or saved.get("deletePin"):
        fails.append("PIN hash/plaintext leaked after save")
    if not verify_delete_pin(gst, "2468"):
        fails.append("verify_delete_pin failed for correct PIN")
    if verify_delete_pin(gst, "0000"):
        fails.append("verify_delete_pin accepted wrong PIN")

    try:
        require_delete_confirm(draft["projectId"], company_gst=gst, pin="0000")
        fails.append("wrong PIN must not delete")
    except PermissionError:
        pass
    # PIN is optional — DELETE / project id still work after a PIN is saved.
    require_delete_confirm(draft["projectId"], company_gst=gst, confirm="DELETE")
    require_delete_confirm(draft["projectId"], company_gst=gst, confirm=draft["projectId"])
    require_delete_confirm(draft["projectId"], company_gst=gst, pin="2468")

    deleted = delete_company_quote(draft["projectId"], company_gst=gst, hard=True)
    if not (deleted.get("ok") or deleted.get("deleted")):
        fails.append("PIN-authorized delete did not remove draft")
    try:
        load_project(draft["projectId"])
        fails.append("deleted test project still loadable")
    except FileNotFoundError:
        pass

    # Real approved quote still present — no need to delete the test project
    # to start production work; leftover drafts no longer inflate turnover.
    led_end = build_ledger(cust, company_gst=gst)
    if abs(float((led_end.get("totals") or {}).get("yearTaxable") or 0) - 80000) > 0.01:
        fails.append("production quote should still count after deleting the test draft")

    _report(fails)
    return 1 if fails else 0


def _report(fails: list[str]) -> None:
    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
    else:
        print("OK quote lifecycle + PIN delete + approved-only turnover")


if __name__ == "__main__":
    raise SystemExit(main())
