"""Design-driven product cost — profiles actually used on the canvas.

Casement / sliding costing from ``setup.casement`` / ``setup.sliding`` rates,
layout (bands · panels · partitions), hardware packs, glass, labour ₹/sft and
profit %.

Aluminium = section weight (kg/m) × rate (₹/kg|rft|rmt) × cut length.
Powder coating = section coating ₹ × finish multiplier (plain / texture+20% /
wooden+50%), separate from aluminium.

WEOS window rulebook v2:
- Quote costing nests the whole quote's cuts together (same-quote offcut reuse;
  any leftover that fits is reusable — no fixed 1–2 ft limit). Customer cost
  uses new-material purchase; approved old stock does not reduce quote cost.
- Closing balance / blade-trim loss is valued and allocated within family
  (sliding↔sliding, casement↔casement) by used-profile material cost share.
- Factory plan may consume approved stock; purchase list = extra full bars.
- Stock posts only reusable leftovers (>~3 ft) on approval, idempotently.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, MutableMapping, Sequence

from WEOS.factory.product_setup import (
    CASEMENT_STD_LENGTHS_M,
    apply_setup_bom,
    apply_stay_size_rate,
    derive_casement_wastage_flags,
    list_wheel_options_for_weight,
    normalize_section,
    normalize_setup,
    setup_has_profile_rates,
    shutter_glass_weight_kg,
    suggest_wheel_for_weight,
    wheel_block_from_option,
    with_active_track,
)
from WEOS.factory.remnant_stock import (
    WASTAGE_THRESHOLD_M,
    is_reusable_remnant_m,
    merge_remnants_into_stock,
    remnant_key,
)

# Fabricator wastage band (percent of purchased bar length attributable to scrap).
WASTAGE_PCT_MIN = 0.0
WASTAGE_PCT_MAX = 2.5
# Alias for callers / UI
WASTAGE_MAX_REUSABLE_FT = 3.0


def _mesh_fabric_pack(line: Mapping[str, Any]) -> dict[str, Any]:
    """Mesh fabric for design cost + materials (in-track / rolling / collapsible)."""
    try:
        from WEOS.factory.mesh_addon import mesh_fabric_for_line, mesh_fabric_material_row
    except Exception:
        return {"mesh": None, "meshLines": [], "meshCost": 0.0}
    fabric = mesh_fabric_for_line(line)
    if not fabric:
        return {"mesh": None, "meshLines": [], "meshCost": 0.0}
    row = mesh_fabric_material_row(fabric)
    return {
        "mesh": dict(fabric),
        "meshLines": [row],
        "meshCost": float(fabric.get("amountUnit") or 0.0),
    }


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


def _line_opt(line: Mapping[str, Any], *keys: str) -> Any:
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    for k in keys:
        if line.get(k) not in (None, ""):
            return line.get(k)
        if isinstance(opts, Mapping) and opts.get(k) not in (None, ""):
            return opts.get(k)
    return None


def _apply_sliding_wheel_clarity(
    norm: Mapping[str, Any],
    line: Mapping[str, Any],
    *,
    width_mm: float,
    height_mm: float,
    shutters: float,
    mesh_n: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Patch sliding hardwarePack wheels from glass weight + user selection."""
    import copy

    setup = copy.deepcopy(dict(norm))
    sl_raw = setup.get("sliding")
    sl = dict(sl_raw) if isinstance(sl_raw, Mapping) else {}
    setup["sliding"] = sl
    pack = dict(sl.get("hardwarePack") or {}) if isinstance(sl.get("hardwarePack"), Mapping) else {}
    sl["hardwarePack"] = pack

    glass_id = _str(_line_opt(line, "glass", "glassId") or "")
    gw = shutter_glass_weight_kg(
        glass_id,
        width_mm=width_mm,
        height_mm=height_mm,
        shutter_count=shutters,
    )
    leaf_kg = _f(gw.get("weightKg"))
    wheel_id = _str(_line_opt(line, "wheelId", "selectedWheelId", "glassWheelId") or "")
    mesh_wheel_id = _str(_line_opt(line, "meshWheelId", "selectedMeshWheelId") or "")

    glass_opts = list_wheel_options_for_weight(leaf_kg, for_mesh=False)
    mesh_opts = list_wheel_options_for_weight(0.0, for_mesh=True)
    glass_pick = suggest_wheel_for_weight(leaf_kg, for_mesh=False, selected_id=wheel_id or None)
    mesh_pick = suggest_wheel_for_weight(0.0, for_mesh=True, selected_id=mesh_wheel_id or None)

    # Prefer catalogue pick; fall back to series pack rates when catalogue empty
    if glass_pick:
        pack["wheels"] = wheel_block_from_option(glass_pick, default_name=_str(glass_pick.get("name") or "Wheels"))
    elif isinstance(pack.get("wheels"), Mapping):
        pack["wheels"] = dict(pack["wheels"])
    if mesh_n > 0:
        if mesh_pick:
            pack["meshWheels"] = wheel_block_from_option(mesh_pick, default_name="Mesh wheel")
        elif not isinstance(pack.get("meshWheels"), Mapping):
            # Light default when series pack omitted mesh wheels
            base = pack.get("wheels") if isinstance(pack.get("wheels"), Mapping) else {}
            pack["meshWheels"] = {
                "qtyPerShutter": float(base.get("qtyPerShutter") or 2),
                "rate": min(float(base.get("rate") or 70), 70.0),
                "unit": "PC",
                "brand": _str(base.get("brand")),
                "origin": _str(base.get("origin") or "indian"),
                "name": "Mesh wheel",
                "weightCapacityKg": 40.0,
                "notes": "regular mesh wheel",
            }

    meta = {
        "shutterGlassWeightKg": leaf_kg,
        "totalGlassKg": _f(gw.get("totalGlassKg")),
        "paneWidthMm": gw.get("paneWidthMm"),
        "paneHeightMm": gw.get("paneHeightMm"),
        "glassName": gw.get("glassName"),
        "wheelOptions": glass_opts,
        "meshWheelOptions": mesh_opts,
        "selectedWheel": pack.get("wheels"),
        "selectedMeshWheel": pack.get("meshWheels") if mesh_n > 0 else None,
    }
    return setup, meta


def _apply_casement_hw_clarity(
    norm: Mapping[str, Any],
    line: Mapping[str, Any],
    *,
    side_n: float,
    top_n: float,
) -> dict[str, Any]:
    """Side-swing stay XOR hinge; top hung stay-only with selected size."""
    import copy

    setup = copy.deepcopy(dict(norm))
    cm_raw = setup.get("casement")
    cm = dict(cm_raw) if isinstance(cm_raw, Mapping) else {}
    setup["casement"] = cm
    pack = dict(cm.get("hardwarePack") or {}) if isinstance(cm.get("hardwarePack"), Mapping) else {}
    cm["hardwarePack"] = pack

    raw_open = _str(_line_opt(line, "sideSwingOpenHw", "openHardware", "sideOpenHardware") or pack.get("openHardware") or "hinges").lower()
    if raw_open in ("friction_stay", "friction", "stays", "stay"):
        open_hw = "stay"
    elif raw_open in ("hinge", "hinges"):
        open_hw = "hinges"
    else:
        open_hw = raw_open if raw_open in ("hinges", "stay", "floor_spring") else "hinges"

    # Side-swing path only — top hung never uses hinge
    if side_n > 0 and open_hw not in ("floor_spring",):
        pack["openHardware"] = open_hw
    elif top_n > 0 and side_n <= 0:
        # Only top hung on layout — keep stay mode for series consistency
        pack["openHardware"] = "stay" if open_hw == "stay" else pack.get("openHardware") or "hinges"

    side_inch = _line_opt(line, "sideStayInch", "stayInch", "sideSwingStayInch")
    top_inch = _line_opt(line, "topHungStayInch", "topStayInch")
    hinge_qty = _line_opt(line, "hingeQty", "hingesPerDoor")

    stay = dict(pack.get("stay") or {}) if isinstance(pack.get("stay"), Mapping) else {}
    top_stay = dict(pack.get("topHungStay") or {}) if isinstance(pack.get("topHungStay"), Mapping) else {}
    hinges = dict(pack.get("hinges") or {}) if isinstance(pack.get("hinges"), Mapping) else {}
    lim = dict(pack.get("limitationArm") or {}) if isinstance(pack.get("limitationArm"), Mapping) else {}

    if open_hw == "stay" and side_n > 0:
        stay["enabled"] = True
        hinges["enabled"] = False
        lim["enabled"] = False
        if side_inch not in (None, ""):
            stay = apply_stay_size_rate(stay, _f(side_inch))
    elif open_hw == "hinges" and side_n > 0:
        hinges["enabled"] = True
        lim["enabled"] = True if lim.get("enabled") is not False else False
        stay["enabled"] = False
        if hinge_qty not in (None, ""):
            hinges["qty"] = max(2, min(8, int(_f(hinge_qty, 3))))

    if top_n > 0:
        top_stay["enabled"] = True
        if top_inch not in (None, ""):
            top_stay = apply_stay_size_rate(top_stay, _f(top_inch))
        elif top_stay.get("selectedInch") is None and isinstance(top_stay.get("lengths"), list) and top_stay["lengths"]:
            first = top_stay["lengths"][0]
            if isinstance(first, Mapping):
                top_stay = apply_stay_size_rate(top_stay, _f(first.get("inch"), 10))

    pack["stay"] = stay
    pack["topHungStay"] = top_stay
    pack["hinges"] = hinges
    pack["limitationArm"] = lim
    return setup


def _section_rate_per_m(sec: Mapping[str, Any] | None) -> float:
    """Aluminium ₹ per metre from section rate + weight.

    ``rateUnit``:
    - ``kg`` → rate × weightKgPerM  (Excel / Series Setup default)
    - ``rmt`` / ``m`` → rate as ₹/m
    - ``rft`` / ``ft`` → rate / 0.3048 → ₹/m
    Coating is separate via ``_coating_per_m``.
    """
    if not isinstance(sec, Mapping):
        return 0.0
    s = normalize_section(sec)
    rate = _f(s.get("rate"))
    # Excel / Series Setup default is ₹/kg (must match section_has_profile_rates).
    # A missing unit used to default to rft here, which either under-counted or
    # zeroed Al when weight×kg rates were expected.
    unit = _str(s.get("rateUnit") or "kg").lower()
    if rate <= 0:
        return 0.0
    if unit in ("kg", "per_kg", "kgm", "rs_kg", "inr_kg"):
        kg_m = _section_weight_kg_per_m(s)
        return rate * kg_m if kg_m > 0 else 0.0
    if unit in ("rmt", "rm", "m"):
        return rate
    if unit in ("rft", "ft"):
        return rate / 0.3048  # ₹/ft → ₹/m
    # pc / unknown with weight → treat rate as ₹/kg when weight present
    kg_m = _section_weight_kg_per_m(s)
    if kg_m > 0 and unit in ("pc", "pcs", ""):
        return rate * kg_m
    return rate


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


def _section_std_m(sec: Mapping[str, Any] | None, *, fallback: float = 3.0) -> float:
    """Best std bar length in metres from section stock fields."""
    if not isinstance(sec, Mapping):
        return max(_f(fallback, 3.0), 0.1)
    s = normalize_section(sec)
    mm = _f(s.get("stdLengthMm"))
    if mm > 0:
        return max(mm / 1000.0, 0.1)
    unit = _str(s.get("stdLengthUnit") or "rft").lower()
    raw = s.get("stdLength")
    # "12, 16" / "12 / 16" → prefer longest listed stock
    if isinstance(raw, str) and raw.strip():
        nums: list[float] = []
        for part in raw.replace("/", ",").replace(";", ",").split(","):
            part = part.strip().lower().replace("ft", "").replace("rft", "").replace("m", "")
            try:
                n = float(part)
            except ValueError:
                continue
            if n > 0:
                nums.append(n)
        if nums:
            n = max(nums)
            if unit in ("rmt", "rm", "m"):
                return max(n, 0.1)
            return max(n * 0.3048, 0.1)  # rft default
    if isinstance(raw, (int, float)) and float(raw) > 0:
        n = float(raw)
        if unit in ("rmt", "rm", "m"):
            return max(n, 0.1)
        return max(n * 0.3048, 0.1)
    return max(_f(fallback, 3.0), 0.1)


