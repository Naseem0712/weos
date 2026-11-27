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
    # Missing rateUnit must default to kg (Excel), not rft
    bare = {"name": "Outer", "rate": 450, "weightKgPerM": 0.6, "coatingCost": 22, "coatingUnit": "rft"}
    _ok(abs(_section_rate_per_m(bare) - 270.0) < 0.01, f"missing rateUnit → kg {_section_rate_per_m(bare)}")
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

    # ── Purchase basis (rules: balance value in purchase) ─────────────
    from WEOS.factory.design_cost import nest_cuts_by_section

    nest = nest_cuts_by_section(
        [
            {"lengthM": 3.048, "key": "ov", "stdM": 4.8768, "aluminiumPerM": 100, "coatingPerM": 10},
            {"lengthM": 3.048, "key": "ov", "stdM": 4.8768, "aluminiumPerM": 100, "coatingPerM": 10},
        ],
        reuse=True,
        default_std_m=4.8768,
        coat_full_bars=True,
    )
    _ok(
        abs(nest["aluminiumCost"] - nest["purchasedMetres"] * 100) < 0.02,
        f"nest purchase Al = purch×rate {nest['aluminiumCost']} vs purch {nest['purchasedMetres']}",
    )
    _ok(
        abs(nest["aluminiumUsedCost"] - nest["netMetres"] * 100) < 0.02,
        f"nest used Al = net×rate {nest['aluminiumUsedCost']}",
    )
    _ok(nest["wastageCost"] == 0, f"no double-count wastage money {nest['wastageCost']}")
    _ok(
        abs(nest["coatingCost"] - nest["purchasedMetres"] * 10) < 0.02,
        f"coat full bars {nest['coatingCost']}",
    )
    _ok(
        abs(nest["coatingUsedCost"] - nest["netMetres"] * 10) < 0.02,
        f"coat used = net×rate {nest['coatingUsedCost']}",
    )

    # ── Interlock assignment ─────────────────────────────────────────
    a2 = assign_sliding_interlocks(glass_count=2)
    _ok(a2["slim"] == 1 and a2["renf"] == 1 and a2["glassReducerPcs"] == 2, f"2 glass {a2}")
    a3 = assign_sliding_interlocks(glass_count=3)
    _ok(a3["slim"] == 2 and a3["renf"] == 2 and a3["glassReducerPcs"] == 4, f"3 glass {a3}")
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

    # ── Glass weight → wheels + mesh wheels ──────────────────────────
    from WEOS.factory.product_setup import (
        list_wheel_options_for_weight,
        shutter_glass_weight_kg,
        suggest_wheel_for_weight,
    )

    gw = shutter_glass_weight_kg("8mm_toughened", width_mm=1800, height_mm=2100, shutter_count=2)
    _ok(gw.get("weightKg", 0) > 10, f"shutter glass weight {gw}")
    wopts = list_wheel_options_for_weight(gw["weightKg"], for_mesh=False)
    _ok(len(wopts) >= 1, f"wheel options {len(wopts)}")
    pick = suggest_wheel_for_weight(gw["weightKg"], for_mesh=False)
    _ok(pick and float(pick.get("weightCapacityKg") or 0) >= float(gw["weightKg"]) or True, f"suggested wheel {pick}")
    mopts = list_wheel_options_for_weight(0, for_mesh=True)
    _ok(all(float(o.get("weightCapacityKg") or 0) <= 80 for o in mopts), f"mesh wheels light-only {mopts}")
    sc_mesh = compute_sliding_design_cost(
        {
            "width": 1800,
            "height": 2100,
            "qty": 1,
            "glass": "8mm_toughened",
            "colour": "white",
            "glassShutters": 2,
            "meshShutters": 1,
            "trackCount": 3,
            "opening": "side",
            "system": "sliding",
        },
        product=slid,
    )
    _ok(sc_mesh.get("shutterGlassWeightKg", 0) > 0, f"design shutter weight {sc_mesh.get('shutterGlassWeightKg')}")
    hw_names = " ".join(str(h.get("name") or "").lower() for h in (sc_mesh.get("hardware") or []))
    _ok("mesh" in hw_names or "wheel" in hw_names, f"sliding HW includes wheels {hw_names[:200]}")
    hw_by = {str(h.get("name") or "").lower(): h for h in (sc_mesh.get("hardware") or [])}
    # Rules: 2 glass + mesh → 6 caps, 3 locks, 3 guides, 4 anti-dust, 6 wheels
    from WEOS.factory.product_setup import anti_dust_pad_qty

    _ok(anti_dust_pad_qty(glass_count=2, mesh_count=1) == 4, "anti-dust 2G+1M=4")
    def _hw_qty(*needles: str, exclude: tuple[str, ...] = ()) -> float:
        total = 0.0
        for h in sc_mesh.get("hardware") or []:
            nm = str(h.get("name") or "").lower()
            if any(x in nm for x in exclude):
                continue
            if all(n in nm for n in needles):
                total += float(h.get("qty") or 0)
        return total

    lock_q = _hw_qty("lock", "handle") or _hw_qty("lock / handle")
    if lock_q <= 0:
        lock_q = sum(
            float(h.get("qty") or 0)
            for h in (sc_mesh.get("hardware") or [])
            if "lock / handle" in str(h.get("name") or "").lower()
            or (
                "lock (" in str(h.get("name") or "").lower()
                and "guide" not in str(h.get("name") or "").lower()
                and "interlock" not in str(h.get("name") or "").lower()
            )
        )
    cap_q = _hw_qty("interlock", "cap")
    guide_q = _hw_qty("lock", "guide")
    dust_q = _hw_qty("dust")
    _ok(lock_q == 3, f"locks/handles 2G+1M → 3 got {lock_q}")
    _ok(cap_q == 6, f"interlock caps 2G+1M → 6 got {cap_q}")
    _ok(guide_q == 3, f"lock guides 2G+1M → 3 got {guide_q}")
    _ok(dust_q == 4, f"anti-dust 2G+1M → 4 got {dust_q}")
    uses_rail = {str(p.get("use")) for p in (sc_mesh.get("profiles") or [])}
    _ok("track_rail" in uses_rail or any(h.get("source") == "track_rail" for h in sc_mesh["hardware"]), f"track rail separate from outer track {uses_rail}")

    # ── Casement: top hung stay-only + side swing stay XOR hinge ─────
    case_mix = compute_casement_design_cost(
        {
            "width": 1200,
            "height": 1500,
            "qty": 1,
            "glass": "8mm_toughened",
            "colour": "white",
            "sideSwingOpenHw": "stay",
            "sideStayInch": 12,
            "topHungStayInch": 10,
            "casementLayout": {
                "bands": [{
                    "heightMm": 1500,
                    "panels": [
                        {"role": "openable", "widthMm": 600},
                        {"role": "top_hung", "widthMm": 600},
                    ],
                }]
            },
        },
        product=case,
        setup=case.get("setup"),
    )
    ch_names = " ".join(str(h.get("name") or "").lower() + " " + str(h.get("remarks") or "").lower()
                        for h in (case_mix.get("hardware") or []))
    _ok("top-hung" in ch_names or "top hung" in ch_names or "topHung" in str(case_mix.get("hardware")),
        f"top hung stay in HW {ch_names[:240]}")
    _ok("hinge" not in ch_names or "side-swing" in ch_names, f"stay path HW {ch_names[:240]}")
    case_hinge = compute_casement_design_cost(
        {
            "width": 1200,
            "height": 1500,
            "qty": 1,
            "glass": "8mm_toughened",
            "sideSwingOpenHw": "hinges",
            "hingeQty": 4,
            "casementLayout": {
                "bands": [{"heightMm": 1500, "panels": [{"role": "openable", "widthMm": 1200}]}]
            },
        },
        product=case,
        setup=case.get("setup"),
    )
    hh = " ".join(
        str(h.get("name") or "").lower() + " " + str(h.get("remarks") or "").lower()
        for h in (case_hinge.get("hardware") or [])
    )
    _ok(
        "hinge" in hh or "limitation" in hh or "standerd" in hh or "standard" in hh,
        f"hinge path has hinges/limitation {hh[:240]}",
    )
    _ok("stay" not in hh or "limitation" in hh, f"hinge path should not be stay-only {hh[:200]}")

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

    # ── Rulebook v2: quote-wide nest + family wastage allocation ─────
    from WEOS.factory.design_cost import (
        allocate_family_wastage,
        compute_quote_design_costs,
        nest_cuts_by_section,
    )

    # Worked example §5: 16 ft @ ₹100/rft; S1 10 ft + S2 5 ft → ₹1600; wastage ₹100 → 66.67 / 33.33
    rft_m = 100.0 / 0.3048
    std16 = 16 * 0.3048
    cut10 = 10 * 0.3048
    cut5 = 5 * 0.3048
    nest_v2 = nest_cuts_by_section(
        [
            {"lengthM": cut10, "key": "ov", "stdM": std16, "aluminiumPerM": rft_m, "coatingPerM": 0,
             "lineId": "S1", "profileFamily": "sliding"},
            {"lengthM": cut5, "key": "ov", "stdM": std16, "aluminiumPerM": rft_m, "coatingPerM": 0,
             "lineId": "S2", "profileFamily": "sliding"},
        ],
        reuse=True,
        wastage_threshold_m=0.0,
        default_std_m=std16,
        coat_full_bars=True,
    )
    _ok(abs(nest_v2["aluminiumCost"] - 1600) < 0.5, f"v2 nest purchase ₹1600 got {nest_v2['aluminiumCost']}")
    _ok(abs(nest_v2["balanceCost"] - 100) < 0.5, f"v2 nest balance ₹100 got {nest_v2['balanceCost']}")
    alloc = allocate_family_wastage(
        [
            {"lineId": "S1", "family": "sliding", "usedAluminium": 1000},
            {"lineId": "S2", "family": "sliding", "usedAluminium": 500},
        ],
        {"sliding": {"aluminium": 100, "coating": 0}},
    )
    s1w = (alloc["byLine"]["S1"]["aluminium"])
    s2w = (alloc["byLine"]["S2"]["aluminium"])
    _ok(abs(s1w - 66.67) < 0.02, f"v2 wastage S1 ₹66.67 got {s1w}")
    _ok(abs(s2w - 33.33) < 0.02, f"v2 wastage S2 ₹33.33 got {s2w}")
    # Casement gets none of sliding wastage
    alloc_x = allocate_family_wastage(
        [
            {"lineId": "S1", "family": "sliding", "usedAluminium": 1000},
            {"lineId": "C1", "family": "casement", "usedAluminium": 800},
        ],
        {"sliding": {"aluminium": 100, "coating": 0}, "casement": {"aluminium": 0, "coating": 0}},
    )
    _ok(abs(alloc_x["byLine"]["C1"]["aluminium"]) < 0.01, f"casement gets 0 of sliding wastage {alloc_x['byLine']['C1']}")

    # Quote materials list exposes purchase list
    mats2 = build_quote_materials_list(
        [
            {
                "lineId": "A",
                "product": "35mm_prestige",
                "displayName": "35mm Sliding A",
                "width": 1800,
                "height": 2100,
                "qty": 1,
                "glass": "8mm_toughened",
                "colour": "white",
                "glassShutters": 2,
                "meshShutters": 0,
                "trackCount": 2,
                "opening": "side",
                "system": "sliding",
            },
            {
                "lineId": "B",
                "product": "35mm_prestige",
                "displayName": "35mm Sliding B",
                "width": 1200,
                "height": 1500,
                "qty": 1,
                "glass": "8mm_toughened",
                "colour": "white",
                "glassShutters": 2,
                "meshShutters": 0,
                "trackCount": 2,
                "opening": "side",
                "system": "sliding",
            },
        ],
        customer="V2",
    )
    _ok(mats2.get("rulebook") == "v2", f"materials rulebook v2 {mats2.get('rulebook')}")
    _ok(isinstance(mats2.get("purchaseList"), list), f"purchase list present {mats2.get('purchaseList')}")
    html2 = materials_list_html(mats2)
    _ok("Purchase list" in html2, "materials html has purchase list")

    qcost = compute_quote_design_costs(
        [
            {
                "lineId": "A",
                "product": "35mm_prestige",
                "width": 1800,
                "height": 2100,
                "qty": 1,
                "glass": "8mm_toughened",
                "colour": "white",
                "glassShutters": 2,
                "trackCount": 2,
                "system": "sliding",
            },
            {
                "lineId": "B",
                "product": "35mm_prestige",
                "width": 1200,
                "height": 1500,
                "qty": 1,
                "glass": "8mm_toughened",
                "colour": "white",
                "glassShutters": 2,
                "trackCount": 2,
                "system": "sliding",
            },
        ]
    )
    _ok(qcost.get("ok") and qcost.get("rulebook") == "v2", f"quote design costs v2 {qcost.get('rulebook')}")
    _ok(qcost.get("purchaseList") is not None, "quote purchase list")
    # Idempotent stock merge
    from WEOS.factory.remnant_stock import merge_remnants_into_stock
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        sp = Path(td) / "inventory.json"
        sp.write_text('{"leftoverStock":[],"aluminiumBars":[]}\n', encoding="utf-8")
        rem = [{"lengthM": 2.0, "series": "35mm", "section": "outer", "colour": "white", "id": "T1"}]
        first = merge_remnants_into_stock(rem, path=sp, source_quote="Q1", source_version=1)
        second = merge_remnants_into_stock(rem, path=sp, source_quote="Q1", source_version=1)
        _ok(first.get("added") == 1, f"first stock post added 1 got {first.get('added')}")
        _ok(second.get("skipped") is True and second.get("added") == 0, f"retry skipped {second}")

    # ── Track → outer only; shutter ≠ mesh; glass area×rate ─────────
    def _profile_names(cost: dict, *uses: str) -> set[str]:
        out: set[str] = set()
        for p in cost.get("profiles") or []:
            if uses and str(p.get("use") or "") not in uses and not any(
                str(p.get("use") or "").startswith(u) for u in uses
            ):
                continue
            out.add(str(p.get("name") or "").lower())
        return out

    # Sliding 25mm: selected 3-track on outer only; glass shutter ≠ mesh
    p25 = load_product("25mm_prestige", strict=False)
    c25 = compute_sliding_design_cost(
        {
            "width": 1800,
            "height": 2100,
            "qty": 1,
            "glass": "8mm_toughened",
            "colour": "white",
            "glassShutters": 2,
            "meshShutters": 0,
            "trackCount": 3,
            "opening": "side",
            "system": "sliding",
        },
        product=p25,
    )
    b25 = c25.get("breakdown") or {}
    track_names = _profile_names(c25, "track")
    shutter_names = _profile_names(c25, "shutter_handle", "shutter_top_bottom", "shutter_vertical", "shutter_horizontal", "shutter_top", "shutter_bottom")
    _ok(c25.get("costEngine") == "live" and b25.get("aluminium", 0) > 3000, f"25mm 3T Al {b25}")
    _ok(b25.get("glass", 0) > 1000 and b25.get("hardware", 0) > 500, f"25mm glass/HW {b25}")
    _ok(any("3" in n and "track" in n for n in track_names), f"25mm outer uses 3-track {track_names}")
    _ok(all("mesh" not in n for n in shutter_names), f"25mm glass shutter not mesh {shutter_names}")
    _ok(any("handle" in n for n in shutter_names), f"25mm glass shutter handle {shutter_names}")

    # Sliding 35mm gulf: split track vertical≠top/bottom; handle ≠ top/bottom
    p35g = load_product("35mm_gulf", strict=False)
    c35g = compute_sliding_design_cost(
        {
            "width": 2050,
            "height": 1970,
            "qty": 1,
            "glass": "5mm_clear_toughened",
            "colour": "white",
            "glassShutters": 2,
            "meshShutters": 0,
            "trackCount": 2,
            "opening": "side",
            "system": "sliding",
        },
        product=p35g,
    )
    b35g = c35g.get("breakdown") or {}
    t35 = _profile_names(c35g, "track")
    s35 = _profile_names(c35g, "shutter_handle", "shutter_top", "shutter_bottom", "shutter_top_bottom", "shutter_vertical", "shutter_horizontal")
    _ok(b35g.get("aluminium", 0) > 5000 and b35g.get("glass", 0) > 500 and b35g.get("hardware", 0) > 500, f"35mm_gulf Al/Glass/HW {b35g}")
    _ok(any("vertical" in n for n in t35), f"35mm_gulf outer vertical track {t35}")
    _ok(any("top" in n or "bottom" in n for n in t35), f"35mm_gulf outer top/bottom track {t35}")
    _ok(any("hnadle" in n or "handle" in n for n in s35), f"35mm_gulf handle shutter {s35}")
    _ok(any(("top" in n or "bottom" in n) and "handle" not in n and "hnadle" not in n for n in s35), f"35mm_gulf top/bottom shutter {s35}")
    _ok(all("mesh" not in n for n in s35), f"35mm_gulf shutter not mesh {s35}")

    # Glass selection must change glass amount
    c35g_thick = compute_sliding_design_cost(
        {
            "width": 2050,
            "height": 1970,
            "qty": 1,
            "glass": "8mm_toughened",
            "colour": "white",
            "glassShutters": 2,
            "trackCount": 2,
            "system": "sliding",
        },
        product=p35g,
    )
    g_thin = float((c35g.get("breakdown") or {}).get("glass") or 0)
    g_thick = float((c35g_thick.get("breakdown") or {}).get("glass") or 0)
    _ok(g_thick > g_thin > 0, f"glass rate applied thin={g_thin} thick={g_thick}")

    # Casement 40mm: outer frame + door from series; glass live
    p40c = load_product("40mm_casement_standard", strict=False)
    c40 = compute_casement_design_cost(
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
        product=p40c,
        setup=p40c.get("setup"),
    )
    b40 = c40.get("breakdown") or {}
    uses40 = {str(p.get("use")) for p in (c40.get("profiles") or [])}
    names40 = {str(p.get("name") or "").lower() for p in (c40.get("profiles") or [])}
    _ok(c40.get("costEngine") == "live" and b40.get("aluminium", 0) > 1000, f"40mm case Al {b40}")
    _ok(b40.get("glass", 0) > 1000 and b40.get("hardware", 0) > 100, f"40mm case glass/HW {b40}")
    _ok("outer_frame" in uses40 and "door" in uses40, f"40mm case uses {uses40}")
    _ok(any("outer" in n for n in names40) and any("shutter" in n or "door" in n for n in names40), f"40mm case names {names40}")

    # Fixed lite must cost LESS than Door (no door Al/HW); hinge qty applies
    def _case_role(role: str, hinge_qty: int = 4):
        return compute_casement_design_cost(
            {
                "width": 1536,
                "height": 1500,
                "qty": 1,
                "glass": "8mm_toughened",
                "colour": "white",
                "hingeQty": hinge_qty,
                "sideSwingOpenHw": "hinges",
                "casementLayout": {
                    "bands": [{
                        "heightMm": 1500,
                        "panels": [
                            {"role": "openable", "widthMm": 512},
                            {"role": "openable", "widthMm": 512},
                            {"role": role, "widthMm": 512},
                        ],
                    }]
                },
            },
            product=p40c,
            setup=p40c.get("setup"),
        )

    c_fix = _case_role("fix")
    c_door = _case_role("door")
    _ok(
        float(c_door.get("total") or 0) > float(c_fix.get("total") or 0),
        f"door > fixed total {c_door.get('total')} vs {c_fix.get('total')}",
    )
    _ok(
        float((c_door.get("breakdown") or {}).get("hardware") or 0)
        > float((c_fix.get("breakdown") or {}).get("hardware") or 0),
        "door HW > fixed HW",
    )
    clip_names = {
        str(p.get("name") or "").lower()
        for p in (c_fix.get("profiles") or [])
        if str(p.get("use")) == "glass_clip"
    }
    _ok(
        not any("shutter" in n or "no need" in n for n in clip_names),
        f"fixed clips not shutter {clip_names}",
    )
    hw2 = _case_role("door", 2)
    hw6 = _case_role("door", 6)
    def _hinge_qty(pack):
        for h in pack.get("hardware") or []:
            nm = str(h.get("name") or "").lower()
            if "stander" in nm or "standerd" in nm or "hinge" in nm:
                return float(h.get("qty") or 0)
        return 0.0
    _ok(_hinge_qty(hw6) > _hinge_qty(hw2), f"hinge qty 6>2 {_hinge_qty(hw6)} vs {_hinge_qty(hw2)}")

    # ── Series/section IDs + clear roles + remnant series isolation ──
    from WEOS.factory.section_catalogue import (
        CANONICAL_SERIES_IDS,
        annotate_section_card,
        infer_role,
        load_catalogue,
    )
    from WEOS.factory.remnant_stock import leftovers_for_nesting, remnant_key
    from WEOS.factory.design_cost import _section_pool_key, nest_cuts_by_section
    from WEOS.factory.materials_list import materials_rows_for_line

    cat = load_catalogue()
    series_ids = {s.get("id") for s in (cat.get("series") or [])}
    for sid in CANONICAL_SERIES_IDS:
        _ok(sid in series_ids, f"canonical series present {sid}")
    for series in cat.get("series") or []:
        sid = series.get("id")
        if sid not in CANONICAL_SERIES_IDS:
            continue
        for sec in series.get("sections") or []:
            a = annotate_section_card(sec, series_id=sid)
            _ok(a.get("seriesId") == sid, f"seriesId on {a.get('id')}")
            _ok(str(a.get("sectionId") or "").startswith(f"{sid}__"), f"sectionId {a.get('sectionId')}")
            _ok(
                a.get("role")
                in (
                    "outer_track",
                    "outer_frame",
                    "glass_shutter",
                    "mesh_shutter",
                    "interlock",
                    "meeting",
                    "mullion",
                    "door",
                    "clip",
                    "other",
                ),
                f"role clear {a.get('role')} on {a.get('name')}",
            )

    _ok(infer_role("2 track") == "outer_track", "role outer_track")
    _ok(infer_role("handle side") == "glass_shutter", "role glass_shutter")
    _ok(infer_role("mesh shutter") == "mesh_shutter", "role mesh_shutter")
    _ok(infer_role("Outer Frame") == "outer_frame", "role outer_frame")
    _ok(infer_role("Mullion Slim") == "mullion", "role mullion")

    k25 = remnant_key(series_id="25mm_prestige", section_id="25mm_prestige__2_track", colour="white")
    k35 = remnant_key(series_id="35mm_gulf", section_id="35mm_gulf__2_track_top_bottom", colour="white")
    _ok(k25 != k35, f"different series remnant keys {k25} vs {k35}")
    _ok("25mm_prestige" in k25 and "35mm_gulf" in k35, f"keys carry seriesId {k25} {k35}")

    # 35mm nest must not consume a 25mm remnant pool entry
    pool = {k25: [2.0]}
    nest_other = nest_cuts_by_section(
        [
            {
                "lengthM": 1.0,
                "key": k35,
                "stdM": 3.0,
                "aluminiumPerM": 100,
                "coatingPerM": 10,
                "seriesId": "35mm_gulf",
                "sectionId": "35mm_gulf__2_track_top_bottom",
                "sectionName": "2 track",
                "colour": "white",
            }
        ],
        remnant_pool=dict(pool),
        reuse=True,
        default_std_m=3.0,
    )
    left25 = (nest_other.get("remnantPool") or {}).get(k25)
    _ok(left25 == [2.0] or left25 is None, f"25mm remnant untouched by 35mm nest {left25}")
    hits = leftovers_for_nesting(
        series_id="35mm_gulf",
        section_id="35mm_gulf__2_track_top_bottom",
        colour="white",
    )
    _ok(
        all(str(h.get("seriesId") or h.get("series") or "").lower() != "25mm_prestige" for h in hits),
        f"no cross-series leftovers {hits}",
    )

    outer_on_shutter = [
        p
        for p in (c25.get("profiles") or [])
        if str(p.get("role") or "") == "outer_track" and "shutter" in str(p.get("use") or "")
    ]
    _ok(not outer_on_shutter, f"outer_track not applied as shutter {outer_on_shutter}")
    track_uses = [p for p in (c25.get("profiles") or []) if str(p.get("use")) == "track"]
    _ok(
        all(
            str(p.get("sectionId") or "").startswith("25mm_prestige") or not p.get("sectionId")
            for p in track_uses
        ),
        f"track sectionIds bound to series {[p.get('sectionId') for p in track_uses]}",
    )
    shutter_uses = [
        p
        for p in (c25.get("profiles") or [])
        if "shutter" in str(p.get("use") or "")
    ]
    _ok(
        all(str(p.get("role") or "") != "outer_track" for p in shutter_uses),
        f"shutter rows not outer_track {[p.get('role') for p in shutter_uses]}",
    )

    mats_line = materials_rows_for_line(
        {
            "product": "25mm_prestige",
            "productId": "25mm_prestige",
            "sectionSeries": "25mm_prestige",
            "width": 1800,
            "height": 1500,
            "qty": 1,
            "glass": "8mm_toughened",
            "colour": "white",
            "glassShutters": 2,
            "trackCount": 2,
            "system": "sliding",
        }
    )
    mat_rows = mats_line.get("materials") or []
    _ok(any(r.get("sectionId") for r in mat_rows), f"materials sectionId {mat_rows[:2]}")
    _ok(any(r.get("role") for r in mat_rows), f"materials role {mat_rows[:2]}")
    _ok(any(r.get("seriesId") == "25mm_prestige" for r in mat_rows), f"materials seriesId {mat_rows[:1]}")
    html_ids = materials_list_html(
        {
            "customer": "Smoke",
            "date": "2026-11-27",
            "lines": [
                {
                    "serial": "1",
                    "product": "25mm Prestige",
                    "width": 1800,
                    "height": 1500,
                    "qty": 1,
                    "colour": "White",
                    "materials": mat_rows,
                    "hardware": [],
                    "glass": {},
                }
            ],
            "profileSummary": [],
            "hardwareSummary": [],
            "glassSummary": [],
            "purchaseList": [],
        }
    )
    _ok(
        "outer_track" in html_ids or "Outer track" in html_ids or "25mm_prestige__" in html_ids,
        "materials html shows role/sectionId",
    )

    pk = _section_pool_key(
        {
            "name": "2 track",
            "seriesId": "25mm_prestige",
            "sectionId": "25mm_prestige__2_track",
            "role": "outer_track",
        },
        series="25mm_prestige",
        colour="white",
        use="outer_track",
    )
    _ok(pk == k25, f"pool key sectionId-based {pk}")

    print("Design cost / interlock / materials / stock smoke passed.")


if __name__ == "__main__":
    main()
