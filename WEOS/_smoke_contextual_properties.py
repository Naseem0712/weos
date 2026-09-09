"""Smoke: Contextual Property Panel (Batch 9) — schemas, IDs, no cross-pollution, save/reload."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_contextual_props_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
os.environ["WEOS_UNIVERSAL_CANVAS"] = "0"


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def _field_keys(schema: dict) -> set[str]:
    keys: set[str] = set()
    for g in schema.get("groups") or []:
        for f in g.get("fields") or []:
            if f.get("key"):
                keys.add(str(f["key"]))
    return keys


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fastapi.testclient import TestClient

    from WEOS.api.server import app
    from WEOS.db.engine import init_db
    from WEOS.factory import contextual_properties as cp
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory import design_scene as ds
    from WEOS.factory import product_adapters as pa
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.project_store import empty_project, save_project

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    # --- Window schema ---
    win_schema = pa.property_schema_for("SLIDING_WINDOW")
    _ok(win_schema.get("adapterId") == "window_family", "Window schema loads")
    win_keys = _field_keys(win_schema)
    _ok("widthMm" in win_keys and "heightMm" in win_keys, "Window geometry fields")
    _ok("sectionSeries" in win_keys or "glass" in win_keys, "Window config fields")
    _ok("mountType" not in win_keys, "No railing mount on window schema")

    # --- Railing schema ---
    rail_schema = pa.property_schema_for("RAILING")
    _ok(rail_schema.get("adapterId") == "railing", "Railing schema loads")
    rail_keys = _field_keys(rail_schema)
    _ok("mountType" in rail_keys or "shape" in rail_keys, "Railing system/shape fields")
    _ok("sectionSeries" not in rail_keys, "No window series on railing schema")

    # --- Ventilator schema ---
    vent_schema = pa.property_schema_for("VENTILATOR")
    _ok(vent_schema.get("adapterId") == "ventilator", "Ventilator schema loads")
    vent_keys = _field_keys(vent_schema)
    _ok("widthMm" in vent_keys, "Ventilator width")
    _ok("mountType" not in vent_keys, "No railing mount on ventilator")

    # --- Assembly / Connection schemas ---
    asm_schema = pa.property_schema_for("ASSEMBLY")
    _ok(asm_schema.get("adapterId") == "assembly", "Assembly schema loads")
    _ok("assemblyId" in _field_keys(asm_schema), "Assembly ID field")

    conn_schema = pa.property_schema_for("CONNECTION")
    _ok(conn_schema.get("adapterId") == "connection", "Connection schema loads")
    _ok("connectionId" in _field_keys(conn_schema), "Connection ID field")
    _ok("elementAId" in _field_keys(conn_schema), "Connection element A")

    # --- No cross-product pollution ---
    _ok(not cp.schemas_cross_pollute(win_schema, rail_schema), "No cross-product pollution helper")
    _ok("mountType" not in win_keys, "Railing fields not active on Window")
    _ok("glassShutters" not in rail_keys and "trackCount" not in rail_keys, "Window track not on Railing")

    # Fixture project
    gst = "22AAAAA0000A1Z5"
    ws = open_workspace(
        gst,
        profile={"companyName": "Props Co", "phone": "9000000444", "email": "pp@ex.com"},
        pin="4444",
    )
    tok = ws["sessionToken"]
    hdr = {"X-WEOS-Session": tok}

    cust = create_customer(gst, display_name="Props Cust", mobile="9666777888")
    upsert_project(
        project_id="PRJ-2026-PROPS1",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Props Job",
        status="draft",
    )
    pid = "PRJ-2026-PROPS1"
    doc = empty_project(name="Props Job", customer="Props Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerMobile"] = "9666777888"
    doc["customerId"] = cust["customerId"]
    doc["lines"] = []
    save_project(doc, action="smoke")

    des = dh.ensure_design_document(pid, gst)
    did = des["designDocumentId"]
    living = dh.resolve_location_for_legacy_name(
        project_id=pid, company_gst=gst, location_name="Lobby", create=True
    )
    a01 = ds.create_assembly(
        design_document_id=did,
        company_gst=gst,
        name="Props Assembly",
        display_code="A-01",
        location_id=living["locationId"],
    )
    w01 = ds.create_element(
        assembly_id=a01["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1800,
        height_mm=1500,
        display_code="W-01",
        config_payload={"glass": "8mm_toughened", "colour": "Black"},
    )
    r01 = ds.create_element(
        assembly_id=a01["assemblyId"],
        company_gst=gst,
        product_type="RAILING",
        width_mm=3000,
        height_mm=1000,
        display_code="R-01",
        config_payload={"shape": "straight", "mountType": "side_mount"},
    )
    v01 = ds.create_element(
        assembly_id=a01["assemblyId"],
        company_gst=gst,
        product_type="VENTILATOR",
        width_mm=600,
        height_mm=400,
        display_code="V-01",
    )
    c01 = ds.create_connection(
        assembly_id=a01["assemblyId"],
        company_gst=gst,
        element_a_id=w01["elementId"],
        element_b_id=r01["elementId"],
        connection_type="adjacent_independent",
        side_a="right",
        side_b="left",
    )

    # Panel builders use stable IDs
    panel_w = cp.panel_for_element(w01)
    _ok(panel_w["selection"]["elementId"] == w01["elementId"], "Stable element identity")
    _ok(panel_w["selection"]["kind"] == "element", "Selection kind element")
    _ok(panel_w["values"]["productType"] == "SLIDING_WINDOW", "Panel window type")

    panel_r = cp.panel_for_element(r01)
    _ok(panel_r["values"]["productType"] == "RAILING", "Panel railing type")
    _ok("mountType" in (panel_r["values"] or {}) or "shape" in (panel_r["values"] or {}), "Railing values")

    panel_v = cp.panel_for_element(v01)
    _ok(panel_v["values"]["productType"] == "VENTILATOR", "Panel ventilator type")

    panel_a = cp.panel_for_assembly(a01, child_count=3, connection_count=1)
    _ok(panel_a["selection"]["assemblyId"] == a01["assemblyId"], "Stable assembly identity")
    _ok(panel_a["values"]["childCount"] == 3, "Assembly child count")

    panel_c = cp.panel_for_connection(c01)
    _ok(panel_c["selection"]["connectionId"] == c01["connectionId"], "Stable connection identity")

    # Geometry vs config split
    geom, cfg = cp.split_geometry_and_config(
        {"widthMm": 2000, "heightMm": 1600, "colour": "White", "mesh": True, "elementId": "x"}
    )
    _ok(geom.get("widthMm") == 2000 and "colour" not in geom, "Geometry split")
    _ok(cfg.get("colour") == "White" and "widthMm" not in cfg, "Config split")

    # Save/reload via apply_element_property_update
    saved = cp.apply_element_property_update(
        w01["elementId"],
        company_gst=gst,
        patch={"widthMm": 2050, "colour": "White Texture", "mesh": True},
    )
    _ok(saved.get("persisted") is True, "Property update persisted")
    _ok(saved["element"]["widthMm"] == 2050, "Geometry saved")
    _ok(saved["element"]["productType"] == "SLIDING_WINDOW", "Type retained on save")
    _ok((saved["element"].get("configPayload") or {}).get("colour") == "White Texture", "Config colour saved")
    _ok((saved["element"].get("configPayload") or {}).get("glass") == "8mm_toughened", "Prior glass merged")

    reloaded = ds.get_element(w01["elementId"], company_gst=gst)
    _ok(reloaded["widthMm"] == 2050, "Reload geometry")
    _ok((reloaded.get("configPayload") or {}).get("colour") == "White Texture", "Reload config")

    # API property panel
    client = TestClient(app)
    none = client.get("/api/property-panel?kind=none", headers=hdr)
    _ok(none.status_code == 200 and none.json().get("kind") == "none", "Empty panel guidance")

    el_panel = client.get(
        f"/api/property-panel?kind=element&id={w01['elementId']}",
        headers=hdr,
    )
    _ok(el_panel.status_code == 200, f"element panel API {el_panel.status_code}")
    _ok(el_panel.json()["selection"]["elementId"] == w01["elementId"], "API selection uses elementId")
    _ok(el_panel.json()["values"]["productType"] == "SLIDING_WINDOW", "API window panel")

    rail_panel = client.get(
        f"/api/property-panel?kind=element&id={r01['elementId']}",
        headers=hdr,
    )
    _ok(rail_panel.json()["values"]["productType"] == "RAILING", "API railing panel")
    rail_schema_keys = _field_keys(rail_panel.json().get("schema") or {})
    win_schema_keys = _field_keys(el_panel.json().get("schema") or {})
    _ok("mountType" not in win_schema_keys, "API window schema no mountType")
    _ok("trackCount" not in rail_schema_keys, "API railing schema no trackCount")

    asm_api = client.get(
        f"/api/property-panel?kind=assembly&id={a01['assemblyId']}",
        headers=hdr,
    )
    _ok(asm_api.status_code == 200, "assembly panel API")
    _ok(asm_api.json()["selection"]["assemblyId"] == a01["assemblyId"], "assembly id selection")

    conn_api = client.get(
        f"/api/property-panel?kind=connection&id={c01['connectionId']}",
        headers=hdr,
    )
    _ok(conn_api.status_code == 200, "connection panel API")
    _ok(conn_api.json()["selection"]["connectionId"] == c01["connectionId"], "connection id selection")

    upd = client.post(
        f"/api/property-panel/element/{w01['elementId']}",
        headers=hdr,
        json={"heightMm": 1555, "config": {"handle": "Ozone"}},
    )
    _ok(upd.status_code == 200 and upd.json().get("persisted") is True, "panel update API persisted")
    _ok(upd.json()["element"]["heightMm"] == 1555, "panel update height")
    _ok((upd.json()["element"].get("configPayload") or {}).get("handle") == "Ozone", "panel update handle")

    # JS module present
    js = Path(__file__).resolve().parent / "website" / "canvas" / "property_panel.js"
    _ok(js.is_file(), "property_panel.js present")
    text = js.read_text(encoding="utf-8")
    _ok("hideLegacyTools" in text and "uc-mode" in text or "uc-legacy-hidden" in text, "legacy wrap helpers")
    _ok("elementId" in text and "assemblyId" in text and "connectionId" in text, "stable ID selection")

    # Flag rollback: default OFF means legacy UI path still valid conceptually
    from WEOS.factory import universal_canvas as uc

    _ok(uc.is_universal_canvas_enabled() is False, "flag default OFF keeps old UI path")

    print("SMOKE_CONTEXTUAL_PROPERTIES_OK")


if __name__ == "__main__":
    main()
