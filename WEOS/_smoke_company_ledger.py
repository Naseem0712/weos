"""Smoke: company save→reload via durable DB + advance→balance math."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Isolate filesystem + sqlite so we never touch the developer's real data dir.
_tmp = Path(tempfile.mkdtemp(prefix="weos_ledger_smoke_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
# Force sqlite under our temp dir via resolve_database_url fallback.


def main() -> int:
    fails: list[str] = []

    # Point WEOS paths at temp (paths module may already be imported — set before imports).
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from WEOS.db.engine import init_db, resolve_database_url
    from WEOS.factory import company_store, ledger_store
    from WEOS.factory.customer_store import save_customer_profile
    from WEOS.factory.ledger_pdf import ledger_filename, render_ledger_pdf
    from WEOS.factory.project_store import empty_project, save_project

    url, backend = resolve_database_url()
    if "sqlite" not in url and backend != "sqlite":
        # Still OK if someone has DATABASE_URL — but for smoke we prefer isolation.
        pass
    res = init_db()
    if not res.get("ok"):
        fails.append(f"init_db failed: {res}")
        _report(fails)
        return 1

    # ── Company save → clear cache file → reload from DB ───────────────────
    saved = company_store.save_company(
        {
            "companyName": "Smoke Co Pvt Ltd",
            "address": "12 Test Road",
            "gstNo": "22AAAAA0000A1Z5",
            "phone": "9999900000",
            "bankDetails": "HDFC · 123 · HDFC0001",
            "terms": "50% advance",
        }
    )
    if not (saved.get("companyName") or "").startswith("Smoke"):
        fails.append("company save did not stick in return value")
    if not saved.get("persisted"):
        fails.append("company not persisted to DB (persisted=False)")

    # Wipe filesystem cache — DB must still serve the profile.
    path = company_store.company_path()
    if path.is_file():
        path.unlink()
    for logo in company_store.company_dir().glob("logo.*"):
        logo.unlink()

    loaded = company_store.load_company()
    if (loaded.get("companyName") or "") != "Smoke Co Pvt Ltd":
        fails.append(f"company reload after file wipe failed: {loaded.get('companyName')!r}")
    if loaded.get("gstNo") != "22AAAAA0000A1Z5":
        fails.append("company GST lost after reload")

    # ── Project + customer + advances → balance ────────────────────────────
    cust = "Smoke Customer"
    save_customer_profile(cust, {"name": cust, "phone": "9000011111", "address": "Site A"})
    doc = empty_project(name="Smoke Quote 1", customer=cust)
    doc["lastCalculation"] = {"price": {"total": 100000.0}}
    save_project(doc, action="smoke")

    doc2 = empty_project(name="Smoke Quote 2", customer=cust)
    doc2["lastCalculation"] = {"price": {"total": 50000.0}}
    save_project(doc2, action="smoke")

    a1 = ledger_store.add_advance(cust, {"amount": 40000, "paymentMode": "upi", "reference": "UTR1"})
    a2 = ledger_store.add_advance(cust, {"amount": 25000, "paymentMode": "cheque", "reference": "CHQ99"})
    if a1.get("paymentMode") != "upi":
        fails.append("advance payment mode not stored")

    led = ledger_store.build_ledger(cust)
    billed = float((led.get("totals") or {}).get("billed") or 0)
    adv = float((led.get("totals") or {}).get("advances") or 0)
    bal = float((led.get("totals") or {}).get("balance") or 0)
    if abs(billed - 150000) > 0.01:
        fails.append(f"billed expected 150000 got {billed}")
    if abs(adv - 65000) > 0.01:
        fails.append(f"advances expected 65000 got {adv}")
    if abs(bal - 85000) > 0.01:
        fails.append(f"balance expected 85000 got {bal}")

    pdf = render_ledger_pdf(led, loaded)
    if not pdf.startswith(b"%PDF"):
        fails.append("ledger PDF not valid")
    fname = ledger_filename(cust, led.get("asOf"))
    if "ledger" not in fname or not fname.endswith(".pdf"):
        fails.append(f"bad ledger filename: {fname}")

    # cleanup advance
    ledger_store.delete_advance(cust, int(a2["id"]))
    led2 = ledger_store.build_ledger(cust)
    if abs(float(led2["totals"]["advances"]) - 40000) > 0.01:
        fails.append("delete advance did not update total")

    _report(fails)
    return 1 if fails else 0


def _report(fails: list[str]) -> None:
    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
    else:
        print("OK company+ledger smoke passed")


if __name__ == "__main__":
    raise SystemExit(main())
