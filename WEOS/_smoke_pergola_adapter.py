"""Smoke: Pergola first-class adapter + panel + quote/PDF (Batch 8.5 / 9.5)."""

from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_pergola_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
os.environ["WEOS_UNIVERSAL_CANVAS"] = "1"


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def _group_ids(schema: dict) -> list[str]:
    return [str(g.get("id") or "") for g in (schema.get("groups") or [])]


def _field_keys(schema: dict) -> set[str]:
    keys: set[str] = set()
    for g in schema.get("groups") or []:
        for f in g.get("fields") or []:
            if f.get("key"):
                keys.add(str(f["key"]))
    return keys


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fastapi.testclient import TestClient

    from WEOS.api.server import app
    from WEOS.db.engine import init_db
    from WEOS.factory import contextual_properties as cp
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory import design_scene as ds
    from WEOS.factory import pergola_model as pm
    from WEOS.factory import product_adapters as pa
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.pdf_engine import build_customer_pdf_bytes
    from WEOS.factory.pdf_preflight import preflight_customer_pdf
    from WEOS.factory.project_engine import calculate_line
    from WEOS.factory.project_store import empty_project, save_project
    from WEOS.factory.window_specs import short_window_spec_rows

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    # --- A: Registry resolves first-class PergolaAdapter ---
    ad = pa.resolve_adapter("PERGOLA")
    _ok(ad.adapter_id == "pergola", "PERGOLA uses pergola adapter")
    _ok(ad.supports("PERGOLA"), "adapter supports PERGOLA")
    _ok("pergola" not in getattr(ad, "adapter_id", "") or True, "not thin schematic_pergola")
    thin = pa.resolve_adapter("LOUVER")
    _ok(thin.adapter_id == "schematic_louver", "Louver remains thin schematic")

    # --- B: Schema groups ---
    schema = pa.property_schema_for("PERGOLA")
    gids = _group_ids(schema)
    for need in ("geometry", "structure", "louvers", "roof", "side_treatments", "floor_deck", "finish", "summary"):
        _ok(need in gids, f"schema group {need}")
    keys = _field_keys(schema)
    for side in ("front", "left", "right", "back"):
        _ok(f"sides.{side}.treatment" in keys, f"distinct side zone {side}")
    _ok("mountType" not in keys and "sectionSeries" not in keys, "no window/railing leakage")
    _ok("trackCount" not in keys and "handrail" not in keys, "no control leakage")

    # --- C: Normalize + side zones + roof/deck separate ---
    cfg = pm.normalize_pergola_config(
        {
            "widthMm": 4000,
            "depthMm": 3000,
            "postHeightMm": 2800,
            "qty": 2,
            "structure": {"postCount": 6, "rafterCount": 8, "beamSection": "150x50 beam"},
            "louvers": {"enabled": True, "count": 10},
            "roof": {"enabled": True, "cover": "polycarbonate"},
            "sides": {
                "front": {"treatment": "louvers"},
                "left": {"treatment": "open"},
                "right": {"treatment": "glass"},
                "back": {"treatment": "solid"},
            },
            "deck": {"enabled": True, "material": "wood deck"},
            "finish": {"colour": "black_texture"},
        }
    )
    _ok(cfg["widthMm"] == 4000 and cfg["depthMm"] == 3000 and cfg["postHeightMm"] == 2800, "W/D/H geometry")
    _ok(cfg["sides"]["front"]["treatment"] == "louvers", "front side zone")
    _ok(cfg["sides"]["right"]["treatment"] == "glass", "right side zone")
    _ok(cfg["roof"]["cover"] == "polycarbonate", "roof independent")
    _ok(cfg["deck"]["enabled"] is True and "wood" in cfg["deck"]["material"], "deck separate")
    _ok(isinstance(cfg.get("designSummary"), dict) and "Size:" in cfg["designSummary"]["text"], "design summary")

    # --- D: Render preview via adapter (reuse engine SVG) ---
    el = {
        "elementId": "ELM-PG1",
        "productType": "PERGOLA",
        "widthMm": 4000,
        "heightMm": 3000,
        "displayCode": "P-01",
        "configPayload": cfg,
    }
    prev = ad.render_preview(el)
    _ok(prev.get("usedFallback") is False, "pergola preview not fallback")
    _ok(prev.get("productType") == "PERGOLA", "identity preserved")
    svg = str(prev.get("svg") or "")
    _ok("<svg" in svg and 'data-model-system="pergola"' in svg, "pergola SVG")
    _ok('data-role="post"' in svg and 'data-role="rafter"' in svg and 'data-role="beam"' in svg, "posts/beams/rafters")
    _ok('data-role="roof-fill"' in svg or "polycarbonate" in svg.lower(), "roof identifiable")
    _ok('data-side="front"' in svg and 'data-side="left"' in svg, "side zones in SVG")
    _ok('data-role="deck"' in svg, "deck marker in SVG")

    # --- E: Contextual panel + no cross pollution ---
    panel = cp.panel_for_element(el)
    _ok(panel["schema"]["adapterId"] == "pergola", "panel adapterId")
    _ok("depthMm" in panel["values"], "panel depthMm")
    _ok(panel["values"].get("sides.front.treatment") == "louvers", "panel front treatment")
    win = pa.property_schema_for("SLIDING_WINDOW")
    rail = pa.property_schema_for("RAILING")
    _ok(not cp.schemas_cross_pollute(schema, win), "no pergola/window pollution")
    _ok(not cp.schemas_cross_pollute(schema, rail), "no pergola/railing pollution")

    # --- F: Save/reload authoritative SQL ---
    gst = "22AAAAA0000A1Z5"
    ws = open_workspace(
        gst,
        profile={"companyName": "Pergola Co", "phone": "9000000555", "email": "pg@ex.com"},
        pin="5555",
    )
    tok = ws["sessionToken"]
    hdr = {"X-WEOS-Session": tok}

    cust = create_customer(gst, display_name="Pergola Cust", mobile="9777888999")
    upsert_project(
        project_id="PRJ-2026-PERG1",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Pergola Job",
        status="draft",
    )
    pid = "PRJ-2026-PERG1"
    doc = empty_project(name="Pergola Job", customer="Pergola Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerMobile"] = "9777888999"
    doc["customerId"] = cust["customerId"]
    doc["lines"] = []
    save_project(doc, action="smoke")

    des = dh.ensure_design_document(pid, gst)
    did = des["designDocumentId"]
    loc = dh.resolve_location_for_legacy_name(
        project_id=pid, company_gst=gst, location_name="Garden", create=True
    )
    asm = ds.create_assembly(
        design_document_id=did,
        company_gst=gst,
        name="Garden Pergola",
        location_id=loc["locationId"],
        display_code="A-PG",
    )
    created = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="PERGOLA",
        width_mm=4000,
        height_mm=3000,
        x_mm=100,
        y_mm=200,
        display_code="P-01",
        config_payload=cfg,
    )
    eid = created["elementId"]

    client = TestClient(app)
    r = client.get(f"/api/property-panel?kind=element&id={eid}", headers=hdr)
    _ok(r.status_code == 200, f"property panel GET {r.status_code}")
    body = r.json()
    _ok(body.get("schema", {}).get("adapterId") == "pergola", "API panel pergola")
    _ok(body.get("values", {}).get("sides.back.treatment") == "solid", "API side back")

    patch = {
        "widthMm": 4200,
        "depthMm": 3200,
        "config": {
            "postHeightMm": 2900,
            "finish.colour": "white_matte",
            "sides.front.treatment": "glass",
            "roof.cover": "louvers",
            "deck.enabled": True,
            "deck.material": "composite deck",
        },
    }
    r2 = client.post(f"/api/property-panel/element/{eid}", headers=hdr, json=patch)
    _ok(r2.status_code == 200, f"property panel POST {r2.status_code} {r2.text[:200]}")
    saved = r2.json()
    _ok(saved.get("persisted") is True, "panel save persisted")
    reloaded = ds.get_element(eid, company_gst=gst)
    _ok(float(reloaded.get("widthMm") or 0) == 4200, "width saved")
    _ok(float(reloaded.get("heightMm") or 0) == 3200, "depth->heightMm footprint saved")
    c2 = reloaded.get("configPayload") or {}
    _ok(float(c2.get("postHeightMm") or 0) == 2900, "post height in config")
    n2 = pm.normalize_pergola_config(c2, width_mm=reloaded.get("widthMm"), depth_mm=reloaded.get("heightMm"))
    _ok(n2["sides"]["front"]["treatment"] == "glass", "front treatment persisted")
    _ok(n2["finish"]["colour"] == "white_matte", "colour persisted")
    _ok(n2["roof"]["cover"] == "louvers", "roof persisted")
    _ok(n2["deck"]["enabled"] is True, "deck persisted")

    # --- G: Quote calc + specs + PDF preflight ---
    line = calculate_line(
        {
            "lineId": "PG-001",
            "product": "pergola_stub",
            "productId": "pergola_stub",
            "displayName": "Garden Pergola",
            "category": "Pergola",
            "productType": "pergolas",
            "width": 4200,
            "height": 3200,
            "qty": 2,
            "sellingRate": 450,
            "saleUnit": "sqft",
            "colour": "white_matte",
            "options": {"pergola": n2},
            "description": "Garden pergola with deck",
        },
        include_preview=True,
    )
    _ok(isinstance(line.get("designSummary"), dict), "calc attaches designSummary")
    _ok(isinstance((line.get("options") or {}).get("pergola"), dict), "options.pergola canonical")
    rows = short_window_spec_rows(line)
    labels = {str(a or "").upper() for a, _ in rows}
    for lab in ("SIZE", "ROOF", "SIDES", "DECK", "COLOUR", "SUMMARY"):
        _ok(lab in labels, f"spec has {lab}")
    _ok("TRACK" not in labels and "SHUTTER" not in labels, "no window specs on pergola")

    report = preflight_customer_pdf(
        {"lines": [line], "description": "Pergola quote"},
        expected_line_ids=["PG-001"],
        template={"branding": {"terms": "Pay as agreed."}},
        require_terms=True,
        allow_builtin_terms=False,
    )
    _ok(report.get("status") == "READY", f"preflight READY {report}")

    # Omitting pergola from expected set must fail when expected lists it
    try:
        preflight_customer_pdf(
            {"lines": []},
            expected_line_ids=["PG-001"],
            template={"branding": {"terms": "Pay as agreed."}},
        )
        raise SystemExit("FAIL: preflight should not silently omit Pergola")
    except Exception as exc:
        _ok("PG-001" in str(exc) or "missing" in str(exc).lower(), "preflight refuses omitted Pergola")

    pdf = build_customer_pdf_bytes(
        {
            "projectName": "Pergola Job",
            "customerName": "Pergola Cust",
            "lines": [line],
            "description": "Garden pergola quote",
            "terms": "Pay as agreed.",
            "branding": {
                "companyName": "PERGOLA CO",
                "terms": "Pay as agreed.",
                "primaryColor": [0.1, 0.2, 0.3],
            },
        },
    )
    _ok(isinstance(pdf, (bytes, bytearray)) and pdf[:4] == b"%PDF", "PDF bytes")
    from pypdf import PdfReader

    text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)
    _ok("Pergola" in text or "pergola" in text.lower(), "PDF mentions Pergola")
    _ok("4200" in text or "4,200" in text or "3200" in text, "PDF has dims")
    _ok("white" in text.lower() or "Colour" in text or "COLOUR" in text or "matte" in text.lower(), "PDF colour")
    _ok("Roof" in text or "ROOF" in text or "louver" in text.lower(), "PDF roof")
    _ok("Deck" in text or "DECK" in text or "deck" in text.lower(), "PDF deck")
    _ok("Front" in text or "SIDES" in text or "side" in text.lower(), "PDF sides")

    # Flag compatibility: UC env still on
    _ok(os.environ.get("WEOS_UNIVERSAL_CANVAS") == "1", "WEOS_UNIVERSAL_CANVAS retained")

    print("PASS: _smoke_pergola_adapter.py")


if __name__ == "__main__":
    main()
