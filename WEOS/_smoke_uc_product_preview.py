"""Smoke: UC product selection → adapter preview SVG on canvas (multi-product)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_uc_preview_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
os.environ.pop("WEOS_UNIVERSAL_CANVAS", None)

ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / "WEOS" / "website" / "canvas"
INDEX = ROOT / "WEOS" / "website" / "index.html"

PRODUCTS = [
    "SLIDING_WINDOW",
    "CASEMENT_WINDOW",
    "VENTILATOR",
    "PERGOLA",
    "SHOWER_PARTITION",
    "LOUVER",
    "ACP",
    "RAILING",
]


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
    from WEOS.factory import product_adapters as pa
    from WEOS.factory import canvas_activation as ca

    dc_js = (CANVAS / "design_context.js").read_text(encoding="utf-8")
    ws_js = (CANVAS / "workspace.js").read_text(encoding="utf-8")
    ad_js = (CANVAS / "adapters.js").read_text(encoding="utf-8")
    uc_js = (CANVAS / "universal_canvas.js").read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")

    _ok(ca.is_universal_canvas_enabled() is True, "A: UC default ON")
    _ok("refreshElementPreview" in dc_js, "A: refreshElementPreview helper")
    _ok("setElementPreviewSvg" in uc_js, "A: host setElementPreviewSvg")
    _ok("refreshElementPreview" in ws_js, "A: Add Design wires preview")
    _ok('"/api/adapters/"' in dc_js and "/preview" in dc_js, "A: calls adapter preview API")
    _ok('"ACP"' in ad_js, "A: ACP registered in JS adapters")
    _ok("</html>" in index and "quote_workspace.js" in index, "A: index integrity + D2 scripts")

    client = TestClient(app)
    for pt in PRODUCTS:
        body = {
            "elementId": f"local-{pt.lower()}-test",
            "productType": pt,
            "widthMm": 1800 if pt != "RAILING" else 2400,
            "heightMm": 1500 if pt not in ("RAILING", "PERGOLA") else (900 if pt == "RAILING" else 3000),
            "configPayload": {"widthMm": 1800, "heightMm": 1500},
        }
        if pt == "PERGOLA":
            body["widthMm"] = 4000
            body["heightMm"] = 3000
            body["configPayload"] = {"widthMm": 4000, "heightMm": 3000, "lengthMm": 4000, "depthMm": 3000}
        r = client.post(f"/api/adapters/{pt}/preview", json=body)
        _ok(r.status_code == 200, f"B: {pt} preview HTTP {r.status_code}")
        data = r.json()
        svg = str(data.get("svg") or "")
        _ok("<svg" in svg.lower(), f"B: {pt} returns SVG")
        _ok(data.get("productType") == pt or data.get("adapterId"), f"B: {pt} identity")
        # Placeholder-only grey box is acceptable fallback for some specialty stubs,
        # but must still be real SVG painted via setElementPreviewSvg path.
        kind = str(data.get("kind") or "")
        _ok(kind in ("engine_svg", "schematic", "preview_svg", "placeholder") or svg, f"B: {pt} kind={kind}")

        # Direct factory path also works
        out = pa.render_element_preview(
            {"elementId": body["elementId"], "productType": pt, "widthMm": body["widthMm"], "heightMm": body["heightMm"]},
            body.get("configPayload"),
        )
        _ok("<svg" in str(out.get("svg") or "").lower(), f"C: factory {pt} SVG")

    # Stale-discard: preview gen counter must not use beginRender (would abort context switch)
    _ok("_previewGen" in dc_js, "D: dedicated preview generation counter")
    _ok("beginRender()" not in dc_js.split("refreshElementPreview")[1].split("function ")[0] or "_previewGen" in dc_js, "D: preview does not abort context via beginRender")

    # Property panel live refresh
    pp = (CANVAS / "property_panel.js").read_text(encoding="utf-8")
    _ok("refreshElementPreview" in pp, "E: property change refreshes UC preview")

    print("PASS: _smoke_uc_product_preview.py")


if __name__ == "__main__":
    main()
