"""Smoke: GST workspace open → customers list; same quote number → version bump; totals update."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_gst_ws_smoke_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)


def main() -> int:
    fails: list[str] = []
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from WEOS.db.engine import init_db
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.customer_store import save_customer_profile
    from WEOS.factory.ledger_store import add_advance, build_ledger
    from WEOS.factory.project_store import empty_project, list_projects, save_project, set_project_status

    res = init_db()
    if not res.get("ok"):
        fails.append(f"init_db failed: {res}")
        _report(fails)
        return 1

    gst = "22AAAAA0000A1Z5"
    ws = open_workspace(gst, profile={"companyName": "GST Smoke Co", "phone": "9000000001"})
    if not ws.get("ok"):
        fails.append("workspace open failed")
    if ws.get("gstNo") != gst:
        fails.append(f"gst mismatch: {ws.get('gstNo')}")
    if not ws.get("created"):
        fails.append("expected first open to create workspace")

    # Second open should not re-create.
    ws2 = open_workspace(gst)
    if ws2.get("created"):
        fails.append("second open incorrectly marked created")
    if (ws2.get("company") or {}).get("companyName") != "GST Smoke Co":
        fails.append("company name lost on reopen")

    cust = "Workspace Customer"
    save_customer_profile(cust, {"name": cust, "phone": "9000012345", "companyGst": gst})

    # Project 1 with quote number QT-SMOKE-1
    p1 = empty_project(name="Quote A", customer=cust)
    p1["companyGst"] = gst
    p1["quotationId"] = "QT-SMOKE-1"
    p1["lastCalculation"] = {"price": {"total": 100000.0}}
    p1 = save_project(p1, action="smoke")
    pid_canon = p1["projectId"]
    ver1 = int(p1.get("version") or 0)

    # New project reusing same quote number → should merge as version, not orphan.
    p2 = empty_project(name="Quote A v2", customer=cust)
    p2["companyGst"] = gst
    p2["quotationId"] = "QT-SMOKE-1"
    p2["lastCalculation"] = {"price": {"total": 125000.0}}
    p2 = save_project(p2, action="smoke")
    if p2.get("projectId") != pid_canon:
        fails.append(f"expected merge into {pid_canon}, got {p2.get('projectId')}")
    if not p2.get("quoteNumberVersioned"):
        fails.append("quoteNumberVersioned flag missing on reuse")
    if int(p2.get("version") or 0) <= ver1:
        fails.append(f"version did not bump: {ver1} -> {p2.get('version')}")
    set_project_status(pid_canon, "approved")

    # Only one live project for that quote number under this company.
    rows = list_projects(company_gst=gst)
    same_qid = [r for r in rows if str(r.get("quotationId") or "").upper() == "QT-SMOKE-1"]
    if len(same_qid) != 1:
        fails.append(f"expected 1 live project for QT-SMOKE-1, got {len(same_qid)}")

    # Totals: live billed uses latest grand total (125000), not sum of versions.
    add_advance(cust, {"amount": 25000, "paymentMode": "upi", "reference": "GST-SMOKE"})
    led = build_ledger(cust, company_gst=gst)
    billed = float((led.get("totals") or {}).get("billed") or 0)
    bal = float((led.get("totals") or {}).get("balance") or 0)
    if abs(billed - 125000) > 0.01:
        fails.append(f"billed expected 125000 (latest version) got {billed}")
    if abs(bal - 100000) > 0.01:
        fails.append(f"balance expected 100000 got {bal}")
    if (led.get("totals") or {}).get("basis") != "latest_per_quotation_number":
        fails.append("ledger basis not documented as latest_per_quotation_number")

    # Workspace lists the customer.
    hub = open_workspace(gst)
    names = [c.get("name") for c in hub.get("customers") or []]
    if cust not in names:
        fails.append(f"workspace customers missing {cust}: {names}")
    if int(hub.get("customerCount") or 0) < 1:
        fails.append("customerCount < 1")

    _report(fails)
    return 1 if fails else 0


def _report(fails: list[str]) -> None:
    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
    else:
        print("OK gst workspace + quote version smoke passed")


if __name__ == "__main__":
    raise SystemExit(main())
