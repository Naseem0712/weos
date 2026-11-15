"""Design-driven product cost — profiles actually used on the canvas.

Casement / sliding costing from ``setup.casement`` / ``setup.sliding`` rates,
layout (bands · panels · partitions), hardware packs, glass, labour ₹/sft and
profit %.  Wastage: when project reuse is off (casement gallery default for
stile/slim), leftover on std-length bars that cannot be reused is charged;
reported waste ratio is clamped to the **0–2.5%** band for display when the
true leftover is tiny, otherwise the full leftover cost is still added.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from WEOS.factory.product_setup import (
    CASEMENT_STD_LENGTHS_M,
    apply_setup_bom,
    derive_casement_wastage_flags,
    normalize_section,
    normalize_setup,
)

# Fabricator wastage band (percent of purchased bar length attributable to scrap).
WASTAGE_PCT_MIN = 0.0
WASTAGE_PCT_MAX = 2.5


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _str(v: Any) -> str:
    return str(v or "").strip()


def _role(r: Any) -> str:
    t = _str(r).lower().replace("-", "_").replace(" ", "_")
    if t in ("fix", "fixed"):
        return "fix"
    if t in ("top_hung", "tophung", "top"):
        return "top_hung"
    if t in ("door", "doors", "side_hung_door"):
        return "door"
    if t in ("sliding", "slider", "slide"):
        return "sliding"
    if t in ("openable", "casement", "side_hung", "side_swing"):
        return "openable"
    return "openable"


def _section_rate_per_m(sec: Mapping[str, Any] | None) -> float:
    """Convert section rate (rft/rmt/pc) to ₹ per metre."""
    if not isinstance(sec, Mapping):
        return 0.0
    s = normalize_section(sec)
    rate = _f(s.get("rate"))
    unit = _str(s.get("rateUnit") or "rft").lower()
    if rate <= 0:
        return 0.0
    if unit in ("rmt", "rm", "m"):
        return rate
    if unit in ("rft", "ft"):
        return rate / 0.3048  # ₹/ft → ₹/m
    return rate  # pc / unknown — treat as per metre if length billed


def _coating_per_m(
    sec: Mapping[str, Any] | None,
    *,
    colour: Any = None,
    coating_multiplier: float | None = None,
) -> float:
    """Section coating ₹/m, with finish-family multiplier (plain / texture / wooden)."""
    if not isinstance(sec, Mapping):
        return 0.0
    s = normalize_section(sec)
    c = _f(s.get("coatingCost"))
    unit = _str(s.get("coatingUnit") or "rft").lower()
    if c <= 0:
        return 0.0
    if unit in ("rmt", "rm", "m"):
        base = c
    elif unit in ("rft", "ft"):
        base = c / 0.3048
    else:
        base = c
    mult = coating_multiplier
    if mult is None:
        try:
            from WEOS.factory.commercial_defaults import coating_multiplier_for_colour
            mult = coating_multiplier_for_colour(colour)
        except Exception:
            mult = 1.0
    try:
        mult_f = float(mult)
    except (TypeError, ValueError):
        mult_f = 1.0
    return base * max(mult_f, 0.0)


def _section_weight_kg_per_m(sec: Mapping[str, Any] | None) -> float:
    if not isinstance(sec, Mapping):
        return 0.0
    s = normalize_section(sec)
    kg_m = _f(s.get("weightKgPerM"))
    if kg_m > 0:
        return kg_m
    # Some catalogues store kg/ft
    unit = _str(s.get("weightUnit") or "m").lower()
    raw = _f(s.get("weight") or s.get("kgPerFt") or s.get("weightKgPerFt"))
    if raw <= 0:
        return 0.0
    if unit in ("ft", "rft"):
        return raw / 0.3048
    return raw


def _section_stock_label(sec: Mapping[str, Any] | None, *, fallback_std_m: float | None = None) -> str:
    if not isinstance(sec, Mapping):
        return f"{fallback_std_m:g} m stock" if fallback_std_m else "—"
    s = normalize_section(sec)
    mm = _f(s.get("stdLengthMm"))
    if mm > 0:
        return f"{mm:g} mm stock"
    std = s.get("stdLength")
    unit = _str(s.get("stdLengthUnit") or "rft").lower()
    if isinstance(std, (int, float)) and float(std) > 0:
        return f"{float(std):g} {unit} stock"
    if _str(std):
        return f"{_str(std)} {unit} stock".strip()
    if fallback_std_m and fallback_std_m > 0:
        return f"{fallback_std_m:g} m stock"
    return "—"


def _pick_std_m(costing: Mapping[str, Any] | None) -> float:
    c = costing if isinstance(costing, Mapping) else {}
    stds = c.get("stdLengthsM") or CASEMENT_STD_LENGTHS_M
    default = _f(c.get("defaultStdLengthM"), 3.0)
    try:
        nums = [float(x) for x in stds if _f(x) > 0]
    except TypeError:
        nums = list(CASEMENT_STD_LENGTHS_M)
    if default in nums:
        return float(default)
    return float(nums[0]) if nums else 3.0


def pack_std_length_wastage(
    cut_lengths_m: Sequence[float],
    *,
    std_m: float,
    reuse: bool,
    charge_full_when_split: bool = False,
) -> dict[str, Any]:
    """First-fit pack cuts into standard bars; return purchased m + wastage cost basis.

    When ``reuse`` is False (casement gallery often off), leftover on each bar
    is scrap and charged.  ``wastagePercent`` is clamped to 0–2.5 for UI when the
    scrap share is tiny; full leftover metres still drive ``wastageMetres``.
    """
    std = max(float(std_m or 3.0), 0.1)
    pieces = sorted((max(float(x), 0.0) for x in cut_lengths_m if _f(x) > 0), reverse=True)
    net = sum(pieces)
    if not pieces:
        return {
            "netMetres": 0.0,
            "purchasedMetres": 0.0,
            "wastageMetres": 0.0,
            "wastagePercent": 0.0,
            "bars": 0,
            "stdLengthM": std,
            "reuse": bool(reuse),
        }

    if charge_full_when_split and not reuse:
        # Each piece consumes a full std length when sides differ (gallery flag).
        bars = len(pieces)
        purchased = bars * std
        waste = max(purchased - net, 0.0)
    elif reuse:
        # Ideal: buy only net length (project reuses offcuts elsewhere).
        purchased = net
        waste = 0.0
        bars = max(1, int(math.ceil(net / std))) if net else 0
    else:
        # Pack into std bars; leftover per bar is wastage.
        remaining: list[float] = []
        for L in pieces:
            placed = False
            for i, rem in enumerate(remaining):
                if rem + 1e-9 >= L:
                    remaining[i] = rem - L
                    placed = True
                    break
            if not placed:
                remaining.append(std - L)
        bars = len(remaining)
        purchased = bars * std
        waste = max(purchased - net, 0.0)

    pct_raw = (waste / purchased * 100.0) if purchased > 0 else 0.0
    # Display band 0–2.5 when scrap is a small share of a bar; keep true metres.
    pct_ui = min(max(pct_raw, WASTAGE_PCT_MIN), WASTAGE_PCT_MAX) if waste > 0 else 0.0
    if pct_raw > WASTAGE_PCT_MAX:
        pct_ui = round(pct_raw, 3)  # show real % when leftover is large
    return {
        "netMetres": round(net, 4),
        "purchasedMetres": round(purchased, 4),
        "wastageMetres": round(waste, 4),
        "wastagePercent": round(pct_ui, 3),
        "wastagePercentRaw": round(pct_raw, 3),
        "bars": bars,
        "stdLengthM": std,
        "reuse": bool(reuse),
    }


def _active_casement_sections(cm: Mapping[str, Any]) -> dict[str, Any]:
    of = cm.get("outerFrame") if isinstance(cm.get("outerFrame"), Mapping) else {}
    variants = of.get("variants") if isinstance(of.get("variants"), Mapping) else {}
    active_v = _str(of.get("activeVariant") or cm.get("activeFrameVariant") or "plain")
    frame = variants.get(active_v) or of.get("allSides") or {}
    mull = cm.get("mullions") if isinstance(cm.get("mullions"), Mapping) else {}
    mull_active = _str(mull.get("active") or "slim")
    mull_sec = mull.get(mull_active) or mull.get("slim") or {}
    doors = cm.get("doors") if isinstance(cm.get("doors"), Mapping) else {}
    door_active = _str(doors.get("active") or "slim")
    kind = _str(cm.get("kind") or "normal")
    if kind == "stile":
        door_sec = doors.get("hingeSide") or doors.get("allSides") or {}
    elif kind == "slim_profile":
        door_sec = doors.get("allSides") or doors.get("vertical") or doors.get(door_active) or {}
    else:
        door_sec = doors.get(door_active) or doors.get("slim") or doors.get("allSides") or {}
    return {
        "frame": normalize_section(frame if isinstance(frame, Mapping) else {}),
        "mullion": normalize_section(mull_sec if isinstance(mull_sec, Mapping) else {}),
        "door": normalize_section(door_sec if isinstance(door_sec, Mapping) else {}),
        "mullionSize": mull_active,
        "doorSize": door_active,
        "includeBottom": bool(of.get("includeBottom", kind == "normal")),
        "kind": kind,
    }


def _flatten_layout(
    layout: Mapping[str, Any] | None,
    *,
    width_mm: float,
    height_mm: float,
) -> list[dict[str, Any]]:
    bands = (layout or {}).get("bands") if isinstance(layout, Mapping) else None
    out: list[dict[str, Any]] = []
    if isinstance(bands, (list, tuple)) and bands:
        n = len(bands)
        # Equal heights when missing
        known_h = [_f(b.get("heightMm") if isinstance(b, Mapping) else 0) for b in bands]
        miss = [i for i, h in enumerate(known_h) if h <= 0]
        if miss:
            used = sum(h for h in known_h if h > 0)
            rem = max(height_mm - used, 80.0 * len(miss))
            base = rem / len(miss)
            for i in miss:
                known_h[i] = base
        for bi, band in enumerate(bands):
            if not isinstance(band, Mapping):
                continue
            panels = band.get("panels") if isinstance(band.get("panels"), (list, tuple)) else []
            if not panels:
                panels = [{"role": "openable"}]
            pw = [_f(p.get("widthMm") if isinstance(p, Mapping) else 0) for p in panels]
            miss_w = [i for i, w in enumerate(pw) if w <= 0]
            if miss_w:
                used = sum(w for w in pw if w > 0)
                rem = max(width_mm - used, 80.0 * len(miss_w))
                base = rem / len(miss_w)
                for i in miss_w:
                    pw[i] = base
            for i, p in enumerate(panels):
                if not isinstance(p, Mapping):
                    p = {"role": p}
                out.append({
                    "bandIndex": bi,
                    "index": i,
                    "role": _role(p.get("role")),
                    "widthMm": pw[i],
                    "heightMm": known_h[bi],
                    "profileSeries": _str(p.get("profileSeries") or p.get("fixedSeries") or ""),
                    "mullionSize": _str(p.get("mullionSize") or band.get("mullionSize") or ""),
                    "doorSize": _str(p.get("doorSize") or ""),
                })
        return out
    # Legacy flat panels
    panels = (layout or {}).get("panels") if isinstance(layout, Mapping) else None
    if isinstance(panels, (list, tuple)) and panels:
        n = len(panels)
        w_each = width_mm / max(n, 1)
        for i, p in enumerate(panels):
            if not isinstance(p, Mapping):
                p = {"role": p}
            out.append({
                "bandIndex": 0,
                "index": i,
                "role": _role(p.get("role")),
                "widthMm": _f(p.get("widthMm"), w_each),
                "heightMm": _f(p.get("heightMm"), height_mm),
                "profileSeries": _str(p.get("profileSeries") or ""),
                "mullionSize": _str(p.get("mullionSize") or ""),
                "doorSize": _str(p.get("doorSize") or ""),
            })
    return out


def derive_casement_profile_cuts(
    setup: Mapping[str, Any] | None,
    *,
    width_mm: float,
    height_mm: float,
    casement_layout: Mapping[str, Any] | None = None,
    mullion_size: str | None = None,
    door_size: str | None = None,
    colour: Any = None,
    coating_multiplier: float | None = None,
) -> dict[str, Any]:
    """Cut list from what is on the canvas — only profiles actually used."""
    if not isinstance(setup, Mapping):
        return {"lines": [], "cutsM": [], "counts": {}}
    norm = normalize_setup(setup) if setup.get("type") or setup.get("casement") else setup
    cm = norm.get("casement") if isinstance(norm.get("casement"), Mapping) else None
    if not isinstance(cm, Mapping):
        return {"lines": [], "cutsM": [], "counts": {}}

    # Honour per-design slim/big overrides
    cm = dict(cm)
    if mullion_size in ("slim", "big"):
        mull = dict(cm.get("mullions") or {})
        mull["active"] = mullion_size
        cm["mullions"] = mull
    if door_size in ("slim", "big"):
        doors = dict(cm.get("doors") or {})
        doors["active"] = door_size
        cm["doors"] = doors

    secs = _active_casement_sections(cm)
    W = max(_f(width_mm), 1.0)
    H = max(_f(height_mm), 1.0)
    panels = _flatten_layout(casement_layout, width_mm=W, height_mm=H)
    if not panels:
        panels = [{"bandIndex": 0, "index": 0, "role": "openable", "widthMm": W, "heightMm": H}]

    bands: dict[int, list[dict[str, Any]]] = {}
    for p in panels:
        bands.setdefault(int(p["bandIndex"]), []).append(p)
    n_bands = len(bands)
    band_heights = {
        bi: max((_f(p["heightMm"]) for p in plist), default=H / max(n_bands, 1))
        for bi, plist in bands.items()
    }

    lines: list[dict[str, Any]] = []
    cuts_m: list[float] = []
    coat_mult = coating_multiplier

    def add_profile(
        name: str,
        length_m: float,
        qty: float,
        sec: Mapping[str, Any],
        *,
        use: str,
        remarks: str = "",
    ) -> None:
        if qty <= 0 or length_m <= 0:
            return
        rate_m = _section_rate_per_m(sec)
        coat_m = _coating_per_m(sec, colour=colour, coating_multiplier=coat_mult)
        total_m = length_m * qty
        for _ in range(int(max(round(qty), 1))):
            cuts_m.append(length_m)
        # If qty is fractional, still bill metres
        if abs(qty - round(qty)) > 1e-6:
            cuts_m.append(length_m * (qty - int(qty)))
        amount = total_m * (rate_m + coat_m)
        display = _str(sec.get("name")) or name
        kg_m = _section_weight_kg_per_m(sec)
        pcs = int(round(qty)) if abs(qty - round(qty)) < 1e-6 else round(qty, 4)
        lines.append({
            "category": "profile",
            "name": display,
            "use": use,
            "qty": round(qty, 4),
            "pcs": pcs,
            "lengthM": round(length_m, 4),
            "metres": round(total_m, 4),
            "unit": "RM",
            "unitRate": round(rate_m + coat_m, 4),
            "amount": round(amount, 2),
            "catalogueName": display,
            "remarks": remarks,
            "sides": _str(remarks) or use.replace("_", " "),
            "stock": _section_stock_label(sec),
            "weightKgPerM": round(kg_m, 4) if kg_m else None,
            "weightKg": round(kg_m * total_m, 3) if kg_m else None,
        })

    # Outer frame — always used
    frame = secs["frame"]
    add_profile("Outer frame · top", W / 1000.0, 1, frame, use="outer_frame", remarks="top")
    add_profile("Outer frame · left", H / 1000.0, 1, frame, use="outer_frame", remarks="left")
    add_profile("Outer frame · right", H / 1000.0, 1, frame, use="outer_frame", remarks="right")
    if secs["includeBottom"]:
        add_profile("Outer frame · bottom", W / 1000.0, 1, frame, use="outer_frame", remarks="bottom")

    # Mullions only where divides exist (horizontal transoms + verticals per band)
    mull = secs["mullion"]
    sorted_bi = sorted(bands.keys())
    for i, bi in enumerate(sorted_bi[:-1]):
        # Horizontal mullion / transom under band bi
        add_profile(
            f"Mullion · H ({secs['mullionSize']})",
            W / 1000.0,
            1,
            mull,
            use="mullion",
            remarks=f"transom under row {bi + 1}",
        )
    for bi, plist in bands.items():
        n = len(plist)
        bh = band_heights.get(bi, H)
        if n >= 2:
            add_profile(
                f"Mullion · V ({secs['mullionSize']})",
                bh / 1000.0,
                float(n - 1),
                mull,
                use="mullion",
                remarks=f"row {bi + 1} verticals ×{n - 1}",
            )

    # Door / openable / top_hung leaves — door sections only (never mullion)
    door = secs["door"]
    kind = secs["kind"]
    operable = [p for p in panels if p["role"] in ("openable", "door", "top_hung")]
    side_n = sum(1 for p in operable if p["role"] in ("openable", "door"))
    top_n = sum(1 for p in operable if p["role"] == "top_hung")
    for p in operable:
        pw, ph = _f(p["widthMm"]) / 1000.0, _f(p["heightMm"]) / 1000.0
        if kind == "stile":
            doors_map = cm.get("doors") if isinstance(cm.get("doors"), Mapping) else {}
            for label, key, length, q in (
                ("Hinge side", "hingeSide", ph, 1),
                ("Lock side", "lockSide", ph, 1),
                ("Top", "top", pw, 1),
                ("Bottom", "bottom", pw, 1),
            ):
                sec = doors_map.get(key) or door
                add_profile(
                    f"Door · {label}",
                    length,
                    q,
                    sec if isinstance(sec, Mapping) else door,
                    use="door",
                    remarks=f"{p['role']} R{p['bandIndex']+1}P{p['index']+1}",
                )
        else:
            # 2 verticals + top + bottom of door section
            add_profile("Door · vertical", ph, 2, door, use="door", remarks=p["role"])
            add_profile("Door · top/bottom", pw, 2, door, use="door", remarks=p["role"])

    fixed_n = sum(1 for p in panels if p["role"] in ("fix", "sliding"))
    return {
        "lines": lines,
        "cutsM": cuts_m,
        "counts": {
            "bands": n_bands,
            "panels": len(panels),
            "sideSwingDoors": side_n,
            "topHungDoors": top_n,
            "operable": len(operable),
            "fixed": fixed_n,
            "mullionSize": secs["mullionSize"],
            "doorSize": secs["doorSize"],
        },
        "sections": secs,
    }


def _glass_cost(line: Mapping[str, Any], *, width_mm: float, height_mm: float, qty: float) -> dict[str, Any]:
    area_sft = (max(width_mm, 0) * max(height_mm, 0) / 1_000_000.0) * 10.7639
    rate = 0.0
    name = _str(line.get("glass") or line.get("glassName") or "Glass")
    breakdown = None
    gid = _str(line.get("glass"))
    try:
        from WEOS.factory.glass_catalogue import cart_glass_options, get_glass

        g = get_glass(gid) if gid else None
        if isinstance(g, Mapping):
            name = _str(g.get("name") or g.get("label") or name)
            rate = _f(g.get("rate") or g.get("ratePerSft") or g.get("ratePerSqft"))
            if isinstance(g.get("rateBreakdown"), Mapping):
                breakdown = dict(g["rateBreakdown"])
        if rate <= 0 and gid:
            # Fall back to synced cart / product option rate
            for opt in cart_glass_options(merge_library=True):
                if str(opt.get("id") or "") == gid:
                    rate = _f(opt.get("rate") or opt.get("ratePerSft"))
                    name = _str(opt.get("label") or opt.get("name") or name)
                    if isinstance(opt.get("rateBreakdown"), Mapping):
                        breakdown = dict(opt["rateBreakdown"])
                    break
    except Exception:
        pass
    # Line-level override
    rate = _f(line.get("glassRate") or (line.get("options") or {}).get("glassRate"), rate)
    amt = area_sft * rate * max(qty, 1.0)
    out = {
        "name": name,
        "areaSft": round(area_sft * max(qty, 1.0), 3),
        "unitRate": rate,
        "amount": round(amt, 2),
        "catalogueName": name,
        "glassId": gid or None,
    }
    if breakdown:
        out["rateBreakdown"] = breakdown
    return out


def compute_casement_design_cost(
    line: Mapping[str, Any],
    *,
    product: Mapping[str, Any] | None = None,
    setup: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Actual casement cost from canvas layout + series setup rates."""
    product = product if isinstance(product, Mapping) else {}
    setup_blob = setup
    if setup_blob is None:
        setup_blob = product.get("setup") if isinstance(product.get("setup"), Mapping) else None
    if not isinstance(setup_blob, Mapping):
        return {"ok": False, "costEngine": "stub", "reason": "no_setup", "total": 0.0}

    norm = normalize_setup(setup_blob)
    if _str(norm.get("type")).lower() != "casement" and not isinstance(norm.get("casement"), Mapping):
        return {"ok": False, "costEngine": "stub", "reason": "not_casement", "total": 0.0}

    W = _f(line.get("width"))
    H = _f(line.get("height"))
    qty = max(_f(line.get("qty") or line.get("quantity"), 1.0), 1.0)
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    colour = _str(line.get("colour") or opts.get("colour") or "white")
    layout = (
        line.get("casementLayout")
        or opts.get("casementLayout")
        or product.get("casementLayout")
    )
    mull_ov = _str(line.get("mullionSize") or opts.get("mullionSize") or "")
    door_ov = _str(line.get("doorSize") or opts.get("doorSize") or "")

    cuts = derive_casement_profile_cuts(
        norm,
        width_mm=W,
        height_mm=H,
        casement_layout=layout if isinstance(layout, Mapping) else None,
        mullion_size=mull_ov or None,
        door_size=door_ov or None,
        colour=colour,
    )
    counts = cuts.get("counts") or {}
    cm = norm.get("casement") or {}
    costing = cm.get("costing") if isinstance(cm.get("costing"), Mapping) else {}
    flags = derive_casement_wastage_flags(norm)
    # Match gallery: casement wastage reuse often off
    reuse = bool(flags.get("projectWastageReuse"))
    if costing.get("projectWastageReuse") is False:
        reuse = False
    std_m = _pick_std_m(costing)
    charge_full = bool(flags.get("chargeFullStdLength"))

    waste = pack_std_length_wastage(
        cuts.get("cutsM") or [],
        std_m=std_m,
        reuse=reuse,
        charge_full_when_split=charge_full,
    )

    profile_net = sum(_f(ln.get("amount")) for ln in (cuts.get("lines") or []))
    # Scale profile cost by purchased/net when charging wastage bars
    net_m = _f(waste.get("netMetres"))
    purch_m = _f(waste.get("purchasedMetres"))
    if net_m > 0 and purch_m > net_m and not reuse:
        scale = purch_m / net_m
        profile_purchased = profile_net * scale
        wastage_cost = profile_purchased - profile_net
    else:
        profile_purchased = profile_net
        wastage_cost = 0.0

    # Hardware from pack — only operable doors (side-swing ≠ top-hung)
    side_n = float(counts.get("sideSwingDoors") or 0)
    top_n = float(counts.get("topHungDoors") or 0)
    operable = float(counts.get("operable") or (side_n + top_n) or 1)
    bom = apply_setup_bom(
        norm,
        width_mm=W,
        height_mm=H,
        ctx={
            "shutterCount": operable,
            "leafCount": operable,
            "sideSwingDoors": side_n,
            "topHungDoors": top_n,
            "system": "casement",
        },
        shutter_count=operable,
        system_type="casement",
        qty=1.0,
    )
    hw_lines = []
    hw_amt = 0.0
    for h in bom.get("hardware") or []:
        q = _f(h.get("qty"))
        r = _f(h.get("unitRate") or h.get("rate"))
        amt = q * r
        hw_amt += amt
        hw_lines.append({
            "category": "hardware",
            "name": _str(h.get("name")),
            "catalogueName": _str(h.get("name")),
            "qty": q,
            "unit": _str(h.get("unit") or "PC"),
            "unitRate": r,
            "amount": round(amt, 2),
            "remarks": _str(h.get("remarks")),
        })

    glass = _glass_cost(line, width_mm=W, height_mm=H, qty=1.0)
    glass_amt = _f(glass.get("amount"))

    area_sft = (W * H / 1_000_000.0) * 10.7639
    from WEOS.factory.commercial_defaults import installation_per_sft, labour_per_sft

    labour_rate = labour_per_sft(costing.get("labourPerSft"))
    labour_amt = area_sft * labour_rate
    install_rate = installation_per_sft(costing.get("installationPerSft") or costing.get("installPerSft"))
    install_amt = area_sft * install_rate
    material_sub = profile_purchased + hw_amt + glass_amt
    cost_before_profit = material_sub + labour_amt + install_amt
    profit_pct = _f(costing.get("profitPercent"))
    profit_amt = cost_before_profit * (profit_pct / 100.0) if profit_pct else 0.0
    unit_total = cost_before_profit + profit_amt
    total = unit_total * qty

    suggested_rate = None
    sale_unit = "sqft"
    if costing.get("soldPerRft"):
        sale_unit = "rft"
        peri_ft = (2.0 * (W + H) / 304.8) or 1.0
        suggested_rate = round(unit_total / peri_ft, 2) if peri_ft else None
    elif area_sft > 0:
        suggested_rate = round(unit_total / area_sft, 2)

    engine = "live" if (profile_net > 0 or hw_amt > 0 or glass_amt > 0 or labour_amt > 0 or install_amt > 0) else "stub"
    # Flip costing flag for future loads
    if engine == "live" and isinstance(costing, dict):
        pass

    try:
        from WEOS.factory.commercial_defaults import coating_multiplier_for_colour
        coat_mult = coating_multiplier_for_colour(colour)
    except Exception:
        coat_mult = 1.0

    return {
        "ok": True,
        "costEngine": engine,
        "system": "casement",
        "currency": "INR",
        "qty": qty,
        "unitTotal": round(unit_total, 2),
        "total": round(total, 2),
        "perWindowCost": round(cost_before_profit, 2),
        "profitAmount": round(profit_amt * qty, 2),
        "profitPercent": profit_pct,
        "labourAmount": round(labour_amt * qty, 2),
        "labourPerSft": labour_rate,
        "installationAmount": round(install_amt * qty, 2),
        "installationPerSft": install_rate,
        "coatingMultiplier": coat_mult,
        "colour": colour,
        "materialCost": round(material_sub * qty, 2),
        "profileCost": round(profile_purchased * qty, 2),
        "profileNetCost": round(profile_net * qty, 2),
        "wastageCost": round(wastage_cost * qty, 2),
        "hardwareCost": round(hw_amt * qty, 2),
        "glassCost": round(glass_amt * qty, 2),
        "wastage": waste,
        "profiles": cuts.get("lines") or [],
        "hardware": hw_lines,
        "glass": glass,
        "counts": counts,
        "suggestedSellRate": suggested_rate,
        "saleUnit": sale_unit,
        "areaSft": round(area_sft, 3),
        "breakdown": {
            "profiles": round(profile_purchased, 2),
            "wastage": round(wastage_cost, 2),
            "hardware": round(hw_amt, 2),
            "glass": round(glass_amt, 2),
            "labour": round(labour_amt, 2),
            "installation": round(install_amt, 2),
            "profit": round(profit_amt, 2),
        },
    }


