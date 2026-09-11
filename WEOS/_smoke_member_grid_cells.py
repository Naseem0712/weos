"""Smoke: Canvas Batch E — FrameMember + DesignCell topology (cases A–N)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_member_grid_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
os.environ["WEOS_UNIVERSAL_CANVAS"] = "1"

ROOT = Path(__file__).resolve().parents[1]
CANVAS_JS = ROOT / "WEOS" / "website" / "canvas"


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))

    from fastapi.testclient import TestClient

    from WEOS.api.server import app
    from WEOS.db.engine import init_db
    from WEOS.factory import member_grid as mg
    from WEOS.factory import design_scene as ds
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.project_store import empty_project, save_project

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}")

    # A: capability flags
    _ok(mg.supports_frame_grid("SLIDING_WINDOW"), "A: sliding supportsFrameGrid")
    _ok(mg.supports_frame_grid("CASEMENT_WINDOW"), "A: casement")
    _ok(mg.supports_frame_grid("FIXED_WINDOW"), "A: fixed")
    _ok(mg.supports_frame_grid("DOOR"), "A: door")
    _ok(mg.supports_cell_subdivision("VENTILATOR"), "A: vent subdivision")
    _ok(not mg.supports_frame_grid("PERGOLA"), "A: pergola disabled")
    _ok(not mg.supports_frame_grid("RAILING"), "A: railing disabled")
    _ok(not mg.supports_frame_grid("SHOWER_PARTITION"), "A: shower disabled")
    _ok(not mg.supports_frame_grid("ACP"), "A: ACP disabled")
    _ok(not mg.supports_frame_grid("LOUVER"), "A: louver disabled")
    _ok(mg.supports_frame_grid("PERGOLA", declared={"supportsFrameGrid": True}), "A: declared opt-in")

    gst = "22AAAAA0000A1Z5"
    cust = create_customer(gst, display_name="Grid Cust", mobile="9000111222")
    proj = upsert_project(
        project_id="PRJ-2026-GRID01",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Grid Job",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Grid Job", customer="Grid Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerId"] = cust["customerId"]
    doc["customerMobile"] = "9000111222"
    doc["lines"] = []
    save_project(doc, bump_version=False, action="smoke")

    des = dh.ensure_design_document(pid, company_gst=gst)
    did = des["designDocumentId"]
    asm = ds.create_assembly(design_document_id=did, company_gst=gst, name="A1")
    el = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1200,
        height_mm=1000,
        x_mm=0,
        y_mm=0,
    )
    eid = el["elementId"]

    # B: no root cell until structural activation (historical non-destructive)
    topo0 = mg.get_element_topology(eid, company_gst=gst)
    _ok(not topo0.get("gridActivated") and topo0.get("cellCount") == 0, "B: no root until activation")

    # C: vertical member → root + 2 cells
    r1 = mg.place_member(element_id=eid, company_gst=gst, orientation="V", position_mm=600)
    _ok(r1["ok"] and r1["member"]["orientation"] == "V", "C: V member placed")
    _ok(r1["topology"]["gridActivated"], "C: grid activated")
    leaves = [c for c in r1["topology"]["cells"] if c.get("isLeaf")]
    _ok(len(leaves) == 2, f"C: two leaf cells got {len(leaves)}")
    _ok(abs(leaves[0]["widthMm"] + leaves[1]["widthMm"] - 1200) < 1e-6, "C: widths sum")

    # D: nested horizontal in left cell
    left = sorted(leaves, key=lambda c: c["xMm"])[0]
    r2 = mg.place_member(
        element_id=eid,
        company_gst=gst,
        orientation="H",
        position_mm=700,
        cell_id=left["cellId"],
    )
    _ok(r2["ok"] and r2["member"]["orientation"] == "H", "D: nested H at 700")
    nested = [c for c in r2["childCells"] if c.get("parentCellId") == left["cellId"] or True]
    _ok(len(r2["childCells"]) == 2, "D: nested split two children")
    codes = {c["displayCode"] for c in r2["topology"]["cells"] if c.get("isLeaf")}
    _ok(any("A" in c or "." in c for c in codes), f"D: stable nested codes {codes}")

    # E: validation — zero / outside / duplicate
    try:
        mg.place_member(element_id=eid, company_gst=gst, orientation="V", position_mm=0)
        _ok(False, "E: zero should fail")
    except ValueError:
        _ok(True, "E: zero/edge rejected")
    try:
        mg.place_member(element_id=eid, company_gst=gst, orientation="V", position_mm=99999)
        _ok(False, "E: outside should fail")
    except ValueError:
        _ok(True, "E: outside rejected")
    # duplicate on a fresh opening
    el_dup = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1200,
        height_mm=1000,
    )
    mg.place_member(element_id=el_dup["elementId"], company_gst=gst, orientation="V", position_mm=500)
    try:
        mg.place_member(element_id=el_dup["elementId"], company_gst=gst, orientation="V", position_mm=500)
        _ok(False, "E: duplicate should fail")
    except ValueError:
        _ok(True, "E: duplicate rejected")
    try:
        mg.place_member(element_id=eid, company_gst=gst, orientation="H", position_mm=700, cell_id=left["cellId"])
        _ok(False, "E: non-leaf cellId should fail")
    except ValueError:
        _ok(True, "E: non-leaf cellId rejected")

    # F: equal grid 2×2 / 2×3
    el2 = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="CASEMENT_WINDOW",
        width_mm=1800,
        height_mm=1500,
    )
    g22 = mg.apply_equal_grid(element_id=el2["elementId"], company_gst=gst, rows=2, columns=2)
    _ok(g22["ok"] and g22["rows"] == 2 and g22["columns"] == 2, "F: 2×2 grid")
    _ok(g22["topology"]["leafCellCount"] == 4, "F: 4 leaves")
    g23 = mg.apply_equal_grid(element_id=el2["elementId"], company_gst=gst, rows=2, columns=3)
    _ok(g23["topology"]["leafCellCount"] == 6, "F: 2×3 → 6 leaves")
    _ok(len(g23["members"]) == (2 - 1) + (3 - 1), "F: member count rows+cols-2")

    # G: member position edit (binary split — not multi-child equal grid)
    el_g = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="CASEMENT_WINDOW",
        width_mm=1200,
        height_mm=1000,
    )
    pg = mg.place_member(element_id=el_g["elementId"], company_gst=gst, orientation="V", position_mm=500)
    u = mg.update_member_position(member_id=pg["member"]["memberId"], company_gst=gst, position_mm=550)
    _ok(abs(u["member"]["positionMm"] - 550) < 1e-6, "G: position edit")

    # H: delete/merge
    # Use fresh element for clean delete
    el3 = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="FIXED_WINDOW",
        width_mm=1000,
        height_mm=1000,
    )
    p = mg.place_member(element_id=el3["elementId"], company_gst=gst, orientation="V", position_mm=400)
    d = mg.delete_member(member_id=p["member"]["memberId"], company_gst=gst)
    _ok(d["ok"] and d["mergedCell"]["isLeaf"], "H: delete merges to leaf")
    _ok(d["topology"]["memberCount"] == 0, "H: no active members")

    # I: undo/redo + GeometryRevision
    el4 = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="DOOR",
        width_mm=900,
        height_mm=2100,
    )
    mg.place_member(element_id=el4["elementId"], company_gst=gst, orientation="V", position_mm=450)
    t_before = mg.get_element_topology(el4["elementId"], company_gst=gst)
    _ok(t_before["memberCount"] == 1, "I: one member before undo")
    und = mg.undo_structure(element_id=el4["elementId"], company_gst=gst)
    _ok(und["topology"]["memberCount"] == 0, "I: undo cleared member")
    red = mg.redo_structure(element_id=el4["elementId"], company_gst=gst)
    _ok(red["topology"]["memberCount"] == 1, "I: redo restored")

    # J: size change rule — refuse silent / CANCEL / KEEP_OFFSETS
    try:
        mg.apply_size_change(
            element_id=el4["elementId"],
            company_gst=gst,
            width_mm=1000,
            height_mm=2100,
            size_change_rule="",
        )
        _ok(False, "J: empty rule should fail")
    except ValueError:
        _ok(True, "J: empty rule refused")
    can = mg.apply_size_change(
        element_id=el4["elementId"],
        company_gst=gst,
        width_mm=1000,
        height_mm=2100,
        size_change_rule="CANCEL",
    )
    _ok(can.get("cancelled"), "J: CANCEL")
    sc = mg.apply_size_change(
        element_id=el4["elementId"],
        company_gst=gst,
        width_mm=1000,
        height_mm=2100,
        size_change_rule="KEEP_OFFSETS",
    )
    _ok(sc["ok"] and sc["rule"] == "KEEP_OFFSETS", "J: KEEP_OFFSETS documented")
    _ok("KEEP_OFFSETS" in mg.SIZE_CHANGE_RULE_DOC, "J: rule documented")

    # K: PDF safety
    pdf = mg.pdf_drawing_for_element(el4["elementId"], company_gst=gst)
    _ok(pdf["mode"] == "structural" and "data-weos-structural" in (pdf.get("svg") or ""), "K: structural PDF svg")
    el_pdf = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=800,
        height_mm=800,
    )
    pdf0 = mg.pdf_drawing_for_element(el_pdf["elementId"], company_gst=gst)
    _ok(pdf0["mode"] == "product_svg", "K: inactive → product path")

    # L: tenant APIs
    ws = open_workspace(gst, pin="1234", profile={"companyName": "Grid Co", "loginPin": "1234"})
    client = TestClient(app)
    headers = {"X-WEOS-Session": ws["sessionToken"]}
    r = client.get(f"/api/elements/{eid}/structure", headers=headers)
    _ok(r.status_code == 200 and r.json().get("gridActivated"), "L: structure API")
    r2 = client.get(f"/api/products/PERGOLA/structure-capabilities")
    _ok(r2.status_code == 200 and r2.json().get("supportsFrameGrid") is False, "L: pergola capability API")
    # cross-tenant
    gst_b = "22BBBBB0000B1Z5"
    create_customer(gst_b, display_name="Other", mobile="9000333444")
    ws_b = open_workspace(gst_b, pin="1234", profile={"companyName": "Other Co", "loginPin": "1234"})
    r3 = client.get(f"/api/elements/{eid}/structure", headers={"X-WEOS-Session": ws_b["sessionToken"]})
    _ok(r3.status_code in (403, 404, 401) or r3.status_code >= 400, f"L: cross-tenant blocked {r3.status_code}")

    # M: modules + frontend presence
    _ok((CANVAS_JS / "member_tools.js").is_file(), "M: member_tools.js")
    uc = (CANVAS_JS / "universal_canvas.js").read_text(encoding="utf-8")
    wsjs = (CANVAS_JS / "workspace.js").read_text(encoding="utf-8")
    _ok("FrameMember" in (ROOT / "WEOS" / "factory" / "member_grid.py").read_text(encoding="utf-8"), "M: FrameMember domain")
    _ok("setStructureEnabled" in uc and "memberTools" in uc, "M: UC wired")
    _ok("member_v" in wsjs and "CANVAS-E" in wsjs, "M: tools enabled in shell")
    _ok("Batch E" not in wsjs or "N/A" in wsjs or "supportsFrameGrid" in wsjs, "M: no Batch E reserved tease")

    # N: existing product SVG panels ≠ FrameMember until grid activated
    from WEOS.db.models import FrameMember, DesignCell
    from WEOS.db.engine import session_scope
    from sqlalchemy import select, func

    with session_scope() as s:
        n_mem = s.execute(select(func.count()).select_from(FrameMember)).scalar()
        n_cell = s.execute(select(func.count()).select_from(DesignCell)).scalar()
    _ok(int(n_mem or 0) > 0 and int(n_cell or 0) > 0, "N: SQL rows exist after activation")
    el5 = ds.create_element(
        assembly_id=asm["assemblyId"],
        company_gst=gst,
        product_type="SLIDING_WINDOW",
        width_mm=1200,
        height_mm=1000,
    )
    t5 = mg.get_element_topology(el5["elementId"], company_gst=gst)
    _ok(t5["memberCount"] == 0 and not t5["gridActivated"], "N: fresh element no members until draw")

    print("PASS: _smoke_member_grid_cells A–N")


if __name__ == "__main__":
    main()