def _section_pool_key(sec: Mapping[str, Any] | None, *, series: str = "", colour: str = "", use: str = "") -> str:
    s = normalize_section(sec) if isinstance(sec, Mapping) else {}
    name = _str(s.get("name")) or _str(use) or "section"
    return remnant_key(series=series or name, section=name, colour=colour)


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
    remnants_in: Sequence[float] | None = None,
    wastage_threshold_m: float = WASTAGE_THRESHOLD_M,
) -> dict[str, Any]:
    """First-fit pack cuts into std bars (+ optional remnant pool).

    Leftover ≤ ~3 ft → **wastage** (charged). Leftover > ~3 ft → **reusable
    remnant** (not charged; returned in ``remnantsOut`` for in-quote / stock).
    When ``reuse`` is False, existing remnants are not consumed, but new >3 ft
    leftovers are still classified as remnants (not scrap).
    """
    std = max(float(std_m or 3.0), 0.1)
    thresh = max(_f(wastage_threshold_m, WASTAGE_THRESHOLD_M), 0.0)
    pieces = sorted((max(float(x), 0.0) for x in cut_lengths_m if _f(x) > 0), reverse=True)
    net = sum(pieces)
    empty = {
        "netMetres": 0.0,
        "purchasedMetres": 0.0,
        "wastageMetres": 0.0,
        "remnantMetres": 0.0,
        "wastagePercent": 0.0,
        "bars": 0,
        "stdLengthM": std,
        "reuse": bool(reuse),
        "wastageThresholdM": round(thresh, 4),
        "wastageThresholdFt": round(thresh / 0.3048, 2),
        "remnantsOut": [],
        "remnantsUsedM": 0.0,
    }
    if not pieces:
        return empty

    # Bins: remaining length after cuts. Seed from reusable stock when reuse on.
    # thresh=0 → any positive leftover is reusable within the quote (rulebook v2).
    bins: list[dict[str, Any]] = []
    remnants_used = 0.0
    if reuse:
        for rem in sorted(
            (_f(x) for x in (remnants_in or []) if _f(x) > thresh + 1e-12),
            reverse=True,
        ):
            bins.append({"source": "remnant", "capacity": rem, "remaining": rem, "new": False})

    def _place(L: float) -> None:
        nonlocal remnants_used
        for b in bins:
            if b["remaining"] + 1e-9 >= L:
                if b["source"] == "remnant" and abs(b["remaining"] - b["capacity"]) < 1e-9:
                    remnants_used += b["capacity"]
                b["remaining"] -= L
                return
        # New std bar
        bins.append({"source": "new", "capacity": std, "remaining": std - L, "new": True})

    if charge_full_when_split and not reuse:
        # One new bar per piece (gallery: top/bottom ≠ vertical).
        for L in pieces:
            bins.append({"source": "new", "capacity": std, "remaining": max(std - L, 0.0), "new": True})
    else:
        for L in pieces:
            if L > std + 1e-9:
                # Oversized: charge full piece as net; no pack
                bins.append({"source": "new", "capacity": L, "remaining": 0.0, "new": True})
            else:
                _place(L)

    new_bars = [b for b in bins if b.get("new")]
    purchased = sum(b["capacity"] for b in new_bars)
    waste = 0.0
    remnant_out: list[float] = []
    for b in bins:
        left = max(_f(b.get("remaining")), 0.0)
        if left <= 1e-9:
            continue
        if is_reusable_remnant_m(left, threshold_m=thresh):
            remnant_out.append(round(left, 4))
        else:
            waste += left

    pct_raw = (waste / purchased * 100.0) if purchased > 0 else 0.0
    pct_ui = min(max(pct_raw, WASTAGE_PCT_MIN), WASTAGE_PCT_MAX) if waste > 0 else 0.0
    if pct_raw > WASTAGE_PCT_MAX:
        pct_ui = round(pct_raw, 3)
    return {
        "netMetres": round(net, 4),
        "purchasedMetres": round(purchased, 4),
        "wastageMetres": round(waste, 4),
        "remnantMetres": round(sum(remnant_out), 4),
        "wastagePercent": round(pct_ui, 3),
        "wastagePercentRaw": round(pct_raw, 3),
        "bars": len(new_bars),
        "stdLengthM": std,
        "reuse": bool(reuse),
        "wastageThresholdM": round(thresh, 4),
        "wastageThresholdFt": round(thresh / 0.3048, 2),
        "remnantsOut": remnant_out,
        "remnantsUsedM": round(remnants_used, 4),
    }


def nest_cuts_by_section(
    cut_specs: Sequence[Mapping[str, Any]],
    *,
    remnant_pool: MutableMapping[str, list[float]] | None = None,
    reuse: bool = True,
    charge_full_when_split: bool = False,
    wastage_threshold_m: float = WASTAGE_THRESHOLD_M,
    default_std_m: float = 3.0,
    coat_full_bars: bool = True,
) -> dict[str, Any]:
    """Nest cuts grouped by section key; share remnant pool across groups/lines.

    Each cut spec: ``{lengthM, key, stdM?, aluminiumPerM, coatingPerM, ...}``.

    Costing follows WEOS window rules:
    - Aluminium charges **purchased** bar metres (balance/offcut value included).
    - Powder coating uses full stock length when ``coat_full_bars`` (default),
      otherwise cut (net) length only.
    - Monetary wastage is not added again on top of purchased Al (balance already
      sits inside purchase); scrap metres stay in the wastage report.
    """
    pool: MutableMapping[str, list[float]] = remnant_pool if remnant_pool is not None else {}
    by_key: dict[str, list[Mapping[str, Any]]] = {}
    for c in cut_specs or []:
        if not isinstance(c, Mapping):
            continue
        if _f(c.get("lengthM")) <= 0:
            continue
        key = _str(c.get("key") or c.get("sectionKey") or "section")
        by_key.setdefault(key, []).append(c)

    groups: list[dict[str, Any]] = []
    total_waste_m = 0.0
    total_waste_cost = 0.0
    total_al = 0.0
    total_coat = 0.0
    total_net_m = 0.0
    total_purch_m = 0.0
    total_balance_m = 0.0
    total_balance_cost = 0.0
    remnants_created: list[dict[str, Any]] = []

    for key, specs in by_key.items():
        lengths = [_f(s.get("lengthM")) for s in specs]
        std = _f(specs[0].get("stdM"), default_std_m) if specs else default_std_m
        al_m = _f(specs[0].get("aluminiumPerM"))
        coat_m = _f(specs[0].get("coatingPerM"))
        # Prefer weighted average if rates differ within key
        if len(specs) > 1:
            tw = sum(_f(s.get("lengthM")) for s in specs) or 1.0
            al_m = sum(_f(s.get("aluminiumPerM")) * _f(s.get("lengthM")) for s in specs) / tw
            coat_m = sum(_f(s.get("coatingPerM")) * _f(s.get("lengthM")) for s in specs) / tw
        seed = list(pool.get(key) or []) if reuse else []
        pack = pack_std_length_wastage(
            lengths,
            std_m=std or default_std_m,
            reuse=reuse,
            charge_full_when_split=charge_full_when_split,
            remnants_in=seed,
            wastage_threshold_m=wastage_threshold_m,
        )
        # Consume used remnants from pool; push new remnants back
        if reuse and key in pool:
            used_budget = _f(pack.get("remnantsUsedM"))
            kept: list[float] = []
            for rem in sorted(pool.get(key) or [], reverse=True):
                if used_budget > 1e-9 and rem <= used_budget + 1e-9:
                    used_budget -= rem
                elif used_budget > 1e-9 and rem > used_budget:
                    # partially conceptually consumed — keep remainder if reusable
                    left = rem - used_budget
                    used_budget = 0.0
                    if is_reusable_remnant_m(left, threshold_m=wastage_threshold_m):
                        kept.append(left)
                else:
                    kept.append(rem)
            pool[key] = kept
        for rem in pack.get("remnantsOut") or []:
            pool.setdefault(key, []).append(_f(rem))
            remnants_created.append({
                "key": key,
                "lengthM": _f(rem),
                "series": _str(specs[0].get("series")) if specs else "",
                "section": _str(specs[0].get("sectionName") or specs[0].get("name")) if specs else key,
                "colour": _str(specs[0].get("colour")) if specs else "",
            })
        waste_m = _f(pack.get("wastageMetres"))
        net_m = _f(pack.get("netMetres"))
        purch_m = _f(pack.get("purchasedMetres"))
        remnant_m = _f(pack.get("remnantMetres"))
        balance_m = max(purch_m - net_m, 0.0)  # scrap + reusable offcut in purchase
        # Rules: balance value included in purchase value.
        al_cost = purch_m * al_m
        coat_basis_m = purch_m if coat_full_bars else net_m
        coat_cost = coat_basis_m * coat_m
        # Informational scrap value only — not added again on top of purchased Al.
        bal_cost = balance_m * al_m
        waste_cost = waste_m * al_m
        total_waste_m += waste_m
        total_waste_cost += waste_cost
        total_al += al_cost
        total_coat += coat_cost
        total_net_m += net_m
        total_purch_m += purch_m
        total_balance_m += balance_m
        total_balance_cost += bal_cost
        groups.append({
            "key": key,
            "pack": pack,
            "aluminiumCost": round(al_cost, 2),
            "coatingCost": round(coat_cost, 2),
            "wastageCost": round(waste_cost, 2),
            "balanceMetres": round(balance_m, 4),
            "balanceCost": round(bal_cost, 2),
            "coatBasisMetres": round(coat_basis_m, 4),
            "coatFullBars": bool(coat_full_bars),
            "aluminiumPerM": round(al_m, 4),
            "coatingPerM": round(coat_m, 4),
            "bars": int(pack.get("bars") or 0),
            "sectionName": _str(specs[0].get("sectionName") or specs[0].get("name")) if specs else key,
        })

    return {
        "groups": groups,
        "aluminiumCost": round(total_al, 2),
        "coatingCost": round(total_coat, 2),
        # Monetary wastage already inside purchased Al; keep 0 so callers don't double-count.
        "wastageCost": 0.0,
        "wastageScrapCost": round(total_waste_cost, 2),
        "balanceMetres": round(total_balance_m, 4),
        "balanceCost": round(total_balance_cost, 2),
        "wastageMetres": round(total_waste_m, 4),
        "netMetres": round(total_net_m, 4),
        "purchasedMetres": round(total_purch_m, 4),
        "coatFullBars": bool(coat_full_bars),
        "remnantsCreated": remnants_created,
        "remnantPool": {k: [round(_f(x), 4) for x in v] for k, v in pool.items()},
        "wastage": {
            "netMetres": round(total_net_m, 4),
            "purchasedMetres": round(total_purch_m, 4),
            "wastageMetres": round(total_waste_m, 4),
            "balanceMetres": round(total_balance_m, 4),
            "remnantMetres": round(sum(_f(r.get("lengthM")) for r in remnants_created), 4),
            "wastagePercent": round(
                (total_waste_m / total_purch_m * 100.0) if total_purch_m > 0 else 0.0,
                3,
            ),
            "wastageThresholdM": round(wastage_threshold_m, 4),
            "wastageThresholdFt": round(wastage_threshold_m / 0.3048, 2),
            "reuse": bool(reuse),
            "coatFullBars": bool(coat_full_bars),
            "purchaseIncludesBalance": True,
        },
    }


def _active_casement_sections(
    cm: Mapping[str, Any],
    *,
    series_id: str | None = None,
    glass_kind: str | None = None,
) -> dict[str, Any]:
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
    clip = _resolve_casement_clip_section(cm, series_id=series_id, glass_kind=glass_kind)
    return {
        "frame": normalize_section(frame if isinstance(frame, Mapping) else {}),
        "mullion": normalize_section(mull_sec if isinstance(mull_sec, Mapping) else {}),
        "door": normalize_section(door_sec if isinstance(door_sec, Mapping) else {}),
        "clip": normalize_section(clip if isinstance(clip, Mapping) else {}),
        "mullionSize": mull_active,
        "doorSize": door_active,
        "includeBottom": bool(of.get("includeBottom", kind == "normal")),
        "kind": kind,
    }


