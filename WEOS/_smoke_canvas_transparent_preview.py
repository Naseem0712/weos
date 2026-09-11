"""Smoke: Canvas transparent preview — no white page behind drawings on UC."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_canvas_transparent_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

ROOT = Path(__file__).resolve().parents[1]
CANVAS = ROOT / "WEOS" / "website" / "canvas"
CSS = CANVAS / "workspace.css"
ADAPTERS_JS = CANVAS / "adapters.js"
UC_JS = CANVAS / "universal_canvas.js"
SVG_EXPORT = ROOT / "WEOS" / "factory" / "svg_export.py"

PRODUCTS = [
    "SLIDING_WINDOW",
    "CASEMENT_WINDOW",
    "FIXED_WINDOW",
    "VENTILATOR",
    "SHOWER_PARTITION",
    "PERGOLA",
    "LOUVER",
    "ACP",
    "RAILING",
]

PAGE_BG = re.compile(
    r"<rect\b(?=[^>]*\bfill\s*=\s*[\"'](?:#fff(?:fff)?|white)[\"'])"
    r"(?=[^>]*\bwidth\s*=\s*[\"']100%[\"'])"
    r"(?=[^>]*\bheight\s*=\s*[\"']100%[\"'])"
    r"[^>]*\/?>",
    re.I,
)


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
    from WEOS.factory.canvas_preview import normalize_for_canvas
    from WEOS.factory import product_adapters as pa
    from WEOS.factory.svg_export import render_svg_string
    from WEOS.factory.types import DrawingModel

    js = ADAPTERS_JS.read_text(encoding="utf-8")
    uc = UC_JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    _ok("function normalizeForCanvas" in js or "normalizeForCanvas" in js, "JS normalizeForCanvas present")
    _ok("normalizeForCanvas" in uc, "UC setElementPreviewSvg applies normalizeForCanvas")
    _ok("background: transparent !important" in css and "uc-el-svg" in css, "CSS transparent svg wrappers")
    _ok('fill="{bg}"' in SVG_EXPORT.read_text(encoding="utf-8") or 'bg = "#ffffff"' in SVG_EXPORT.read_text(encoding="utf-8"),
        "PDF/preview engine still defines white paper bg")

    # Unit: strip 100% page bg, preserve glass-like rect
    sample = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80" viewBox="0 0 100 80">'
        '<rect width="100%" height="100%" fill="#ffffff"/>'
        '<rect x="10" y="10" width="80" height="60" fill="#ffffff" fill-opacity="0.35" stroke="#111"/>'
        "</svg>"
    )
    norm = normalize_for_canvas(sample)
    _ok(not PAGE_BG.search(norm), "normalize strips 100% white page")
    _ok('fill-opacity="0.35"' in norm, "normalize preserves glass fill")
    _ok("data-weos-canvas-normalized" in norm, "normalize marks svg")

    # Full viewBox page (railing style)
    rail = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640.0 400.0">'
        '<rect x="0" y="0" width="640.0" height="400.0" fill="#ffffff"/>'
        '<rect x="40" y="40" width="560" height="80" fill="none" stroke="#14181c"/>'
        "</svg>"
    )
    rail_n = normalize_for_canvas(rail)
    _ok('<rect x="0" y="0" width="640.0" height="400.0" fill="#ffffff"/>' not in rail_n, "strips railing page rect")
    _ok('fill="none" stroke="#14181c"' in rail_n, "keeps railing geometry")

    client = TestClient(app)
    for pt in PRODUCTS:
        body = {
            "elementId": f"local-{pt.lower()}-tp",
            "productType": pt,
            "widthMm": 1500,
            "heightMm": 1500,
            "configPayload": {"widthMm": 1500, "heightMm": 1500},
            "renderPurpose": "CANVAS_RENDER",
        }
        if pt == "PERGOLA":
            body["widthMm"] = 4500
            body["heightMm"] = 3200
            body["configPayload"] = {"widthMm": 4500, "depthMm": 3200, "lengthMm": 4500}
        r = client.post(f"/api/adapters/{pt}/preview", json=body)
        _ok(r.status_code == 200, f"{pt} canvas preview HTTP 200")
        svg = str((r.json() or {}).get("svg") or "")
        _ok("<svg" in svg.lower(), f"{pt} returns svg")
        _ok(not PAGE_BG.search(svg), f"{pt} canvas SVG has no 100% white page")
        # No full-bleed x=0 y=0 white covering entire viewBox after normalize
        vb = re.search(r'viewBox\s*=\s*["\']\s*[-\d.]+\s+[-\d.]+\s+([-\d.]+)\s+([-\d.]+)', svg, re.I)
        if vb:
            ww, hh = vb.group(1), vb.group(2)
            bleed = re.search(
                rf'<rect\b[^>]*x\s*=\s*["\']0(?:\.0+)?["\'][^>]*y\s*=\s*["\']0(?:\.0+)?["\'][^>]*'
                rf'width\s*=\s*["\']{re.escape(ww)}["\'][^>]*height\s*=\s*["\']{re.escape(hh)}["\'][^>]*'
                rf'fill\s*=\s*["\'](?:#fff(?:fff)?|white)["\'][^>]*\/?>',
                svg,
                re.I,
            )
            _ok(bleed is None, f"{pt} no full-viewBox white page rect")

        # Without CANVAS_RENDER, white paper may remain (PDF path parity)
        body_pdf = dict(body)
        body_pdf.pop("renderPurpose", None)
        r2 = client.post(f"/api/adapters/{pt}/preview", json=body_pdf)
        svg2 = str((r2.json() or {}).get("svg") or "")
        _ok("<svg" in svg2.lower(), f"{pt} default/PDF-style preview still returns svg")

    # Window family engine still emits white paper when style=preview (PDF path)
    dm = DrawingModel(
        product_type="sliding",
        width=1200,
        height=1200,
        polylines=[],
        segments=[],
        metadata={"system": "sliding"},
    )
    raw = render_svg_string(dm, colour="white")
    _ok(PAGE_BG.search(raw) is not None or 'fill="#ffffff"' in raw, "engine raw SVG keeps white paper for PDF")
    _ok(PAGE_BG.search(normalize_for_canvas(raw)) is None, "normalize clears engine paper for canvas")

    # Adapter render without purpose still has paper; canvas path strips it
    el = {
        "elementId": "t",
        "productType": "SLIDING_WINDOW",
        "widthMm": 1200,
        "heightMm": 1400,
        "configPayload": {"widthMm": 1200, "heightMm": 1400, "system": "sliding"},
    }
    raw_ad = pa.render_element_preview(el)
    raw_svg = str((raw_ad or {}).get("svg") or "")
    _ok("<svg" in raw_svg.lower(), "adapter raw preview exists")
    _ok("normalizeForCanvas" in js and "CANVAS_RENDER" in (CANVAS / "design_context.js").read_text(encoding="utf-8"),
        "design_context requests CANVAS_RENDER")

    print("PASS: _smoke_canvas_transparent_preview.py")


if __name__ == "__main__":
    main()
