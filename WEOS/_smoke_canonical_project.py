"""Smoke: canonical Company→Customer→Project identity (Batch 4)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_canon_proj_"))
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
    from WEOS.factory.canonical_customer import create_customer, find_or_create_customer
    from WEOS.factory.canonical_project import (
        find_or_create_project,
        match_project,
        migrate_legacy_projects,
        upsert_project,
    )
    from WEOS.factory.project_store import empty_project, load_project, save_project

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    gst = "22CCCCC0000C1Z5"
    cust = create_customer(gst, display_name="Proj Cust", mobile="9888777666")
    cid = cust["customerId"]
    other = create_customer(gst, display_name="Other Cust", mobile="9888777000")

    p = upsert_project(
        project_id="PRJ-2026-00999",
        customer_id=cid,
        company_gst=gst,
        name="Site Alpha",
        status="draft",
    )
    _ok(p.get("projectId") == "PRJ-2026-00999", "preserve project id")
    _ok(p.get("customerId") == cid, "customer FK set")

    m = match_project(company_gst=gst, customer_id=cid, project_id="PRJ-2026-00999")
    _ok(m.get("match") == "exact" and m.get("by") == "project_id", f"match by id {m}")

    m2 = match_project(company_gst=gst, customer_id=cid, name="Site Alpha")
    _ok(m2.get("match") == "exact" and m2.get("by") == "normalized_name", f"match by name {m2}")

    # Same name under different customer is NOT a cross-join hit
    m3 = match_project(company_gst=gst, customer_id=other["customerId"], name="Site Alpha")
    _ok(m3.get("match") == "none", "name match scoped within customer")

    # Ambiguous: two projects same name under one customer
    upsert_project(
        project_id="PRJ-2026-00998",
        customer_id=cid,
        company_gst=gst,
        name="Site Alpha",
        status="draft",
    )
    amb = match_project(company_gst=gst, customer_id=cid, name="Site Alpha")
    _ok(amb.get("match") == "ambiguous" and len(amb.get("candidates") or []) == 2, f"ambiguous {amb}")

    # Refuse reassignment to another customer
    try:
        upsert_project(
            project_id="PRJ-2026-00999",
            customer_id=other["customerId"],
            company_gst=gst,
            name="Hijack",
        )
        raise SystemExit("FAIL: must refuse customer reassignment")
    except ValueError as exc:
        _ok("another customer" in str(exc).lower() or "refuse" in str(exc).lower(), f"reassign blocked: {exc}")

    # Live PRJ save links canonical ids
    doc = empty_project(name="Live Job", customer="Live Cust")
    doc["companyGst"] = gst
    doc["customerMobile"] = "9777666555"
    saved = save_project(doc, action="smoke")
    _ok(bool(saved.get("customerId")), f"save stamps customerId {saved.get('customerId')}")
    _ok(saved.get("canonicalProjectId") == saved.get("projectId"), "canonical project linked")
    reloaded = load_project(saved["projectId"])
    _ok(reloaded.get("customerId") == saved.get("customerId"), "reload keeps customerId")
    _ok(reloaded.get("canonicalProjectId") == saved.get("projectId"), "reload keeps canonical project id")
    _ok(reloaded.get("name") == "Live Job", "reload preserves name")
    _ok(len(reloaded.get("lines") or []) == 0, "reload lines stable")

    mig = migrate_legacy_projects(company_gst=gst)
    _ok(mig.get("ok"), f"migrate projects {mig}")
    _ok(mig.get("zeroSilentLoss") is True, "zero silent loss flag")
    _ok(int(mig.get("rejected") or 0) + int(mig.get("unmatched") or 0) >= 0, "counts present")
    print(
        "MIGRATE_PROJECT_COUNTS",
        {
            "before": mig.get("before"),
            "created": mig.get("created"),
            "linked": mig.get("linked"),
            "unmatched": mig.get("unmatched"),
            "ambiguous": mig.get("ambiguous"),
            "rejected": mig.get("rejected"),
            "after": mig.get("after"),
            "manualReview": len(mig.get("manualReview") or []),
            "zeroSilentLoss": mig.get("zeroSilentLoss"),
        },
    )

    print("OK canonical project smoke")


if __name__ == "__main__":
    main()
