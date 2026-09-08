"""Smoke: Universal Engineering Canvas Host (Batch 7) — cases A–H."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_universal_canvas_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
# Flag off by default — tests toggle explicitly where needed.
os.environ["WEOS_UNIVERSAL_CANVAS"] = "0"


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
    from WEOS.factory import design_scene as ds
    from WEOS.factory import universal_canvas as uc
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.project_store import empty_project, save_project

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    # Flag default OFF
    _ok(uc.is_universal_canvas_enabled() is False, "flag default OFF")
    os.environ["WEOS_UNIVERSAL_CANVAS"] = "1"
    _ok(uc.is_universal_canvas_enabled() is True, "flag ON via env")
    os.environ["WEOS_UNIVERSAL_CANVAS"] = "0"

    gst_a = "22AAAAA0000A1Z5"
    gst_b = "22BBBBB0000B1Z5"

    ws_a = open_workspace(
        gst_a,
        profile={"companyName": "Canvas A", "phone": "9000000111", "email": "ca@ex.com"},
        pin="1111",
    )
    ws_b = open_workspace(
        gst_b,
        profile={"companyName": "Canvas B", "phone": "9000000222", "email": "cb@ex.com"},
        pin="2222",
    )
    tok_a = ws_a["sessionToken"]
    tok_b = ws_b["sessionToken"]
    hdr_a = {"X-WEOS-Session": tok_a}
    hdr_b = {"X-WEOS-Session": tok_b}

    cust = create_customer(gst_a, display_name="Canvas Cust", mobile="9444555666")
    upsert_project(
        project_id="PRJ-2026-CANVAS1",
        customer_id=cust["customerId"],
        company_gst=gst_a,
        name="Canvas Job",
        status="draft",
    )
    pid = "PRJ-2026-CANVAS1"
    doc = empty_project(name="Canvas Job", customer="Canvas Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst_a
    doc["customerMobile"] = "9444555666"
    doc["customerId"] = cust["customerId"]
    doc["lines"] = []
    save_project(doc, action="smoke")

    des = dh.ensure_design_document(pid, gst_a)
    did = des["designDocumentId"]
    living = dh.resolve_location_for_legacy_name(
        project_id=pid, company_gst=gst_a, location_name="Living Room", create=True
    )
    floor_id = living["floorId"]
    loc_id = living["locationId"]

    # Mixed products + unequal / offset geometry
    a01 = ds.create_assembly(
        design_document_id=did,
        company_gst=gst_a,
        name="Mixed Assembly",
        display_code="A-01",
        location_id=loc_id,
    )
    w01 = ds.create_element(
        assembly_id=a01["assemblyId"],
        company_gst=gst_a,
        product_type="SLIDING_WINDOW",
        product_id="29mm_sliding",
        display_code="W-01",
        width_mm=1800,
        height_mm=1500,
        x_mm=0,
        y_mm=0,
    )
    r01 = ds.create_element(
        assembly_id=a01["assemblyId"],
        company_gst=gst_a,
        product_type="RAILING",
        product_id="railings_stub",
        display_code="R-01",
        width_mm=2400,
        height_mm=900,
        x_mm=2000,
        y_mm=100,
    )
    v01 = ds.create_element(
        assembly_id=a01["assemblyId"],
        company_gst=gst_a,
        product_type="VENTILATOR",
        product_id="ventilator_stub",
        display_code="V-01",
        width_mm=600,
        height_mm=400,
        x_mm=500,
        y_mm=1600,
    )
    # Unknown product type → fallback placeholder path
    x01 = ds.create_element(
        assembly_id=a01["assemblyId"],
        company_gst=gst_a,
        product_type="CUSTOM_WIDGET",
        product_id="custom_x",
        display_code="X-01",
        width_mm=700,
        height_mm=700,
        x_mm=3200,
        y_mm=0,
    )
    conn = ds.create_connection(
        assembly_id=a01["assemblyId"],
        company_gst=gst_a,
        element_a_id=w01["elementId"],
        element_b_id=r01["elementId"],
        connection_type="adjacent_independent",
        side_a="right",
        side_b="left",
    )

    scene = ds.build_scene_read_model(did, company_gst=gst_a)

    # --- A: scene load Floor→Location→Assembly→Elements→Connections ---
    vm = uc.build_canvas_view_model(scene)
    _ok(vm["host"] == "UniversalCanvas", "A host name")
    _ok(len(vm["elements"]) >= 4, f"A elements loaded {len(vm['elements'])}")
    _ok(len(vm["connections"]) == 1, "A connections loaded")
    _ok(any(f.get("floorId") == floor_id for f in vm["floors"]), "A floor present")
    _ok(
        any(
            e.get("locationId") == loc_id and e.get("assemblyId") == a01["assemblyId"]
            for e in vm["elements"]
        ),
        "A location/assembly linkage",
    )
    print("OK: A scene load")

    # --- B: mixed products ---
    pts = {e["productType"] for e in vm["elements"]}
    _ok(
        {"SLIDING_WINDOW", "RAILING", "VENTILATOR", "CUSTOM_WIDGET"} <= pts,
        f"B mixed products {pts}",
    )
    print("OK: B mixed products")

    # --- C: unequal / offset geometry visible ---
    by_code = {e["displayCode"]: e for e in vm["elements"]}
    _ok(by_code["W-01"]["widthMm"] == 1800 and by_code["W-01"]["heightMm"] == 1500, "C W-01 dims")
    _ok(by_code["R-01"]["widthMm"] == 2400 and by_code["R-01"]["xMm"] == 2000, "C R-01 offset")
    _ok(by_code["V-01"]["yMm"] == 1600 and by_code["V-01"]["heightMm"] == 400, "C V-01 offset")
    _ok(
        by_code["W-01"]["widthMm"] != by_code["R-01"]["widthMm"]
        and by_code["W-01"]["xMm"] != by_code["R-01"]["xMm"],
        "C unequal geometry",
    )
    print("OK: C unequal geometry")

    # --- D: stable IDs + labels from scene (not DOM order) ---
    _ok(all(str(e["elementId"]).startswith("ELM-") for e in vm["elements"]), "D elementId prefix")
    _ok(by_code["W-01"]["label"] == "W-01", "D label W-01 from scene")
    _ok(by_code["R-01"]["elementId"] == r01["elementId"], "D stable R-01 id")
    ids1 = [e["elementId"] for e in vm["elements"]]
    ids2 = [e["elementId"] for e in uc.build_canvas_view_model(scene)["elements"]]
    _ok(ids1 == ids2, "D ids stable across rebuild")
    print("OK: D IDs and labels")

    # --- E: adapter lookup + fallback ---
    reg = uc.build_default_registry()
    _ok(reg.lookup("SLIDING_WINDOW") is not None, "E sliding adapter registered")
    _ok(reg.lookup("RAILING") is not None, "E railing adapter registered")
    _ok(reg.lookup("CUSTOM_WIDGET") is None, "E unknown not registered")
    rendered_known = reg.render(w01, {"previewSvg": "<svg id='prev'/>"})
    _ok(
        rendered_known.get("kind") == "preview_svg" and "prev" in (rendered_known.get("svg") or ""),
        "E known uses preview svg",
    )
    rendered_fallback = reg.render(x01)
    _ok(
        rendered_fallback.get("kind") == "placeholder"
        and rendered_fallback.get("usedFallback") is True
        and "X-01" in (rendered_fallback.get("svg") or ""),
        "E fallback placeholder",
    )
    # No giant if/elif product calc in canvas module — registry only
    src = Path(__file__).resolve().parents[0] / "factory" / "universal_canvas.py"
    text = src.read_text(encoding="utf-8")
    _ok("compute_quotation" not in text and "railing_svg" not in text, "E no engine calc in host")
    print("OK: E adapter lookup+fallback")

    # --- F: connection model (explicit only) ---
    _ok(vm["connections"][0]["connectionId"] == conn["connectionId"], "F connection id")
    _ok(
        not ds.elements_are_connected(w01["elementId"], v01["elementId"], company_gst=gst_a),
        "F touching/near does not imply connection",
    )
    _ok(
        ds.elements_are_connected(w01["elementId"], r01["elementId"], company_gst=gst_a),
        "F explicit connection true",
    )
    print("OK: F connection model")

    # --- G: tenant isolation ---
    client = TestClient(app)
    r_flags = client.get("/api/flags")
    _ok(r_flags.status_code == 200 and r_flags.json().get("universalCanvas") is False, "G flags default off")
    os.environ["WEOS_UNIVERSAL_CANVAS"] = "1"
    r_flags2 = client.get("/api/flags")
    _ok(r_flags2.json().get("WEOS_UNIVERSAL_CANVAS") is True, "G flags reflect env")
    os.environ["WEOS_UNIVERSAL_CANVAS"] = "0"

    r_ok = client.get(f"/api/design-documents/{did}/canvas", headers=hdr_a)
    _ok(r_ok.status_code == 200 and len(r_ok.json().get("elements") or []) >= 4, "G owner canvas ok")
    r_deny = client.get(f"/api/design-documents/{did}/canvas", headers=hdr_b)
    _ok(r_deny.status_code in (403, 404), f"G cross-tenant canvas deny {r_deny.status_code}")
    r_unauth = client.get(f"/api/design-documents/{did}/canvas")
    _ok(r_unauth.status_code in (401, 403, 404), f"G unauth canvas {r_unauth.status_code}")
    print("OK: G tenant isolation")

    # --- H: durable pose save/reload (drag deferred; API pose is SoT) ---
    _ok(uc.ELEMENT_DRAG_ENABLED is False, "H element drag deferred")
    r_pose = client.patch(
        f"/api/elements/{r01['elementId']}/pose",
        headers=hdr_a,
        json={"xMm": 2100, "yMm": 150},
    )
    _ok(r_pose.status_code == 200, f"H pose patch {r_pose.status_code}")
    body = r_pose.json()
    _ok(body.get("xMm") == 2100 and body.get("yMm") == 150, "H pose response")
    _ok(body.get("widthMm") == 2400 and body.get("heightMm") == 900, "H engineering dims untouched")
    reloaded = ds.get_element(r01["elementId"], company_gst=gst_a)
    _ok(reloaded and reloaded["xMm"] == 2100 and reloaded["yMm"] == 150, "H SQL reload pose")
    vm2 = uc.build_canvas_view_model(ds.build_scene_read_model(did, company_gst=gst_a))
    r01b = next(e for e in vm2["elements"] if e["elementId"] == r01["elementId"])
    _ok(r01b["xMm"] == 2100 and r01b["widthMm"] == 2400, "H canvas reflects SQL pose")

    # Zoom display-only: world→viewport must not mutate dims
    vx, vy = uc.world_to_viewport(100, 200, pan_x=10, pan_y=20, zoom=2)
    _ok(vx == 210 and vy == 420, f"H world_to_viewport {vx},{vy}")
    wx, wy = uc.viewport_to_world(vx, vy, pan_x=10, pan_y=20, zoom=2)
    _ok(abs(wx - 100) < 1e-9 and abs(wy - 200) < 1e-9, "H viewport_to_world inverse")
    # Selection dims = engineering values
    vm_sel = uc.build_canvas_view_model(
        ds.build_scene_read_model(did, company_gst=gst_a),
        selected_element_ids=[w01["elementId"]],
    )
    _ok(
        vm_sel["selected"]
        and vm_sel["selected"]["widthMm"] == 1800
        and vm_sel["selected"]["heightMm"] == 1500
        and vm_sel["selected"]["elementId"] == w01["elementId"]
        and vm_sel["selected"]["floorId"] == floor_id
        and vm_sel["selected"]["locationId"] == loc_id,
        "H selection exposes engineering dims + hierarchy",
    )
    # Cross-tenant cannot pose-update
    r_pose_deny = client.patch(
        f"/api/elements/{r01['elementId']}/pose",
        headers=hdr_b,
        json={"xMm": 9999},
    )
    _ok(r_pose_deny.status_code in (403, 404), f"H pose tenant deny {r_pose_deny.status_code}")
    print("OK: H save/reload pose + zoom display-only")

    # Floor/location filter uses canonical IDs
    vm_f = uc.build_canvas_view_model(scene, floor_id=floor_id, location_id=loc_id)
    _ok(all(e["floorId"] == floor_id for e in vm_f["elements"]), "filter floorId")
    _ok(all(e["locationId"] == loc_id for e in vm_f["elements"]), "filter locationId")

    # Static canvas JS modules present
    web = Path(__file__).resolve().parents[0] / "website" / "canvas"
    for name in (
        "universal_canvas.js",
        "viewport.js",
        "scene_renderer.js",
        "selection.js",
        "adapters.js",
    ):
        _ok((web / name).is_file(), f"JS module {name}")

    print("OK universal canvas smoke A–H")


if __name__ == "__main__":
    main()