def compute_sliding_design_cost(
    line: Mapping[str, Any],
    *,
    product: Mapping[str, Any] | None = None,
    setup: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Sliding cost from setup track/shutter rates + hardware (best-effort live)."""
    product = product if isinstance(product, Mapping) else {}
    setup_blob = setup or (product.get("setup") if isinstance(product.get("setup"), Mapping) else None)
    if not isinstance(setup_blob, Mapping):
        return {"ok": False, "costEngine": "stub", "reason": "no_setup", "total": 0.0}
    norm = normalize_setup(setup_blob)
    if _str(norm.get("type")).lower() != "sliding" and not isinstance(norm.get("sliding"), Mapping):
        return {"ok": False, "costEngine": "stub", "reason": "not_sliding", "total": 0.0}

    W = _f(line.get("width"))
    H = _f(line.get("height"))
    qty = max(_f(line.get("qty") or line.get("quantity"), 1.0), 1.0)
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    colour = _str(line.get("colour") or opts.get("colour") or "white")
    shutters = max(_f(line.get("glassShutters") or opts.get("glassCount"), 2), 1)
    bom = apply_setup_bom(
        norm,
        width_mm=W,
        height_mm=H,
        ctx={"shutterCount": shutters, "glassCount": shutters, "system": "sliding"},
        shutter_count=shutters,
        system_type="sliding",
        qty=1.0,
    )
    sl = norm.get("sliding") or {}
    costing = sl.get("costing") if isinstance(sl.get("costing"), Mapping) else {}

    profile_amt = 0.0
    profile_lines = []
    # Track fill lengths
    for tf in (bom.get("trackFill") or {}).get("lines") or []:
        sec = tf.get("section") if isinstance(tf.get("section"), Mapping) else {}
        length_mm = _f(tf.get("lengthMm"))
        if length_mm <= 0:
            # all-side pattern without lengths — use W or H by role
            role = _str(tf.get("role"))
            length_mm = H if "vertical" in role or "left" in role or "right" in role else W
            if "all" in role:
                # 2W + 2H billed as 4 pieces average
                length_mm = (2 * W + 2 * H) / max(_f(tf.get("qty"), 4), 1)
        q = _f(tf.get("qty"), 1)
        Lm = length_mm / 1000.0
        rate_m = _section_rate_per_m(sec) + _coating_per_m(sec, colour=colour)
        amt = Lm * q * rate_m
        profile_amt += amt
        kg_m = _section_weight_kg_per_m(sec)
        role = _str(tf.get("role"))
        profile_lines.append({
            "category": "profile",
            "name": _str(sec.get("name")) or role or "Track",
            "catalogueName": _str(sec.get("name")) or role,
            "qty": q,
            "pcs": int(round(q)) if abs(q - round(q)) < 1e-6 else round(q, 4),
            "lengthM": round(Lm, 4),
            "metres": round(Lm * q, 4),
            "unit": "RM",
            "unitRate": round(rate_m, 4),
            "amount": round(amt, 2),
            "use": "track",
            "sides": role.replace("_", " ") or "track",
            "stock": _section_stock_label(sec, fallback_std_m=5.85),
            "weightKgPerM": round(kg_m, 4) if kg_m else None,
            "weightKg": round(kg_m * Lm * q, 3) if kg_m else None,
            "remarks": role,
        })

    # Member cuts
    for m in bom.get("members") or []:
        q = _f(m.get("qty") or m.get("metres"))
        r = _f(m.get("unitRate"))
        amt = q * r
        profile_amt += amt
        profile_lines.append({
            "category": "profile",
            "name": _str(m.get("name")),
            "catalogueName": _str(m.get("name")),
            "qty": q,
            "unit": _str(m.get("unit") or "RM"),
            "unitRate": r,
            "amount": round(amt, 2),
        })

    # Fixed partition series surcharge — anonymous fix is not allowed when series set
    parts = line.get("partitions") or (line.get("options") or {}).get("partitions") or []
    for p in parts if isinstance(parts, (list, tuple)) else []:
        if not isinstance(p, Mapping):
            continue
        series = _str(p.get("profileSeries") or p.get("sectionSeries") or p.get("fixedSeries"))
        if series:
            profile_lines.append({
                "category": "profile",
                "name": f"Fix panel · {series}",
                "catalogueName": series,
                "qty": 1,
                "unit": "set",
                "unitRate": 0,
                "amount": 0,
                "remarks": f"{_str(p.get('side'))} {_f(p.get('sizeMm'))} mm — series {series}",
                "use": "fixed_partition",
            })

    hw_amt = 0.0
    hw_lines = []
    for h in bom.get("hardware") or []:
        q = _f(h.get("qty"))
        r = _f(h.get("unitRate") or h.get("rate"))
        amt = q * r
        hw_amt += amt
        hw_lines.append({
            "category": "hardware",
            "name": _str(h.get("name")),
            "catalogueName": _str(h.get("name")),
            "qty": q,
            "unit": _str(h.get("unit") or "PC"),
            "unitRate": r,
            "amount": round(amt, 2),
        })

    glass = _glass_cost(line, width_mm=W, height_mm=H, qty=1.0)
    glass_amt = _f(glass.get("amount"))
    area_sft = (W * H / 1_000_000.0) * 10.7639
    from WEOS.factory.commercial_defaults import (
        coating_multiplier_for_colour,
        installation_per_sft,
        labour_per_sft,
    )

    labour_rate = labour_per_sft(costing.get("labourPerSft"))
    labour_amt = area_sft * labour_rate
    install_rate = installation_per_sft(costing.get("installationPerSft") or costing.get("installPerSft"))
    install_amt = area_sft * install_rate
    reuse = bool(costing.get("projectWastageReuse", True))
    waste = pack_std_length_wastage(
        [ _f(ln.get("lengthM")) for ln in profile_lines for _ in range(max(int(_f(ln.get("qty"), 1)), 1)) ],
        std_m=5.85,  # typical sliding bar
        reuse=reuse,
    )
    wastage_cost = 0.0
    if not reuse and _f(waste.get("netMetres")) > 0:
        scale = _f(waste.get("purchasedMetres")) / max(_f(waste.get("netMetres")), 1e-9)
        wastage_cost = max(profile_amt * (scale - 1.0), 0.0)
        profile_amt = profile_amt + wastage_cost

    material_sub = profile_amt + hw_amt + glass_amt
    cost_before = material_sub + labour_amt + install_amt
    profit_pct = _f(costing.get("profitPercent"))
    profit_amt = cost_before * (profit_pct / 100.0) if profit_pct else 0.0
    unit_total = cost_before + profit_amt
    engine = "live" if (profile_amt > 0 or hw_amt > 0 or labour_amt > 0 or install_amt > 0) else "stub"
    suggested = round(unit_total / area_sft, 2) if area_sft > 0 else None
    try:
        coat_mult = coating_multiplier_for_colour(colour)
    except Exception:
        coat_mult = 1.0
    return {
        "ok": True,
        "costEngine": engine,
        "system": "sliding",
        "currency": "INR",
        "qty": qty,
        "unitTotal": round(unit_total, 2),
        "total": round(unit_total * qty, 2),
        "perWindowCost": round(cost_before, 2),
        "profitAmount": round(profit_amt * qty, 2),
        "profitPercent": profit_pct,
        "labourAmount": round(labour_amt * qty, 2),
        "labourPerSft": labour_rate,
        "installationAmount": round(install_amt * qty, 2),
        "installationPerSft": install_rate,
        "coatingMultiplier": coat_mult,
        "colour": colour,
        "materialCost": round(material_sub * qty, 2),
        "profileCost": round(profile_amt * qty, 2),
        "wastageCost": round(wastage_cost * qty, 2),
        "hardwareCost": round(hw_amt * qty, 2),
        "glassCost": round(glass_amt * qty, 2),
        "wastage": waste,
        "profiles": profile_lines,
        "hardware": hw_lines,
        "glass": glass,
        "suggestedSellRate": suggested,
        "saleUnit": "sqft",
        "areaSft": round(area_sft, 3),
        "breakdown": {
            "profiles": round(profile_amt - wastage_cost, 2),
            "wastage": round(wastage_cost, 2),
            "hardware": round(hw_amt, 2),
            "glass": round(glass_amt, 2),
            "labour": round(labour_amt, 2),
            "installation": round(install_amt, 2),
            "profit": round(profit_amt, 2),
        },
    }


def compute_design_cost(
    line: Mapping[str, Any],
    *,
    product: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Route to casement / sliding design cost; stub otherwise."""
    product = product if isinstance(product, Mapping) else {}
    if not product and _str(line.get("product") or line.get("productId")):
        try:
            from WEOS.factory.product_loader import load_product
            from WEOS.factory.quote_item_snapshot import product_id_of

            product = load_product(product_id_of(line), strict=False)
        except Exception:
            product = {}
    setup = product.get("setup") if isinstance(product.get("setup"), Mapping) else None
    system = _str(
        line.get("system")
        or (line.get("options") or {}).get("system")
        or (setup or {}).get("type")
        or product.get("productType")
        or ""
    ).lower()
    if "casement" in system or "openable" in system or (setup and _str(setup.get("type")) == "casement"):
        return compute_casement_design_cost(line, product=product, setup=setup)
    if "sliding" in system or (setup and _str(setup.get("type")) == "sliding"):
        return compute_sliding_design_cost(line, product=product, setup=setup)
    # Try casement layout presence
    if line.get("casementLayout") or (line.get("options") or {}).get("casementLayout"):
        return compute_casement_design_cost(line, product=product, setup=setup)
    return {"ok": False, "costEngine": "stub", "reason": "unsupported", "total": 0.0}
