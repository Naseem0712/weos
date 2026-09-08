"""Smoke: Floor / Location / DesignDocument foundation (Batch 5) — cases A–H."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_design_hier_"))
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

    from WEOS.api.server import app
    from WEOS.db.engine import init_db
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.project_store import empty_project, save_project

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    gst_a = "22AAAAA0000A1Z5"
    gst_b = "22BBBBB0000B1Z5"

    # --- A: canonical Customer + Project ---
    cust = create_customer(gst_a, display_name="Hier Cust", mobile="9111222333")
    cid = cust["customerId"]
    proj = upsert_project(
        project_id="PRJ-2026-HIER01",
        customer_id=cid,
        company_gst=gst_a,
        name="Hierarchy Job",
        status="draft",
    )
    pid = proj["projectId"]
    _ok(pid == "PRJ-2026-HIER01" and proj.get("customerId") == cid, "A: canonical customer+project")

    # Also stamp a durable project doc for ownership APIs / migration
    doc = empty_project(name="Hierarchy Job", customer="Hier Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst_a
    doc["customerMobile"] = "9111222333"
    doc["customerId"] = cid
    doc["lines"] = [
        {
            "lineId": "L1",
            "product": "29mm_sliding",
            "productType": "sliding",
            "width": 1200,
            "height": 1400,
            "qty": 1,
            "locationName": "Living Room",
        },
        {
            "lineId": "L2",
            "product": "29mm_sliding",
            "productType": "sliding",
            "width": 900,
            "height": 1200,
            "qty": 1,
            "locationName": "Kitchen",
        },
        {
            "lineId": "L3",
            "product": "casement_stub",
            "productType": "casements",
            "width": 1000,
            "height": 1000,
            "qty": 1,
            # no locationName → unassigned item
        },
    ]
    saved = save_project(doc, action="smoke")
    _ok(saved.get("projectId") == pid, "A: durable project saved")

    # --- B: create floors ---
    ground = dh.create_floor(
        project_id=pid, company_gst=gst_a, name="Ground Floor", code="GF", level_index=0
    )
    first = dh.create_floor(
        project_id=pid, company_gst=gst_a, name="First Floor", code="FF", level_index=1
    )
    _ok(ground["name"] == "Ground Floor" and first["name"] == "First Floor", "B: floors created")
    _ok(ground["floorId"] != first["floorId"], "B: distinct floor ids")

    # --- C: locations ---
    living = dh.create_location(
        floor_id=ground["floorId"], company_gst=gst_a, name="Living Room", sort_order=1
    )
    kitchen = dh.create_location(
        floor_id=ground["floorId"], company_gst=gst_a, name="Kitchen", sort_order=2
    )
    bed = dh.create_location(
        floor_id=first["floorId"], company_gst=gst_a, name="Bedroom 1", sort_order=1
    )
    _ok(
        living["floorId"] == ground["floorId"]
        and kitchen["floorId"] == ground["floorId"]
        and bed["floorId"] == first["floorId"],
        "C: locations on correct floors",
    )

    # Design document
    des = dh.ensure_design_document(pid, gst_a)
    _ok(bool(des.get("designDocumentId")), "C: design document ensured")
    rev = dh.create_geometry_revision(
        des["designDocumentId"],
        company_gst=gst_a,
        payload={"note": "freeze-1"},
        label="v1",
    )
    _ok(rev.get("immutable") is True, "C: geometry revision immutable flag")
    try:
        dh.try_update_geometry_revision(
            rev["revisionId"], company_gst=gst_a, payload={"hack": True}
        )
        raise SystemExit("FAIL: immutable revision must refuse update")
    except ValueError as exc:
        _ok("immutable" in str(exc).lower(), f"C: revision mutate blocked: {exc}")

    # --- D: save/reload identity ---
    floors = dh.list_floors(pid, company_gst=gst_a)
    locs_g = dh.list_locations(floor_id=ground["floorId"], company_gst=gst_a)
    locs_f = dh.list_locations(floor_id=first["floorId"], company_gst=gst_a)
    des2 = dh.get_design_document(des["designDocumentId"], company_gst=gst_a)
    rev2 = dh.get_geometry_revision(rev["revisionId"], company_gst=gst_a)
    _ok(
        {f["floorId"] for f in floors} >= {ground["floorId"], first["floorId"]},
        "D: floors reload",
    )
    _ok(
        {x["locationId"] for x in locs_g} == {living["locationId"], kitchen["locationId"]},
        "D: ground locations reload",
    )
    _ok({x["locationId"] for x in locs_f} == {bed["locationId"]}, "D: first locations reload")
    _ok(
        des2
        and des2.get("designDocumentId") == des["designDocumentId"]
        and des2.get("currentRevisionId") == rev["revisionId"],
        "D: design document + revision pointer",
    )
    _ok(rev2 and rev2.get("payload", {}).get("note") == "freeze-1", "D: revision payload intact")

    # --- E: same location name on two floors ---
    bal_g = dh.create_location(
        floor_id=ground["floorId"], company_gst=gst_a, name="Balcony", sort_order=9
    )
    bal_f = dh.create_location(
        floor_id=first["floorId"], company_gst=gst_a, name="Balcony", sort_order=9
    )
    _ok(
        bal_g["locationId"] != bal_f["locationId"]
        and bal_g["normalizedName"] == bal_f["normalizedName"],
        "E: same name different floors allowed",
    )

    # --- F: company isolation ---
    create_customer(gst_b, display_name="Other Co Cust", mobile="9222333444")
    # B cannot read A's floors via domain
    _ok(dh.get_floor(ground["floorId"], company_gst=gst_b) is None, "F: floor hidden from B")
    _ok(dh.get_location(living["locationId"], company_gst=gst_b) is None, "F: location hidden from B")
    _ok(
        dh.get_design_document(des["designDocumentId"], company_gst=gst_b) is None,
        "F: design doc hidden from B",
    )

    ws_a = open_workspace(
        gst_a,
        profile={"companyName": "Hier A", "phone": "9000000011", "email": "a@ex.com"},
        pin="1111",
    )
    ws_b = open_workspace(
        gst_b,
        profile={"companyName": "Hier B", "phone": "9000000022", "email": "b@ex.com"},
        pin="2222",
    )
    client = TestClient(app)
    hdr_a = {"X-WEOS-Session": ws_a["sessionToken"]}
    hdr_b = {"X-WEOS-Session": ws_b["sessionToken"]}
    r = client.get(f"/api/projects/{pid}/floors", headers=hdr_a)
    _ok(r.status_code == 200 and len(r.json().get("floors") or []) >= 2, f"F: A lists floors {r.status_code}")
    r = client.get(f"/api/projects/{pid}/floors", headers=hdr_b)
    _ok(r.status_code == 404, f"F: B floors denied {r.status_code}")
    r = client.get(f"/api/design-documents/{des['designDocumentId']}", headers=hdr_b)
    _ok(r.status_code == 404, f"F: B design doc API denied {r.status_code}")

    # --- G: legacy locationName compatibility → Unassigned (never invent Ground) ---
    mapped = dh.resolve_location_for_legacy_name(
        project_id=pid, company_gst=gst_a, location_name="Living Room", create=True
    )
    unassigned = dh.ensure_unassigned_floor(pid, gst_a)
    _ok(unassigned.get("code") == "UNASSIGNED" and unassigned.get("isSystem") is True, "G: Unassigned floor")
    _ok(
        mapped
        and mapped.get("floorId") == unassigned["floorId"]
        and mapped.get("name") == "Living Room",
        "G: legacy name under Unassigned",
    )
    # Evidence: Ground Floor exists as user floor, but legacy map must NOT use it blindly
    _ok(mapped.get("floorId") != ground["floorId"], "G: legacy does not invent/use Ground Floor")

    # --- H: migration counts + zeroSilentLoss ---
    mig = dh.migrate_legacy_locations(company_gst=gst_a, project_id=pid)
    _ok(mig.get("ok") is True, f"H: migrate ok {mig}")
    _ok(mig.get("zeroSilentLoss") is True, "H: zeroSilentLoss")
    _ok(int(mig.get("projectsInspected") or 0) >= 1, "H: projects inspected")
    print(
        "MIGRATE_DESIGN_HIERARCHY_COUNTS",
        {
            "projectsInspected": mig.get("projectsInspected"),
            "floorsCreated": mig.get("floorsCreated"),
            "locationsCreated": mig.get("locationsCreated"),
            "legacyLocationNamesLinked": mig.get("legacyLocationNamesLinked"),
            "unassignedItems": mig.get("unassignedItems"),
            "conflicts": mig.get("conflicts"),
            "rejected": mig.get("rejected"),
            "manualReview": len(mig.get("manualReview") or []),
            "zeroSilentLoss": mig.get("zeroSilentLoss"),
            "rule": mig.get("rule"),
        },
    )

    print("OK design hierarchy smoke")


if __name__ == "__main__":
    main()
