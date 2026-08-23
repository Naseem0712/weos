"""Single customer-facing window/casement/vent spec builder.

Keep quote text short: no SERIES dump, no ALUMINIUM repeat, no JOINT/INTERLOCK,
no five SECTION rows, no shutter_N_glass ids. Factory PDF may still dump BOM.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

_INTERNAL_GLASS = re.compile(
    r"(?:fix_)?shutter_\d+_glass|fix_[a-z]+_glass|left_glass|right_glass",
    re.I,
)
_SG_DG_TOKEN = re.compile(r"(?i)(?:^|[\s,;/]+)(?:sg|dg|gd|dgu)\b")


def _laminated_config_label(thickness_mm: Any, glass_type: str = "") -> str | None:
    """Customer-facing laminated makeup e.g. ``6+1.52+5 mm Laminated``.

    Never nearest-match 8/10/12/15mm singles into a laminated construction.
    """
    gt = str(glass_type or "").lower()
    if "lam" not in gt and "pvb" not in gt:
        return None
    try:
        thk = float(thickness_mm or 0)
    except (TypeError, ValueError):
        thk = 0.0
    try:
        from WEOS.factory.glass_catalogue import LAMINATED_MAKEUPS_MM, default_layers_for

        layers = default_layers_for("laminated", thk) if thk in LAMINATED_MAKEUPS_MM else {}
        if not layers and thk:
            # Exact table keys only (11.52, 12.52, …) — do not snap 12mm tuff to 12.52.
            if thk in LAMINATED_MAKEUPS_MM:
                layers = dict(LAMINATED_MAKEUPS_MM[thk])
        g1, pvb, g2 = layers.get("glass1Mm"), layers.get("pvbMm"), layers.get("glass2Mm")
        if g1 and pvb and g2:
            return f"{g1:g}+{pvb:g}+{g2:g} mm Laminated"
    except Exception:
        pass
    return None


def is_internal_glass_name(name: Any) -> bool:
    s = str(name or "").strip()
    if not s:
        return True
    if _INTERNAL_GLASS.search(s.replace(" ", "_")):
        return True
    if re.fullmatch(r"(?:fix[_\s-]?)?shutter[_\s-]?\d+(?:[_\s-]?glass)?", s, re.I):
        return True
    return False


def glass_family_from_makeup(makeup: Any, *, glass_id: Any = None, name: Any = None) -> str:
    """``single`` (SG, including laminated) or ``dgu`` (DG/IGU with air gap)."""
    blob = " ".join(str(x or "") for x in (makeup, glass_id, name)).lower().replace("-", "_")
    if re.search(r"\d+\s*\+\s*\d+\s*a\s*\+\s*\d+", blob):
        return "dgu"
    if any(k in blob for k in ("dgu", "igu", "double_glaz", "doubleglaz", "insulated")):
        return "dgu"
    return "single"


def glass_family_from_line(line: Mapping[str, Any] | None) -> str:
    line = line or {}
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    gspec = line.get("glassSpec") if isinstance(line.get("glassSpec"), Mapping) else {}
    glass = line.get("glass")
    if not (isinstance(glass, list) and glass) and isinstance(opts, Mapping):
        glass = opts.get("glass") or glass
    g0: Mapping[str, Any] = {}
    if isinstance(glass, list) and glass and isinstance(glass[0], Mapping):
        g0 = glass[0]
    elif isinstance(glass, Mapping):
        g0 = glass
    makeup = (
        g0.get("makeup")
        or gspec.get("makeup")
        or opts.get("glassMakeup")
        or line.get("glassMakeup")
        or ""
    )
    gid = ""
    if isinstance(glass, str):
        gid = glass
    else:
        gid = str(g0.get("id") or gspec.get("id") or opts.get("glassId") or line.get("glassId") or "")
        if not gid and isinstance(line.get("glass"), str):
            gid = str(line.get("glass"))
    name = g0.get("name") or gspec.get("name") or ""
    if not makeup and gid:
        try:
            from WEOS.factory.glass_catalogue import get_glass

            spec = get_glass(str(gid).split("@")[0].strip())
            makeup = spec.get("makeup") or makeup
            name = spec.get("name") or name
        except Exception:
            pass
    return glass_family_from_makeup(makeup, glass_id=gid, name=name)


def clean_profile_print_name(name: Any) -> str:
    """Strip sg/dg/dgu tags so dual-tagged catalogue rows never print 'sg, dg'."""
    raw = str(name or "").strip()
    if not raw:
        return ""
    cleaned = _SG_DG_TOKEN.sub(" ", raw)
    cleaned = re.sub(r"[\s,;]+", " ", cleaned).strip(" ,;/-")
    return cleaned or raw


def _mm_txt(v: Any) -> str:
    from WEOS.factory.fmt import mm_str

    return mm_str(v, suffix="")


def _money_txt(v: Any) -> str:
    try:
        from WEOS.factory.pdf_fonts import money_text

        return money_text(v)
    except Exception:
        try:
            return f"{float(v):.2f}"
        except (TypeError, ValueError):
            return str(v or "")


def _area_sqft(w: float, h: float) -> float:
    return round((w * h) / 1_000_000.0 * 10.7639, 2)


def _lookup_glass_spec(line: Mapping[str, Any]) -> dict[str, Any]:
    from WEOS.factory.quote_item_snapshot import get_glass_snapshot

    snap = get_glass_snapshot(line)
    if snap:
        out = dict(snap)
        if snap.get("display_label"):
            out["display_label"] = snap["display_label"]
        if snap.get("glass_id") and not out.get("id"):
            out["id"] = snap["glass_id"]
        if snap.get("glass_construction") and not out.get("makeup"):
            out["makeup"] = snap["glass_construction"]
        return out
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    gspec = dict(line.get("glassSpec") or {}) if isinstance(line.get("glassSpec"), Mapping) else {}
    glass = line.get("glass")
    if not (isinstance(glass, list) and glass) and isinstance(opts, Mapping):
        glass = opts.get("glass") if opts.get("glass") is not None else glass
    g0: dict[str, Any] = {}
    gid = ""
    if isinstance(glass, list) and glass:
        if isinstance(glass[0], Mapping):
            g0 = dict(glass[0])
            gid = str(g0.get("id") or "")
        elif glass[0]:
            gid = str(glass[0])
    elif isinstance(glass, Mapping):
        g0 = dict(glass)
        gid = str(g0.get("id") or "")
    elif isinstance(glass, str) and glass.strip():
        gid = glass.split("@")[0].strip()
    if not gid:
        gid = str(g0.get("id") or gspec.get("id") or (opts or {}).get("glassId") or line.get("glassId") or "")
    lib: dict[str, Any] = {}
    if gid:
        try:
            from WEOS.factory.glass_catalogue import get_glass

            lib = dict(get_glass(str(gid).split("@")[0].strip()) or {})
        except Exception:
            lib = {}
    out = {**lib, **gspec, **g0}
    if gid and not out.get("id"):
        out["id"] = gid.split("@")[0].strip() if isinstance(gid, str) else gid
    if isinstance(opts, Mapping):
        if opts.get("glassColour") and not out.get("colour"):
            out["colour"] = opts.get("glassColour")
        if opts.get("glassBrand") and not out.get("brand"):
            out["brand"] = opts.get("glassBrand")
        if opts.get("glassMakeup") and not out.get("makeup"):
            out["makeup"] = opts.get("glassMakeup")
    return out


def human_glass_label(line: Mapping[str, Any]) -> str:
    """Thickness (+ laminated/DGU makeup) · colour · brand. Never internal ids."""
    from WEOS.factory.quote_item_snapshot import get_glass_snapshot, glass_display_label

    snap = get_glass_snapshot(line)
    if snap:
        label = glass_display_label(snap)
        if label:
            return label
    spec = _lookup_glass_spec(line)
    if spec.get("display_label"):
        return str(spec["display_label"])
    thick = spec.get("thicknessMm") or spec.get("thickness_mm") or spec.get("overallMm")
    makeup = str(spec.get("makeup") or spec.get("kind") or "").lower()
    makeup_lbl = str(spec.get("makeupLabel") or "")
    gcolour = spec.get("colour") or spec.get("color") or ""
    gbrand = spec.get("brand") or ""
    gname = spec.get("name") or spec.get("label") or ""
    if is_internal_glass_name(gname):
        gname = ""

    lam = _laminated_config_label(thick, makeup or gname)
    if not lam and "+" in makeup_lbl and "a+" not in makeup_lbl.lower().replace(" ", ""):
        lam = makeup_lbl.replace("PVB", "").strip()
        if lam and not lam.lower().endswith("mm"):
            lam = f"{lam}mm"
    dgu_lbl = ""
    if makeup in ("dgu", "igu", "double", "insulated") or glass_family_from_makeup(makeup, name=gname) == "dgu":
        g1, gap, g2 = spec.get("glass1Mm"), spec.get("airGapMm"), spec.get("glass2Mm")
        if g1 and gap and g2:
            dgu_lbl = f"{g1:g}+{gap:g}A+{g2:g}"
        elif makeup_lbl:
            dgu_lbl = makeup_lbl

    bits: list[str] = []
    if lam:
        bits.append(str(lam))
    elif dgu_lbl:
        dtxt = str(dgu_lbl)
        if "dgu" not in dtxt.lower():
            dtxt = f"{dtxt} mm DGU" if not dtxt.lower().endswith("dgu") else dtxt
        bits.append(dtxt)
    elif thick not in (None, ""):
        bits.append(f"{thick:g} mm" if isinstance(thick, (int, float)) else f"{thick} mm")
    if gcolour and str(gcolour).lower() not in " ".join(str(b).lower() for b in bits):
        bits.append(str(gcolour).replace("_", " "))
    if gbrand and str(gbrand).lower() not in " ".join(str(b).lower() for b in bits):
        bits.append(str(gbrand))
    if gname and not is_internal_glass_name(gname):
        nl = str(gname).replace("_", " ").strip()
        blob = " ".join(str(b).lower() for b in bits)
        if re.fullmatch(r"glass\s*\d+", nl, re.I):
            pass
        elif nl.lower() not in blob and not any(t in nl.lower() for t in ("shutter", "_glass")):
            # Skip name when it only restates thickness+colour already listed.
            if not (str(thick) and str(thick) in nl and (not gcolour or str(gcolour).lower() in nl.lower())):
                bits.append(nl)
    if not bits and isinstance(line.get("glass"), str) and line.get("glass"):
        raw = str(line["glass"]).split("@")[0].replace("_", " ").strip()
        if raw and not is_internal_glass_name(raw):
            bits.append(raw)
    return " · ".join(bits)


def _frame_material(line: Mapping[str, Any]) -> str:
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    raw = (
        line.get("frameMaterial")
        or (opts or {}).get("frameMaterial")
        or line.get("material")
        or (opts or {}).get("material")
        or "aluminium"
    )
    key = str(raw or "aluminium").strip().lower().replace("-", "").replace(" ", "")
    if key in ("upvc", "upv", "pvc"):
        return "upvc"
    return "aluminium"


def _upvc_print(text: Any, mat: str) -> str:
    s = str(text or "").strip()
    if mat != "upvc" or not s:
        return s
    s = re.sub(r"(?i)\balumin(?:ium|um)\b", "UPVC", s)
    s = re.sub(r"(?i)\balloy\b", "UPVC", s)
    s = re.sub(r"(?i)powder\s*-?\s*coat", "uPVC colour", s)
    return s


def _section_summary(line: Mapping[str, Any]) -> dict[str, Any]:
    from WEOS.factory.quote_item_snapshot import get_item_snapshot

    snap = get_item_snapshot(line)
    frozen = {}
    prof = snap.get("profile_snapshot") if isinstance(snap.get("profile_snapshot"), Mapping) else {}
    if prof:
        frozen = {k: v for k, v in prof.items() if v not in (None, "", [], {})}
    live = line.get("sectionSpecs") if isinstance(line.get("sectionSpecs"), Mapping) else {}
    section = dict(live or {})
    for k, v in frozen.items():
        if k in ("trackPrint", "sashPrint", "framePrint", "wallThicknessMm", "trackWallMm", "sashWallMm", "frameWallMm") and v:
            section[k] = v
        elif k not in section or section[k] in (None, "", [], {}):
            section[k] = v
    series = (
        frozen.get("sectionSeries")
        or snap.get("series_id")
        or line.get("sectionSeries")
        or ((line.get("options") or {}).get("sectionSeries") if isinstance(line.get("options"), Mapping) else None)
    )
    family = glass_family_from_line(line)
    layout = line.get("layout") if isinstance(line.get("layout"), Mapping) else {}
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    tc = layout.get("trackCount") if layout else None
    if tc is None:
        tc = (opts or {}).get("trackCount") or line.get("trackCount")
    try:
        from WEOS.factory.section_catalogue import specs_summary_for_series

        fresh = specs_summary_for_series(
            str(series) if series else (section or {}).get("seriesId"),
            glass_family=family,
            track_count=tc,
            clean_names=True,
        )
        if fresh:
            merged = dict(section or {})
            for k, v in fresh.items():
                if v in (None, "", [], {}):
                    continue
                existing = merged.get(k)
                if k in ("trackPrint", "sashPrint", "framePrint") and existing:
                    blob = str(existing)
                    if re.search(r"\d+\s*[×x]\s*\d+", blob) and "wall" in blob.lower():
                        continue
                if k in ("wallThicknessMm", "trackWallMm", "sashWallMm", "frameWallMm") and existing not in (None, ""):
                    continue
                merged[k] = v
            return merged
    except Exception:
        pass
    return dict(section or {})


def _dim_wall(sec_label: Any, wall: Any) -> str:
    text = str(sec_label or "").strip()
    # If catalogue already embedded wall, keep it.
    if wall not in (None, "") and "wall" not in text.lower():
        wtxt = f"{wall:g}" if isinstance(wall, (int, float)) else str(wall)
        text = f"{text} · wall {wtxt} mm" if text else f"wall {wtxt} mm"
    return text


def short_window_spec_rows(line: Mapping[str, Any], *, audience: str = "customer") -> list[tuple[str, str]]:
    """Customer window/door/casement/vent rows — one field each, no catalogue dump."""
    factory = str(audience or "customer").lower() == "factory"
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    layout = line.get("layout") if isinstance(line.get("layout"), Mapping) else {}
    specs_in = line.get("specifications") if isinstance(line.get("specifications"), Mapping) else {}
    w = float((layout or {}).get("widthMm") or line.get("width") or 0)
    h = float((layout or {}).get("heightMm") or line.get("height") or 0)
    section = _section_summary(line)
    family = glass_family_from_line(line)
    mat = _frame_material(line)
    system = str((layout or {}).get("system") or opts.get("system") or line.get("productType") or "").lower()
    is_bifold = system in ("bifold", "fold", "fold_sliding", "fold_and_sliding") or (
        str((layout or {}).get("kind") or "") == "fold_and_sliding"
    )
    is_casement = system in ("casement", "openable", "opening", "casements")
    is_vent = system in ("ventilator", "bathroom_ventilator")

    rows: list[tuple[str, str]] = []

    def add(label: str, value: Any) -> None:
        v = str(value or "").strip()
        if not v:
            return
        # Never leak internal glass ids or dual sg,dg tags.
        if is_internal_glass_name(v) or re.search(r"(?i)\bshutter_\d+_glass\b", v):
            return
        low = v.lower()
        if "sg" in low.split() and "dg" in low.split():
            v = clean_profile_print_name(v)
        rows.append((str(label or "").strip().upper(), v))

    try:
        from WEOS.factory.line_kind import line_world

        world = line_world(line)
    except Exception:
        world = "window"
    if world in ("louver", "pergola"):
        title = str(line.get("displayName") or ("Pergola" if world == "pergola" else "Louvers"))
        add("", title)
        add("SIZE", f"{_mm_txt(w)} x {_mm_txt(h)} mm")
        add("AREA", f"{_area_sqft(w, h)} Sq.Ft.")
        colour = opts.get("powderCoatName") or line.get("powderCoatName") or opts.get("colour") or line.get("colour")
        if world == "louver":
            fill = line.get("panelFill") if isinstance(line.get("panelFill"), Mapping) else opts.get("panelFill")
            fill = fill if isinstance(fill, Mapping) else {}
            orient = str(fill.get("orientation") or "horizontal").replace("_", " ").title()
            blade = fill.get("bladeWidthMm") or fill.get("bladeMm") or 80
            gap = fill.get("gapMm") or 20
            add("TYPE", "Standalone aluminium louvers")
            add("BLADE", f"{orient} blades - {_mm_txt(blade)} mm face")
            add("GAP", f"{_mm_txt(gap)} mm")
            add("MATERIAL", "Aluminium louver blades and outer frame")
        else:
            pergola = opts.get("pergola") if isinstance(opts.get("pergola"), Mapping) else {}
            fixing = pergola.get("fixing") or pergola.get("mount") or opts.get("fixing") or "Floor / wall / garden as specified"
            post = pergola.get("post") or pergola.get("postSection") or "Posts as specified"
            rafter = pergola.get("rafter") or pergola.get("rafterSection") or "Rafters as specified"
            cover = pergola.get("cover") or pergola.get("roofFill") or "Louvers / glass / polycarbonate as specified"
            add("TYPE", "Pergola catalogue design")
            add("FIXING", fixing)
            add("POSTS", post)
            add("RAFTERS", rafter)
            add("ROOF", cover)
        if colour:
            add("COLOUR", str(colour).replace("_", " ").title())
        return rows

    snap_title = ""
    ident = line.get("itemSnapshot") or line.get("item_snapshot")
    if isinstance(ident, Mapping):
        snap_title = str(ident.get("product_name_snapshot") or "").strip()
    title = str(snap_title or line.get("displayName") or line.get("product") or "Window")
    title = _upvc_print(title, mat)
    try:
        from WEOS.factory.section_catalogue import clean_series_print_name, has_track_option_dump

        if has_track_option_dump(title):
            cleaned_title = clean_series_print_name(title)
            if cleaned_title:
                title = cleaned_title
    except Exception:
        pass
    add("", title)
    add("SIZE", f"{_mm_txt(w)} × {_mm_txt(h)} mm")
    add("AREA", f"{_area_sqft(w, h)} Sq.Ft.")

    fill_type = "glass"
    try:
        from WEOS.factory.panel_fills import panel_fill_from_line

        fill_type = str((panel_fill_from_line(line) or {}).get("fillType") or "glass")
    except Exception:
        fill_type = "glass"
    is_louver_fill = fill_type in ("louvers", "aluminium_sheet", "compact_sheet")

    glass_n = (
        (layout or {}).get("glassCount")
        or opts.get("glassShutters")
        or opts.get("glassCount")
        or line.get("glassShutters")
    )
    mesh_n = (layout or {}).get("meshCount") or opts.get("meshShutters") or opts.get("meshCount") or 0
    try:
        glass_n_i = int(float(glass_n)) if glass_n not in (None, "") else 0
    except (TypeError, ValueError):
        glass_n_i = 0
    if glass_n_i <= 0:
        panels_tmp = list((layout or {}).get("panels") or [])
        glass_n_i = sum(
            1
            for p in panels_tmp
            if str(p.get("role") or "").lower() in ("sliding", "glass", "openable", "")
        )
        if glass_n_i <= 0 and panels_tmp:
            glass_n_i = len(panels_tmp)
    if glass_n_i > 0 and not is_louver_fill:
        opening_raw = (
            (layout or {}).get("opening")
            or (opts or {}).get("opening")
            or line.get("opening")
            or ""
        )
        opening_mode = str(opening_raw).strip().lower()
        if is_bifold or is_casement or is_vent:
            add("SHUTTER", f"{glass_n_i} Nos")
        else:
            if opening_mode not in ("center", "centre", "telescopic", "side"):
                opening_mode = "center" if glass_n_i == 4 else "side"
            if opening_mode in ("center", "centre"):
                add("SHUTTER", f"{glass_n_i} Nos · center opening")
            else:
                add("SHUTTER", f"{glass_n_i} Nos · side opening")

    wall = section.get("wallThicknessMm") or section.get("trackWallMm") or section.get("sashWallMm")
    track_lbl = _upvc_print(section.get("trackPrint") or section.get("track"), mat)
    sash_lbl = _upvc_print(section.get("sashPrint") or section.get("sash"), mat)
    frame_lbl = _upvc_print(section.get("framePrint") or section.get("frame"), mat)
    if is_casement or is_vent:
        add("FRAME", _dim_wall(frame_lbl or track_lbl, wall or section.get("frameWallMm")))
        if is_vent and mat == "upvc":
            add("PROFILE", "Casement / openable")
    elif not is_bifold:
        tc = (layout or {}).get("trackCount") if layout else None
        if tc is None:
            tc = (opts or {}).get("trackCount") or line.get("trackCount")
        track_wall = wall or section.get("trackWallMm")
        printed = ""
        try:
            from WEOS.factory.section_catalogue import (
                format_active_track_print,
                has_track_option_dump,
            )

            blob = str(track_lbl or "")
            has_dims = bool(re.search(r"\d+\s*[×x]\s*\d+", blob))
            has_wall_txt = "wall" in blob.lower()
            has_active = False
            try:
                if tc is not None:
                    has_active = f"{float(tc):g}-track" in blob.lower().replace(" ", "")
            except (TypeError, ValueError):
                has_active = False
            needs_lookup = (
                (not blob)
                or has_track_option_dump(blob)
                or (tc is not None and not has_active)
                or (not has_dims)
                or (track_wall not in (None, "") and not has_wall_txt)
            )
            if needs_lookup:
                track_sec = None
                if isinstance(section.get("sections"), list) and tc is not None:
                    try:
                        from WEOS.factory.section_catalogue import parse_track_count

                        want = float(tc)
                        for sec in section.get("sections") or []:
                            if not isinstance(sec, Mapping):
                                continue
                            stc = sec.get("trackCount")
                            if stc is None:
                                stc = parse_track_count(sec.get("name"))
                            if stc is None:
                                continue
                            if abs(float(stc) - want) <= 0.05:
                                track_sec = sec
                                break
                    except Exception:
                        track_sec = None
                printed = format_active_track_print(tc, track_sec, wall_mm=track_wall)
            else:
                printed = _dim_wall(track_lbl, track_wall)
        except Exception:
            extra = ""
            try:
                if tc:
                    extra = f" · {float(tc):g}-track"
            except (TypeError, ValueError):
                extra = ""
            base = _dim_wall(track_lbl, track_wall)
            printed = f"{base}{extra}" if base else extra.lstrip(" ·")
        add("TRACK", printed)
    add("SASH", _dim_wall(sash_lbl, section.get("sashWallMm") or wall))

    gtxt = human_glass_label(line)
    if gtxt and not is_louver_fill:
        add("GLASS", gtxt)

    handle = opts.get("handle") or line.get("handle")
    handle_name = opts.get("handleName") or line.get("handleName")
    handle_finish = (
        opts.get("handleFinish")
        or line.get("handleFinish")
        or opts.get("handleColour")
        or opts.get("hardwareColour")
        or line.get("hardwareColour")
    )
    handle_brand = (
        opts.get("hardwareBrand")
        or line.get("hardwareBrand")
        or opts.get("handleBrand")
        or line.get("handleBrand")
        or specs_in.get("hardwareBrand")
    )
    hw_type = opts.get("hardwareType") or line.get("hardwareType") or handle_name or (
        str(handle).replace("_", " ").title() if handle else ""
    )
    if mat == "upvc":
        hw_type = _upvc_print(hw_type, mat)
        if not hw_type:
            hw_type = "uPVC Espag handle"
        handle_brand = _upvc_print(handle_brand, mat) if handle_brand else handle_brand
    hbits = []
    if handle_brand:
        hbits.append(str(handle_brand))
    if hw_type:
        hbits.append(str(hw_type).strip())
    if handle_finish:
        hbits.append(f"colour {handle_finish}")
    add("HANDLE", " · ".join(x for x in hbits if x) if not is_louver_fill else "")

    colour = opts.get("powderCoatName") or line.get("powderCoatName") or opts.get("colour") or line.get("colour")
    if mat == "upvc" and not colour:
        colour = "white"
    if colour:
        add("COLOUR", str(colour).replace("_", " ").title())

    mesh_name = opts.get("meshName") or line.get("meshName")
    mesh_brand = opts.get("meshBrand") or line.get("meshBrand")
    mesh_colour = opts.get("meshColour") or opts.get("meshColor") or line.get("meshColour")
    try:
        mesh_n_i = int(float(mesh_n or 0))
    except (TypeError, ValueError):
        mesh_n_i = 0
    mesh_on = bool((layout or {}).get("mesh") or (opts or {}).get("mesh") or mesh_n_i)
    mesh_bits = ["yes" if mesh_on else "no"]
    if mesh_on:
        if mesh_name:
            mesh_bits.append(str(mesh_name))
        if mesh_brand:
            mesh_bits.append(str(mesh_brand))
        if mesh_colour:
            mesh_bits.append(f"colour {mesh_colour}")
    add("MESH", " · ".join(mesh_bits))

    if mat == "upvc":
        add("MATERIAL", "UPVC")
        reinf_on = opts.get("reinforcement") if isinstance(opts, Mapping) else line.get("reinforcement")
        if reinf_on is None:
            reinf_on = True
        reinf_yes = str(reinf_on).strip().lower() not in ("no", "false", "0", "")
        reinf_mat = (
            opts.get("reinforcementMaterial")
            or line.get("reinforcementMaterial")
            or "gi"
        )
        if reinf_yes:
            add("REINFORCEMENT", f"Yes · {str(reinf_mat).upper()}")
        else:
            add("REINFORCEMENT", "No")
    elif factory:
        alloy = (
            specs_in.get("alloy")
            or opts.get("alloy")
            or line.get("alloy")
            or section.get("alloy")
        )
        if alloy:
            add("ALLOY", str(alloy))

    if system == "grid":
        add("TYPE", "Partition grid (per-cell fix/sliding/openable)")
    elif is_casement:
        add("TYPE", "Casement / Openable")
    elif is_bifold:
        fl = layout.get("foldLeft") if layout else opts.get("foldLeft")
        fr = layout.get("foldRight") if layout else opts.get("foldRight")
        cfg = f"{int(fl or 0)}+{int(fr or 0)}"
        add("TYPE", f"Fold & Sliding ({cfg})")
        add("FOLD", f"{cfg} (left + right leaves)")
        sizes = (layout or {}).get("sectionSizes") or opts.get("sectionSizes") or {}
        if isinstance(sizes, Mapping) and sizes:
            bits = []
            labels = (
                ("topRail", "Top"),
                ("bottomRail", "Bottom"),
                ("leftJamb", "Left jamb"),
                ("rightJamb", "Right jamb"),
                ("leafStile", "Leaf stile"),
            )
            for key, lab in labels:
                if sizes.get(key) not in (None, ""):
                    bits.append(
                        f"{lab} {sizes[key]:g} mm"
                        if isinstance(sizes[key], (int, float))
                        else f"{lab} {sizes[key]}"
                    )
            if bits:
                add("SECTIONS", " · ".join(bits))

    try:
        from WEOS.factory.panel_fills import fill_spec_rows, panel_fill_from_line

        for lab, val in fill_spec_rows(panel_fill_from_line(line)):
            if str(lab).upper() in ("SERIES", "ALUMINIUM", "SECTION", "JOINT", "INTERLOCK"):
                continue
            add(lab, val)
    except Exception:
        pass

    if factory:
        wsrc = (line.get("weight") or {}).get("weightSource") if isinstance(line.get("weight"), Mapping) else None
        total_kg = (line.get("weight") or {}).get("totalKg") if isinstance(line.get("weight"), Mapping) else None
        if total_kg not in (None, "") and float(total_kg or 0) > 0:
            add("WEIGHT", f"{total_kg} kg" + (f" ({wsrc})" if wsrc else ""))
        if section.get("seriesTitle"):
            add("SERIES", section["seriesTitle"])
        if section.get("interlockPrint") or section.get("interlock"):
            add("INTERLOCK", clean_profile_print_name(section.get("interlockPrint") or section.get("interlock")))
        detail_rows = list(line.get("sectionDetails") or [])
        if not detail_rows and isinstance(section.get("sections"), list):
            for sec in section.get("sections") or []:
                if not isinstance(sec, Mapping):
                    continue
                detail_rows.append(
                    {
                        "name": sec.get("name"),
                        "use": sec.get("usage") or sec.get("use"),
                        "wMm": sec.get("widthMm") or sec.get("wMm"),
                        "hMm": sec.get("sectionDepthMm") or sec.get("hMm"),
                        "wallMm": sec.get("wallThicknessMm") or sec.get("wallMm"),
                        "weightKgPerM": sec.get("weightKgPerM") or sec.get("weightKgPerMtr"),
                        "glassOptions": sec.get("glassOptions"),
                    }
                )
        for sec in detail_rows[:12]:
            if not isinstance(sec, Mapping):
                continue
            opts_g = list(sec.get("glassOptions") or [])
            if opts_g and family not in opts_g and not (family == "single" and "single" in opts_g):
                if family == "dgu" and "dgu" not in opts_g:
                    continue
            name = clean_profile_print_name(sec.get("name") or sec.get("use") or "Section")
            bits = [str(name)]
            if sec.get("use") and sec.get("name"):
                bits.append(f"({sec.get('use')})")
            w_mm, h_mm = sec.get("wMm"), sec.get("hMm")
            if w_mm is not None or h_mm is not None:
                bits.append(f"{w_mm or '—'}×{h_mm or '—'} mm")
            if sec.get("wallMm") is not None:
                bits.append(f"wall {sec['wallMm']} mm")
            if sec.get("weightKgPerM") is not None:
                bits.append(f"{sec['weightKgPerM']} kg/m")
            add("SECTION", " · ".join(bits))

    notes = (layout or {}).get("notes") or []
    desc = str(line.get("description") or opts.get("description") or "").strip()
    if desc and desc.lower() != str(title).lower():
        add("NOTE", desc)
    for note in notes[:3]:
        if note and str(note).strip() and str(note).strip() != desc:
            add("NOTE", note)
    return rows
