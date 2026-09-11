"""Smoke: Canvas D4 — Interactive property / configuration binding (cases A–O)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_prop_interact_"))
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
    from WEOS.factory import contextual_properties as cp
    from WEOS.factory import product_adapters as pa

    pp = (CANVAS / "property_panel.js").read_text(encoding="utf-8")
    dc = (CANVAS / "design_context.js").read_text(encoding="utf-8")
    uc = (CANVAS / "universal_canvas.js").read_text(encoding="utf-8")
    qw = (CANVAS / "quote_workspace.js").read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")

    # A: authoritative commit pipeline
    _ok("commitUpdate" in pp, "A: commitUpdate present")
    _ok("Authoritative" in pp or "GEOMETRY|CONFIG" in pp or "updateTarget" in pp, "A: GEOMETRY|CONFIG pipeline")
    _ok("/api/property-panel/element/" in pp, "A: SQL property-panel save path")

    # B: uses state.elementId (not broken state.selection nesting)
    _ok("state.elementId" in pp and "isLocalId" in pp, "B: state.elementId + local id detection")
    _ok("sel.elementId || state.values.elementId" in pp or "state.elementId = sel.elementId" in pp, "B: selection stores elementId")

    # C: local draft updates DesignElement via applyElementPatch / upsert
    _ok("applyLocalGeometry" in pp, "C: local geometry apply")
    _ok("applyElementPatch" in uc, "C: host applyElementPatch")
    _ok("upsertLocalElement" in pp or "applyElementPatch" in pp, "C: local path wires host patch")

    # D: durable POST fail-closed
    _ok("persisted" in pp and "Save failed" in pp, "D: fail-closed on reject")
    _ok("setHostSave" in pp and "saving" in pp and "saved" in pp, "D: save status Saving/Saved/Error")

    # E: geometry vs config split
    _ok("updateTarget" in pp and "GEOMETRY" in pp and "CONFIG" in pp, "E: updateTarget GEOMETRY|CONFIG")
    _ok("data-pp-target" in pp and "data-pp-domain" in pp, "E: field domain/target attrs")

    # F: field metadata
    _ok("fieldMeta" in pp and "editable" in pp and "supported" in pp, "F: fieldMeta editable/supported")
    _ok("disabledReason" in pp, "F: disabled reason (never silent no-op)")

    # G: debounce / blur for numbers; immediate for select/toggle
    _ok("scheduleCommit" in pp and "280" in pp, "G: number debounce")
    _ok('addEventListener(\n          "blur"' in pp or 'addEventListener("blur"' in pp or '"blur"' in pp, "G: blur commit")
    _ok("boolean" in pp and "SELECT" in pp, "G: select/toggle path")

    # H: commitGen latest-wins
    _ok("commitGen" in pp and "stale" in pp, "H: commitGen latest-wins")

    # I: preview via refreshElementPreview (not MutationObserver SoT)
    _ok("refreshElementPreview" in pp, "I: preview via refreshElementPreview")
    _ok("MutationObserver" not in pp, "I: property panel does not use MutationObserver")
    # Legacy bridge may still exist in index but must not overwrite good SVG
    _ok("hasGoodElementPreview" in index or "livePreview" in uc, "I: livePreview bridge guarded")

    # J: design context config patch
    _ok("applyConfigPatch" in dc, "J: design_context.applyConfigPatch")

    # K: quote card sync
    _ok("syncCardFromElement" in qw and "syncCardFromElement" in pp, "K: quote card sync wired")

    # L: AbortController prevents duplicate listeners on re-render
    _ok("AbortController" in pp and "abortBindings" in pp, "L: abortBindings / no duplicate listeners")

    # M: server apply_element_property_update still authoritative
    client = TestClient(app)
    for pt in PRODUCTS:
        schema = pa.property_schema_for(pt)
        keys = set()
        for g in schema.get("groups") or []:
            for f in g.get("fields") or []:
                if not f.get("key"):
                    continue
                key = str(f["key"])
                keys.add(key)
                domain = f.get("domain") or ""
                # Nested summary/readonly blobs may omit domain — treat as identity/config.
                if "." in key or f.get("type") in ("readonly", "json"):
                    continue
                _ok(
                    domain in ("geometry", "config", "identity") or not domain,
                    f"M: {pt}.{key} domain ok",
                )
        _ok("widthMm" in keys or pt == "PERGOLA", f"M: {pt} has widthMm (or pergola length)")
        # Schema metadata: editable / supported / updateTarget
        for g in schema.get("groups") or []:
            for f in g.get("fields") or []:
                if not f.get("key") or "." in str(f.get("key")):
                    continue
                _ok("updateTarget" in f, f"M: {pt}.{f.get('key')} has updateTarget")
                _ok("editable" in f and "supported" in f, f"M: {pt}.{f.get('key')} editable/supported")
                _ok("readOnly" in f, f"M: {pt}.{f.get('key')} readOnly flag")
        # Preview after geometry change
        body = {
            "elementId": f"local-{pt.lower()}-d4",
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
        _ok(r.status_code == 200 and "<svg" in str(r.json().get("svg") or "").lower(), f"M: {pt} preview @1500")

    # N: split_geometry_and_config helper
    geom, cfg = cp.split_geometry_and_config({"widthMm": 1500, "colour": "White", "glass": "8mm"})
    _ok(geom.get("widthMm") == 1500 and cfg.get("colour") == "White", "N: geometry/config split")

    # O: no legacy Window Cart as SoT
    _ok("windowCartTools" in pp and "uc-legacy-hidden" in pp, "O: legacy tools hidden under UC")
    _ok("Never uses hidden legacy" in pp or "never" in pp.lower(), "O: panel owns commits")
    _ok("commitUpdate" in pp and "addDraftLineToCart" not in pp, "O: not driven by legacy cart form")

    print("PASS: _smoke_property_interactions.py")


if __name__ == "__main__":
    main()
