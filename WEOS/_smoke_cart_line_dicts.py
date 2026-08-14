"""Smoke: cart PUT/PDF bodies accept full line dicts; leftover ids coerce from saved lines."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_cart_dicts_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    fails: list[str] = []
    html = Path(__file__).resolve().parents[1] / "WEOS" / "website" / "index.html"
    src = html.read_text(encoding="utf-8")
    if "return ln.lineId;" in src.replace(" ", ""):
        fails.append("index.html still has ensureLineId that returns a string id")
    if "Math.random().toString(16).slice(2, 10)" in src:
        fails.append("index.html still generates 8-char hex line ids in duplicate ensureLineId")
    if "function serializeCartLines" not in src:
        fails.append("serializeCartLines helper missing")
    if "function serializeCartLinesForPdf" not in src:
        fails.append("serializeCartLinesForPdf helper missing")
    if src.count("function ensureLineId") != 1:
        fails.append(f"expected 1 ensureLineId, found {src.count('function ensureLineId')}")
    if "cartLineProductLabel" not in src:
        fails.append("cart product label helper missing")

    from pydantic import ValidationError

    from WEOS.api.server import PdfExportBody, ProjectCreate, ProjectUpdate, _coerce_cart_lines

    full = {
        "lineId": "463846cb",
        "product": "29mm_sliding",
        "productId": "29mm_sliding",
        "width": 1440,
        "height": 1800,
        "qty": 1,
        "glass": "8mm_toughened",
        "colour": "white",
    }
    try:
        ProjectUpdate.model_validate({"lines": ["463846cb", "b3a5a2c5"]})
        PdfExportBody.model_validate({"lines": ["463846cb"]})
        ProjectCreate.model_validate({"name": "t", "lines": ["463846cb"]})
    except ValidationError as exc:
        fails.append(f"id-string lines still 422: {exc}")

    coerced = _coerce_cart_lines(["463846cb", "missing"], existing=[full])
    if len(coerced) != 1 or coerced[0].get("product") != "29mm_sliding":
        fails.append(f"id coerce failed: {coerced}")

    coerced2 = _coerce_cart_lines([full])
    if not coerced2 or coerced2[0].get("width") != 1440:
        fails.append(f"full dict coerce failed: {coerced2}")

    from fastapi.testclient import TestClient

    from WEOS.api.server import app
    from WEOS.factory.project_store import empty_project, save_project

    doc = empty_project(name="Cart dict smoke", customer="Smoke")
    doc["lines"] = [dict(full)]
    saved = save_project(doc, action="smoke")
    pid = saved["projectId"]
    client = TestClient(app)

    r = client.put(
        f"/api/projects/{pid}",
        json={
            "name": "Cart dict smoke",
            "lines": [
                {
                    "lineId": "b3a5a2c5",
                    "product": "railing",
                    "productId": "railing",
                    "displayName": "Railing",
                    "width": 3000,
                    "height": 1050,
                    "qty": 1,
                    "glass": "12mm_clear",
                    "colour": "ss",
                    "options": {"railing": {"shape": "straight", "lengthMm": 3000}},
                }
            ],
        },
    )
    if r.status_code != 200:
        fails.append(f"PUT full dicts HTTP {r.status_code}: {r.text[:400]}")
    else:
        got = r.json().get("lines") or []
        if not got or not isinstance(got[0], dict) or got[0].get("product") != "railing":
            fails.append(f"PUT did not persist full line dict: {got[:1]}")

    r2 = client.put(f"/api/projects/{pid}", json={"lines": ["b3a5a2c5"]})
    if r2.status_code != 200:
        fails.append(f"PUT leftover ids HTTP {r2.status_code}: {r2.text[:400]}")
    else:
        got2 = r2.json().get("lines") or []
        if not got2 or not isinstance(got2[0], dict) or got2[0].get("product") != "railing":
            fails.append(f"PUT leftover ids did not resolve: {got2[:1]}")

    if fails:
        print("FAIL cart line dicts smoke")
        for f in fails:
            print(" -", f)
        return 1
    print("OK cart line dicts smoke: serializeCartLines + PUT dicts + leftover id coerce")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
