"""Smoke: Al kg×rate, ≤3ft wastage, sliding interlocks, materials, stock."""
from __future__ import annotations

import sys


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)
    print("OK:", msg)


def main() -> None:
    from WEOS.factory.design_cost import (
        _section_rate_per_m,
        compute_casement_design_cost,
        compute_sliding_design_cost,
        pack_std_length_wastage,
    )
    from WEOS.factory.product_loader import load_product
    from WEOS.factory.product_setup import assign_sliding_interlocks
    from WEOS.factory.remnant_stock import stock_viewer_payload
    from WEOS.factory.materials_list import build_quote_materials_list, materials_list_html

    # ── Aluminium kg×rate + explicit RFT ─────────────────────────────
    from WEOS.factory.design_cost import _coating_per_m
    from WEOS.factory.profile_hardware_import import _parse_rate, parse_use_bom_counts

    sec = {"name": "Outer", "rate": 450, "rateUnit": "kg", "weightKgPerM": 0.6, "coatingCost": 22, "coatingUnit": "rft"}
    _ok(abs(_section_rate_per_m(sec) - 270.0) < 0.01, f"Al ₹/m = wt×rate → {_section_rate_per_m(sec)}")
    rft_sec = {"name": "mesh adapter", "rate": 200, "rateUnit": "rft", "weightKgPerM": 0.8, "coatingCost": 9, "coatingUnit": "rft"}
    _ok(abs(_section_rate_per_m(rft_sec) - (200 / 0.3048)) < 0.1, f"Al per RFT → {_section_rate_per_m(rft_sec)}")
    rate_n, rate_u = _parse_rate("200 rft")
    _ok(rate_u == "rft" and abs((rate_n or 0) - 200) < 0.01, f"parse 200 rft → {rate_n} {rate_u}")
    rate_n2, rate_u2 = _parse_rate(450)
    _ok(rate_u2 == "kg", f"numeric rate defaults kg → {rate_u2}")
    coat = _coating_per_m(sec)
    _ok(abs(coat - (22 / 0.3048)) < 0.1, f"coating always per RFT → {coat}")

    # ── V / H / V2 H2 ────────────────────────────────────────────────
    v2 = parse_use_bom_counts("V2 H2")
    _ok(v2["allSidesSame"] and v2["pcsVertical"] == 2 and v2["pcsHorizontal"] == 2, f"V2 H2 {v2}")
    vh = parse_use_bom_counts(None, 1, 2, section_name="handle side")
    _ok(vh["pcsVertical"] == 1 and vh["pcsHorizontal"] == 2, f"V=1 H=2 {vh}")
    top = parse_use_bom_counts(None, 2, None, section_name="2 track top, bottom")
    _ok(top["pcsHorizontal"] == 2 and not top["pcsVertical"], f"top/bottom V→H fix {top}")
    vert = parse_use_bom_counts(None, None, 2, section_name="2 track vertical left right")
    _ok(vert["pcsVertical"] == 2 and not vert["pcsHorizontal"], f"vertical H→V fix {vert}")
    il = parse_use_bom_counts(None, 1, 0, section_name="Slim interlock")
    _ok(il["pcsVertical"] == 1 and (il["pcsHorizontal"] in (0, None) or il["pcsHorizontal"] == 0), f"interlock V=1 H=0 {il}")

    # ── ≤3 ft wastage ────────────────────────────────────────────────
    short = pack_std_length_wastage([2.5], std_m=3.0, reuse=True)
    _ok(short["wastageMetres"] > 0 and not short["remnantsOut"], f"0.5m leftover = wastage {short}")
    long = pack_std_length_wastage([1.5], std_m=3.0, reuse=True)
    _ok(long["wastageMetres"] == 0 and long["remnantsOut"], f"1.5m leftover = remnant {long}")

    # ── Interlock assignment ─────────────────────────────────────────
    a2 = assign_sliding_interlocks(glass_count=2)
    _ok(a2["slim"] == 1 and a2["renf"] == 1 and a2["glassReducerPcs"] == 2, f"2 glass {a2}")
    a3 = assign_sliding_interlocks(glass_count=3)
    _ok(a3["slim"] == 1 and a3["renf"] == 2 and a3["glassReducerPcs"] == 3, f"3 glass {a3}")
    a4c = assign_sliding_interlocks(glass_count=4, opening="center")
    _ok(a4c["slim"] == 2 and a4c["renf"] == 2, f"4 center {a4c}")
    a4s = assign_sliding_interlocks(glass_count=4, opening="side", track_count=4)
    _ok(a4s["slim"] == 1 and a4s["renf"] == 3, f"4-track side {a4s}")
    am = assign_sliding_interlocks(glass_count=2, mesh_count=1)
    _ok(am["meshSlim"] == 1 and am["renf"] == 1 and am["glassReducerPcs"] == 3, f"mesh slim only {am}")

    # ── Live casement cost ───────────────────────────────────────────
    case = load_product("40mm_casement_standard", strict=False)
    dcost = compute_casement_design_cost(
        {
            "width": 1200,
            "height": 1500,
            "qty": 1,
            "glass": "8mm_toughened",
            "colour": "white",
            "casementLayout": {
                "bands": [{"heightMm": 1500, "panels": [{"role": "openable", "widthMm": 1200}]}]
            },
        },
        product=case,
        setup=case.get("setup"),
    )
    _ok(dcost.get("ok") and dcost.get("costEngine") == "live", f"casement live {dcost.get('costEngine')} total={dcost.get('total')}")
    br = dcost.get("breakdown") or {}
    _ok(br.get("aluminium", 0) > 0, f"casement Al {br.get('aluminium')}")
    _ok(br.get("coating", 0) > 0, f"casement coat {br.get('coating')}")
    _ok(br.get("labour", 0) > 0, f"casement labour {br.get('labour')}")

    # ── Live sliding + interlocks ────────────────────────────────────
    from WEOS.factory.product_setup import defined_track_options

    slid = load_product("35mm_prestige", strict=False)
    defined = defined_track_options(slid.get("setup") or {})
    _ok(any(o["id"] == "3" for o in defined), f"35mm defined tracks {[o['id'] for o in defined]}")
    _ok("4" in {o["id"] for o in defined}, "35mm has 4-track defined")
    scost = compute_sliding_design_cost(
        {
            "width": 1800,
            "height": 2100,
            "qty": 1,
            "glass": "8mm_toughened",
            "colour": "black_texture",
            "glassShutters": 2,
            "meshShutters": 1,
            "trackCount": 3,
            "opening": "side",
        },
        product=slid,
        setup=slid.get("setup"),
    )
    _ok(scost.get("ok") and scost.get("costEngine") == "live", f"sliding live total={scost.get('total')}")
    inter = scost.get("interlocks") or {}
    _ok(inter.get("slim") == 1 and inter.get("renf") == 1 and inter.get("meshSlim") == 1, f"sliding interlocks {inter}")
    _ok(inter.get("glassReducerPcs") == 3, f"glass reducer pcs {inter.get('glassReducerPcs')}")
    uses = {str(p.get("use")) for p in (scost.get("profiles") or [])}
    _ok("interlock_slim" in uses or any("interlock" in u for u in uses), f"interlock profiles {uses}")
    _ok("glass_reducer" in uses, f"glass reducer in profiles {uses}")
    sbr = scost.get("breakdown") or {}
    _ok(sbr.get("aluminium", 0) > 0 and sbr.get("coating", 0) > 0, f"sliding Al/coat {sbr}")
    _ok(sbr.get("hardware", 0) > 0, f"sliding HW {sbr.get('hardware')}")

    # Cart trackCount must select that series' track section (not saved active=2 only)
    sc4 = compute_sliding_design_cost(
        {
            "width": 2050,
            "height": 1970,
            "qty": 1,
            "glass": "5mm_clear_toughened",
            "colour": "white",
            "glassShutters": 4,
            "meshShutters": 0,
            "trackCount": 4,
            "opening": "side",
            "system": "sliding",
        },
        product=slid,
    )
    b4 = sc4.get("breakdown") or {}
    _ok(
        sc4.get("ok") and b4.get("aluminium", 0) > 5000 and b4.get("coating", 0) > 0 and b4.get("hardware", 0) > 0,
        f"4-track 2050×1970 Al/coat/HW {b4} total={sc4.get('total')}",
    )
    # 25mm / 29mm must not offer undefined 4-track as the only BOM source
    p25 = load_product("25mm_prestige", strict=False)
    t25 = {o["id"] for o in defined_track_options(p25.get("setup") or {})}
    _ok("4" not in t25 and "3" in t25, f"25mm defined tracks only {t25}")
    for pid in ("27mm_high_end_domal", "31mm_gulf_lux_slim", "32mm_dual_euro"):
        px = load_product(pid, strict=False)
        sx = compute_sliding_design_cost(
            {
                "width": 2050,
                "height": 1970,
                "qty": 1,
                "glass": "5mm_clear_toughened",
                "colour": "white",
                "glassShutters": 3,
                "trackCount": 3,
                "opening": "side",
                "system": "sliding",
            },
            product=px,
        )
        bx = sx.get("breakdown") or {}
        _ok(
            bx.get("aluminium", 0) > 0 and bx.get("coating", 0) > 0 and bx.get("hardware", 0) > 0,
            f"{pid} 3T Al/coat/HW {bx}",
        )

    # ── Materials list ───────────────────────────────────────────────
    mats = build_quote_materials_list(
        [
            {
                "product": "35mm_prestige",
                "displayName": "35mm Sliding",
                "width": 1800,
                "height": 2100,
                "qty": 1,
                "glass": "8mm_toughened",
                "colour": "black_texture",
                "glassShutters": 2,
                "meshShutters": 1,
                "trackCount": 3,
                "opening": "side",
            }
        ],
        customer="Smoke",
    )
    html = materials_list_html(mats)
    _ok("Sections used" in html or "Materials" in html, "materials html sections")
    _ok("Smoke" in html, "materials customer")
    row = (mats.get("lines") or [{}])[0]
    _ok(row.get("materials"), f"materials rows {len(row.get('materials') or [])}")

    # ── Stock viewer ─────────────────────────────────────────────────
    stock = stock_viewer_payload()
    _ok(stock.get("ok") and stock.get("remnants") is not None, f"stock remnants {stock.get('counts')}")

    print("Design cost / interlock / materials / stock smoke passed.")


if __name__ == "__main__":
    main()