def _resolve_casement_layout_from_line(
    line: Mapping[str, Any],
    *,
    width_mm: float,
    height_mm: float,
) -> dict[str, Any] | None:
    """Prefer casementLayout; fall back to casementPanels / handleOverrides.

    Geometry uses handleOverrides + glassCount even when casementLayout is
    missing; costing must follow the same canvas so fix+mullion is counted.
    """
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    layout = line.get("casementLayout") or opts.get("casementLayout")
    if isinstance(layout, Mapping) and (
        (isinstance(layout.get("bands"), (list, tuple)) and layout.get("bands"))
        or (isinstance(layout.get("panels"), (list, tuple)) and layout.get("panels"))
    ):
        return dict(layout)

    panels_flat = line.get("casementPanels") or opts.get("casementPanels")
    if isinstance(panels_flat, (list, tuple)) and panels_flat:
        by_band: dict[int, list[dict[str, Any]]] = {}
        for i, p in enumerate(panels_flat):
            if not isinstance(p, Mapping):
                p = {"role": p}
            bi = int(_f(p.get("bandIndex"), 0))
            by_band.setdefault(bi, []).append({
                "index": int(_f(p.get("index"), i)),
                "role": _role(p.get("role")),
                "widthMm": p.get("widthMm"),
                "heightMm": p.get("heightMm"),
                "profileSeries": p.get("profileSeries") or p.get("fixedSeries"),
                "doorSize": p.get("doorSize"),
            })
        bands = []
        for bi in sorted(by_band):
            plist = by_band[bi]
            h = next((_f(p.get("heightMm")) for p in plist if _f(p.get("heightMm")) > 0), 0.0)
            bands.append({"heightMm": h or None, "panels": plist})
        return {
            "mullionSize": _str(line.get("mullionSize") or opts.get("mullionSize") or ""),
            "bands": bands,
        }

    overrides = line.get("handleOverrides") or opts.get("handleOverrides") or {}
    if not isinstance(overrides, Mapping):
        overrides = {}
    n_raw = (
        line.get("glassShutters")
        or line.get("glassCount")
        or opts.get("glassShutters")
        or opts.get("glassCount")
    )
    try:
        n = int(_f(n_raw, 0))
    except (TypeError, ValueError):
        n = 0
    keys: list[int] = []
    for k in overrides:
        try:
            keys.append(int(k))
        except (TypeError, ValueError):
            continue
    if keys:
        n = max(n, max(keys) + 1)
    if n <= 0 and not overrides:
        return None
    n = max(n, 1)
    by_band2: dict[int, list[dict[str, Any]]] = {}
    for i in range(n):
        ov = overrides.get(i) or overrides.get(str(i)) or {}
        if not isinstance(ov, Mapping):
            ov = {}
        bi = int(_f(ov.get("bandIndex"), 0))
        by_band2.setdefault(bi, []).append({
            "index": i,
            "role": _role(ov.get("role") or "openable"),
            "widthMm": ov.get("widthMm"),
            "heightMm": ov.get("heightMm"),
        })
    bands2 = []
    for bi in sorted(by_band2):
        plist = by_band2[bi]
        h = next((_f(p.get("heightMm")) for p in plist if _f(p.get("heightMm")) > 0), 0.0)
        bands2.append({"heightMm": h or (height_mm if len(by_band2) == 1 else None), "panels": plist})
    return {
        "mullionSize": _str(line.get("mullionSize") or opts.get("mullionSize") or ""),
        "bands": bands2,
        "widthMm": width_mm,
        "heightMm": height_mm,
    }


def _clip_section_from_catalogue(series_id: str | None, *, kind: str) -> dict[str, Any]:
    """Load Clip SG / Clip DG from products/sections/<series>.json when setup is empty."""
    sid = _str(series_id)
    if not sid:
        return {}
    try:
        from WEOS.factory.section_catalogue import get_series

        doc = get_series(sid)
    except Exception:
        return {}
    needles = ("clip", "sg") if kind == "sg" else ("clip", "dg")
    alt = ("clip", "dgu") if kind != "sg" else ("clip", "single")
    found = None
    for s in doc.get("sections") or []:
        if not isinstance(s, Mapping):
            continue
        nl = _str(s.get("name")).lower()
        if all(n in nl for n in needles) or all(n in nl for n in alt):
            found = s
            break
    if found is None and kind == "sg":
        for s in doc.get("sections") or []:
            if isinstance(s, Mapping) and "clip" in _str(s.get("name")).lower():
                found = s
                break
    if not found:
        return {}
    return normalize_section({
        "name": found.get("name"),
        "wMm": found.get("widthMm"),
        "hMm": found.get("sectionDepthMm"),
        "wallMm": found.get("wallThicknessMm"),
        "weightKgPerM": found.get("weightKgPerMtr"),
        "rate": found.get("rate"),
        "rateUnit": found.get("rateUnit") or "rft",
        "coatingCost": found.get("coatingCost"),
        "coatingUnit": found.get("coatingUnit") or "rft",
        "stdLength": found.get("standardLength"),
        "use": found.get("use"),
    })


def _resolve_casement_clip_section(
    cm: Mapping[str, Any],
    *,
    series_id: str | None = None,
    glass_kind: str | None = None,
) -> dict[str, Any]:
    """Active glass/mullion clip section (SG or DGU) with catalogue fallback."""
    clips = cm.get("glassClips") if isinstance(cm.get("glassClips"), Mapping) else {}
    glass = cm.get("glass") if isinstance(cm.get("glass"), Mapping) else {}
    active = _str(clips.get("active") or "sg").lower()
    if glass_kind:
        gk = glass_kind.lower()
        if any(x in gk for x in ("dgu", "double", "igu", "lam", "laminat")):
            active = "dgu"
        elif any(x in gk for x in ("sg", "single", "clear", "tuff", "tough")):
            active = "sg"
    if active in ("dg", "double"):
        active = "dgu"
    if active not in ("sg", "dgu"):
        active = "sg"
    block = clips.get("sg" if active == "sg" else "dgu")
    block = block if isinstance(block, Mapping) else {}
    for cand in (
        block.get("section"),
        glass.get("sgClip" if active == "sg" else "dgClip"),
        glass.get("sgClip") if active == "sg" else glass.get("dgClip"),
    ):
        if isinstance(cand, Mapping) and (
            _str(cand.get("name"))
            or _f(cand.get("weightKgPerM")) > 0
            or _f(cand.get("rate")) > 0
        ):
            return normalize_section(cand)
    return _clip_section_from_catalogue(series_id, kind="sg" if active == "sg" else "dg")


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
    series_id: str | None = None,
    glass_kind: str | None = None,
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

    sid = _str(series_id) or _str((setup or {}).get("id") or (setup or {}).get("series") or "")
    secs = _active_casement_sections(cm, series_id=sid or None, glass_kind=glass_kind)
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
    cut_specs: list[dict[str, Any]] = []
    coat_mult = coating_multiplier
    series_label = ""
    try:
        series_label = _str((setup or {}).get("id") or (setup or {}).get("series") or "")
    except Exception:
        series_label = ""

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
        s = normalize_section(sec) if isinstance(sec, Mapping) else {}
        rate_m = _section_rate_per_m(s)
        coat_m = _coating_per_m(s, colour=colour, coating_multiplier=coat_mult)
        total_m = length_m * qty
        n_int = int(max(round(qty), 1))
        for _ in range(n_int):
            cuts_m.append(length_m)
        if abs(qty - round(qty)) > 1e-6:
            cuts_m.append(length_m * (qty - int(qty)))
        al_amt = total_m * rate_m
        coat_amt = total_m * coat_m
        amount = al_amt + coat_amt
        display = _str(s.get("name")) or name
        kg_m = _section_weight_kg_per_m(s)
        pcs = int(round(qty)) if abs(qty - round(qty)) < 1e-6 else round(qty, 4)
        std_m = _section_std_m(s, fallback=3.0)
        key = _section_pool_key(s, series=series_label, colour=_str(colour), use=use)
        piece_count = n_int
        if abs(qty - round(qty)) > 1e-6:
            piece_count += 1
        for i in range(piece_count):
            Lm = length_m if i < n_int else length_m * (qty - int(qty))
            if Lm <= 0:
                continue
            cut_specs.append({
                "lengthM": Lm,
                "key": key,
                "stdM": std_m,
                "aluminiumPerM": rate_m,
                "coatingPerM": coat_m,
                "sectionName": display,
                "series": series_label,
                "colour": _str(colour),
                "use": use,
            })
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
            "aluminiumPerM": round(rate_m, 4),
            "coatingPerM": round(coat_m, 4),
            "aluminiumAmount": round(al_amt, 2),
            "coatingAmount": round(coat_amt, 2),
            "amount": round(amount, 2),
            "rateUnit": _str(s.get("rateUnit") or "kg"),
            "catalogueName": display,
            "remarks": remarks,
            "sides": _str(remarks) or use.replace("_", " "),
            "stock": _section_stock_label(s, fallback_std_m=std_m),
            "stdLengthM": round(std_m, 4),
            "sectionKey": key,
            "weightKgPerM": round(kg_m, 4) if kg_m else None,
            "weightKg": round(kg_m * total_m, 3) if kg_m else None,
            "colour": _str(colour),
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

    # Fixed / sliding-in-casement lites — glass clips (v2 + h2 per lite) from series
    clip = secs.get("clip") if isinstance(secs.get("clip"), Mapping) else {}
    fixed_panels = [p for p in panels if p["role"] in ("fix", "sliding")]
    for p in fixed_panels:
        if not clip or not (
            _str(clip.get("name"))
            or _f(clip.get("weightKgPerM")) > 0
            or _f(clip.get("rate")) > 0
        ):
            break
        pw, ph = _f(p["widthMm"]) / 1000.0, _f(p["heightMm"]) / 1000.0
        add_profile(
            f"Glass clip · vertical",
            ph,
            2,
            clip,
            use="glass_clip",
            remarks=f"fix R{p['bandIndex']+1}P{p['index']+1}",
        )
        add_profile(
            f"Glass clip · horizontal",
            pw,
            2,
            clip,
            use="glass_clip",
            remarks=f"fix R{p['bandIndex']+1}P{p['index']+1}",
        )

    fixed_n = len(fixed_panels)
    mullion_pcs = sum(max(len(plist) - 1, 0) for plist in bands.values()) + max(n_bands - 1, 0)
    return {
        "lines": lines,
        "cutsM": cuts_m,
        "cutSpecs": cut_specs,
        "counts": {
            "bands": n_bands,
            "panels": len(panels),
            "sideSwingDoors": side_n,
            "topHungDoors": top_n,
            "operable": len(operable),
            "fixed": fixed_n,
            "mullionCount": mullion_pcs,
            "mullionSize": secs["mullionSize"],
            "doorSize": secs["doorSize"],
            "hasClip": bool(
                clip
                and (
                    _str(clip.get("name"))
                    or _f(clip.get("weightKgPerM")) > 0
                    or _f(clip.get("rate")) > 0
                )
            ),
        },
        "sections": secs,
    }


def _glass_order_area_sft(
    line: Mapping[str, Any],
    *,
    width_mm: float,
    height_mm: float,
) -> dict[str, Any]:
    """Glass order area from pane dims after series deductions (rules book).

    Sliding: N glass panes share opening width; each pane uses insertion/overlap
    from product glass rules when available. Mesh does not add glass area.
    Fallback: opening W×H (matches nominal 2-pane = opening area example).
    """
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    shutters = max(
        _f(
            line.get("glassShutters")
            or opts.get("glassCount")
            or opts.get("glassShutters")
            or line.get("shutterCount")
            or 0
        ),
        0.0,
    )
    opening_sft = (max(width_mm, 0) * max(height_mm, 0) / 1_000_000.0) * 10.7639
    if shutters < 1:
        return {
            "areaSft": round(opening_sft, 4),
            "paneCount": 1,
            "paneWidthMm": round(width_mm, 1),
            "paneHeightMm": round(height_mm, 1),
            "basis": "opening",
        }

    pane_w = max(width_mm, 0.0) / shutters
    pane_h = max(height_mm, 0.0)
    glass_rules = None
    try:
        from WEOS.factory.quote_item_snapshot import product_id_of
        from WEOS.factory.product_loader import load_product

        pid = product_id_of(line) if line else None
        if pid:
            prod = load_product(pid, strict=False)
            glass_rules = (prod or {}).get("glass") if isinstance(prod, Mapping) else None
            if not isinstance(glass_rules, Mapping):
                eng = (prod or {}).get("engineering") if isinstance(prod, Mapping) else {}
                glass_rules = eng.get("glass") if isinstance(eng, Mapping) else None
    except Exception:
        glass_rules = None

    total_sft = 0.0
    sized_w = pane_w
    sized_h = pane_h
    basis = "pane_share"
    if isinstance(glass_rules, Mapping):
        try:
            from WEOS.factory.glass_sizing import preview_from_profile

            # End shutters: handle side + interlock; middle: interlock both sides.
            for i in range(int(round(shutters))):
                left_il = i > 0
                right_il = i < int(round(shutters)) - 1
                if int(round(shutters)) == 2:
                    left_il = i == 1
                    right_il = i == 0
                sized = preview_from_profile(
                    glass_rules,
                    clear_width_mm=pane_w,
                    clear_height_mm=pane_h,
                    interlock_left=left_il,
                    interlock_right=right_il,
                    label=f"pane{i + 1}",
                )
                total_sft += _f(sized.get("areaSqft"))
                sized_w = _f(sized.get("glassWidthMm"), pane_w)
                sized_h = _f(sized.get("glassHeightMm"), pane_h)
            if total_sft > 0:
                basis = "pane_after_deductions"
                return {
                    "areaSft": round(total_sft, 4),
                    "paneCount": int(round(shutters)),
                    "paneWidthMm": round(sized_w, 1),
                    "paneHeightMm": round(sized_h, 1),
                    "basis": basis,
                }
        except Exception:
            pass

    # Without insertion rules: equal panes sum to opening area (rules worked example).
    return {
        "areaSft": round(opening_sft, 4),
        "paneCount": int(round(shutters)),
        "paneWidthMm": round(pane_w, 1),
        "paneHeightMm": round(pane_h, 1),
        "basis": basis,
    }


