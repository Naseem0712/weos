"""Smoke: GST+PIN auth rejects wrong/empty PIN and keeps company data isolated."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_pin_auth_smoke_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)


def main() -> int:
    fails: list[str] = []
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from WEOS.db.engine import init_db
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.customer_store import list_customer_profiles, save_customer_profile
    from WEOS.factory.project_store import empty_project, list_projects, save_project

    res = init_db()
    if not res.get("ok"):
        print("FAIL init_db", res)
        return 1

    a = "27AAAAA0000A1Z5"
    b = "27BBBBB0000B1Z5"

    try:
        open_workspace(a, create=True, profile={"companyName": "A Co"})
        fails.append("create without PIN succeeded")
    except PermissionError:
        pass

    ws_a = open_workspace(
        a,
        create=True,
        pin="1234",
        profile={"companyName": "Alpha Glass", "email": "a@example.com"},
    )
    if not ws_a.get("created"):
        fails.append("company A not created")

    try:
        open_workspace(a, create=False, pin="0000")
        fails.append("wrong PIN accepted for A")
    except PermissionError:
        pass

    try:
        open_workspace(a, create=False, pin="")
        fails.append("empty PIN accepted for A")
    except (PermissionError, ValueError):
        pass

    tok = ws_a.get("sessionToken")
    try:
        open_workspace(a, create=False, pin="0000", session_token=tok)
        fails.append("session+wrong PIN accepted for A")
    except PermissionError:
        pass

    # Valid session restore without typing PIN is OK.
    ws_restore = open_workspace(a, create=False, session_token=tok)
    if not ws_restore.get("ok"):
        fails.append("valid session restore failed")

    ws_b = open_workspace(
        b,
        create=True,
        pin="5678",
        profile={"companyName": "Beta Frames", "email": "b@example.com"},
    )
    save_customer_profile("Alpha Cust", {"name": "Alpha Cust", "companyGst": a})
    save_customer_profile("Beta Cust", {"name": "Beta Cust", "companyGst": b})
    pa = empty_project(name="A Quote", customer="Alpha Cust")
    pa["companyGst"] = a
    save_project(pa, action="smoke")
    pb = empty_project(name="B Quote", customer="Beta Cust")
    pb["companyGst"] = b
    save_project(pb, action="smoke")

    a_custs = [c.get("name") for c in list_customer_profiles(company_gst=a)]
    b_custs = [c.get("name") for c in list_customer_profiles(company_gst=b)]
    if "Beta Cust" in a_custs:
        fails.append("company A sees Beta customer")
    if "Alpha Cust" in b_custs:
        fails.append("company B sees Alpha customer")
    a_projects = [p.get("name") for p in list_projects(company_gst=a)]
    b_projects = [p.get("name") for p in list_projects(company_gst=b)]
    if "B Quote" in a_projects:
        fails.append("company A sees B quote")
    if "A Quote" in b_projects:
        fails.append("company B sees A quote")

    # create:true must not bypass PIN on an existing company.
    try:
        open_workspace(a, create=True, pin="9999")
        fails.append("create:true + wrong PIN opened existing company")
    except PermissionError:
        pass

    if fails:
        print("FAIL")
        for f in fails:
            print(" -", f)
        return 1
    print("OK pin auth + isolation smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
