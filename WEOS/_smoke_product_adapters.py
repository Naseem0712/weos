"""Smoke: Product Plugin Adapters (Batch 8) — Sliding/Fixed/Casement/Ventilator/Railing/Unknown/Mixed/identity."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_product_adapters_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
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
    from WEOS.factory import product_adapters as pa
    from WEOS.factory import universal_canvas as uc
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.project_store import empty_project, save_project

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    reg = pa.DEFAULT_PRODUCT_REGISTRY

    # --- Sliding ---
    sliding_ad = reg.resolve("SLIDING_WINDOW")
    _ok(sliding_ad.adapter_id == "window_family", "Sliding adapter chosen")
    _ok(sliding_ad.supports("SLIDING_WINDOW"), "Sliding supports")
    el_s = {
        "elementId": "ELM-S",
        "productType": "SLIDING_WINDOW",
        "widthMm": 2050,
        "heightMm": 1970,
        "displayCode": "W-01",
        "configPayload": {"glass": "8mm_toughened", "colour": "Black Texture"},
    }
    prev_s = sliding_ad.render_preview(el_s)
    _ok(prev_s.get("productType") == "SLIDING_WINDOW", "Sliding identity in preview")
    _ok(prev_s.get("usedFallback") is False, "Sliding engine preview")
    _ok("<svg" in str(prev_s.get("svg") or ""), "Sliding SVG")
    _ok("WINDOW" != prev_s.get("productType"), "Sliding not collapsed to WINDOW")

    # --- Fixed ---
    fixed_ad = reg.resolve("FIXED_WINDOW")
    _ok(fixed_ad.adapter_id == "window_family", "Fixed adapter")
    el_f = {
        "elementId": "ELM-F",
        "productType": "FIXED_WINDOW",
        "widthMm": 1200,
        "heightMm": 1200,
        "displayCode": "F-01",
        "configPayload": {},
    }
    prev_f = fixed_ad.render_preview(el_f)
    _ok(prev_f.get("productType") == "FIXED_WINDOW", "Fixed identity preserved")
    _ok(prev_f.get("usedFallback") is False, "Fixed engine preview")
    _ok("<svg" in str(prev_f.get("svg") or ""), "Fixed SVG")

    # --- Casement ---
    case_ad = reg.resolve("CASEMENT_WINDOW")
    _ok(case_ad.adapter_id == "window_family", "Casement adapter")
    el_c = {
        "elementId": "ELM-C",
        "productType": "CASEMENT_WINDOW",
        "widthMm": 2050,
        "heightMm": 1970,
        "configPayload": {
            "system": "casement",
            "glassCount": 2,
            "sashOverlapMm": 15,
            "mullionGapMm": 15,
            "handleOverrides": {
                "0": {"role": "fix", "side": "none"},
                "1": {"role": "openable", "side": "right"},
            },
        },
    }
    prev_c = case_ad.render_preview(el_c)
    _ok(prev_c.get("productType") == "CASEMENT_WINDOW", "Casement identity")
    _ok(prev_c.get("usedFallback") is False, "Casement engine preview")
    _ok("<svg" in str(prev_c.get("svg") or ""), "Casement SVG")

    # --- Ventilator ---
    vent_ad = reg.resolve("VENTILATOR")
    _ok(vent_ad.adapter_id == "ventilator", "Ventilator adapter")
    el_v = {
        "elementId": "ELM-V",
        "productType": "VENTILATOR",
        "widthMm": 600,
        "heightMm": 400,
        "configPayload": {},
    }
    prev_v = vent_ad.render_preview(el_v)
    _ok(prev_v.get("productType") == "VENTILATOR", "Ventilator identity")
    _ok(prev_v.get("usedFallback") is False, "Ventilator engine preview")
    _ok("<svg" in str(prev_v.get("svg") or ""), "Ventilator SVG")

    # --- Railing + calculate ---
    rail_ad = reg.resolve("RAILING")
    _ok(rail_ad.adapter_id == "railing", "Railing adapter")
    el_r = {
        "elementId": "ELM-R",
        "productType": "RAILING",
        "widthMm": 3000,
        "heightMm": 1000,
        "configPayload": {"shape": "straight", "panels": 4, "mountType": "side_mount"},
    }
    prev_r = rail_ad.render_preview(el_r)
    _ok(prev_r.get("productType") == "RAILING", "Railing identity")
    _ok(prev_r.get("usedFallback") is False, "Railing engine preview")
    _ok("<svg" in str(prev_r.get("svg") or ""), "Railing SVG")
    calc_r = rail_ad.calculate(el_r)
    _ok(isinstance(calc_r, dict) and (calc_r.get("panelCount") or calc_r.get("shape")), "Railing calculate works")

    # Stair railing still works through adapter
    el_stair = {
        "elementId": "ELM-RS",
        "productType": "RAILING",
        "widthMm": 3600,
        "heightMm": 1000,
        "configPayload": {"shape": "staircase", "stairSteps": 12, "mountType": "side_mount"},
    }
    calc_stair = rail_ad.calculate(el_stair)
    _ok(isinstance(calc_stair, dict), "Stair railing calculate")
    shape = str((calc_stair or {}).get("shape") or "").lower()
    _ok(shape == "staircase" or isinstance((calc_stair or {}).get("stairGeometry"), dict), "Stair geometry preserved")

    # --- Pergola first-class (Batch 8.5) ---
    perg_ad = reg.resolve("PERGOLA")
    _ok(perg_ad.adapter_id == "pergola", "Pergola first-class adapter")
    el_p = {
        "elementId": "ELM-P",
        "productType": "PERGOLA",
        "widthMm": 3000,
        "heightMm": 2400,
        "configPayload": {
            "postHeightMm": 2700,
            "structure": {"postCount": 4, "rafterCount": 6},
            "sides": {"front": {"treatment": "open"}, "back": {"treatment": "louvers"}},
            "roof": {"cover": "polycarbonate"},
            "finish": {"colour": "Black"},
        },
    }
    prev_p = perg_ad.render_preview(el_p)
    _ok(prev_p.get("productType") == "PERGOLA", "Pergola identity")
    _ok(prev_p.get("usedFallback") is False, "Pergola engine preview")
    _ok("<svg" in str(prev_p.get("svg") or "") and 'data-role="post"' in str(prev_p.get("svg") or ""), "Pergola SVG posts")
    pschema = perg_ad.get_property_schema()
    pgroups = {g.get("id") for g in (pschema.get("groups") or [])}
    _ok("side_treatments" in pgroups and "floor_deck" in pgroups and "summary" in pgroups, "Pergola property groups")

    # --- Unknown → fallback ---
    unk = reg.resolve("CUSTOM_WIDGET")
    _ok(unk.adapter_id == "fallback", "Unknown uses fallback")
    prev_u = unk.render_preview(
        {"elementId": "ELM-U", "productType": "CUSTOM_WIDGET", "widthMm": 800, "heightMm": 600, "displayCode": "X-01"}
    )
    _ok(prev_u.get("usedFallback") is True, "Unknown usedFallback")
    _ok(prev_u.get("kind") == "placeholder", "Unknown placeholder kind")
    _ok("<svg" in str(prev_u.get("svg") or ""), "Unknown placeholder SVG")

    # WINDOW collapse refused at registry level for schema API path
    win_ad = reg.resolve("WINDOW")
    _ok(win_ad.adapter_id == "fallback", "WINDOW collapses to fallback not window_family")

    # --- Mixed assembly on Universal Canvas view model ---
    gst = "22AAAAA0000A1Z5"
    ws = open_workspace(
        gst,
        profile={"companyName": "Adapter Co", "phone": "9000000333", "email": "ad@ex.com"},
        pin="3333",
    )
    tok = ws["sessionToken"]
    hdr = {"X-WEOS-Session": tok}

    cust = create_customer(gst, display_name="Adapter Cust", mobile="9555666777")
    upsert_project(
        project_id="PRJ-2026-ADAPT1",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Adapter Job",
        status="draft",
    )
    pid = "PRJ-2026-ADAPT1"
    doc = empty_project(name="Adapter Job", customer="Adapter Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerMobile"] = "9555666777"
    doc["customerId"] = cust["customerId"]
    doc["lines"] = []
    save_project(doc, action="smoke")

    des = dh.ensure_design_document(pid, gst)
    did = des["designDocumentId"]
    living = dh.resolve_location_for_legacy_name(
        project_id=pid, company_gst=gst, location_name="Hall", create=True
    )
    loc_id = living["locationId"]

    a01 = ds.create_assembly(
        design_document_id=did,
        company_gst=gst,
        name="Mixed Assembly",
        display_code="A-01",
        location_id=loc_id,
    )
    w01 = ds.create_element(
        assembly_id=a01["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1800,
        height_mm=1500,
        x_mm=0,
        y_mm=0,
        display_code="W-01",
        config_payload={"glass": "8mm_toughened"},
    )
    w02 = ds.create_element(
        assembly_id=a01["assemblyId"],
        company_gst=gst,
        product_type="FIXED_WINDOW",
        width_mm=900,
        height_mm=1500,
        x_mm=1900,
        y_mm=0,
        display_code="W-02",
    )
    v01 = ds.create_element(
        assembly_id=a01["assemblyId"],
        company_gst=gst,
        product_type="VENTILATOR",
        width_mm=600,
        height_mm=400,
        x_mm=0,
        y_mm=1600,
        display_code="V-01",
    )
    _ok(
        {w01["productType"], w02["productType"], v01["productType"]}
        == {"SLIDING_WINDOW", "FIXED_WINDOW", "VENTILATOR"},
        "Mixed A-01 product identities",
    )

    scene = ds.build_scene_read_model(did, company_gst=gst)
    view = uc.build_canvas_view_model(scene)
    _ok(view.get("host") == "UniversalCanvas", "ONE Universal Canvas host")
    pts = {e.get("productType") for e in view.get("elements") or []}
    _ok({"SLIDING_WINDOW", "FIXED_WINDOW", "VENTILATOR"} <= pts, "Mixed products on same canvas")
    # Engine previews via canvas_adapter_fn when no supplied SVG
    for e in view.get("elements") or []:
        r = e.get("render") or {}
        _ok(r.get("svg"), f"render svg for {e.get('displayCode')}")
        _ok(e.get("productType") != "WINDOW", f"{e.get('displayCode')} not WINDOW")

    # --- Identity save/reload ---
    updated = ds.update_element(
        w01["elementId"],
        company_gst=gst,
        config_payload={"colour": "White", "mesh": True},
        merge_config=True,
    )
    _ok(updated["productType"] == "SLIDING_WINDOW", "Save keeps Sliding type")
    _ok((updated.get("configPayload") or {}).get("colour") == "White", "Config colour saved")
    _ok((updated.get("configPayload") or {}).get("mesh") is True, "Config mesh saved")
    _ok((updated.get("configPayload") or {}).get("glass") == "8mm_toughened", "Merge keeps glass")

    reloaded = ds.get_element(w01["elementId"], company_gst=gst)
    _ok(reloaded and reloaded["productType"] == "SLIDING_WINDOW", "Reload retains Sliding")
    _ok((reloaded.get("configPayload") or {}).get("colour") == "White", "Reload colour")

    # Geometry vs config separation: W/H on element columns
    geo_up = ds.update_element(
        w01["elementId"],
        company_gst=gst,
        width_mm=2100,
        height_mm=1600,
        x_mm=50,
        y_mm=10,
    )
    _ok(geo_up["widthMm"] == 2100 and geo_up["heightMm"] == 1600, "Geometry W/H on element")
    _ok(geo_up["xMm"] == 50 and geo_up["yMm"] == 10, "Geometry X/Y on element")
    _ok((geo_up.get("configPayload") or {}).get("colour") == "White", "Config untouched by geom update")

    # API surface
    client = TestClient(app)
    listed = client.get("/api/adapters")
    _ok(listed.status_code == 200, f"GET /api/adapters {listed.status_code}")
    body = listed.json()
    _ok(body.get("host") == "UniversalCanvas", "adapters host UniversalCanvas")
    _ok("SLIDING_WINDOW" in (body.get("adapters") or []), "adapters list Sliding")

    sch = client.get("/api/adapters/SLIDING_WINDOW/schema")
    _ok(sch.status_code == 200, "Sliding schema")
    _ok(sch.json().get("adapterId") == "window_family", "schema adapterId")

    bad = client.get("/api/adapters/WINDOW/schema")
    _ok(bad.status_code == 400, "WINDOW schema refused")

    prev_api = client.post(
        f"/api/elements/{w01['elementId']}/preview",
        headers=hdr,
    )
    _ok(prev_api.status_code == 200, f"element preview API {prev_api.status_code}")
    _ok("<svg" in str(prev_api.json().get("svg") or ""), "element preview SVG")
    _ok(prev_api.json().get("productType") == "SLIDING_WINDOW", "API preview identity")

    patch = client.patch(
        f"/api/elements/{w01['elementId']}",
        headers=hdr,
        json={"configPayload": {"handle": "Ozone"}, "widthMm": 2150},
    )
    _ok(patch.status_code == 200, f"element patch {patch.status_code}")
    _ok(patch.json().get("persisted") is True, "patch persisted")
    _ok(patch.json()["element"]["widthMm"] == 2150, "patch width")
    _ok(patch.json()["element"]["productType"] == "SLIDING_WINDOW", "patch keeps type")

    # Cross-check: no WindowCanvas / RailingCanvas modules invented
    canvas_dir = Path(__file__).resolve().parent / "website" / "canvas"
    names = {p.name.lower() for p in canvas_dir.glob("*.js")}
    _ok("window_canvas.js" not in names and "railing_canvas.js" not in names, "no duplicate product canvases")

    print("SMOKE_PRODUCT_ADAPTERS_OK")


if __name__ == "__main__":
    main()
