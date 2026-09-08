"""Smoke: tenant ownership on project + customer sensitive routes.

Unauth -> 401; Company A cannot read/write Company B; owner still works.
Does not change business calculations.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_tenant_own_"))
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
    from fastapi.testclient import TestClient

    from WEOS.db.engine import init_db
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.api.server import app

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    gst_a = "22AAAAA0000A1Z5"
    gst_b = "22BBBBB0000B1Z5"
    ws_a = open_workspace(
        gst_a,
        profile={"companyName": "Tenant A Co", "phone": "9000000001", "email": "a@example.com"},
        pin="1111",
    )
    ws_b = open_workspace(
        gst_b,
        profile={"companyName": "Tenant B Co", "phone": "9000000002", "email": "b@example.com"},
        pin="2222",
    )
    tok_a = ws_a["sessionToken"]
    tok_b = ws_b["sessionToken"]
    _ok(bool(tok_a and tok_b), "two company sessions")

    client = TestClient(app)
    hdr_a = {"X-WEOS-Session": tok_a}
    hdr_b = {"X-WEOS-Session": tok_b}

    # --- unauth rejected ---
    r = client.get("/api/customers/CustA/profile")
    _ok(r.status_code == 401, f"unauth customer GET -> 401 got {r.status_code}")
    r = client.put("/api/customers/CustA/profile", json={"name": "CustA", "phone": "9111111111"})
    _ok(r.status_code == 401, f"unauth customer PUT -> 401 got {r.status_code}")
    r = client.put("/api/projects/PRJ-TENANT-A1", json={"name": "Hack", "customer": "X", "lines": []})
    _ok(r.status_code == 401, f"unauth project PUT -> 401 got {r.status_code}")
    r = client.post("/api/projects", json={"name": "Hack", "customer": "X", "lines": []})
    _ok(r.status_code == 401, f"unauth project POST -> 401 got {r.status_code}")

    # --- Company A creates customer + project ---
    r = client.put(
        "/api/customers/CustA/profile",
        headers=hdr_a,
        json={"name": "CustA", "phone": "9111111111", "address": "A Street", "companyGst": gst_b},
    )
    _ok(r.status_code == 200, f"A saves customer profile got {r.status_code} {r.text[:200]}")
    body = r.json()
    _ok(body.get("companyGst") == gst_a, f"customer stamped to A not spoofed B: {body.get('companyGst')}")

    r = client.post(
        "/api/projects",
        headers=hdr_a,
        json={
            "name": "Job A",
            "customer": "CustA",
            "customerMobile": "9111111111",
            "status": "draft",
            "lines": [],
            "companyGst": gst_b,
        },
    )
    _ok(r.status_code == 200, f"A creates project got {r.status_code} {r.text[:200]}")
    proj = r.json()
    pid = str(proj.get("projectId") or "")
    _ok(bool(pid), f"project id present: {pid}")
    _ok(proj.get("companyGst") == gst_a, f"project stamped to A: {proj.get('companyGst')}")

    # --- owner still works ---
    r = client.get(f"/api/customers/CustA/profile", headers=hdr_a)
    _ok(r.status_code == 200 and r.json().get("phone") == "9111111111", "A reads own customer")
    r = client.get(f"/api/projects/{pid}", headers=hdr_a)
    _ok(r.status_code == 200 and r.json().get("projectId") == pid, "A reads own project")
    r = client.put(
        f"/api/projects/{pid}",
        headers=hdr_a,
        json={"name": "Job A v2", "customer": "CustA", "lines": []},
    )
    _ok(r.status_code == 200 and r.json().get("name") == "Job A v2", "A updates own project")
    r = client.get(f"/api/projects/{pid}/quotation", headers=hdr_a)
    _ok(r.status_code == 200, f"A quotation got {r.status_code}")
    r = client.get(f"/api/projects/{pid}/customer-pdf", headers=hdr_a)
    _ok(r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf"), "A PDF ok")
    r = client.get(f"/api/projects/{pid}/customer-pdf?session={tok_a}")
    _ok(r.status_code == 200, "A PDF via query session ok")
    r = client.get(f"/api/customers/CustA/ledger", headers=hdr_a)
    _ok(r.status_code == 200, f"A ledger JSON got {r.status_code}")
    r = client.get(f"/api/customers/CustA/ledger.pdf", headers=hdr_a)
    _ok(r.status_code == 200, f"A ledger PDF got {r.status_code}")

    # --- Company B denied ---
    r = client.get("/api/customers/CustA/profile", headers=hdr_b)
    _ok(r.status_code == 404, f"B customer GET -> 404 got {r.status_code}")
    r = client.put(
        "/api/customers/CustA/profile",
        headers=hdr_b,
        json={"name": "CustA", "phone": "9999999999"},
    )
    _ok(r.status_code == 404, f"B customer PUT -> 404 got {r.status_code}")
    r = client.get(f"/api/projects/{pid}", headers=hdr_b)
    _ok(r.status_code == 404, f"B project GET -> 404 got {r.status_code}")
    r = client.put(
        f"/api/projects/{pid}",
        headers=hdr_b,
        json={"name": "Hijacked", "customer": "CustA", "lines": []},
    )
    _ok(r.status_code == 404, f"B project PUT -> 404 got {r.status_code}")
    r = client.get(f"/api/projects/{pid}/customer-pdf", headers=hdr_b)
    _ok(r.status_code == 404, f"B PDF -> 404 got {r.status_code}")
    r = client.get(f"/api/projects/{pid}/quotation", headers=hdr_b)
    _ok(r.status_code == 404, f"B quotation -> 404 got {r.status_code}")
    r = client.get(f"/api/customers/CustA/ledger.pdf", headers=hdr_b)
    _ok(r.status_code == 404, f"B ledger PDF -> 404 got {r.status_code}")
    r = client.get(f"/api/projects/{pid}/master-ledger", headers=hdr_b)
    _ok(r.status_code == 404, f"B master-ledger -> 404 got {r.status_code}")

    # Ensure A's data unchanged after B attempts
    r = client.get(f"/api/projects/{pid}", headers=hdr_a)
    _ok(r.json().get("name") == "Job A v2", "A project name unchanged after B PUT")
    r = client.get("/api/customers/CustA/profile", headers=hdr_a)
    _ok(r.json().get("phone") == "9111111111", "A customer phone unchanged after B PUT")

    print("OK tenant ownership smoke")


if __name__ == "__main__":
    main()
