"""Quote item snapshot integrity: add → refresh → PDF must not re-roll identity."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_qsnap_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _ok(cond: bool, msg: str, fails: list[str]) -> None:
    safe = msg.encode("ascii", "replace").decode("ascii")
    if not cond:
        fails.append(safe)
    else:
        print("OK:", safe)


def _pdf_glass_blob(pdf_bytes: bytes) -> str:
    raw = pdf_bytes.decode("latin-1", errors="ignore")
    return raw


def main() -> int:
    fails: list[str] = []
    html = Path(__file__).resolve().parents[1] / "WEOS" / "website" / "index.html"
    src = html.read_text(encoding="utf-8")
    _ok("function stampItemSnapshot" in src, "index.html stamps item snapshot on add", fails)
    _ok("Never replace a saved project" in src or "Never replace a restored cart" in src, "dummy init guarded against saved cart", fails)
    _ok("!restoredCart && !state.projectId && !hasSavedLines && !state.workspaceRestored" in src, "dummy 4 windows only for empty session", fails)
    _ok("Never silently substitute 8mm_toughened" in src, "glass dropdown does not fall back to 8mm", fails)
    _ok("world === 'louver'" in src, "JS product world includes louver", fails)
    _ok("keptProduct" in src, "ensureLineId keeps productId", fails)
    _ok("wrapLineGlass" in src and "wrapLineHandle" in src, "louver can hide glass/handle wraps", fails)
    _ok("Keep nearest option" not in src, "railing glass preset does not nearest-match laminated to 12mm", fails)
    _ok("ensureProductOptionFromLine(ln, { select:" in src, "loadProducts keeps every cart line product_id", fails)

    from WEOS.factory.quote_item_snapshot import (
        PRODUCT_UNAVAILABLE,
        attach_snapshot,
        freeze_item_snapshot,
        glass_display_label,
        get_item_snapshot,
        resolved_config,
    )
    from WEOS.factory.line_kind import is_louver_cart_line, line_world
    from WEOS.factory.project_engine import calculate_line, calculate_project
    from WEOS.factory.project_store import empty_project, load_project, save_project
    from WEOS.factory.marqt_pdf import _spec_rows, render_marqt_pdf
    from WEOS.factory.window_specs import human_glass_label

    # ── Laminated display: 6+1.52+5, never 12mm random ──
    lam_line = {
        "lineId": "Llam1",
        "product": "29mm_sliding",
        "productId": "29mm_sliding",
        "displayName": "29mm Sliding",
        "category": "Windows",
        "width": 1200,
        "height": 1400,
        "qty": 1,
        "glass": "lam_6_152_5",
        "colour": "white",
        "sellingRate": 900,
        "saleUnit": "sqft",
    }
    frozen_lam = attach_snapshot(dict(lam_line), overwrite_identity=True)
    snap = get_item_snapshot(frozen_lam)
    glabel = glass_display_label(snap.get("glass_snapshot") or {})
    _ok("6+1.52+5" in glabel.replace(" ", ""), f"laminated label has 6+1.52+5 got {glabel!r}", fails)
    _ok("Laminated" in glabel, f"laminated label says Laminated got {glabel!r}", fails)
    _ok(glabel.strip() not in ("12 mm", "12mm", "8 mm", "10 mm", "15 mm"), f"must not collapse to round mm: {glabel!r}", fails)

    calc1 = calculate_line(frozen_lam, include_preview=False)
    calc2 = calculate_line(frozen_lam, include_preview=False)
    g1 = human_glass_label(calc1)
    g2 = human_glass_label(calc2)
    _ok(g1 == g2, f"two calcs same glass label {g1!r} vs {g2!r}", fails)
    _ok("6+1.52+5" in g1.replace(" ", ""), f"calc glass keeps laminated makeup {g1!r}", fails)

    # Library V2 must not rewrite Quote V1 snapshot
    hijack = dict(frozen_lam)
    hijack["product"] = "casement_stub"
    hijack["displayName"] = "SHOULD NOT APPLY"
    hijack["glass"] = "8mm_toughened"
    kept = freeze_item_snapshot(hijack, overwrite_identity=False)
    _ok(kept.get("product_id") == "29mm_sliding", f"identity locked got {kept.get('product_id')}", fails)
    _ok("lam_6_152_5" in str((kept.get("glass_snapshot") or {}).get("glass_id")), "glass id stays laminated", fails)

    # ── Louver stays louver after calc / “refresh” ──
    lou = {
        "lineId": "Llou1",
        "product": "louvers_stub",
        "productId": "louvers_stub",
        "displayName": "Louvers",
        "category": "Facades",
        "productType": "louvers_stub",
        "width": 1500,
        "height": 1800,
        "qty": 2,
        "sellingRate": 450,
        "saleUnit": "sqft",
    }
    frozen_lou = attach_snapshot(dict(lou), overwrite_identity=True)
    _ok(is_louver_cart_line(frozen_lou), "louver cart line detected", fails)
    _ok(line_world(frozen_lou) == "louver", f"world is louver got {line_world(frozen_lou)!r}", fails)
    lou_calc = calculate_line(frozen_lou, include_preview=False)
    _ok(lou_calc.get("product") == "louvers_stub", f"calc product still louvers_stub got {lou_calc.get('product')}", fails)
    _ok(lou_calc.get("product") != "29mm_sliding", "louver must not become 29mm_sliding", fails)
    _ok("window" not in str(lou_calc.get("category") or "").lower(), f"category not Windows: {lou_calc.get('category')}", fails)
    _ok(not lou_calc.get("trackRail"), "louver has no window track rail", fails)
    spec_lou = _spec_rows(lou_calc, audience="customer")
    blob_lou = " | ".join(f"{a}: {b}" for a, b in spec_lou).lower()
    _ok("louver" in blob_lou or "louvers" in blob_lou, f"PDF specs stay louver: {blob_lou[:200]}", fails)
    _ok("track" not in [a.lower() for a, _ in spec_lou], f"louver PDF must not print TRACK: {spec_lou}", fails)
    _ok("GLASS" not in [a for a, _ in spec_lou], f"louver PDF must not force GLASS: {spec_lou}", fails)
    _ok("HANDLE" not in [a for a, _ in spec_lou], f"louver PDF must not force HANDLE: {spec_lou}", fails)
    _ok("SHUTTER" not in [a for a, _ in spec_lou], f"louver PDF must not force SHUTTER: {spec_lou}", fails)

    # Missing product → error, item unchanged
    missing = attach_snapshot(
        {"lineId": "Lx", "product": "no_such_product_zzz", "productId": "no_such_product_zzz", "width": 1000, "height": 1000, "qty": 1},
        overwrite_identity=True,
    )
    miss_calc = calculate_line(missing, include_preview=False)
    _ok(miss_calc.get("product") == "no_such_product_zzz", "missing product id preserved", fails)
    _ok(
        PRODUCT_UNAVAILABLE in str(miss_calc.get("error") or ""),
        f"missing product errors without substitute: {miss_calc.get('error')}",
        fails,
    )
    _ok(miss_calc.get("product") != "29mm_sliding", "no silent first-window substitute", fails)

    # ── Railing 12mm tuff is railing glass, not window ──
    rail = {
        "lineId": "Lrail1",
        "product": "railing",
        "productId": "railing",
        "displayName": "Railing",
        "category": "Railings",
        "productType": "railing",
        "width": 3000,
        "height": 1050,
        "qty": 1,
        "sellingRate": 850,
        "saleUnit": "rft",
        "options": {
            "railing": {
                "shape": "straight",
                "lengthMm": 3000,
                "heightMm": 1050,
                "glassThicknessMm": 12,
                "glassType": "toughened",
                "glassColour": "clear",
                "bottomKind": "continuous",
            }
        },
    }
    frozen_rail = attach_snapshot(dict(rail), overwrite_identity=True)
    rsnap = (get_item_snapshot(frozen_rail) or {}).get("glass_snapshot") or {}
    rlab = glass_display_label(rsnap)
    _ok("12" in rlab, f"railing glass 12mm got {rlab!r}", fails)
    _ok("6+1.52+5" not in rlab.replace(" ", ""), f"railing must not steal laminated makeup {rlab!r}", fails)
    rail_calc = calculate_line(frozen_rail, include_preview=False)
    _ok(rail_calc.get("product") in ("railing", "railings_stub") or "rail" in str(rail_calc.get("product") or "").lower(),
        f"railing product identity {rail_calc.get('product')}", fails)
    _ok(str(rail_calc.get("category") or "").lower().find("window") < 0, f"railing category {rail_calc.get('category')}", fails)
    rail_rows = _spec_rows(rail_calc, audience="customer")
    rail_blob = " | ".join(f"{a}: {b}" for a, b in rail_rows)
    _ok("GLASS" in [a for a, _ in rail_rows], f"railing has GLASS row {rail_rows[:8]}", fails)
    _ok("lam_6" not in rail_blob.lower() and "29mm" not in rail_blob.lower(), f"railing PDF not window glass {rail_blob[:240]}", fails)

    # Railing laminated: glass_id layers, never nearest 12 mm dual string
    rail_lam = {
        "lineId": "LrailLam",
        "product": "railing",
        "productId": "railing",
        "displayName": "Staircase railing",
        "category": "Railings",
        "productType": "staircase_railing",
        "width": 4000,
        "height": 1050,
        "qty": 1,
        "glass": "lam_5_152_5",
        "sellingRate": 900,
        "saleUnit": "rft",
        "options": {
            "railing": {
                "shape": "staircase",
                "glassPreset": "lam_5_152_5",
                "glassType": "laminated",
                "glassThicknessMm": 12,
                "glassColour": "clear",
            }
        },
    }
    frozen_rlam = attach_snapshot(dict(rail_lam), overwrite_identity=True)
    rlam_lab = glass_display_label((get_item_snapshot(frozen_rlam) or {}).get("glass_snapshot") or {})
    _ok("5+1.52+5" in rlam_lab.replace(" ", ""), f"railing laminated makeup {rlam_lab!r}", fails)
    _ok("12 mm ·" not in rlam_lab and not rlam_lab.strip().startswith("12 mm"), f"no dual 12mm+lam {rlam_lab!r}", fails)
    rlam_rows = _spec_rows(frozen_rlam, audience="customer")
    rlam_glass = next((v for a, v in rlam_rows if a == "GLASS"), "")
    _ok("5+1.52+5" in rlam_glass.replace(" ", ""), f"PDF railing GLASS laminated {rlam_glass!r}", fails)
    _ok("12 mm ·" not in rlam_glass, f"PDF railing GLASS not dual {rlam_glass!r}", fails)

    # W1-like TRACK must include profile mm + wall; NOTE from description
    w1 = attach_snapshot(
        {
            "lineId": "Lw1",
            "product": "29mm_sliding",
            "productId": "29mm_sliding",
            "displayName": "29mm Sliding",
            "category": "Windows",
            "width": 2760,
            "height": 2380,
            "qty": 1,
            "glass": "8mm_toughened",
            "trackCount": 3,
            "sectionSeries": "25mm_eco_gulf",
            "description": "50MM Premium Series Fluted Laminated",
            "sellingRate": 1100,
            "saleUnit": "sqft",
        },
        overwrite_identity=True,
    )
    from WEOS.factory.window_specs import short_window_spec_rows

    w1_rows = short_window_spec_rows(w1)
    w1_track = next((v for a, v in w1_rows if a == "TRACK"), "")
    _ok("3-track" in w1_track.lower().replace(" ", ""), f"W1 TRACK count {w1_track!r}", fails)
    _ok(("×" in w1_track or "x" in w1_track.lower()), f"W1 TRACK has profile mm {w1_track!r}", fails)
    _ok("wall" in w1_track.lower(), f"W1 TRACK has wall {w1_track!r}", fails)
    _ok(any(a == "NOTE" and "50MM" in v for a, v in w1_rows), f"NOTE from description {w1_rows}", fails)
    w1_title = next((v for a, v in w1_rows if a == ""), "")
    _ok("29mm" in w1_title or "Sliding" in w1_title, f"title from snapshot not description {w1_title!r}", fails)

    # ── Persist snapshots on project JSON + identical PDFs ──
    doc = empty_project(name="Snapshot integrity", customer="Smoke")
    doc["lines"] = [frozen_lam, frozen_lou, frozen_rail]
    saved = save_project(doc, action="smoke")
    pid = saved["projectId"]
    loaded = load_project(pid)
    _ok(len(loaded.get("lines") or []) == 3, "saved 3 snapshot lines", fails)
    for i, expect_pid in enumerate(("29mm_sliding", "louvers_stub", "railing")):
        ln = (loaded.get("lines") or [])[i]
        snap_i = get_item_snapshot(ln)
        _ok(snap_i.get("product_id") == expect_pid, f"line {i} snapshot product_id {snap_i.get('product_id')} vs {expect_pid}", fails)
        _ok(ln.get("product") == expect_pid or snap_i.get("product_id") == expect_pid, f"line {i} product frozen", fails)

    # Dummy init must not overwrite: re-load project after “refresh”
    loaded2 = load_project(pid)
    _ok([get_item_snapshot(x).get("product_id") for x in loaded2["lines"]] == ["29mm_sliding", "louvers_stub", "railing"],
        "reload keeps product ids", fails)

    result = calculate_project(loaded2, optimize=False, include_preview=False)
    payload = {
        **result,
        "projectId": pid,
        "customer": "Smoke",
        "name": "Snapshot integrity",
        "quotationId": "SNAP-1",
        "createdAt": loaded2.get("createdAt"),
        "updatedAt": loaded2.get("updatedAt"),
        "version": loaded2.get("version"),
    }
    tmpl = {"branding": {"companyName": "TEST CO", "primaryColor": [0.1, 0.2, 0.3]}}
    pdf_a = render_marqt_pdf(tmpl, {**payload, "lines": result["lines"], "price": {"total": 1}})
    pdf_b = render_marqt_pdf(tmpl, {**payload, "lines": result["lines"], "price": {"total": 1}})
    _ok(isinstance(pdf_a, (bytes, bytearray)) and len(pdf_a) > 500, f"PDF generate works ({len(pdf_a) if pdf_a else 0} bytes)", fails)
    _ok(isinstance(pdf_b, (bytes, bytearray)) and len(pdf_b) > 500, "second PDF generate works", fails)

    # Spec identity (names, category, glass) must match across two generates
    lines_a = result["lines"]
    result_b = calculate_project(load_project(pid), optimize=False, include_preview=False)
    for la, lb in zip(lines_a, result_b["lines"]):
        sa, sb = _spec_rows(la), _spec_rows(lb)
        _ok(sa == sb, f"PDF spec rows identical for {la.get('product')}", fails)
        _ok(la.get("product") == lb.get("product"), "product id identical", fails)
        _ok(la.get("displayName") == lb.get("displayName"), "displayName identical", fails)
        _ok(human_glass_label(la) == human_glass_label(lb), "glass label identical", fails)

    cfg = resolved_config(frozen_lam)
    _ok(cfg.get("product_id") == "29mm_sliding", "resolved config uses snapshot product", fails)
    _ok("6+1.52+5" in str(cfg.get("glass_display_label") or "").replace(" ", ""), "resolved config laminated label", fails)

    long_desc = ("Cover description overflow sentence. " * 80).strip()
    long_terms = "\n".join("Payment, delivery, warranty and site measurement terms. " * 6 for _ in range(40))
    pdf_long = render_marqt_pdf(
        tmpl,
        {
            **payload,
            "description": long_desc,
            "terms": long_terms,
            "lines": result["lines"],
            "price": {"total": 1},
        },
    )
    page_objs = pdf_long.count(b"/Type /Page") - pdf_long.count(b"/Type /Pages")
    _ok(page_objs >= 3, f"long cover/terms paginate to extra pages got {page_objs}", fails)
    cover_txt = pdf_long.decode("latin-1", errors="ignore")
    _ok("Description" in cover_txt or "Descrip" in cover_txt, "cover Description heading present", fails)

    if fails:
        print("FAIL quote item snapshot smoke")
        for f in fails:
            print(" -", f)
        return 1
    print("OK quote item snapshot: louver/laminated/railing/dummy-guard/PDF identity")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
