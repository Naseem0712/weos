"""Smoke: company PIN login, session, logout, scanner approve/reject windows."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_login_pin_"))
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
    from WEOS.factory.company_store import company_has_login_pin, public_company_profile, verify_login_pin
    from WEOS.factory.company_workspace import (
        find_companies_for_login,
        logout_workspace,
        open_workspace,
        request_pin_reset,
    )
    from WEOS.factory.quote_share import apply_scanner_status, scanner_decision_windows

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    gst = "22BBBBB0000B1Z5"
    ws = open_workspace(
        gst,
        profile={"companyName": "Pin Co", "phone": "9876543210", "email": "pinco@example.com"},
        pin="1234",
    )
    _ok(ws.get("created"), "first open creates company")
    _ok(bool(ws.get("sessionToken")), "login returns session token")
    _ok((ws.get("company") or {}).get("hasLoginPin"), "public profile has login PIN flag")
    _ok("loginPinHash" not in (ws.get("company") or {}), "PIN hash never returned")
    _ok(verify_login_pin(gst, "1234"), "PIN 1234 verifies")
    _ok(not verify_login_pin(gst, "0000"), "wrong PIN fails")

    try:
        open_workspace(gst, pin="0000", create=False)
        raise SystemExit("FAIL: wrong PIN must not open workspace")
    except PermissionError:
        print("OK: wrong PIN rejected")

    session = ws["sessionToken"]
    again = open_workspace(gst, session_token=session, create=False)
    _ok(again.get("ok") and not again.get("created"), "session token reopens without PIN")

    by_mobile = find_companies_for_login("9876543210")
    _ok(len(by_mobile) == 1 and by_mobile[0].get("gstNo") == gst, "login by registered mobile")
    by_name = find_companies_for_login("Pin Co")
    _ok(len(by_name) == 1, "login by company name")

    named = open_workspace(login="9876543210", pin="1234", create=False)
    _ok(named.get("gstNo") == gst, "open by mobile + PIN")

    logout_workspace(gst_no=gst, session_token=session)
    try:
        open_workspace(gst, session_token=session, create=False)
        # old session may still work until revoked — revoke_workspace_session should drop it
        raise SystemExit("FAIL: revoked session must not open workspace")
    except PermissionError:
        print("OK: logout revokes session")

    from WEOS.factory.company_store import mint_pin_reset_token, consume_pin_reset_token

    token = mint_pin_reset_token(gst)
    consume_pin_reset_token(token, "9876")
    _ok(verify_login_pin(gst, "9876"), "reset token sets new PIN")
    _ok(not verify_login_pin(gst, "1234"), "old PIN dead after reset")
    opened = open_workspace(gst, pin="9876", create=False)
    _ok(opened.get("ok"), "new PIN logs in")

    ack = request_pin_reset("Pin Co")
    _ok(ack.get("ok") and "email" in str(ack.get("message") or "").lower(), "reset request generic ack")

    now = datetime.now(timezone.utc)
    fresh = {"status": "draft", "createdAt": now.isoformat()}
    win = scanner_decision_windows(fresh, now=now)
    _ok(win["canApprove"] and win["canReject"], "fresh quote scanner can approve and reject")
    week_later = scanner_decision_windows(fresh, now=now + timedelta(days=8))
    _ok(not week_later["canReject"] and week_later["canApprove"], "after 7 days reject gone, approve stays")
    late = scanner_decision_windows(fresh, now=now + timedelta(days=16))
    _ok(not late["canApprove"] and not late["canReject"], "after 15 days scanner buttons gone")
    approved = {"status": "approved", "createdAt": now.isoformat()}
    _ok(not scanner_decision_windows(approved, now=now)["canApprove"], "already approved hides scanner approve")

    from WEOS.factory.project_store import empty_project, load_project, save_project, set_project_status

    doc = empty_project(name="Scan win", customer="Pin Cust")
    doc["companyGst"] = gst
    doc["createdAt"] = (now - timedelta(days=10)).isoformat()
    doc = save_project(doc, action="smoke")
    token_ref = str(doc.get("shareToken") or doc["projectId"])
    try:
        apply_scanner_status(token_ref, "rejected", confirm_reject=True)
        raise SystemExit("FAIL: scanner reject after 7 days must fail")
    except PermissionError:
        print("OK: scanner reject blocked after 7 days")
    apply_scanner_status(token_ref, "approved")
    live_doc = load_project(doc["projectId"])
    _ok(str(live_doc.get("status")) == "approved", "scanner approve still allowed at day 10")
    set_project_status(doc["projectId"], "draft")
    set_project_status(doc["projectId"], "rejected")
    _ok(load_project(doc["projectId"]).get("status") == "rejected", "panel reject unlimited")

    pub = public_company_profile({"loginPinHash": "secret", "companyName": "X", "email": "a@b.c"})
    _ok("loginPinHash" not in pub and pub.get("hasLoginPin") and pub.get("hasEmail"), "public profile strips hash")

    print("SMOKE_COMPANY_LOGIN_OK")


if __name__ == "__main__":
    main()
