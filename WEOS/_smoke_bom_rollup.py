"""Smoke: BOM rollup Cell → Element → Assembly → Design → Project."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_bom_roll_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
os.environ["WEOS_UNIVERSAL_CANVAS"] = "1"

ROOT = Path(__file__).resolve().parents[1]


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))

    from WEOS.db.engine import init_db
    from WEOS.factory import design_hierarchy as dh
    from WEOS.factory import design_scene as ds
    from WEOS.factory import engineering_bom as eb
    from WEOS.factory import engineering_masters as em
    from WEOS.factory.canonical_customer import create_customer
    from WEOS.factory.canonical_project import upsert_project
    from WEOS.factory.project_store import empty_project, save_project

    init_db()
    gst = "22DDDDD0000D1Z5"
    em.seed_default_window_masters(company_gst=gst)
    series = em.resolve_series_ref("29mm_sliding", company_gst=gst)

    cust = create_customer(gst, display_name="Roll Cust", mobile="9000555777")
    proj = upsert_project(
        project_id="PRJ-2026-ROLL",
        customer_id=cust["customerId"],
        company_gst=gst,
        name="Rollup Job",
        status="draft",
    )
    pid = proj["projectId"]
    doc = empty_project(name="Rollup", customer="Roll Cust")
    doc["projectId"] = pid
    doc["companyGst"] = gst
    doc["customerId"] = cust["customerId"]
    doc["lines"] = []
    save_project(doc, bump_version=False, action="smoke")

    des = dh.ensure_design_document(pid, company_gst=gst)
    asm = ds.create_assembly(design_document_id=des["designDocumentId"], company_gst=gst)

    eids = []
    for i, (w, h) in enumerate(((1000, 1200), (900, 1100)), start=1):
        el = ds.create_element(
            assembly_id=asm["assemblyId"],
            company_gst=gst,
            product_type="SLIDING_WINDOW",
            width_mm=w,
            height_mm=h,
            display_code=f"W-R{i}",
            config_payload={"seriesId": series["seriesId"]},
        )
        eids.append(el["elementId"])
        eb.generate_element_bom(el["elementId"], company_gst=gst, persist=True, force=True)

    piece = eb.make_bom_line(
        category="PROFILE",
        description="test",
        code="X",
        quantity=1,
        length_mm=1000,
        required_length_mm=1000,
        weight_per_rmt=0.5,
    )
    _ok(abs(piece["weightKg"] - 0.5) < 1e-9, "piece weight helper")

    rolled = eb.rollup_lines(
        [
            eb.make_bom_line(category="HARDWARE", description="Handle", code="H", quantity=2, unit="PC"),
            eb.make_bom_line(category="HARDWARE", description="Handle", code="H", quantity=3, unit="PC"),
        ],
        scope_level="ASSEMBLY",
    )
    _ok(len(rolled) == 1, "rollup merges same key")
    _ok(rolled[0]["quantity"] == 5, "rollup sums qty")

    hier = eb.rollup_hierarchy(project_id=pid, company_gst=gst)
    _ok(hier["scopeLevel"] == "PROJECT", "project scope")
    _ok(hier.get("usesQuoteSellingRate") is False, "rollup no selling rate")
    _ok((hier.get("summary") or {}).get("lineCount", 0) >= 1, "project has lines")
    _ok(len(hier.get("assemblies") or []) >= 1, "assembly nodes")
    _ok("CELL" in (hier.get("hierarchy") or []), "hierarchy includes CELL")
    _ok("LOCATION" in (hier.get("hierarchy") or []) and "FLOOR" in hier["hierarchy"], "location/floor in hierarchy")
    _ok(len(hier.get("rollup") or []) >= 1, "project rollup lines")

    print("PASS: bom rollup")


if __name__ == "__main__":
    main()
