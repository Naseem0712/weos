"""Smoke: canonical company-scoped customer identity (Batch 3)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_canon_cust_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from WEOS.db.engine import init_db
    from WEOS.factory.canonical_customer import (
        create_customer,
        find_or_create_customer,
        match_customer,
        migrate_legacy_customer_profiles,
        normalize_mobile,
    )
    from WEOS.factory.customer_store import load_customer_profile, save_customer_profile

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")
    _ok(normalize_mobile("+91 98765 43210") == "9876543210", "normalize mobile +91")
    _ok(normalize_mobile("09876543210") == "9876543210", "normalize mobile leading 0")

    gst_a = "22AAAAA0000A1Z5"
    gst_b = "22BBBBB0000B1Z5"

    a1 = create_customer(gst_a, display_name="Alpha Cust", mobile="9876543210", gst_no="22AAAAA0000A1Z5")
    _ok(bool(a1.get("customerId")), f"created A customer {a1.get('customerId')}")

    # Same mobile different company — allowed (no global uniqueness)
    b1 = create_customer(gst_b, display_name="Beta Cust", mobile="9876543210")
    _ok(b1.get("customerId") != a1.get("customerId"), "same mobile allowed across companies")

    # Exact match by mobile within company A
    m = match_customer(company_gst=gst_a, mobile="98765-43210")
    _ok(m.get("match") == "exact" and m.get("customerId") == a1["customerId"], f"mobile match {m}")

    # Match by customer_id
    m2 = match_customer(company_gst=gst_a, customer_id=a1["customerId"])
    _ok(m2.get("match") == "exact", "customer_id match")

    # Cross-company customer_id lookup denied
    m3 = match_customer(company_gst=gst_b, customer_id=a1["customerId"])
    _ok(m3.get("match") == "none", "cross-company customer_id denied")

    # Conflict: two customers, identity evidence would collide on create
    create_customer(gst_a, display_name="Other", mobile="9000000001", gst_no="29AAAAA0000A1Z5")
    # Attempt to create with mobile of A and GST of Other → conflict or refuse
    try:
        create_customer(gst_a, display_name="Merge Attempt", mobile="9876543210", gst_no="29AAAAA0000A1Z5")
        raise SystemExit("FAIL: create must refuse conflicting identity merge")
    except ValueError as exc:
        _ok("refuse" in str(exc).lower() or "conflict" in str(exc).lower() or "belongs" in str(exc).lower(), f"conflict: {exc}")

    # find_or_create returns existing, not duplicate
    foc = find_or_create_customer(gst_a, mobile="9876543210", display_name="Alpha Cust")
    _ok(foc.get("created") is False and foc.get("customerId") == a1["customerId"], "find_or_create reuses")

    # Legacy profile save stamps customerId
    saved = save_customer_profile("Legacy Alpha", {"name": "Legacy Alpha", "phone": "9111222333", "companyGst": gst_a})
    _ok(bool(saved.get("customerId")), f"profile stamped customerId {saved.get('customerId')}")
    reloaded = load_customer_profile("Legacy Alpha")
    _ok(reloaded.get("customerId") == saved.get("customerId"), "profile reload keeps customerId")

    mig = migrate_legacy_customer_profiles(company_gst=gst_a)
    _ok(mig.get("ok"), f"migrate {mig}")
    _ok(mig.get("zeroSilentLoss") is True, f"zeroSilentLoss {mig.get('zeroSilentLoss')}")
    print(
        "MIGRATE_CUSTOMER_COUNTS",
        {
            "before": mig.get("before"),
            "created": mig.get("created"),
            "linked": mig.get("linked"),
            "conflicts": mig.get("conflicts"),
            "rejected": mig.get("rejected"),
            "skipped": mig.get("skipped"),
            "after": mig.get("after"),
            "manualReview": len(mig.get("manualReview") or []),
        },
    )

    print("OK canonical customer smoke")


if __name__ == "__main__":
    main()