def _glass_cost(line: Mapping[str, Any], *, width_mm: float, height_mm: float, qty: float) -> dict[str, Any]:
    order = _glass_order_area_sft(line, width_mm=width_mm, height_mm=height_mm)
    area_sft = _f(order.get("areaSft"))
    rate = 0.0
    name = _str(line.get("glass") or line.get("glassName") or "Glass")
    breakdown = None
    gid = _str(line.get("glass"))
    thickness_mm = None
    glass_colour = None
    pack_name = None
    kind = None
    g: Mapping[str, Any] | None = None
    try:
        from WEOS.factory.glass_catalogue import (
            cart_glass_options,
            clear_tuff_rate,
            commercial_rate_for_spec,
            get_glass,
        )

        g = get_glass(gid) if gid else None
        if isinstance(g, Mapping):
            name = _str(g.get("name") or g.get("label") or g.get("displayName") or name)
            pack_name = name
            rate = _f(g.get("rate") or g.get("ratePerSft") or g.get("ratePerSqft"))
            thickness_mm = g.get("thicknessMm") or g.get("overallMm")
            glass_colour = _str(g.get("colour") or g.get("color") or "")
            kind = _str(g.get("makeup") or g.get("kind") or g.get("type") or "")
            if isinstance(g.get("rateBreakdown"), Mapping):
                breakdown = dict(g["rateBreakdown"])
            priced = commercial_rate_for_spec(g)
            if priced and str(g.get("makeup") or "").lower() in ("dgu", "laminated"):
                rate = _f(priced.get("rate"), rate)
                if isinstance(priced.get("rateBreakdown"), Mapping):
                    breakdown = dict(priced["rateBreakdown"])
            # Never leave catalogue glass at ₹0 — fall back to commercial leaf rates.
            if rate <= 0:
                thk = _f(thickness_mm) or 5.0
                leaf = clear_tuff_rate(thk)
                if leaf:
                    tough = bool(g.get("toughened"))
                    rate = float(leaf) if tough else round(float(leaf) * 0.7, 2)
                    breakdown = {
                        "leafRate": rate,
                        "formula": "fallback clear-tuff leaf" if tough else "fallback annealed (~70% of tuff)",
                    }
        if rate <= 0 and gid:
            for opt in cart_glass_options(merge_library=True):
                if str(opt.get("id") or "") == gid:
                    rate = _f(opt.get("rate") or opt.get("ratePerSft"))
                    name = _str(opt.get("label") or opt.get("name") or name)
                    pack_name = name
                    thickness_mm = opt.get("thicknessMm") or thickness_mm
                    glass_colour = _str(opt.get("colour") or glass_colour or "")
                    kind = _str(opt.get("makeup") or kind or "")
                    if isinstance(opt.get("rateBreakdown"), Mapping):
                        breakdown = dict(opt["rateBreakdown"])
                    priced = commercial_rate_for_spec(opt)
                    if priced and str(opt.get("makeup") or "").lower() in ("dgu", "laminated"):
                        rate = _f(priced.get("rate"), rate)
                        if isinstance(priced.get("rateBreakdown"), Mapping):
                            breakdown = dict(priced["rateBreakdown"])
                    if rate <= 0:
                        thk = _f(thickness_mm) or 5.0
                        leaf = clear_tuff_rate(thk)
                        if leaf:
                            tough = bool(opt.get("toughened"))
                            rate = float(leaf) if tough else round(float(leaf) * 0.7, 2)
                    break
    except Exception:
        pass
    rate = _f(line.get("glassRate") or (line.get("options") or {}).get("glassRate"), rate)
    q = max(qty, 1.0)
    amt = area_sft * rate * q
    out = {
        "name": name,
        "packName": pack_name or name,
        "areaSft": round(area_sft * q, 3),
        "widthMm": round(_f(order.get("paneWidthMm"), width_mm), 1),
        "heightMm": round(_f(order.get("paneHeightMm"), height_mm), 1),
        "sizeLabel": (
            f"{round(_f(order.get('paneWidthMm'), width_mm)):g}×"
            f"{round(_f(order.get('paneHeightMm'), height_mm)):g} mm"
            f" × {int(order.get('paneCount') or 1)} pane(s)"
        ),
        "paneCount": order.get("paneCount"),
        "areaBasis": order.get("basis"),
        "qty": q,
        "thicknessMm": _f(thickness_mm) if thickness_mm is not None else None,
        "colour": glass_colour or None,
        "kind": kind or None,
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
    setup_blob = resolve_costing_setup(line, product=product, setup=setup)
    if not isinstance(setup_blob, Mapping):
        return {"ok": False, "costEngine": "stub", "reason": "no_setup", "total": 0.0}

    norm = normalize_setup(setup_blob) if not isinstance(setup_blob.get("casement"), Mapping) else setup_blob
    if not isinstance(norm.get("casement"), Mapping):
        try:
            norm = normalize_setup(setup_blob)
        except Exception:
            return {"ok": False, "costEngine": "stub", "reason": "not_casement", "total": 0.0}
    if _str(norm.get("type")).lower() != "casement" and not isinstance(norm.get("casement"), Mapping):
        return {"ok": False, "costEngine": "stub", "reason": "not_casement", "total": 0.0}

    W = _f(line.get("width"))
    H = _f(line.get("height"))
    qty = max(_f(line.get("qty") or line.get("quantity"), 1.0), 1.0)
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    colour = _str(line.get("colour") or opts.get("colour") or "white")
    layout = _resolve_casement_layout_from_line(line, width_mm=W, height_mm=H)
    if layout is None and isinstance(product.get("casementLayout"), Mapping):
        layout = product.get("casementLayout")
    mull_ov = _str(
        line.get("mullionSize")
        or opts.get("mullionSize")
        or (layout or {}).get("mullionSize")
        or ""
    )
    door_ov = _str(line.get("doorSize") or opts.get("doorSize") or "")
    series_id = _str(
        product.get("id")
        or line.get("sectionSeries")
        or line.get("productId")
        or line.get("product")
        or ""
    )
    glass_kind = _str(line.get("glass") or line.get("glassName") or opts.get("glass") or "")

    cuts = derive_casement_profile_cuts(
        norm,
        width_mm=W,
        height_mm=H,
        casement_layout=layout if isinstance(layout, Mapping) else None,
        mullion_size=mull_ov or None,
        door_size=door_ov or None,
        colour=colour,
        series_id=series_id or None,
        glass_kind=glass_kind or None,
    )
    counts = cuts.get("counts") or {}
    cm = norm.get("casement") or {}
    costing = cm.get("costing") if isinstance(cm.get("costing"), Mapping) else {}
    flags = derive_casement_wastage_flags(norm)
    reuse = bool(flags.get("projectWastageReuse"))
    if costing.get("projectWastageReuse") is False:
        reuse = False
    std_m = _pick_std_m(costing)
    charge_full = bool(flags.get("chargeFullStdLength"))
    remnant_pool: dict[str, list[float]] = {}
    if isinstance(line.get("_remnantPool"), dict):
        remnant_pool = {str(k): list(v) for k, v in line["_remnantPool"].items() if isinstance(v, list)}

    coat_full = True
    if costing.get("coatFullBars") is False or costing.get("coatCutsOnly") is True:
        coat_full = False
    nest = nest_cuts_by_section(
        cuts.get("cutSpecs") or [],
        remnant_pool=remnant_pool,
        reuse=reuse,
        charge_full_when_split=charge_full,
        default_std_m=std_m,
        coat_full_bars=coat_full,
    )
    waste = nest.get("wastage") or {}
    al_amt = _f(nest.get("aluminiumCost"))
    coat_amt = _f(nest.get("coatingCost"))
    wastage_cost = _f(nest.get("wastageCost"))  # 0 — balance already in purchased Al
    profile_net = al_amt + coat_amt
    profile_purchased = profile_net  # purchase basis (Al + coat)

    # Hardware from pack — only operable doors (side-swing ≠ top-hung).
    # Fixed-only layouts must not invent a phantom leaf via ``or 1``.
    side_n = float(counts.get("sideSwingDoors") or 0)
    top_n = float(counts.get("topHungDoors") or 0)
    operable = float(counts.get("operable") if counts.get("operable") is not None else (side_n + top_n))
    # Side-swing stay XOR hinge; top hung stay-only + size from Specs
    norm = _apply_casement_hw_clarity(norm, line, side_n=side_n, top_n=top_n)
    bom = apply_setup_bom(
        norm,
        width_mm=W,
        height_mm=H,
        ctx={
            "shutterCount": max(operable, 0.0),
            "leafCount": max(operable, 0.0),
            "sideSwingDoors": side_n,
            "topHungDoors": top_n,
            "mullionCount": float(counts.get("mullionCount") or 0),
            "fixedCount": float(counts.get("fixed") or 0),
            "system": "casement",
        },
        shutter_count=max(operable, 0.0),
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
        brand = ""
        try:
            from WEOS.factory.hardware_brands import resolve_hardware_brand
            brand = resolve_hardware_brand(h, brand=h.get("brand"), origin=h.get("origin"), name=h.get("name"))
        except Exception:
            brand = _str(h.get("brand"))
        hw_lines.append({
            "category": "hardware",
            "name": _str(h.get("name")),
            "catalogueName": _str(h.get("name")),
            "brand": brand,
            "qty": q,
            "unit": _str(h.get("unit") or "PC"),
            "unitRate": r,
            "amount": round(amt, 2),
            "remarks": _str(h.get("remarks")),
        })

    glass = _glass_cost(line, width_mm=W, height_mm=H, qty=1.0)
    glass_amt = _f(glass.get("amount"))
    mesh_pack = _mesh_fabric_pack(line)
    mesh_amt = _f(mesh_pack.get("meshCost"))

    area_sft = (W * H / 1_000_000.0) * 10.7639
    from WEOS.factory.commercial_defaults import (
        coating_multiplier_for_colour,
        default_coating_brand,
        finish_family_for_colour,
        installation_per_sft,
        labour_per_sft,
    )

    labour_rate = labour_per_sft(costing.get("labourPerSft"))
    labour_amt = area_sft * labour_rate
    install_rate = installation_per_sft(costing.get("installationPerSft") or costing.get("installPerSft"))
    install_amt = area_sft * install_rate
    material_sub = profile_purchased + hw_amt + glass_amt + mesh_amt
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
        suggested_rate = round(unit_total / peri_ft, 1) if peri_ft else None
    elif area_sft > 0:
        suggested_rate = round(unit_total / area_sft, 1)

    engine = "live" if (profile_net > 0 or hw_amt > 0 or glass_amt > 0 or mesh_amt > 0 or labour_amt > 0 or install_amt > 0) else "stub"
    try:
        coat_mult = coating_multiplier_for_colour(colour)
        finish_family = finish_family_for_colour(colour)
        coat_brand = default_coating_brand()
    except Exception:
        coat_mult = 1.0
        finish_family = "plain"
        coat_brand = ""

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
        "coatingFinishFamily": finish_family,
        "coatingBrand": coat_brand,
        "colour": colour,
        "materialCost": round(material_sub * qty, 2),
        "aluminiumCost": round(al_amt * qty, 2),
        "coatingCost": round(coat_amt * qty, 2),
        "profileCost": round(profile_purchased * qty, 2),
        "profileNetCost": round(profile_net * qty, 2),
        "wastageCost": round(wastage_cost * qty, 2),
        "hardwareCost": round(hw_amt * qty, 2),
        "glassCost": round(glass_amt * qty, 2),
        "meshCost": round(mesh_amt * qty, 2),
        "wastage": waste,
        "remnants": nest.get("remnantsCreated") or [],
        "remnantPool": nest.get("remnantPool") or {},
        "profiles": cuts.get("lines") or [],
        "hardware": hw_lines,
        "glass": glass,
        "mesh": mesh_pack.get("mesh"),
        "meshLines": mesh_pack.get("meshLines") or [],
        "suggestedSellRate": suggested_rate,
        "costPerUnit": suggested_rate,
        "saleUnit": sale_unit,
        "areaSft": round(area_sft, 3),
        "nestGroups": nest.get("groups") or [],
        "purchasedMetres": nest.get("purchasedMetres"),
        "balanceMetres": nest.get("balanceMetres"),
        "balanceCost": nest.get("balanceCost"),
        "cutSpecs": cuts.get("cutSpecs") or [],
        "profileFamily": "casement",
        "counts": counts,
        "sideSwingOpenHw": _str(
            ((norm.get("casement") or {}).get("hardwarePack") or {}).get("openHardware") or "hinges"
        ),
        "sideStayInch": ((norm.get("casement") or {}).get("hardwarePack") or {}).get("stay", {}).get("selectedInch")
        if isinstance(((norm.get("casement") or {}).get("hardwarePack") or {}).get("stay"), Mapping)
        else None,
        "topHungStayInch": (
            ((norm.get("casement") or {}).get("hardwarePack") or {}).get("topHungStay", {}).get("selectedInch")
            if isinstance(((norm.get("casement") or {}).get("hardwarePack") or {}).get("topHungStay"), Mapping)
            else None
        ),
        "breakdown": {
            "aluminium": round(al_amt, 2),
            "coating": round(coat_amt, 2),
            "profiles": round(profile_net, 2),
            "wastage": round(wastage_cost, 2),
            "balance": round(_f(nest.get("balanceCost")), 2),
            "hardware": round(hw_amt, 2),
            "glass": round(glass_amt, 2),
            "mesh": round(mesh_amt, 2),
            "labour": round(labour_amt, 2),
            "installation": round(install_amt, 2),
            "profit": round(profit_amt, 2),
        },
    }


def _try_load_setup(product_id: str | None) -> dict[str, Any] | None:
    pid = _str(product_id)
    if not pid:
        return None
    try:
        from WEOS.factory.product_loader import load_product

        doc = load_product(pid, strict=False)
        setup = doc.get("setup") if isinstance(doc.get("setup"), Mapping) else None
        return dict(setup) if isinstance(setup, Mapping) else None
    except Exception:
        return None


def _setup_from_catalogue_profiles(product: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Build a minimal sliding setup from catalogue.profiles when Series Setup is missing."""
    if not isinstance(product, Mapping):
        return None
    cat = product.get("catalogue") if isinstance(product.get("catalogue"), Mapping) else {}
    profiles = list(cat.get("profiles") or [])
    if not profiles:
        return None
    try:
        from WEOS.factory.profile_hardware_import import _build_sliding_setup, _setup_section_from_row
    except Exception:
        _build_sliding_setup = None  # type: ignore
    # Convert catalogue profiles → import section rows (preserve weight/dims; default Al ₹450/kg)
    sections: list[dict[str, Any]] = []
    for p in profiles:
        if not isinstance(p, Mapping):
            continue
        row = {
            "name": p.get("name") or "",
            "usage": p.get("usage") or "",
            "usageLabel": p.get("usageLabel") or "",
            "widthMm": p.get("widthMm"),
            "sectionDepthMm": p.get("sectionDepthMm"),
            "weightKgPerMtr": p.get("weightKgPerMtr") or p.get("weightKgPerM"),
            "wallThicknessMm": p.get("wallThicknessMm"),
            "standardLength": p.get("standardLength"),
            "trackCount": p.get("trackCount"),
            "rate": p.get("rate") if p.get("rate") not in (None, "") else 450.0,
            "rateUnit": p.get("rateUnit") or "kg",
            # Powder coat is always ₹/rft in Series Setup — default plain white rate
            # when Excel catalogue rows omit coating so live Coat never stays at 0.
            "coatingCost": (
                p.get("coatingCost")
                if p.get("coatingCost") not in (None, "")
                else 22.0
            ),
            "coatingUnit": p.get("coatingUnit") or "rft",
            "use": p.get("use") or p.get("usageLabel") or "",
            "pcsVertical": p.get("pcsVertical"),
            "pcsHorizontal": p.get("pcsHorizontal"),
            "allSidesSame": p.get("allSidesSame"),
            "bomHint": p.get("bomHint"),
            "designNote": p.get("designNote"),
            "glassOptions": p.get("glassOptions") or [],
            "centerOpeningOnly": p.get("centerOpeningOnly"),
        }
        sections.append(row)
    if not sections:
        return None
    series = {
        "id": _str(product.get("id") or product.get("sectionSeries") or "catalogue"),
        "title": product.get("displayName") or product.get("id"),
        "family": "sliding",
        "sections": sections,
    }
    if _build_sliding_setup:
        try:
            return _build_sliding_setup(series, [])
        except Exception:
            pass
    # Minimal fallback without import helper
    from WEOS.factory.product_setup import normalize_setup as _ns

    track_options = []
    seen: set[str] = set()
    for sec in sections:
        tc = sec.get("trackCount")
        if tc is None:
            continue
        tid = "2.5" if abs(float(tc) - 2.5) < 0.01 else str(int(float(tc)))
        if tid in seen:
            continue
        seen.add(tid)
        try:
            from WEOS.factory.profile_hardware_import import _setup_section_from_row as _ss

            s = _ss(sec)
        except Exception:
            s = {
                "name": sec.get("name"),
                "weightKgPerM": sec.get("weightKgPerMtr"),
                "rate": sec.get("rate") or 450,
                "rateUnit": "kg",
                "coatingCost": sec.get("coatingCost") if sec.get("coatingCost") not in (None, "") else 22,
                "coatingUnit": "rft",
                "wMm": sec.get("widthMm"),
                "hMm": sec.get("sectionDepthMm"),
                "wallMm": sec.get("wallThicknessMm"),
            }
        track_options.append({
            "id": tid,
            "label": f"{tid} track",
            "sides": {"all": s, "vertical": s, "top": s, "bottom": s},
        })
    return _ns({"type": "sliding", "sliding": {"trackOptions": track_options, "activeTrackOption": (track_options[0]["id"] if track_options else "2")}})


def resolve_costing_setup(
    line: Mapping[str, Any] | None,
    *,
    product: Mapping[str, Any] | None = None,
    setup: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Resolve the richest sliding/casement setup for live design cost.

    Prefers product.setup with profile rates; else sectionSeries product; else
    linked engine; else catalogue.profiles → ephemeral setup. Syncs cart trackCount.
    """
    product = product if isinstance(product, Mapping) else {}
    line = line if isinstance(line, Mapping) else {}
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    setup_blob = setup if isinstance(setup, Mapping) else None
    if setup_blob is None and isinstance(product.get("setup"), Mapping):
        setup_blob = dict(product.get("setup") or {})

    candidates: list[dict[str, Any]] = []
    if isinstance(setup_blob, Mapping) and setup_blob:
        candidates.append(dict(setup_blob))

    cat = product.get("catalogue") if isinstance(product.get("catalogue"), Mapping) else {}
    series_id = _str(
        line.get("sectionSeries")
        or opts.get("sectionSeries")
        or product.get("sectionSeries")
        or cat.get("sectionSeries")
    )
    pid = _str(product.get("id") or line.get("product") or line.get("productId"))
    if series_id and series_id != pid:
        alt = _try_load_setup(series_id)
        if alt:
            candidates.append(alt)

    linked = _str(product.get("linkedProductId") or cat.get("productId"))
    if linked and linked != pid:
        alt = _try_load_setup(linked)
        if alt:
            candidates.append(alt)

    chosen: dict[str, Any] | None = None
    for cand in candidates:
        if setup_has_profile_rates(cand):
            chosen = cand
            break
    if chosen is None and candidates:
        # Last resort: first candidate even if empty (labour/install still apply)
        chosen = candidates[0]

    # Only hydrate sliding catalogue profiles for sliding/window series — never
    # overwrite a casement setup with an ephemeral sliding BOM.
    ptype = _str(product.get("productType") or line.get("system") or opts.get("system")).lower()
    wants_casement = "casement" in ptype or "openable" in ptype
    if not wants_casement and isinstance(chosen, Mapping):
        wants_casement = _str(chosen.get("type")).lower() == "casement"
    if (chosen is None or not setup_has_profile_rates(chosen)) and not wants_casement:
        built = _setup_from_catalogue_profiles(product)
        if built and setup_has_profile_rates(built):
            chosen = built

    if not isinstance(chosen, Mapping):
        return None

    track_c = line.get("trackCount") if line.get("trackCount") is not None else opts.get("trackCount")
    try:
        st = _str(chosen.get("type")).lower()
        if st == "casement" or wants_casement:
            return normalize_setup(chosen)
        return with_active_track(chosen, track_count=track_c)
    except Exception:
        return normalize_setup(chosen)


def compute_sliding_design_cost(
    line: Mapping[str, Any],
    *,
    product: Mapping[str, Any] | None = None,
    setup: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Sliding cost from setup track/shutter rates + hardware (best-effort live)."""
    product = product if isinstance(product, Mapping) else {}
    setup_blob = resolve_costing_setup(line, product=product, setup=setup)
    if not isinstance(setup_blob, Mapping):
        return {"ok": False, "costEngine": "stub", "reason": "no_setup", "total": 0.0}
    norm = normalize_setup(setup_blob) if not setup_blob.get("sliding") else setup_blob
    if not isinstance(norm.get("sliding"), Mapping) and _str(norm.get("type")).lower() != "sliding":
        # resolve may already return normalized setup
        try:
            norm = normalize_setup(setup_blob)
        except Exception:
            return {"ok": False, "costEngine": "stub", "reason": "not_sliding", "total": 0.0}
    if _str(norm.get("type")).lower() != "sliding" and not isinstance(norm.get("sliding"), Mapping):
        return {"ok": False, "costEngine": "stub", "reason": "not_sliding", "total": 0.0}

    W = _f(line.get("width"))
    H = _f(line.get("height"))
    qty = max(_f(line.get("qty") or line.get("quantity"), 1.0), 1.0)
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    colour = _str(line.get("colour") or opts.get("colour") or "white")
    shutters = max(_f(line.get("glassShutters") or opts.get("glassCount") or opts.get("glassShutters"), 2), 1)
    # Rolling / collapsible are fabric add-ons — never count as in-track mesh sashes.
    _addon_mesh = False
    try:
        from WEOS.factory.mesh_addon import is_addon_mesh

        _addon_mesh = is_addon_mesh(line)
    except Exception:
        _addon_mesh = False
    mesh_n = max(
        _f(
            line.get("meshShutters")
            or opts.get("meshCount")
            or opts.get("meshShutters")
            or (0 if _addon_mesh else (1 if (line.get("mesh") or opts.get("mesh")) else 0))
        ),
        0,
    )
    if _addon_mesh:
        mesh_n = 0.0
    opening = _str(
        line.get("opening")
        or line.get("openingType")
        or opts.get("opening")
        or opts.get("openingType")
        or ""
    )
    track_c = line.get("trackCount") if line.get("trackCount") is not None else opts.get("trackCount")
    # Ensure cart track is applied even if resolve skipped with_active_track
    if track_c is not None:
        try:
            norm = with_active_track(norm, track_count=track_c)
        except Exception:
            pass
    # Glass weight → suggest/filter wheels; mesh shutters → regular mesh wheels
    norm, wheel_meta = _apply_sliding_wheel_clarity(
        norm,
        line,
        width_mm=W,
        height_mm=H,
        shutters=shutters,
        mesh_n=mesh_n,
    )
    glass_kg_total = _f(wheel_meta.get("totalGlassKg"))
    bom = apply_setup_bom(
        norm,
        width_mm=W,
        height_mm=H,
        ctx={
            "shutterCount": shutters,
            "glassCount": shutters,
            "meshCount": mesh_n,
            "meshShutters": mesh_n,
            "opening": opening or None,
            "trackCount": track_c,
            "colour": colour,
            "system": "sliding",
            "leafWeightKg": _f(wheel_meta.get("shutterGlassWeightKg")),
        },
        glass_kg_total=glass_kg_total,
        shutter_count=shutters,
        system_type="sliding",
        qty=1.0,
    )
    sl = norm.get("sliding") or {}
    costing = sl.get("costing") if isinstance(sl.get("costing"), Mapping) else {}

    profile_lines: list[dict[str, Any]] = []
    cut_specs: list[dict[str, Any]] = []
    series_label = _str(
        line.get("sectionSeries")
        or product.get("id")
        or product.get("displayName")
        or "sliding"
    )
    # Track fill lengths
    for tf in (bom.get("trackFill") or {}).get("lines") or []:
        sec = tf.get("section") if isinstance(tf.get("section"), Mapping) else {}
        s = normalize_section(sec) if sec else {}
        length_mm = _f(tf.get("lengthMm"))
        role = _str(tf.get("role"))
        if length_mm <= 0:
            length_mm = H if "vertical" in role or "left" in role or "right" in role else W
            if "all" in role:
                length_mm = (2 * W + 2 * H) / max(_f(tf.get("qty"), 4), 1)
        q = _f(tf.get("qty"), 1)
        Lm = length_mm / 1000.0
        al_m = _section_rate_per_m(s)
        coat_m = _coating_per_m(s, colour=colour)
        al_amt = Lm * q * al_m
        coat_amt = Lm * q * coat_m
        amt = al_amt + coat_amt
        kg_m = _section_weight_kg_per_m(s)
        std_m = _section_std_m(s, fallback=5.85)
        display = _str(s.get("name")) or role or "Track"
        key = _section_pool_key(s, series=series_label, colour=colour, use="track")
        pcs = int(round(q)) if abs(q - round(q)) < 1e-6 else round(q, 4)
        for _ in range(max(int(round(q)), 1)):
            cut_specs.append({
                "lengthM": Lm,
                "key": key,
                "stdM": std_m,
                "aluminiumPerM": al_m,
                "coatingPerM": coat_m,
                "sectionName": display,
                "series": series_label,
                "colour": colour,
                "use": "track",
            })
        profile_lines.append({
            "category": "profile",
            "name": display,
            "catalogueName": display,
            "qty": q,
            "pcs": pcs,
            "lengthM": round(Lm, 4),
            "metres": round(Lm * q, 4),
            "unit": "RM",
            "unitRate": round(al_m + coat_m, 4),
            "aluminiumPerM": round(al_m, 4),
            "coatingPerM": round(coat_m, 4),
            "aluminiumAmount": round(al_amt, 2),
            "coatingAmount": round(coat_amt, 2),
            "amount": round(amt, 2),
            "rateUnit": _str(s.get("rateUnit") or "kg"),
            "use": "track",
            "sides": role.replace("_", " ") or "track",
            "stock": _section_stock_label(s, fallback_std_m=std_m),
            "stdLengthM": round(std_m, 4),
            "sectionKey": key,
            "weightKgPerM": round(kg_m, 4) if kg_m else None,
            "weightKg": round(kg_m * Lm * q, 3) if kg_m else None,
            "colour": colour,
            "remarks": role,
        })

    def _append_bom_profile_lines(raw_lines: Sequence[Any], *, default_use: str) -> None:
        for il in raw_lines or []:
            if not isinstance(il, Mapping):
                continue
            sec = il.get("section") if isinstance(il.get("section"), Mapping) else {}
            s = normalize_section(sec) if sec else {}
            q = _f(il.get("qty"), 1)
            Lm = _f(il.get("lengthM"))
            if Lm <= 0:
                Lm = H / 1000.0
            al_m = _section_rate_per_m(s)
            coat_m = _coating_per_m(s, colour=colour)
            al_amt_l = Lm * q * al_m
            coat_amt_l = Lm * q * coat_m
            kg_m = _section_weight_kg_per_m(s)
            std_m = _section_std_m(s, fallback=5.85)
            display = _str(il.get("catalogueName") or il.get("name") or s.get("name") or il.get("use") or default_use)
            key = _section_pool_key(s, series=series_label, colour=colour, use=_str(il.get("use") or default_use))
            for _ in range(max(int(round(q)), 1)):
                cut_specs.append({
                    "lengthM": Lm,
                    "key": key,
                    "stdM": std_m,
                    "aluminiumPerM": al_m,
                    "coatingPerM": coat_m,
                    "sectionName": display,
                    "series": series_label,
                    "colour": colour,
                    "use": _str(il.get("use") or default_use),
                })
            profile_lines.append({
                "category": "profile",
                "name": display,
                "catalogueName": display,
                "qty": q,
                "pcs": int(round(q)) if abs(q - round(q)) < 1e-6 else round(q, 4),
                "lengthM": round(Lm, 4),
                "metres": round(Lm * q, 4),
                "unit": "RM",
                "unitRate": round(al_m + coat_m, 4),
                "aluminiumPerM": round(al_m, 4),
                "coatingPerM": round(coat_m, 4),
                "aluminiumAmount": round(al_amt_l, 2),
                "coatingAmount": round(coat_amt_l, 2),
                "amount": round(al_amt_l + coat_amt_l, 2),
                "rateUnit": _str(s.get("rateUnit") or "kg"),
                "use": _str(il.get("use") or default_use),
                "sides": _str(il.get("sides") or il.get("use") or default_use),
                "stock": _section_stock_label(s, fallback_std_m=std_m),
                "stdLengthM": round(std_m, 4),
                "sectionKey": key,
                "weightKgPerM": round(kg_m, 4) if kg_m else None,
                "weightKg": round(kg_m * Lm * q, 3) if kg_m else None,
                "colour": colour,
                "remarks": _str(il.get("remarks")),
                "pcsVertical": s.get("pcsVertical"),
                "pcsHorizontal": s.get("pcsHorizontal"),
            })

    # Separate track rail (rules: keep rail apart from outer aluminium track)
    rail_pack = bom.get("trackRail") if isinstance(bom.get("trackRail"), Mapping) else {}
    _append_bom_profile_lines(rail_pack.get("lines") or [], default_use="track_rail")

    # Shutter frames from Excel V/H / V2 H2
    shutter_pack = bom.get("shutterFrames") if isinstance(bom.get("shutterFrames"), Mapping) else {}
    _append_bom_profile_lines(shutter_pack.get("lines") or [], default_use="shutter")

    # Interlocks (slim / renf / mesh-slim) + glass reducer 1/interlock
    inter_pack = bom.get("interlocks") if isinstance(bom.get("interlocks"), Mapping) else {}
    _append_bom_profile_lines(inter_pack.get("lines") or [], default_use="interlock")

    # 4-glass centre meeting vertical
    meeting_pack = bom.get("meeting") if isinstance(bom.get("meeting"), Mapping) else {}
    _append_bom_profile_lines(meeting_pack.get("lines") or [], default_use="meeting")

    # Member cuts (legacy wFactor/hFactor) — metres already billed
    for m in bom.get("members") or []:
        metres = _f(m.get("metres"))
        q = _f(m.get("qty") or metres)
        # Members may already convert rft; prefer metres × (kg rate) when weight present
        kg_m = _f(m.get("weightKgPerM"))
        rate_unit = _str(m.get("rateUnit") or "m").lower()
        raw_rate = _f(m.get("unitRate") or m.get("ratePerM") or m.get("rate"))
        if rate_unit == "kg" and kg_m > 0 and metres > 0:
            al_m = raw_rate * kg_m
            bill_m = metres
        elif _str(m.get("unit") or "").upper() == "RFT" and metres > 0:
            al_m = raw_rate / 0.3048
            bill_m = metres
        else:
            al_m = raw_rate
            bill_m = metres if metres > 0 else q
        al_amt = bill_m * al_m
        name = _str(m.get("name"))
        key = remnant_key(series=series_label, section=name or "member", colour=colour)
        if bill_m > 0:
            cut_specs.append({
                "lengthM": bill_m,
                "key": key,
                "stdM": 5.85,
                "aluminiumPerM": al_m,
                "coatingPerM": 0.0,
                "sectionName": name,
                "series": series_label,
                "colour": colour,
                "use": "member",
            })
        profile_lines.append({
            "category": "profile",
            "name": name,
            "catalogueName": name,
            "qty": q,
            "pcs": 1,
            "lengthM": round(bill_m, 4) if bill_m else None,
            "metres": round(bill_m, 4) if bill_m else None,
            "unit": _str(m.get("unit") or "RM"),
            "unitRate": round(al_m, 4),
            "aluminiumPerM": round(al_m, 4),
            "coatingPerM": 0.0,
            "aluminiumAmount": round(al_amt, 2),
            "coatingAmount": 0.0,
            "amount": round(al_amt, 2),
            "weightKgPerM": kg_m or None,
            "colour": colour,
            "sectionKey": key,
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
                "colour": colour,
            })

    hw_amt = 0.0
    hw_lines = []
    for h in bom.get("hardware") or []:
        q = _f(h.get("qty"))
        r = _f(h.get("unitRate") or h.get("rate"))
        amt = q * r
        hw_amt += amt
        brand = ""
        try:
            from WEOS.factory.hardware_brands import resolve_hardware_brand
            brand = resolve_hardware_brand(h, brand=h.get("brand"), origin=h.get("origin"), name=h.get("name"))
        except Exception:
            brand = _str(h.get("brand"))
        hw_lines.append({
            "category": "hardware",
            "name": _str(h.get("name")),
            "catalogueName": _str(h.get("name")),
            "brand": brand,
            "qty": q,
            "unit": _str(h.get("unit") or "PC"),
            "unitRate": r,
            "amount": round(amt, 2),
        })

    glass = _glass_cost(line, width_mm=W, height_mm=H, qty=1.0)
    glass_amt = _f(glass.get("amount"))
    mesh_pack = _mesh_fabric_pack(line)
    mesh_amt = _f(mesh_pack.get("meshCost"))
    area_sft = (W * H / 1_000_000.0) * 10.7639
    from WEOS.factory.commercial_defaults import (
        coating_multiplier_for_colour,
        default_coating_brand,
        finish_family_for_colour,
        installation_per_sft,
        labour_per_sft,
    )

    labour_rate = labour_per_sft(costing.get("labourPerSft"))
    labour_amt = area_sft * labour_rate
    install_rate = installation_per_sft(costing.get("installationPerSft") or costing.get("installPerSft"))
    install_amt = area_sft * install_rate
    reuse = bool(costing.get("projectWastageReuse", True))
    remnant_pool: dict[str, list[float]] = {}
    if isinstance(line.get("_remnantPool"), dict):
        remnant_pool = {str(k): list(v) for k, v in line["_remnantPool"].items() if isinstance(v, list)}
    # Recover zero-Al cuts when weight exists but rate was missing/0 (stale Excel rows).
    DEFAULT_AL_RATE_KG = 450.0
    DEFAULT_COAT_RFT = 22.0
    for spec in cut_specs:
        if not isinstance(spec, dict):
            continue
        if _f(spec.get("aluminiumPerM")) <= 0:
            kg_m = _f(spec.get("weightKgPerM"))
            if kg_m > 0:
                spec["aluminiumPerM"] = DEFAULT_AL_RATE_KG * kg_m
        if _f(spec.get("coatingPerM")) <= 0 and _f(spec.get("lengthM")) > 0:
            # Only fill coat when this cut looks like a real profile (has weight or al)
            if _f(spec.get("weightKgPerM")) > 0 or _f(spec.get("aluminiumPerM")) > 0:
                try:
                    from WEOS.factory.commercial_defaults import coating_multiplier_for_colour as _cm

                    mult = float(_cm(colour) or 1.0)
                except Exception:
                    mult = 1.0
                spec["coatingPerM"] = (DEFAULT_COAT_RFT / 0.3048) * max(mult, 0.0)
    for pl in profile_lines:
        if not isinstance(pl, dict):
            continue
        if _f(pl.get("aluminiumPerM")) <= 0 and _f(pl.get("weightKgPerM")) > 0:
            pl["aluminiumPerM"] = DEFAULT_AL_RATE_KG * _f(pl.get("weightKgPerM"))
            Lm = _f(pl.get("lengthM") or pl.get("metres"))
            q = _f(pl.get("qty"), 1)
            pl["aluminiumAmount"] = round(Lm * q * _f(pl["aluminiumPerM"]), 2)
        if _f(pl.get("coatingPerM")) <= 0 and (
            _f(pl.get("weightKgPerM")) > 0 or _f(pl.get("aluminiumPerM")) > 0
        ):
            try:
                from WEOS.factory.commercial_defaults import coating_multiplier_for_colour as _cm

                mult = float(_cm(colour) or 1.0)
            except Exception:
                mult = 1.0
            pl["coatingPerM"] = (DEFAULT_COAT_RFT / 0.3048) * max(mult, 0.0)
            Lm = _f(pl.get("lengthM") or pl.get("metres"))
            q = _f(pl.get("qty"), 1)
            pl["coatingAmount"] = round(Lm * q * _f(pl["coatingPerM"]), 2)
        if _f(pl.get("amount")) <= 0:
            pl["amount"] = round(_f(pl.get("aluminiumAmount")) + _f(pl.get("coatingAmount")), 2)

    coat_full = True
    if costing.get("coatFullBars") is False or costing.get("coatCutsOnly") is True:
        coat_full = False
    nest = nest_cuts_by_section(
        cut_specs,
        remnant_pool=remnant_pool,
        reuse=reuse,
        default_std_m=5.85,
        coat_full_bars=coat_full,
    )
    al_amt = _f(nest.get("aluminiumCost"))
    coat_amt = _f(nest.get("coatingCost"))
    wastage_cost = _f(nest.get("wastageCost"))  # 0 — balance already in purchased Al
    profile_net = al_amt + coat_amt
    profile_amt = profile_net
    waste = nest.get("wastage") or {}

    material_sub = profile_amt + hw_amt + glass_amt + mesh_amt
    cost_before = material_sub + labour_amt + install_amt
    profit_pct = _f(costing.get("profitPercent"))
    profit_amt = cost_before * (profit_pct / 100.0) if profit_pct else 0.0
    unit_total = cost_before + profit_amt
    engine = "live" if (profile_amt > 0 or hw_amt > 0 or mesh_amt > 0 or labour_amt > 0 or install_amt > 0) else "stub"
    suggested = round(unit_total / area_sft, 1) if area_sft > 0 else None
    try:
        coat_mult = coating_multiplier_for_colour(colour)
        finish_family = finish_family_for_colour(colour)
        coat_brand = default_coating_brand()
    except Exception:
        coat_mult = 1.0
        finish_family = "plain"
        coat_brand = ""
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
        "coatingFinishFamily": finish_family,
        "coatingBrand": coat_brand,
        "colour": colour,
        "materialCost": round(material_sub * qty, 2),
        "aluminiumCost": round(al_amt * qty, 2),
        "coatingCost": round(coat_amt * qty, 2),
        "profileCost": round(profile_amt * qty, 2),
        "wastageCost": round(wastage_cost * qty, 2),
        "hardwareCost": round(hw_amt * qty, 2),
        "glassCost": round(glass_amt * qty, 2),
        "meshCost": round(mesh_amt * qty, 2),
        "wastage": waste,
        "remnants": nest.get("remnantsCreated") or [],
        "remnantPool": nest.get("remnantPool") or {},
        "interlocks": inter_pack.get("assignment") or {},
        "profiles": profile_lines,
        "hardware": hw_lines,
        "glass": glass,
        "mesh": mesh_pack.get("mesh"),
        "meshLines": mesh_pack.get("meshLines") or [],
        "shutterGlassWeightKg": wheel_meta.get("shutterGlassWeightKg"),
        "wheelOptions": wheel_meta.get("wheelOptions") or [],
        "meshWheelOptions": wheel_meta.get("meshWheelOptions") or [],
        "selectedWheel": wheel_meta.get("selectedWheel"),
        "selectedMeshWheel": wheel_meta.get("selectedMeshWheel"),
        "suggestedSellRate": suggested,
        "costPerUnit": suggested,  # actual cost ₹ / sale unit (sft) before cart profit %
        "saleUnit": "sqft",
        "areaSft": round(area_sft, 3),
        "nestGroups": nest.get("groups") or [],
        "purchasedMetres": nest.get("purchasedMetres"),
        "balanceMetres": nest.get("balanceMetres"),
        "balanceCost": nest.get("balanceCost"),
        "cutSpecs": cut_specs,
        "profileFamily": "sliding",
        "breakdown": {
            "aluminium": round(al_amt, 2),
            "coating": round(coat_amt, 2),
            "profiles": round(profile_net, 2),
            "wastage": round(wastage_cost, 2),
            "balance": round(_f(nest.get("balanceCost")), 2),
            "hardware": round(hw_amt, 2),
            "glass": round(glass_amt, 2),
            "mesh": round(mesh_amt, 2),
            "labour": round(labour_amt, 2),
            "installation": round(install_amt, 2),
            "profit": round(profit_amt, 2),
        },
    }


def compute_design_cost(
    line: Mapping[str, Any],
    *,
    product: Mapping[str, Any] | None = None,
    remnant_pool: MutableMapping[str, list[float]] | None = None,
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
    # Prefer Excel series product when cart product is an engine + sectionSeries
    payload = dict(line) if isinstance(line, Mapping) else {}
    series_id = _str(
        payload.get("sectionSeries")
        or (payload.get("options") or {}).get("sectionSeries")
        or product.get("sectionSeries")
    )
    if series_id and series_id != _str(product.get("id")):
        try:
            from WEOS.factory.product_loader import load_product

            series_prod = load_product(series_id, strict=False)
            if isinstance(series_prod.get("setup"), Mapping) and setup_has_profile_rates(series_prod["setup"]):
                product = series_prod
        except Exception:
            pass
    setup = resolve_costing_setup(payload, product=product)
    if remnant_pool is not None:
        payload["_remnantPool"] = remnant_pool
    system = _str(
        payload.get("system")
        or (payload.get("options") or {}).get("system")
        or (setup or {}).get("type")
        or product.get("productType")
        or ""
    ).lower()
    if "casement" in system or "openable" in system or (setup and _str(setup.get("type")) == "casement"):
        return compute_casement_design_cost(payload, product=product, setup=setup)
    if "sliding" in system or (setup and _str(setup.get("type")) == "sliding"):
        return compute_sliding_design_cost(payload, product=product, setup=setup)
    if payload.get("casementLayout") or (payload.get("options") or {}).get("casementLayout"):
        return compute_casement_design_cost(payload, product=product, setup=setup)
    return {"ok": False, "costEngine": "stub", "reason": "unsupported", "total": 0.0}


def _line_profile_family(line: Mapping[str, Any], cost: Mapping[str, Any] | None = None) -> str:
    """sliding | casement — wastage pools stay within family (rulebook v2 §4)."""
    fam = _str((cost or {}).get("profileFamily") or (cost or {}).get("system")).lower()
    if "casement" in fam or "openable" in fam:
        return "casement"
    if "sliding" in fam:
        return "sliding"
    system = _str(
        line.get("system")
        or (line.get("options") or {}).get("system")
        or ""
    ).lower()
    if "casement" in system or "openable" in system:
        return "casement"
    if "sliding" in system:
        return "sliding"
    if line.get("casementLayout") or (line.get("options") or {}).get("casementLayout"):
        return "casement"
    return fam or "sliding"


def _expand_cut_specs_for_qty(
    specs: Sequence[Mapping[str, Any]],
    *,
    qty: float,
    line_id: Any,
    family: str,
) -> list[dict[str, Any]]:
    """Replicate one-window cut list by line qty; tag window + family."""
    q = max(int(round(_f(qty, 1.0))), 1)
    out: list[dict[str, Any]] = []
    for spec in specs or []:
        if not isinstance(spec, Mapping) or _f(spec.get("lengthM")) <= 0:
            continue
        for copy_i in range(q):
            row = dict(spec)
            row["lineId"] = line_id
            row["profileFamily"] = family
            row["qtyCopy"] = copy_i
            out.append(row)
    return out


def _used_profile_costs(specs: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Net used profile material + coating from cut lengths (before nesting)."""
    used_al = 0.0
    used_coat = 0.0
    used_m = 0.0
    for s in specs or []:
        if not isinstance(s, Mapping):
            continue
        Lm = _f(s.get("lengthM"))
        if Lm <= 0:
            continue
        used_al += Lm * _f(s.get("aluminiumPerM"))
        used_coat += Lm * _f(s.get("coatingPerM"))
        used_m += Lm
    return {
        "usedAluminium": round(used_al, 4),
        "usedCoating": round(used_coat, 4),
        "usedMetres": round(used_m, 4),
    }


def allocate_family_wastage(
    line_used: Sequence[Mapping[str, Any]],
    family_wastage: Mapping[str, Mapping[str, float]],
) -> dict[str, dict[str, float]]:
    """Distribute family closing wastage ₹ by used-profile material cost share.

    window share = family_wastage × window_used / family_used_total.
    Rounding remainder lands on the last applicable line. Zero family used cost
    with leftover allocation stays ``unallocated``.
    """
    by_line: dict[str, dict[str, float]] = {}
    unallocated: dict[str, float] = {"aluminium": 0.0, "coating": 0.0}
    families = sorted({_str(r.get("family") or "sliding") for r in line_used})
    for fam in families:
        members = [r for r in line_used if _str(r.get("family") or "sliding") == fam]
        waste = family_wastage.get(fam) if isinstance(family_wastage.get(fam), Mapping) else {}
        waste_al = _f((waste or {}).get("aluminium"))
        waste_coat = _f((waste or {}).get("coating"))
        total_used = sum(_f(m.get("usedAluminium")) for m in members)
        if (waste_al > 1e-9 or waste_coat > 1e-9) and total_used <= 1e-9:
            unallocated["aluminium"] += waste_al
            unallocated["coating"] += waste_coat
            for m in members:
                lid = _str(m.get("lineId"))
                by_line[lid] = {"aluminium": 0.0, "coating": 0.0, "unallocated": True}
            continue
        assigned_al = 0.0
        assigned_coat = 0.0
        for i, m in enumerate(members):
            lid = _str(m.get("lineId"))
            share = (_f(m.get("usedAluminium")) / total_used) if total_used > 0 else 0.0
            if i == len(members) - 1:
                al_share = round(waste_al - assigned_al, 2)
                coat_share = round(waste_coat - assigned_coat, 2)
            else:
                al_share = round(waste_al * share, 2)
                coat_share = round(waste_coat * share, 2)
                assigned_al += al_share
                assigned_coat += coat_share
            by_line[lid] = {
                "aluminium": al_share,
                "coating": coat_share,
                "share": round(share, 6),
                "unallocated": False,
            }
    return {
        "byLine": by_line,
        "unallocated": {k: round(v, 2) for k, v in unallocated.items()},
    }


def _purchase_list_from_nest(nest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Full bars to buy from a commercial/factory nest (rulebook v2 §2)."""
    rows: list[dict[str, Any]] = []
    for g in nest.get("groups") or []:
        if not isinstance(g, Mapping):
            continue
        pack = g.get("pack") if isinstance(g.get("pack"), Mapping) else {}
        bars = int(pack.get("bars") or g.get("bars") or 0)
        if bars <= 0:
            continue
        std_m = _f(pack.get("stdLengthM"))
        rows.append({
            "key": _str(g.get("key")),
            "sectionName": _str(g.get("sectionName") or g.get("key")),
            "bars": bars,
            "stdLengthM": round(std_m, 4),
            "stdLengthFt": round(std_m / 0.3048, 2) if std_m else None,
            "purchasedMetres": round(_f(pack.get("purchasedMetres")), 4),
            "aluminiumCost": round(_f(g.get("aluminiumCost")), 2),
            "coatingCost": round(_f(g.get("coatingCost")), 2),
            "balanceMetres": round(_f(g.get("balanceMetres")), 4),
            "balanceCost": round(_f(g.get("balanceCost")), 2),
            "coatFullBars": bool(g.get("coatFullBars")),
        })
    return rows


def compute_quote_design_costs(
    lines: Sequence[Mapping[str, Any]],
    *,
    persist_remnants: bool = False,
    use_approved_stock: bool = False,
    source_quote: str | None = None,
    source_version: int | str | None = None,
) -> dict[str, Any]:
    """Quote-wide commercial nest + family wastage allocation (rulebook v2).

    1. Cost each window alone for BOM / glass / HW (cut list source).
    2. Nest all cuts per family with same-quote offcut reuse (threshold 0 —
       any leftover that fits is reused; final balance is closing wastage).
    3. Quote cost ignores approved old stock unless ``use_approved_stock``
       (factory cutting plan). Purchase list = new full bars after nesting.
    4. Allocate closing balance ₹ within each family by used-profile share.
    """
    results: list[dict[str, Any]] = []
    line_meta: list[dict[str, Any]] = []
    cuts_by_family: dict[str, list[dict[str, Any]]] = {"sliding": [], "casement": []}
    coat_full = True

    for raw in lines or []:
        if not isinstance(raw, Mapping) or raw.get("cancelled"):
            continue
        # Per-line nest is only a cut-list / BOM source; quote Al is rewritten below.
        cost = compute_design_cost(raw)
        line_id = raw.get("lineId") or raw.get("id") or f"L{len(line_meta)+1}"
        family = _line_profile_family(raw, cost if isinstance(cost, Mapping) else None)
        qty = max(_f(raw.get("qty") or raw.get("quantity"), 1.0), 1.0)
        specs = _expand_cut_specs_for_qty(
            (cost.get("cutSpecs") if isinstance(cost, Mapping) else None) or [],
            qty=qty,
            line_id=line_id,
            family=family,
        )
        used = _used_profile_costs(specs)
        if isinstance(cost, Mapping) and cost.get("ok"):
            # Prefer cut-only coating flag from nest if present
            if (cost.get("wastage") or {}).get("coatFullBars") is False:
                coat_full = False
        cuts_by_family.setdefault(family, []).extend(specs)
        line_meta.append({
            "lineId": line_id,
            "family": family,
            "qty": qty,
            "raw": raw,
            "cost": cost,
            "usedAluminium": used["usedAluminium"],
            "usedCoating": used["usedCoating"],
            "usedMetres": used["usedMetres"],
            "cutCount": len(specs),
        })

    family_nests: dict[str, dict[str, Any]] = {}
    family_wastage: dict[str, dict[str, float]] = {}
    purchase_list: list[dict[str, Any]] = []
    all_remnants: list[dict[str, Any]] = []
    remnant_pool_out: dict[str, list[float]] = {}

    for fam, fam_cuts in cuts_by_family.items():
        if not fam_cuts:
            continue
        # Quote costing: never seed approved stock. Factory plan may.
        seed_pool: dict[str, list[float]] = {}
        if use_approved_stock:
            try:
                from WEOS.factory.remnant_stock import leftovers_for_nesting

                for spec in fam_cuts:
                    key = _str(spec.get("key"))
                    if not key or key in seed_pool:
                        continue
                    leftovers = leftovers_for_nesting(
                        series=spec.get("series"),
                        section=spec.get("sectionName"),
                        colour=spec.get("colour"),
                    )
                    seed_pool[key] = [
                        _f(x.get("lengthMm")) / 1000.0
                        for x in leftovers
                        if _f(x.get("lengthMm")) > 0
                    ]
            except Exception:
                seed_pool = {}
        nest = nest_cuts_by_section(
            fam_cuts,
            remnant_pool=seed_pool,
            reuse=True,
            # v2 §1: in-quote reuse has no fixed leftover floor
            wastage_threshold_m=0.0,
            default_std_m=5.85 if fam == "sliding" else 3.0,
            coat_full_bars=coat_full,
        )
        family_nests[fam] = nest
        bal_al = _f(nest.get("balanceCost"))
        # Full-bar coating: include coating on balance once; cut-only → 0.
        bal_coat = 0.0
        if coat_full:
            for g in nest.get("groups") or []:
                if not isinstance(g, Mapping):
                    continue
                bal_coat += _f(g.get("balanceMetres")) * _f(g.get("coatingPerM"))
        family_wastage[fam] = {
            "aluminium": round(bal_al, 2),
            "coating": round(bal_coat, 2),
            "balanceMetres": round(_f(nest.get("balanceMetres")), 4),
        }
        for row in _purchase_list_from_nest(nest):
            row["profileFamily"] = fam
            purchase_list.append(row)
        for r in nest.get("remnantsCreated") or []:
            if isinstance(r, Mapping):
                piece = dict(r)
                piece["profileFamily"] = fam
                all_remnants.append(piece)
        for k, v in (nest.get("remnantPool") or {}).items():
            if isinstance(v, list):
                remnant_pool_out.setdefault(str(k), []).extend(_f(x) for x in v)

    alloc = allocate_family_wastage(
        [
            {
                "lineId": m["lineId"],
                "family": m["family"],
                "usedAluminium": m["usedAluminium"],
            }
            for m in line_meta
        ],
        family_wastage,
    )
    by_line_waste = alloc.get("byLine") if isinstance(alloc.get("byLine"), Mapping) else {}

    totals = {
        "aluminium": 0.0,
        "coating": 0.0,
        "glass": 0.0,
        "hardware": 0.0,
        "labour": 0.0,
        "installation": 0.0,
        "wastage": 0.0,
        "total": 0.0,
        "usedAluminium": 0.0,
        "allocatedWastage": 0.0,
    }

    for m in line_meta:
        cost = dict(m["cost"]) if isinstance(m["cost"], Mapping) else {"ok": False}
        lid = _str(m["lineId"])
        share = by_line_waste.get(lid) if isinstance(by_line_waste.get(lid), Mapping) else {}
        waste_al = _f((share or {}).get("aluminium"))
        waste_coat = _f((share or {}).get("coating"))
        used_al = _f(m["usedAluminium"])
        used_coat = _f(m["usedCoating"])
        # Commercial Al/coat = used + allocated closing balance (purchase breakup).
        new_al = used_al + waste_al
        new_coat = used_coat + waste_coat
        # Rebuild unit economics from replaced profile costs.
        qty = max(_f(m["qty"]), 1.0)
        hw = _f(cost.get("hardwareCost"))
        glass = _f(cost.get("glassCost"))
        mesh = _f(cost.get("meshCost"))
        labour = _f(cost.get("labourAmount"))
        install = _f(cost.get("installationAmount"))
        profit_pct = _f(cost.get("profitPercent"))
        # design_cost stores qty-multiplied component costs — normalize to unit then reapply.
        unit_al = new_al / qty
        unit_coat = new_coat / qty
        unit_hw = hw / qty
        unit_glass = glass / qty
        unit_mesh = mesh / qty
        unit_labour = labour / qty
        unit_install = install / qty
        material_sub = unit_al + unit_coat + unit_hw + unit_glass + unit_mesh
        cost_before = material_sub + unit_labour + unit_install
        profit_amt = cost_before * (profit_pct / 100.0) if profit_pct else 0.0
        unit_total = cost_before + profit_amt
        area_sft = _f(cost.get("areaSft"))
        sale_unit = _str(cost.get("saleUnit") or "sqft")
        if sale_unit == "rft":
            suggested = cost.get("suggestedSellRate")
        else:
            suggested = round(unit_total / area_sft, 1) if area_sft > 0 else cost.get("suggestedSellRate")

        br = dict(cost.get("breakdown") or {}) if isinstance(cost.get("breakdown"), Mapping) else {}
        br["aluminium"] = round(unit_al, 2)
        br["coating"] = round(unit_coat, 2)
        br["profiles"] = round(unit_al + unit_coat, 2)
        br["wastage"] = round(waste_al / qty, 2)
        br["balance"] = round(waste_al / qty, 2)
        br["allocatedWastage"] = round((waste_al + waste_coat) / qty, 2)
        br["usedAluminium"] = round(used_al / qty, 2)
        br["profit"] = round(profit_amt, 2)

        cost["aluminiumCost"] = round(new_al, 2)
        cost["coatingCost"] = round(new_coat, 2)
        cost["profileCost"] = round(new_al + new_coat, 2)
        cost["wastageCost"] = round(waste_al, 2)
        cost["allocatedWastageAluminium"] = round(waste_al, 2)
        cost["allocatedWastageCoating"] = round(waste_coat, 2)
        cost["usedAluminiumCost"] = round(used_al, 2)
        cost["usedCoatingCost"] = round(used_coat, 2)
        cost["materialCost"] = round(material_sub * qty, 2)
        cost["unitTotal"] = round(unit_total, 2)
        cost["total"] = round(unit_total * qty, 2)
        cost["perWindowCost"] = round(cost_before, 2)
        cost["profitAmount"] = round(profit_amt * qty, 2)
        cost["suggestedSellRate"] = suggested
        cost["costPerUnit"] = suggested
        cost["breakdown"] = br
        cost["quoteNestFamily"] = m["family"]
        cost["wastageShare"] = share
        cost["balanceMetres"] = family_wastage.get(m["family"], {}).get("balanceMetres")
        cost["balanceCost"] = round(waste_al, 2)
        fam_nest = family_nests.get(m["family"]) or {}
        cost["purchasedMetres"] = fam_nest.get("purchasedMetres")
        cost["nestGroups"] = fam_nest.get("groups") or []
        cost["wastage"] = fam_nest.get("wastage") or cost.get("wastage")
        cost["remnants"] = [
            r for r in all_remnants
            if isinstance(r, Mapping) and _str(r.get("profileFamily")) == m["family"]
        ]
        cost["remnantPool"] = fam_nest.get("remnantPool") or {}

        results.append({"lineId": m["lineId"], "cost": cost, "family": m["family"]})
        if cost.get("ok"):
            totals["aluminium"] += _f(cost.get("aluminiumCost"))
            totals["coating"] += _f(cost.get("coatingCost"))
            totals["glass"] += _f(cost.get("glassCost"))
            totals["hardware"] += _f(cost.get("hardwareCost"))
            totals["labour"] += _f(cost.get("labourAmount"))
            totals["installation"] += _f(cost.get("installationAmount"))
            totals["wastage"] += waste_al
            totals["usedAluminium"] += used_al
            totals["allocatedWastage"] += waste_al + waste_coat
            totals["total"] += _f(cost.get("total"))

    # Stock: only >~3 ft pieces; quote costing never posts theoretical unused of unused bars.
    stock_remnants = [
        r for r in all_remnants
        if isinstance(r, Mapping) and is_reusable_remnant_m(_f(r.get("lengthM")))
    ]
    for r in stock_remnants:
        if source_quote:
            r["sourceQuote"] = _str(source_quote)
        if source_version is not None:
            r["sourceVersion"] = source_version
        r["source"] = _str(r.get("source") or "quote_approval")

    persisted = None
    if persist_remnants and stock_remnants:
        try:
            persisted = merge_remnants_into_stock(
                stock_remnants,
                source_quote=source_quote,
                source_version=source_version,
            )
        except TypeError:
            # Older signature without idempotency kwargs
            try:
                persisted = merge_remnants_into_stock(stock_remnants)
            except Exception as exc:
                persisted = {"ok": False, "error": str(exc)}
        except Exception as exc:
            persisted = {"ok": False, "error": str(exc)}

    purch_m = sum(_f(n.get("purchasedMetres")) for n in family_nests.values())
    purch_al = sum(_f(n.get("aluminiumCost")) for n in family_nests.values())
    purch_coat = sum(_f(n.get("coatingCost")) for n in family_nests.values())

    return {
        "ok": True,
        "rulebook": "v2",
        "lines": results,
        "totals": {k: round(v, 2) for k, v in totals.items()},
        "familyNests": {k: {
            "purchasedMetres": v.get("purchasedMetres"),
            "balanceMetres": v.get("balanceMetres"),
            "balanceCost": v.get("balanceCost"),
            "aluminiumCost": v.get("aluminiumCost"),
            "coatingCost": v.get("coatingCost"),
            "wastage": v.get("wastage"),
            "groups": v.get("groups"),
        } for k, v in family_nests.items()},
        "familyWastage": family_wastage,
        "wastageAllocation": alloc,
        "purchaseList": purchase_list,
        "purchaseSummary": {
            "purchasedMetres": round(purch_m, 4),
            "aluminiumCost": round(purch_al, 2),
            "coatingCost": round(purch_coat, 2),
            "bars": sum(int(r.get("bars") or 0) for r in purchase_list),
        },
        "remnantPool": {k: [round(_f(x), 4) for x in v] for k, v in remnant_pool_out.items()},
        "remnants": stock_remnants,
        "closingRemnants": all_remnants,
        "persistedStock": persisted,
        "useApprovedStock": bool(use_approved_stock),
        "coatFullBars": bool(coat_full),
        "wastageThresholdFt": 0.0,  # in-quote commercial reuse floor
        "stockWastageThresholdFt": WASTAGE_MAX_REUSABLE_FT,
        "notes": (
            "Rulebook v2: quote-wide nest per family, same-quote offcut reuse, "
            "new-material quote cost (old stock ignored"
            + (" unless factory use_approved_stock)." if use_approved_stock else ").")
            + " Closing balance allocated by used-profile share within family."
            + (" Stock remnants >3 ft merged into inventory.json." if persist_remnants else "")
        ),
    }
