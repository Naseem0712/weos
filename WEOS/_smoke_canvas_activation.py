"""Smoke: Canvas D1 — Universal Canvas Activation + Workspace Cutover (cases A–O)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_canvas_activation_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)
# Explicit isolation: start unset so default-ON can be proven, then toggle.
os.environ.pop("WEOS_UNIVERSAL_CANVAS", None)

ROOT = Path(__file__).resolve().parents[1]
CANVAS_JS = ROOT / "WEOS" / "website" / "canvas"
INDEX = ROOT / "WEOS" / "website" / "index.html"
FACTORY = ROOT / "WEOS" / "factory"


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))

    from WEOS.factory import canvas_activation as ca
    from WEOS.factory import canvas_workspace as cw
    from WEOS.factory import design_context as dc
    from WEOS.factory import product_adapters as pa
    from WEOS.factory import universal_canvas as uc
    from fastapi.testclient import TestClient
    from WEOS.api.server import app

    uc_js = (CANVAS_JS / "universal_canvas.js").read_text(encoding="utf-8")
    ws_js = (CANVAS_JS / "workspace.js").read_text(encoding="utf-8")
    ws_css = (CANVAS_JS / "workspace.css").read_text(encoding="utf-8")
    pp_js = (CANVAS_JS / "property_panel.js").read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")
    act_py = (FACTORY / "canvas_activation.py").read_text(encoding="utf-8")

    # ── A: normal V2 boot chooses UC mode ────────────────────────────────────
    os.environ.pop("WEOS_UNIVERSAL_CANVAS", None)
    _ok(ca.is_universal_canvas_enabled() is True, "A: activation default ON")
    _ok(uc.is_universal_canvas_enabled() is True, "A: universal_canvas default ON")
    client = TestClient(app)
    flags = client.get("/api/flags").json()
    _ok(flags.get("universalCanvas") is True, "A: /api/flags universalCanvas true")
    _ok(flags.get("universalCanvasDefault") == "on", "A: flags document default on")
    _ok("serverEnabled = true" in index or "D1 default ON" in index, "A: boot defaults ON")
    _ok("applyPrimaryCutover" in ws_js and "uc-primary" in ws_css, "A: primary cutover present")

    # ── B: explicit legacy override works ────────────────────────────────────
    _ok(ca.is_universal_canvas_enabled(query_value="0") is False, "B: query 0 → OFF")
    _ok(ca.is_universal_canvas_enabled(env_value="0") is False, "B: env 0 → OFF")
    _ok(ca.is_universal_canvas_enabled(env_value="false") is False, "B: env false → OFF")
    os.environ["WEOS_UNIVERSAL_CANVAS"] = "0"
    _ok(uc.is_universal_canvas_enabled() is False, "B: env disables UC")
    flags_off = client.get("/api/flags").json()
    _ok(flags_off.get("universalCanvas") is False, "B: /api/flags reflects env OFF")
    os.environ.pop("WEOS_UNIVERSAL_CANVAS", None)
    _ok("universalCanvas=0" in act_py or "queryOff" in act_py, "B: fallback documented")
    _ok("/^(0|false|no|off)$/i" in uc_js or "false|no|off" in uc_js, "B: JS query OFF")

    # ── C: only one UC host ──────────────────────────────────────────────────
    _ok("never mount a second host" in uc_js or "ONE Universal Canvas" in uc_js, "C: single host guard")
    _ok("universalCanvasHost" in uc_js, "C: host id")

    # ── D: legacy Live Preview not primary-visible in UC ─────────────────────
    _ok("data-uc-compat" in uc_js, "D: livePreview marked compat")
    _ok(
        "preview[data-uc-compat" in index or "preview[data-uc-compat" in ws_css,
        "D: CSS hides compat preview",
    )
    _ok("Live Preview" in index, "D: livePreview label remains in DOM for rollback")
    _ok("uc-primary" in ws_css and "preview-head" in ws_css, "D: preview-head hidden in primary")

    # ── E: legacy giant product editor not primary-visible in UC ─────────────
    _ok("uc-legacy-form" in ws_js, "E: legacy form class")
    _ok(".cart-tools.uc-legacy-form" in ws_css and "display: none" in ws_css, "E: form hidden CSS")
    _ok("uc-legacy-hidden" in pp_js, "E: tool stacks wrapped")
    _ok("windowCartTools" in index, "E: legacy DOM retained")

    # ── F: tool rail mounted ─────────────────────────────────────────────────
    _ok("uc-tool-rail" in ws_js and 'toolBtn("select"' in ws_js, "F: tool rail in shell")
    _ok("56px" in ws_css or "48px" in ws_css, "F: tool rail width band")

    # ── G: command bar mounted ───────────────────────────────────────────────
    _ok("uc-command-bar" in ws_js and "Engineering Canvas" in ws_js, "G: command bar")
    _ok("data-uc=\"fit\"" in ws_js and "data-uc=\"undo\"" in ws_js, "G: command controls")

    # ── H: property panel mounted ────────────────────────────────────────────
    _ok("ucPropertyPanel" in ws_js and "uc-props-rail" in ws_js, "H: props rail mount")
    _ok("minmax(300px, 360px)" in ws_css or "minmax(280px, 320px)" in ws_css or "minmax(240px, 280px)" in ws_css or "minmax(220px, 260px)" in ws_css, "H: props width band")
    _ok("tryMount" in pp_js and "propertyPanelEl" in uc_js, "H: panel API")

    # ── I: product selection updates property panel ──────────────────────────
    _ok("selectElementById" in uc_js and "upsertLocalElement" in uc_js, "I: local element APIs")
    _ok("createDesignOnCanvas" in ws_js and "btnUcAddDesign" in ws_js, "I: Add Design entry")
    slid = dc.property_schema_for_context("SLIDING_WINDOW")
    case = dc.property_schema_for_context("CASEMENT_WINDOW")
    _ok(slid.get("toolset") == "sliding" and case.get("toolset") == "casement", "I: schemas differ by product")
    _ok("refreshPropertyPanel" in (CANVAS_JS / "design_context.js").read_text(encoding="utf-8"), "I: panel refresh")

    # ── J: Pergola schema visible ────────────────────────────────────────────
    perg = pa.property_schema_for("PERGOLA")
    labels = [str(g.get("label") or "") for g in (perg.get("groups") or [])]
    for need in ("Geometry", "Structure", "Louvers", "Roof", "Side Treatments", "Floor/Deck", "Finish", "Summary"):
        _ok(any(need.lower() in x.lower() for x in labels), f"J: pergola group {need}")

    # ── K: Shower schema visible ─────────────────────────────────────────────
    shower = pa.property_schema_for("SHOWER_PARTITION")
    _ok(shower.get("adapterId") in ("shower", "window_family") or (shower.get("groups") or []), "K: shower schema")
    _ok(shower.get("toolset") == "shower" or shower.get("productType") == "SHOWER_PARTITION", "K: shower identity")

    # ── L: Ventilator schema visible ─────────────────────────────────────────
    vent = pa.property_schema_for("VENTILATOR")
    _ok(vent.get("toolset") == "ventilator" or vent.get("adapterId") == "ventilator", "L: ventilator schema")
    _ok(bool(vent.get("groups")), "L: ventilator has groups")

    # ── M: unsupported does not show Window tools ────────────────────────────
    unk = dc.resolve_active_design_context(product_type="UNKNOWN_WIDGET_XYZ")
    _ok(unk.get("supported") is False, "M: unsupported flagged")
    _ok(unk.get("toolset") == "unsupported" or unk.get("adapterId") == "fallback", "M: no window toolset")
    keys = []
    for g in (unk.get("propertySchema") or {}).get("groups") or []:
        for f in g.get("fields") or []:
            keys.append(str(f.get("key") or ""))
    _ok("trackCount" not in keys and "glassShutters" not in keys, "M: no window-only fields")

    # ── N: fit uses engineering element/scene bounds (never SVG viewBox units) ─
    _ok("fitToSelectionOrScene" in uc_js, "N: fit helper")
    _ok("element_mm" in uc_js, "N: element mm bounds source")
    _ok("parts[2]" not in uc_js, "N: no viewBox width override in Fit")
    z = cw.fit_with_padding({"width": 1200, "height": 2000}, 900, 700, padding=40)
    _ok(0.15 <= z <= 6.0, f"N: fit zoom sensible {z}")
    plan = cw.compute_fit({"width": 1200, "height": 1000, "minX": 0, "minY": 0}, 1200, 800, padding=48)
    _ok(abs(plan["panX"] - (1200 / 2 - 600 * plan["zoom"])) < 1e-6, "N: Fit centers horizontally")
    _ok(plan["worldOriginX"] == 0 and plan["worldOriginY"] == 0, "N: worldOrigin stays 0")
    _ok("uc-el-svg svg" in ws_css and "width: 100%" in ws_css, "N: SVG fills element box")

    # ── O: no second product canvas popup ────────────────────────────────────
    dc_js = (CANVAS_JS / "design_context.js").read_text(encoding="utf-8")
    _ok("data-product-canvas-popup" in dc_js, "O: popup routing")
    _ok("routeLegacyIntoUc" in dc_js and "routeLegacyIntoUc" in uc_js, "O: legacy routed into UC")
    _ok("FrameMember" not in uc_js and "mullion" not in uc_js.lower(), "O: no member engine")
    _ok(
        "CANVAS-D1" in ws_js
        or "CANVAS-D1" in uc_js
        or "CANVAS-D3" in uc_js
        or "CANVAS-D4" in uc_js
        or "CANVAS-D1" in act_py,
        "O: D1/D3/D4 batch marker",
    )

    # Header / identity
    _ok("Engineering Workspace" in index or "Engineering Workspace" in ws_js, "header: neutral title")
    _ok("btnUcAddDesign" in ws_js, "Add Design button")

    print("OK canvas activation smoke A–O")


if __name__ == "__main__":
    main()
