"""Smoke: Assembly / Element / Connection scene domain (Batch 6) — cases 1–7."""

from __future__ import annotations

import copy
import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_design_scene_"))
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
    from WEOS.factory import design_scene as ds
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.project_store import empty_project, save_project

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    gst_a = "22AAAAA0000A1Z5"
    gst_b = "22BBBBB0000B1Z5"

    cust = create_customer(gst_a, display_name="Scene Cust", mobile="9333444555")
    upsert_project(
        project_id="PRJ-2026-SCENE1",
        customer_id=cust["customerId"],
        company_gst=gst_a,
        name="Scene Job",
        status="draft",
    )
    pid = "PRJ-2026-SCENE1"
    doc = empty_project(name="Scene Job", customer="Scene Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst_a
    doc["customerMobile"] = "9333444555"
    doc["customerId"] = cust["customerId"]
    cart_line = {
        "lineId": "LINE-OLD-1",
        "product": "29mm_sliding",
        "productType": "sliding",
        "width": 1800,
        "height": 1500,
        "qty": 2,
        "locationName": "Living Room",
        "sellingRate": 450.0,
        "previewSvg": "<svg id='keep-me'/>",
        "sectionSeries": "29mm",
        "colour": "white",
    }
    doc["lines"] = [copy.deepcopy(cart_line)]
    save_project(doc, action="smoke")

    des = dh.ensure_design_document(pid, gst_a)
    did = des["designDocumentId"]
    living = dh.resolve_location_for_legacy_name(
        project_id=pid, company_gst=gst_a, location_name="Living Room", create=True
    )

    # --- CASE 1: Single Window A-01 → W-01 Sliding 1800×1500 ---
    a01 = ds.create_assembly(
        design_document_id=did,
        company_gst=gst_a,
        name="Single Sliding",
        display_code="A-01",
        location_id=living["locationId"],
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
        config_payload={"sectionSeries": "29mm"},
    )
    _ok(
        a01["displayCode"] == "A-01"
        and w01["displayCode"] == "W-01"
        and w01["productType"] == "SLIDING_WINDOW"
        and w01["widthMm"] == 1800
        and w01["heightMm"] == 1500,
        "CASE1 single window",
    )
    _ok(
        "sectionSeries" not in (w01.get("geometryPayload") or {}),
        "CASE1 geometry independent of series",
    )

    # --- CASE 2: Combination unequal sizes + mixed products ---
    a02 = ds.create_assembly(
        design_document_id=did,
        company_gst=gst_a,
        name="Living Room Combined Window",
        display_code="A-02",
        location_id=living["locationId"],
    )
    w02 = ds.create_element(
        assembly_id=a02["assemblyId"],
        company_gst=gst_a,
        product_type="SLIDING_WINDOW",
        display_code="W-02",
        width_mm=2000,
        height_mm=1500,
        x_mm=0,
        y_mm=0,
    )
    w03 = ds.create_element(
        assembly_id=a02["assemblyId"],
        company_gst=gst_a,
        product_type="FIXED_WINDOW",
        display_code="W-03",
        width_mm=1000,
        height_mm=1800,
        x_mm=2000,
        y_mm=0,
    )
    v01 = ds.create_element(
        assembly_id=a02["assemblyId"],
        company_gst=gst_a,
        product_type="VENTILATOR",
        display_code="V-01",
        width_mm=1000,
        height_mm=600,
        x_mm=2000,
        y_mm=1800,
    )
    _ok(
        w02["widthMm"] == 2000
        and w03["heightMm"] == 1800
        and w03["xMm"] == 2000
        and v01["productType"] == "VENTILATOR"
        and {w02["productType"], w03["productType"], v01["productType"]}
        == {"SLIDING_WINDOW", "FIXED_WINDOW", "VENTILATOR"},
        "CASE2 mixed unequal products",
    )

    # --- CASE 3: Explicit connection ---
    conn = ds.create_connection(
        assembly_id=a02["assemblyId"],
        company_gst=gst_a,
        element_a_id=w02["elementId"],
        element_b_id=w03["elementId"],
        connection_type="frame_to_frame",
        side_a="right",
        side_b="left",
    )
    _ok(
        conn["connectionType"] == "frame_to_frame"
        and ds.elements_are_connected(w02["elementId"], w03["elementId"], company_gst=gst_a),
        "CASE3 explicit connection",
    )

    # --- CASE 4: No implicit connection (touching geometry alone) ---
    # Place W-01 visually adjacent to a new element without Connection row
    touch = ds.create_element(
        assembly_id=a01["assemblyId"],
        company_gst=gst_a,
        product_type="FIXED_WINDOW",
        display_code="W-99",
        width_mm=500,
        height_mm=1500,
        x_mm=1800,
        y_mm=0,
    )
    _ok(
        not ds.elements_are_connected(w01["elementId"], touch["elementId"], company_gst=gst_a),
        "CASE4 touching geometry remains unconnected",
    )

    # --- CASE 5: Save/reload exact geometry ---
    w02_r = ds.get_element(w02["elementId"], company_gst=gst_a)
    w03_r = ds.get_element(w03["elementId"], company_gst=gst_a)
    v01_r = ds.get_element(v01["elementId"], company_gst=gst_a)
    _ok(
        w02_r
        and w02_r["widthMm"] == 2000
        and w02_r["heightMm"] == 1500
        and w02_r["xMm"] == 0
        and w03_r
        and w03_r["widthMm"] == 1000
        and w03_r["heightMm"] == 1800
        and w03_r["xMm"] == 2000
        and v01_r
        and v01_r["yMm"] == 1800
        and v01_r["displayCode"] == "V-01",
        "CASE5 reload preserves geometry + ids",
    )
    scene = ds.build_scene_read_model(did, company_gst=gst_a)
    _ok(
        scene.get("designDocumentId") == did and isinstance(scene.get("floors"), list),
        "CASE5 scene read model shape",
    )

    # --- CASE 6: Tenant isolation ---
    create_customer(gst_b, display_name="Other Scene", mobile="9444555666")
    _ok(ds.get_assembly(a01["assemblyId"], company_gst=gst_b) is None, "CASE6 assembly hidden")
    _ok(ds.get_element(w01["elementId"], company_gst=gst_b) is None, "CASE6 element hidden")
    ws_a = open_workspace(
        gst_a,
        profile={"companyName": "Scene A", "phone": "9000000033", "email": "sa@ex.com"},
        pin="1111",
    )
    ws_b = open_workspace(
        gst_b,
        profile={"companyName": "Scene B", "phone": "9000000044", "email": "sb@ex.com"},
        pin="2222",
    )
    client = TestClient(app)
    r = client.get(f"/api/design-documents/{did}/scene", headers={"X-WEOS-Session": ws_a["sessionToken"]})
    _ok(r.status_code == 200 and r.json().get("designDocumentId") == did, f"CASE6 A scene {r.status_code}")
    r = client.get(f"/api/design-documents/{did}/scene", headers={"X-WEOS-Session": ws_b["sessionToken"]})
    _ok(r.status_code == 404, f"CASE6 B scene denied {r.status_code}")

    # --- CASE 7: Old single cart line adapter ---
    before = copy.deepcopy(cart_line)
    adapted = ds.adapt_cart_line_to_assembly_element(
        design_document_id=did, company_gst=gst_a, line=cart_line
    )
    _ok(adapted.get("mapped") in {"created", "existing"}, f"CASE7 adapted {adapted.get('mapped')}")
    el = adapted["element"]
    asm = adapted["assembly"]
    _ok(asm and el and el["productType"] == "SLIDING_WINDOW", "CASE7 product identity Sliding")
    _ok(el["widthMm"] == 1800 and el["heightMm"] == 1500 and el["quantity"] == 2, "CASE7 dims+qty")
    _ok(el.get("legacyLineId") == "LINE-OLD-1", "CASE7 legacy line link")
    unchanged = adapted.get("unchanged") or {}
    _ok(
        unchanged.get("width") == before["width"]
        and unchanged.get("height") == before["height"]
        and unchanged.get("product") == before["product"]
        and unchanged.get("locationName") == before["locationName"]
        and unchanged.get("qty") == before["qty"]
        and unchanged.get("sellingRate") == before["sellingRate"]
        and unchanged.get("previewSvg") == before["previewSvg"],
        "CASE7 cart fields unchanged by adapter",
    )
    # cart line object itself must not be mutated
    _ok(cart_line == before, "CASE7 line dict not mutated")

    mig = ds.migrate_cart_lines_to_scene(company_gst=gst_a, project_id=pid)
    _ok(mig.get("ok") is True and mig.get("zeroSilentLoss") is True, f"CASE7 migrate {mig}")
    print(
        "MIGRATE_DESIGN_SCENE_COUNTS",
        {
            "legacyLinesInspected": mig.get("legacyLinesInspected"),
            "assembliesMapped": mig.get("assembliesMapped"),
            "elementsMapped": mig.get("elementsMapped"),
            "unmapped": mig.get("unmapped"),
            "conflicts": mig.get("conflicts"),
            "rejected": mig.get("rejected"),
            "manualReview": len(mig.get("manualReview") or []),
            "zeroSilentLoss": mig.get("zeroSilentLoss"),
        },
    )

    print("OK design scene smoke")


if __name__ == "__main__":
    main()
