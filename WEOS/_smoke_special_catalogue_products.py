"""Smoke: standalone louvers/pergola stay out of window geometry/specs."""

from __future__ import annotations

from WEOS.factory.line_kind import is_pergola_cart_line, line_world
from WEOS.factory.marqt_pdf import _spec_rows
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.svg_export import elevation_svg_for_line
from WEOS.factory.window_specs import short_window_spec_rows


def _ok(cond: bool, msg: str, fails: list[str]) -> None:
    if not cond:
        fails.append(msg)


def _labels(rows: list[tuple[str, str]]) -> set[str]:
    return {str(a or "").upper() for a, _ in rows}


def main() -> None:
    fails: list[str] = []

    louver = {
        "product": "louvers_stub",
        "productId": "louvers_stub",
        "displayName": "Louvers",
        "category": "Facades",
        "productType": "louvers_stub",
        "width": 1500,
        "height": 1800,
        "qty": 1,
        "panelFill": {
            "fillType": "louvers",
            "orientation": "horizontal",
            "bladeWidthMm": 80,
            "gapMm": 20,
        },
    }
    lcalc = calculate_line(louver, include_preview=False)
    lsvg = elevation_svg_for_line(lcalc) or ""
    lrows = short_window_spec_rows(lcalc)
    _ok(line_world(lcalc) == "louver", f"louver world wrong: {line_world(lcalc)!r}", fails)
    _ok("<svg" in lsvg and 'data-model-system="louver"' in lsvg, "louver SVG missing", fails)
    _ok("TRACK" not in _labels(lrows), f"louver printed TRACK: {lrows}", fails)
    _ok("SHUTTER" not in _labels(lrows), f"louver printed SHUTTER: {lrows}", fails)
    _ok("HANDLE" not in _labels(lrows), f"louver printed HANDLE: {lrows}", fails)

    pergola = {
        "product": "pergola_stub",
        "productId": "pergola_stub",
        "displayName": "Pergola",
        "category": "Pergola",
        "productType": "pergola_stub",
        "width": 3000,
        "height": 2400,
        "qty": 1,
    }
    pcalc = calculate_line(pergola, include_preview=False)
    psvg = elevation_svg_for_line(pcalc) or ""
    prows = short_window_spec_rows(pcalc)
    _ok(is_pergola_cart_line(pcalc), "pergola cart line not detected", fails)
    _ok(line_world(pcalc) == "pergola", f"pergola world wrong: {line_world(pcalc)!r}", fails)
    _ok("<svg" in psvg and 'data-model-system="pergola"' in psvg, "pergola SVG missing", fails)
    _ok("Pergola isometric drawing" in psvg, "pergola isometric title missing", fails)
    _ok('data-role="post"' in psvg and 'data-role="rafter"' in psvg, "pergola posts/rafters missing", fails)
    _ok("Fixing plate plan" in psvg, "pergola fixing plate plan missing", fails)
    _ok("TRACK" not in _labels(prows), f"pergola printed TRACK: {prows}", fails)
    _ok("SASH" not in _labels(prows), f"pergola printed SASH: {prows}", fails)
    _ok("SHUTTER" not in _labels(prows), f"pergola printed SHUTTER: {prows}", fails)
    _ok(any(a == "FIXING" for a, _ in prows), f"pergola fixing missing: {prows}", fails)

    acp = {
        "product": "acp_stub",
        "productId": "acp_stub",
        "displayName": "ACP Cladding",
        "category": "Facades",
        "productType": "acp_stub",
        "width": 2050,
        "height": 1970,
        "qty": 1,
        "sellingRate": 560,
        "saleUnit": "sqft",
    }
    acalc = calculate_line(acp, include_preview=False)
    asvg = elevation_svg_for_line(acalc) or ""
    arows = short_window_spec_rows(acalc)
    _ok(line_world(acalc) == "surface", f"acp world wrong: {line_world(acalc)!r}", fails)
    _ok("<svg" in asvg and 'data-model-system="surface"' in asvg, "ACP surface SVG missing", fails)
    _ok("TRACK" not in _labels(arows), f"ACP printed TRACK: {arows}", fails)
    _ok("SASH" not in _labels(arows), f"ACP printed SASH: {arows}", fails)
    _ok("GLASS" not in _labels(arows), f"ACP printed GLASS: {arows}", fails)

    vent = {
        "product": "bathroom_ventilator",
        "productType": "bathroom_ventilator",
        "width": 600,
        "height": 450,
        "qty": 1,
        "sellingRate": 560,
        "saleUnit": "sqft",
        "options": {
            "ventilator": {"widthMm": 600, "heightMm": 450, "mode": "split"},
        },
    }
    vcalc = calculate_line(vent, include_preview=False)
    vrows = _spec_rows(vcalc)
    _ok("RATE" not in _labels(vrows), f"vent RATE duplicate: {vrows}", fails)
    _ok("AMOUNT" not in _labels(vrows), f"vent AMOUNT duplicate: {vrows}", fails)
    _ok("QTY" not in _labels(vrows), f"vent QTY duplicate: {vrows}", fails)

    if fails:
        raise SystemExit("\n".join(fails))
    print("OK special catalogue products: louver/pergola preview + PDF specs")


if __name__ == "__main__":
    main()
