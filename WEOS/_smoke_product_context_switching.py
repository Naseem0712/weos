"""Smoke: Canvas D0 — Product Context / Stale State / Single Canvas Parity (cases A–N)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_product_context_"))
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fastapi.testclient import TestClient

    from WEOS.api.server import app
    from WEOS.db.engine import init_db
    from WEOS.factory import contextual_properties as cp
    from WEOS.factory import design_context as dc
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory import design_scene as ds
    from WEOS.factory import product_adapters as pa
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.project_store import empty_project, save_project

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    # ── A: No WINDOW fallthrough ─────────────────────────────────────────────
    dc.assert_no_window_fallthrough("WINDOW")
    dc.assert_no_window_fallthrough("")
    dc.assert_no_window_fallthrough(None)
    a = dc.resolve_active_design_context(product_type="WINDOW")
    _ok(a["adapterId"] == "fallback" and a["toolset"] == "unsupported", "A: WINDOW → fallback/unsupported")
    _ok("Window tools" in (a.get("guidance") or ""), "A: fallback message mentions Window tools not shown")

    # ── B: product_type → registry → schema → toolset ────────────────────────
    for pt, toolset, adapter in [
        ("SLIDING_WINDOW", "sliding", "window_family"),
        ("CASEMENT_WINDOW", "casement", "window_family"),
        ("VENTILATOR", "ventilator", "ventilator"),
        ("SHOWER_PARTITION", "shower", "shower"),
        ("LOUVER", "louver", "louver"),
        ("ACP", "acp", "surface"),
        ("RAILING", "railing", "railing"),
        ("PERGOLA", "pergola", "pergola"),
    ]:
        ctx = dc.resolve_active_design_context(product_type=pt)
        _ok(ctx["selectedProductType"] == pt, f"B: {pt} type preserved")
        _ok(ctx["toolset"] == toolset, f"B: {pt} toolset={toolset}")
        _ok(ctx["adapterId"] == adapter, f"B: {pt} adapter={adapter}")
        _ok(ctx["supported"] is True, f"B: {pt} supported")
        _ok(ctx["propertySchema"].get("toolset") == toolset, f"B: {pt} schema toolset")

    # ── C: Casement ≠ Sliding exact fields ───────────────────────────────────
    slid = dc.property_schema_for_context("SLIDING_WINDOW")
    case = dc.property_schema_for_context("CASEMENT_WINDOW")
    sk, ck = _field_keys(slid), _field_keys(case)
    _ok("trackCount" in sk, "C: Sliding has trackCount")
    _ok("trackCount" not in ck, "C: Casement has no trackCount")
    _ok("casementPanels" in ck or "sashOverlapMm" in ck, "C: Casement has sash fields")
    _ok("casementPanels" not in sk, "C: Sliding has no casementPanels")

    # ── D: Unsupported → message, not Window tools ───────────────────────────
    unk = dc.resolve_active_design_context(product_type="WEIRD_WIDGET")
    _ok(unk["toolset"] == "unsupported" and unk["adapterId"] == "fallback", "D: unknown → unsupported")
    _ok(unk["guidance"] and "Window tools are not shown" in unk["guidance"], "D: fallback guidance")
    uk = _field_keys(unk["propertySchema"])
    _ok("trackCount" not in uk and "sectionSeries" not in uk, "D: no window chrome on fallback")

    # ── E: Atomic product switch clears prior context ────────────────────────
    prev = dc.resolve_active_design_context(product_type="SLIDING_WINDOW", element_id="E1")
    nxt = dc.switch_product_context(
        prev, product_type="PERGOLA", element_id=None, source="catalogue"
    )
    _ok(nxt["renderRevision"] == prev["renderRevision"] + 1, "E: renderRevision bumps")
    _ok(nxt["selectedProductType"] == "PERGOLA" and nxt["toolset"] == "pergola", "E: Pergola active")
    _ok(nxt.get("clearedPriorContext") is True, "E: clearedPriorContext")
    _ok(nxt.get("previousProductType") == "SLIDING_WINDOW", "E: previous recorded")
    _ok(not nxt.get("configPayload"), "E: prior window config not inherited on catalogue switch")
    _ok(not dc.contexts_leak(prev, nxt), "E: no toolset leak Sliding→Pergola")

    # ── F: Switch chain no leakage (Window→Vent→Shower→ACP→Pergola) ──────────
    chain = ["SLIDING_WINDOW", "VENTILATOR", "SHOWER_PARTITION", "ACP", "PERGOLA", "RAILING"]
    cur = None
    for pt in chain:
        nxt = dc.switch_product_context(cur, product_type=pt, source="switch")
        if cur:
            _ok(not dc.contexts_leak(cur, nxt), f"F: no leak {cur['selectedProductType']}→{pt}")
            _ok(nxt["toolset"] != cur["toolset"] or {cur["toolset"], nxt["toolset"]} <= {"acp", "surface"},
                f"F: toolset changed for {pt}")
        cur = nxt
    _ok(cur["selectedProductType"] == "RAILING" and cur["toolset"] == "railing", "F: chain ends on railing")

    # ── G: Element-scoped config (not shared global) ─────────────────────────
    e1 = dc.resolve_active_design_context(
        product_type="SLIDING_WINDOW",
        element_id="EL-A",
        config_payload={"sectionSeries": "SER-A", "trackCount": 3},
    )
    e2 = dc.resolve_active_design_context(
        product_type="CASEMENT_WINDOW",
        element_id="EL-B",
        config_payload={"casementPanels": [{"w": 1}], "sashOverlapMm": 15},
    )
    _ok(e1["configScope"] == "element:EL-A", "G: element A scope")
    _ok(e2["configScope"] == "element:EL-B", "G: element B scope")
    _ok(e1["configPayload"].get("sectionSeries") == "SER-A", "G: A keeps series")
    _ok("sectionSeries" not in e2["configPayload"], "G: B does not share A's series")
    _ok(e2["configPayload"].get("sashOverlapMm") == 15, "G: B keeps casement config")

    # ── H: Stale render revision discard contract ────────────────────────────
    t0 = dc.resolve_active_design_context(product_type="LOUVER", render_revision=5)
    t1 = dc.switch_product_context(t0, product_type="SHOWER_PARTITION", source="switch")
    _ok(t1["renderRevision"] > t0["renderRevision"], "H: newer revision wins")
    _ok(t0["renderRevision"] != t1["renderRevision"], "H: old revision distinct")

    # ── I: API design-context + switch ───────────────────────────────────────
    client = TestClient(app)
    r = client.get("/api/design-context", params={"productType": "PERGOLA"})
    _ok(r.status_code == 200, "I: GET design-context")
    body = r.json()
    _ok(body["toolset"] == "pergola" and body["adapterId"] == "pergola", "I: Pergola context API")

    r2 = client.post(
        "/api/design-context/switch",
        json={
            "productType": "VENTILATOR",
            "previous": body,
            "source": "catalogue",
        },
    )
    _ok(r2.status_code == 200, "I: POST switch")
    sw = r2.json()
    _ok(sw["toolset"] == "ventilator" and sw["previousProductType"] == "PERGOLA", "I: switch Pergola→Vent")

    r3 = client.get("/api/adapters/WINDOW/schema")
    _ok(r3.status_code == 400, "I: WINDOW schema rejected")

    # ── J: Adapter schema specialization via public API ──────────────────────
    rs = client.get("/api/adapters/SLIDING_WINDOW/schema")
    rc = client.get("/api/adapters/CASEMENT_WINDOW/schema")
    _ok(rs.status_code == 200 and rc.status_code == 200, "J: sliding/casement schemas")
    _ok(rs.json().get("toolset") == "sliding", "J: sliding toolset on schema")
    _ok(rc.json().get("toolset") == "casement", "J: casement toolset on schema")
    _ok("trackCount" in _field_keys(rs.json()), "J: sliding track in API schema")
    _ok("trackCount" not in _field_keys(rc.json()), "J: casement no track in API schema")

    # ── K: Catalogue vs element selection ────────────────────────────────────
    cat_pt = dc.catalogue_product_type(
        {"productType": "pergolas", "id": "pergola_stub", "category": "Pergolas"}, world="pergola"
    )
    _ok(cat_pt == "PERGOLA", "K: catalogue → PERGOLA")
    cat_vent = dc.catalogue_product_type(
        {"productType": "bathroom_ventilator", "category": "Bathrooms"}, world="ventilator"
    )
    _ok(cat_vent == "VENTILATOR", "K: catalogue → VENTILATOR")
    cat_acp = dc.catalogue_product_type({"id": "acp_stub", "category": "ACP"}, world="surface")
    _ok(cat_acp in ("ACP", "SURFACE"), "K: catalogue → ACP/SURFACE")

    # ── L: Multi-element scene — selection refreshes all context ─────────────
    gst = "22AAAAA0000A1Z5"
    ws = open_workspace(
        gst,
        profile={"companyName": "Ctx Co", "phone": "9000000333", "email": "ctx@ex.com"},
        pin="3333",
    )
    tok = ws["sessionToken"]
    hdr = {"X-WEOS-Session": tok}
    cust = create_customer(gst, display_name="Ctx Cust", mobile="9444555777")
    upsert_project(
        project_id="PRJ-2026-CTX1",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Context Job",
        status="draft",
    )
    pid = "PRJ-2026-CTX1"
    doc = empty_project(name="Context Job", customer="Ctx Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerMobile"] = "9444555777"
    doc["customerId"] = cust["customerId"]
    doc["lines"] = []
    save_project(doc, action="smoke")

    des = dh.ensure_design_document(pid, gst)
    did = des["designDocumentId"]
    living = dh.resolve_location_for_legacy_name(
        project_id=pid, company_gst=gst, location_name="Hall", create=True
    )
    loc_id = living["locationId"]
    asm = ds.create_assembly(
        design_document_id=did,
        company_gst=gst,
        name="Mixed",
        display_code="A-CTX",
        location_id=loc_id,
    )
    el_slide = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1200,
        height_mm=1400,
        display_code="W-01",
        config_payload={"sectionSeries": "SER-SLIDE", "trackCount": 2},
    )
    el_perg = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="PERGOLA",
        width_mm=4000,
        height_mm=3000,
        display_code="P-01",
        x_mm=2000,
        config_payload={"posts": 4},
    )
    el_vent = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="VENTILATOR",
        width_mm=600,
        height_mm=400,
        display_code="V-01",
        x_mm=5000,
    )

    c_slide = dc.context_from_element(el_slide)
    c_perg = dc.context_from_element(el_perg)
    c_vent = dc.context_from_element(el_vent)
    _ok(c_slide["toolset"] == "sliding" and c_perg["toolset"] == "pergola", "L: multi-element toolsets")
    _ok(c_vent["toolset"] == "ventilator", "L: ventilator element context")
    _ok(c_slide["configScope"] != c_perg["configScope"], "L: distinct config scopes")
    _ok(not dc.contexts_leak(c_slide, c_perg), "L: no leak slide→pergola elements")

    # Panel for each element
    p_slide = cp.panel_for_element(el_slide)
    p_perg = cp.panel_for_element(el_perg)
    _ok(p_slide.get("toolset") == "sliding", "L: panel sliding toolset")
    _ok(p_perg.get("toolset") == "pergola", "L: panel pergola toolset")
    _ok("depthMm" in _field_keys(p_perg["schema"]) or "sides.front.treatment" in _field_keys(p_perg["schema"]),
        "L: pergola panel schema intact")

    # ── M: UC single host marker + static design_context.js served ───────────
    os.environ["WEOS_UNIVERSAL_CANVAS"] = "1"
    flags = client.get("/api/flags").json()
    _ok(flags.get("universalCanvas") is True or flags.get("WEOS_UNIVERSAL_CANVAS") is True, "M: UC flag ON")
    js = client.get("/static/canvas/design_context.js")
    _ok(js.status_code == 200 and ("ActiveDesignContext" in js.text or "designContext" in js.text), "M: design_context.js served")
    _ok("AbortController" in js.text or "renderRevision" in js.text, "M: stale render protection in JS")
    _ok("routeLegacyIntoUc" in js.text, "M: legacy popup routing present")
    index = client.get("/")
    # index may be / or /static — check website file content via static path if needed
    idx_html = (Path(__file__).resolve().parent / "website" / "index.html").read_text(encoding="utf-8")
    _ok("design_context.js" in idx_html, "M: index loads design_context.js")
    _ok("WEOS_DESIGN_CONTEXT" in idx_html or "selectCatalogue" in idx_html, "M: index wires design context")
    os.environ["WEOS_UNIVERSAL_CANVAS"] = "0"

    # ── N: Pergola no regression + hard refresh multi-product ────────────────
    perg_schema = pa.property_schema_for("PERGOLA")
    _ok(perg_schema.get("adapterId") == "pergola", "N: Pergola adapter")
    pk = _field_keys(perg_schema)
    _ok("depthMm" in pk and "sides.front.treatment" in pk, "N: Pergola geometry + front")
    _ok("sectionSeries" not in pk and "mountType" not in pk, "N: no window/rail on Pergola")

    # Hard refresh simulation: rebuild contexts from elements independently
    refreshed = [dc.context_from_element(el_slide), dc.context_from_element(el_perg), dc.context_from_element(el_vent)]
    _ok([c["toolset"] for c in refreshed] == ["sliding", "pergola", "ventilator"], "N: hard refresh multi-product")

    # Element property API still works under company session
    r_el = client.get(f"/api/elements/{el_perg['elementId']}/property-schema", headers=hdr)
    _ok(r_el.status_code == 200, f"N: pergola property-schema HTTP {r_el.status_code}")
    _ok(r_el.json().get("adapterId") == "pergola" or r_el.json().get("toolset") == "pergola"
        or "sides.front.treatment" in _field_keys(r_el.json()), "N: pergola schema via element API")

    print("PASS: product context switching A–N")


if __name__ == "__main__":
    main()
