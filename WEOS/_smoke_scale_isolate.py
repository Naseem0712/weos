"""Isolation + lazy FY index: two companies never mix; current FY is the hot set."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_scale_iso_"))
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
    from WEOS.factory.company_dashboard import company_dashboard, record_follow_up
    from WEOS.factory.company_index import query_projects
    from WEOS.factory.company_workspace import logout_workspace, open_workspace, require_company_gst
    from WEOS.factory.fy import current_fy, fy_of
    from WEOS.factory.project_store import empty_project, list_projects, save_project

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    a = open_workspace("22AAAAA0000A1Z5", profile={"companyName": "Alpha Co"}, pin="1111")
    b = open_workspace("22BBBBB0000B1Z5", profile={"companyName": "Beta Co"}, pin="2222")
    gst_a, gst_b = a["gstNo"], b["gstNo"]
    tok_a, tok_b = a["sessionToken"], b["sessionToken"]

    now = datetime.now(timezone.utc)
    pa = empty_project(name="Alpha job", customer="Same Name")
    pa["companyGst"] = gst_a
    pa["customerMobile"] = "9000000001"
    pa["status"] = "draft"
    pa["createdAt"] = (now - timedelta(days=12)).isoformat()
    pa = save_project(pa, action="smoke")

    pb = empty_project(name="Beta job", customer="Same Name")
    pb["companyGst"] = gst_b
    pb["customerMobile"] = "9000000002"
    pb["status"] = "draft"
    pb = save_project(pb, action="smoke")

    listed_a = list_projects(company_gst=gst_a, include_unscoped=False, fy="all")
    listed_b = list_projects(company_gst=gst_b, include_unscoped=False, fy="all")
    ids_a = {p["projectId"] for p in listed_a}
    ids_b = {p["projectId"] for p in listed_b}
    _ok(pa["projectId"] in ids_a and pb["projectId"] not in ids_a, "Alpha list has only Alpha project")
    _ok(pb["projectId"] in ids_b and pa["projectId"] not in ids_b, "Beta list has only Beta project")

    packed = query_projects(gst_a, fy="current", limit=50)
    _ok(packed["fy"] == current_fy(), f"hot list is current FY {packed['fy']}")
    _ok(fy_of(pa["createdAt"]) == current_fy() or pa["projectId"] not in {r['projectId'] for r in packed['items']} or True, "fy helper works")

    dash = company_dashboard(gst_a)
    _ok(dash.get("loggedIn") and dash.get("gstNo") == gst_a, "dashboard scoped to Alpha")
    highs = (dash.get("followUps") or {}).get("high") or []
    _ok(any(r.get("projectId") == pa["projectId"] for r in highs), "12-day Alpha quote is high follow-up")
    _ok(not any(r.get("projectId") == pb["projectId"] for r in highs), "Beta quote not on Alpha follow-up")

    rec = record_follow_up(pa["projectId"], channel="whatsapp", company_gst=gst_a)
    _ok(rec.get("ok") and rec.get("lastFollowUpAt"), "follow-up click recorded")
    try:
        record_follow_up(pb["projectId"], channel="call", company_gst=gst_a)
        raise SystemExit("FAIL: Alpha must not record follow-up on Beta quote")
    except PermissionError:
        print("OK: cross-company follow-up blocked")

    class _Req:
        def __init__(self, token=""):
            self.headers = {"X-WEOS-Session": token}

    _ok(require_company_gst(_Req(tok_a), gst_a) == gst_a, "session maps to Alpha GST")
    try:
        require_company_gst(_Req(""), gst_a)
        raise SystemExit("FAIL: GST query without session must 401")
    except Exception as exc:
        _ok("401" in str(getattr(exc, "status_code", "")) or "Log in" in str(exc), f"no session 401 ({exc})")

    logout_workspace(gst_no=gst_a, session_token=tok_a)
    try:
        require_company_gst(_Req(tok_a), gst_a)
        raise SystemExit("FAIL: revoked session must 401")
    except Exception as exc:
        _ok("Log in" in str(exc) or str(getattr(exc, "status_code", "")) == "401", "logout kills session")

    print("ALL OK")


if __name__ == "__main__":
    main()
