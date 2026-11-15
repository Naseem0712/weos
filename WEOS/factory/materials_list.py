"""Materials + hardware list for products already on a quote.

Uses catalogue / Series Setup display names (not internal ids). Includes
customer name, date, and colour. Suitable for printable HTML or PDF attach.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence


def _str(v: Any) -> str:
    return str(v or "").strip()


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _glass_catalogue_name(line: Mapping[str, Any]) -> str:
    name = _str(line.get("glassName") or line.get("glassLabel"))
    if name and not name.startswith("5mm_") and "mm_" not in name.replace(" ", ""):
        # Prefer human label already on the line
        pass
    gid = _str(line.get("glass"))
    try:
        from WEOS.factory.glass_catalogue import get_glass
        from WEOS.factory.quote_item_snapshot import get_glass_snapshot, glass_display_label

        snap_g = get_glass_snapshot(line)
        label = glass_display_label(snap_g) if snap_g else ""
        if label:
            return _str(label)
        g = get_glass(gid) if gid else None
        if isinstance(g, Mapping):
            return _str(g.get("name") or g.get("label") or g.get("displayName") or gid)
    except Exception:
        pass
    # Snapshot
    snap = line.get("itemSnapshot") or line.get("snapshot") or {}
    if isinstance(snap, Mapping):
        gn = _str(snap.get("glass_name_snapshot") or snap.get("glassName"))
        if gn:
            return gn
    return name or gid or "—"


def _colour_label(line: Mapping[str, Any]) -> str:
    c = _str(line.get("colour") or line.get("color") or (line.get("options") or {}).get("colour"))
    if not c:
        return "—"
    return c.replace("_", " ").title()


def _product_label(line: Mapping[str, Any]) -> str:
    return (
        _str(line.get("displayName") or line.get("description") or line.get("product"))
        or "Product"
    )


def materials_rows_for_line(line: Mapping[str, Any]) -> dict[str, Any]:
    """One quote line → materials, hardware, glass with catalogue names."""
    from WEOS.factory.design_cost import compute_design_cost
    from WEOS.factory.quote_item_snapshot import product_id_of

    product: dict[str, Any] = {}
    pid = product_id_of(line) if line else None
    if pid:
        try:
            from WEOS.factory.product_loader import load_product

            product = load_product(pid, strict=False)
        except Exception:
            product = {"id": pid, "displayName": _product_label(line)}

    design = compute_design_cost(line, product=product)
    materials: list[dict[str, Any]] = []
    hardware: list[dict[str, Any]] = []

    waste = design.get("wastage") if isinstance(design.get("wastage"), Mapping) else {}
    waste_m = _f(waste.get("wastageMetres"))
    waste_pct = _f(waste.get("wastagePercent"))
    stock_std = waste.get("stdLengthM")
    line_qty = max(_f(line.get("qty") or line.get("quantity"), 1.0), 1.0)

    colour_raw = _str(line.get("colour") or line.get("color") or (line.get("options") or {}).get("colour"))
    finish_family = _str(design.get("coatingFinishFamily") or "")
    coat_brand = _str(design.get("coatingBrand") or "")
    if not finish_family and colour_raw:
        try:
            from WEOS.factory.commercial_defaults import finish_family_for_colour, default_coating_brand
            finish_family = finish_family_for_colour(colour_raw)
            coat_brand = coat_brand or default_coating_brand()
        except Exception:
            finish_family = "plain"
    colour_detail = _colour_label(line)
    if finish_family:
        colour_detail = f"{colour_detail} · {finish_family}"
        if coat_brand:
            colour_detail = f"{colour_detail} · {coat_brand}"

    for p in design.get("profiles") or []:
        pcs = p.get("pcs")
        if pcs is None:
            pcs = p.get("qty")
        materials.append({
            "kind": "profile",
            "name": _str(p.get("catalogueName") or p.get("name")),
            "qty": p.get("qty"),
            "pcs": pcs,
            "unit": p.get("unit") or "RM",
            "lengthM": p.get("lengthM") or p.get("metres"),
            "cutLengthM": p.get("lengthM"),
            "sides": _str(p.get("sides") or p.get("remarks") or p.get("use") or ""),
            "use": _str(p.get("use") or ""),
            "stock": _str(p.get("stock")) or (f"{_f(stock_std):g} m stock" if stock_std else ""),
            "weightKg": p.get("weightKg"),
            "weightKgPerM": p.get("weightKgPerM"),
            "aluminiumPerM": p.get("aluminiumPerM"),
            "coatingPerM": p.get("coatingPerM"),
            "aluminiumAmount": p.get("aluminiumAmount"),
            "coatingAmount": p.get("coatingAmount"),
            "amount": p.get("amount"),
            "rate": p.get("rate"),
            "rateUnit": p.get("rateUnit"),
            "colour": _str(p.get("colour") or colour_raw) or colour_detail,
            "finishFamily": finish_family or None,
            "coatingBrand": coat_brand or None,
            "wastageM": waste_m if waste_m > 0 else None,
            "wastagePercent": waste_pct if waste_pct > 0 else None,
            "remarks": p.get("remarks") or p.get("use") or "",
        })
    # Also surface setup section names when design engine stubbed
    if not materials and isinstance(product.get("setup"), Mapping):
        try:
            from WEOS.factory.product_setup import flatten_setup_sections

            for sec in flatten_setup_sections(product["setup"]):
                nm = _str(sec.get("name"))
                if nm:
                    std_mm = _f(sec.get("stdLengthMm"))
                    stock = f"{std_mm:g} mm stock" if std_mm else _str(sec.get("stdLength") or "")
                    materials.append({
                        "kind": "profile",
                        "name": nm,
                        "qty": 1,
                        "pcs": 1,
                        "unit": "section",
                        "sides": _str(sec.get("use")),
                        "stock": stock or "—",
                        "weightKgPerM": sec.get("weightKgPerM"),
                        "remarks": _str(sec.get("use")),
                    })
        except Exception:
            pass

    def _hw_display(h: Mapping[str, Any]) -> tuple[str, str]:
        try:
            from WEOS.factory.hardware_brands import resolve_hardware_brand

            brand = resolve_hardware_brand(
                h,
                brand=h.get("brand"),
                origin=h.get("origin") or h.get("hardwareOrigin"),
                name=h.get("catalogueName") or h.get("name") or h.get("description"),
            )
        except Exception:
            brand = _str(h.get("brand"))
        nm = _str(h.get("catalogueName") or h.get("name") or h.get("description"))
        if brand and brand.lower() not in nm.lower():
            nm = f"{brand} {nm}".strip()
        return nm, brand

    for h in design.get("hardware") or []:
        if not isinstance(h, Mapping):
            continue
        nm, brand = _hw_display(h)
        hardware.append({
            "kind": "hardware",
            "name": nm,
            "brand": brand,
            "qty": h.get("qty"),
            "pcs": h.get("qty"),
            "unit": h.get("unit") or "PC",
            "unitRate": h.get("unitRate") if h.get("unitRate") is not None else h.get("rate"),
            "amount": h.get("amount"),
            "remarks": h.get("remarks") or "",
        })

    # Mesh fabric (in-track standard/premium · rolling · collapsible)
    mesh_lines = list(design.get("meshLines") or [])
    if not mesh_lines:
        try:
            from WEOS.factory.mesh_addon import mesh_fabric_for_line, mesh_fabric_material_row

            fabric = mesh_fabric_for_line(line)
            if fabric:
                mesh_lines = [mesh_fabric_material_row(fabric)]
        except Exception:
            mesh_lines = []
    for m in mesh_lines:
        if not isinstance(m, Mapping):
            continue
        materials.append({
            "kind": "mesh",
            "name": _str(m.get("catalogueName") or m.get("name") or "Mesh"),
            "qty": m.get("qty") or m.get("areaSft"),
            "pcs": m.get("pcs") or 1,
            "unit": m.get("unit") or "sft",
            "areaSft": m.get("areaSft") or m.get("qty"),
            "widthMm": m.get("widthMm"),
            "heightMm": m.get("heightMm"),
            "unitRate": m.get("unitRate") if m.get("unitRate") is not None else m.get("rate"),
            "amount": m.get("amount"),
            "sides": _str(m.get("formula") or m.get("type") or ""),
            "use": "mesh_fabric",
            "stock": "—",
            "remarks": _str(m.get("remarks") or m.get("formula") or ""),
        })
    for h in line.get("hardware") or []:
        if isinstance(h, Mapping):
            nm, brand = _hw_display(h)
            if nm and not any(x["name"] == nm for x in hardware):
                hardware.append({
                    "kind": "hardware",
                    "name": nm,
                    "brand": brand,
                    "qty": h.get("qty") or h.get("quantity"),
                    "pcs": h.get("qty") or h.get("quantity"),
                    "unit": h.get("unit") or "PC",
                    "unitRate": h.get("unitRate") if h.get("unitRate") is not None else h.get("rate"),
                    "amount": h.get("amount"),
                    "remarks": "",
                })

    glass_name = _glass_catalogue_name(line)
    g = design.get("glass") if isinstance(design.get("glass"), Mapping) else {}
    glass_row = {
        "kind": "glass",
        "name": _str(g.get("catalogueName") or g.get("packName") or g.get("name") or glass_name),
        "packName": _str(g.get("packName") or g.get("catalogueName") or g.get("name") or glass_name),
        "qty": g.get("qty") or 1,
        "pcs": g.get("qty") or 1,
        "unit": "sft",
        "areaSft": g.get("areaSft"),
        "widthMm": g.get("widthMm") or line.get("width"),
        "heightMm": g.get("heightMm") or line.get("height"),
        "sizeLabel": g.get("sizeLabel") or (
            f"{line.get('width')}×{line.get('height')} mm"
            if line.get("width") and line.get("height") else ""
        ),
        "thicknessMm": g.get("thicknessMm"),
        "colour": g.get("colour"),
        "kindGlass": g.get("kind"),
        "unitRate": g.get("unitRate"),
        "amount": g.get("amount"),
        "remarks": "",
    }

    # Fixed partition series names
    parts = line.get("partitions") or (line.get("options") or {}).get("partitions") or []
    for p in parts if isinstance(parts, (list, tuple)) else []:
        if not isinstance(p, Mapping):
            continue
        series = _str(p.get("profileSeries") or p.get("sectionSeries") or p.get("fixedSeries"))
        if series:
            side = _str(p.get("side"))
            materials.append({
                "kind": "profile",
                "name": series,
                "qty": 1,
                "pcs": 1,
                "unit": "fix",
                "sides": f"{side} fix" if side else "fix",
                "stock": "—",
                "remarks": f"{side} fix {_f(p.get('sizeMm'))} mm",
            })

    return {
        "lineId": line.get("lineId"),
        "serial": line.get("serial"),
        "product": _product_label(line),
        "productId": pid,
        "width": line.get("width"),
        "height": line.get("height"),
        "qty": line_qty,
        "colour": colour_detail,
        "colourId": colour_raw,
        "finishFamily": finish_family or None,
        "coatingBrand": coat_brand or None,
        "location": _str(line.get("locationName") or line.get("positionName") or ""),
        "materials": materials,
        "hardware": hardware,
        "glass": glass_row,
        "interlocks": design.get("interlocks") if isinstance(design.get("interlocks"), Mapping) else None,
        "wastageM": waste_m if waste_m > 0 else None,
        "wastagePercent": waste_pct if waste_pct > 0 else None,
        "stockStdM": stock_std,
        "costEngine": design.get("costEngine"),
        "designCost": design.get("total") if design.get("ok") else None,
        "costBreakdown": design.get("breakdown") if isinstance(design.get("breakdown"), Mapping) else None,
    }


def build_quote_materials_list(
    lines: Sequence[Mapping[str, Any]],
    *,
    customer: str | None = None,
    quote_date: str | None = None,
    colour: str | None = None,
    project_name: str | None = None,
) -> dict[str, Any]:
    """Aggregate materials/hardware for all cart lines."""
    rows = [materials_rows_for_line(ln) for ln in lines if isinstance(ln, Mapping)]
    # Roll up by catalogue name
    mat_roll: dict[str, dict[str, Any]] = {}
    hw_roll: dict[str, dict[str, Any]] = {}
    glass_roll: dict[str, dict[str, Any]] = {}
    for row in rows:
        lq = _f(row.get("qty"), 1)
        for m in row.get("materials") or []:
            key = _str(m.get("name")).lower()
            if not key:
                continue
            slot = mat_roll.setdefault(
                key,
                {
                    "name": m["name"],
                    "qty": 0.0,
                    "unit": m.get("unit"),
                    "sides": set(),
                    "stock": _str(m.get("stock")),
                    "weightKg": 0.0,
                    "wastageM": 0.0,
                    "remarks": [],
                },
            )
            pcs = m.get("pcs")
            if pcs is None:
                pcs = m.get("qty") or m.get("lengthM") or 1
            slot["qty"] = _f(slot["qty"]) + _f(pcs) * lq
            if m.get("sides"):
                slot["sides"].add(_str(m.get("sides")))
            if m.get("stock") and not slot.get("stock"):
                slot["stock"] = _str(m.get("stock"))
            if m.get("weightKg") is not None:
                slot["weightKg"] = _f(slot.get("weightKg")) + _f(m.get("weightKg")) * lq
            if m.get("wastageM") is not None:
                slot["wastageM"] = _f(slot.get("wastageM")) + _f(m.get("wastageM")) * lq
            if m.get("remarks"):
                slot["remarks"].append(str(m["remarks"]))
        for h in row.get("hardware") or []:
            key = _str(h.get("name")).lower()
            if not key:
                continue
            slot = hw_roll.setdefault(key, {"name": h["name"], "qty": 0.0, "unit": h.get("unit") or "PC"})
            slot["qty"] = _f(slot["qty"]) + _f(h.get("qty")) * lq
        g = row.get("glass") or {}
        gname = _str(g.get("name"))
        if gname and gname != "—":
            slot = glass_roll.setdefault(gname.lower(), {"name": gname, "areaSft": 0.0, "unit": "sft"})
            slot["areaSft"] = _f(slot["areaSft"]) + _f(g.get("areaSft")) * lq

    for slot in mat_roll.values():
        sides = slot.get("sides")
        if isinstance(sides, set):
            slot["sides"] = ", ".join(sorted(sides)) if sides else ""
        if not slot.get("weightKg"):
            slot["weightKg"] = None
        if not slot.get("wastageM"):
            slot["wastageM"] = None

    # Dominant colour from lines if not provided
    colours = sorted({_str(r.get("colour")) for r in rows if r.get("colour") and r.get("colour") != "—"})
    return {
        "customer": _str(customer) or "—",
        "date": _str(quote_date) or date.today().isoformat(),
        "colour": _str(colour) or (", ".join(colours) if colours else "—"),
        "projectName": _str(project_name) or "",
        "lineCount": len(rows),
        "lines": rows,
        "materialsSummary": sorted(mat_roll.values(), key=lambda x: str(x["name"]).lower()),
        "hardwareSummary": sorted(hw_roll.values(), key=lambda x: str(x["name"]).lower()),
        "glassSummary": sorted(glass_roll.values(), key=lambda x: str(x["name"]).lower()),
    }


def materials_list_html(pack: Mapping[str, Any]) -> str:
    """Printable HTML document."""
    esc = (
        lambda s: str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    def _mat_bits(m: Mapping[str, Any]) -> str:
        bits: list[str] = []
        pcs = m.get("pcs")
        if pcs is None:
            pcs = m.get("qty")
        if pcs is not None and pcs != "":
            bits.append(f"{esc(pcs)} pcs")
        if m.get("lengthM") is not None:
            bits.append(f"{esc(round(_f(m.get('lengthM')), 3))} m cut")
        if m.get("sides"):
            bits.append(f"sides: {esc(m.get('sides'))}")
        if m.get("use"):
            bits.append(f"use: {esc(m.get('use'))}")
        if m.get("colour"):
            bits.append(f"colour: {esc(m.get('colour'))}")
        if m.get("finishFamily"):
            bits.append(esc(m.get("finishFamily")))
        if m.get("coatingBrand"):
            bits.append(esc(m.get("coatingBrand")))
        if m.get("stock"):
            bits.append(f"stock: {esc(m.get('stock'))}")
        if m.get("weightKg") is not None:
            bits.append(f"{esc(round(_f(m.get('weightKg')), 3))} kg")
        elif m.get("weightKgPerM") is not None:
            bits.append(f"{esc(round(_f(m.get('weightKgPerM')), 3))} kg/m")
        if m.get("wastageM") is not None:
            wp = m.get("wastagePercent")
            bits.append(
                f"wastage {esc(round(_f(m.get('wastageM')), 3))} m"
                + (f" ({esc(wp)}%)" if wp is not None else "")
            )
        return " · ".join(bits)

    def _hw_bits(h: Mapping[str, Any]) -> str:
        bits: list[str] = []
        if h.get("brand"):
            bits.append(esc(h.get("brand")))
        pcs = h.get("pcs") if h.get("pcs") is not None else h.get("qty")
        if pcs is not None and pcs != "":
            bits.append(f"{esc(pcs)} {esc(h.get('unit') or 'PC')}")
        if h.get("unitRate") is not None and _f(h.get("unitRate")) > 0:
            bits.append(f"₹{esc(round(_f(h.get('unitRate')), 2))}")
        if h.get("amount") is not None and _f(h.get("amount")) > 0:
            bits.append(f"= ₹{esc(round(_f(h.get('amount')), 2))}")
        return " · ".join(bits)

    rows_html = []
    for ln in pack.get("lines") or []:
        mats = "".join(
            f"<li><strong>{esc(m.get('name'))}</strong>"
            f"{(' — ' + _mat_bits(m)) if _mat_bits(m) else ''}"
            f"</li>"
            for m in (ln.get("materials") or [])
        ) or "<li class=muted>—</li>"
        hws = "".join(
            f"<li><strong>{esc(h.get('name'))}</strong>"
            f"{(' — ' + _hw_bits(h)) if _hw_bits(h) else ''}</li>"
            for h in (ln.get("hardware") or [])
        ) or "<li class=muted>—</li>"
        g = ln.get("glass") or {}
        g_bits = []
        if g.get("packName") or g.get("name"):
            g_bits.append(esc(g.get("packName") or g.get("name")))
        if g.get("colour"):
            g_bits.append(f"colour {esc(g.get('colour'))}")
        if g.get("thicknessMm") is not None:
            g_bits.append(f"{esc(g.get('thicknessMm'))} mm")
        if g.get("sizeLabel"):
            g_bits.append(esc(g.get("sizeLabel")))
        if g.get("qty") is not None:
            g_bits.append(f"qty {esc(g.get('qty'))}")
        if g.get("areaSft") is not None:
            g_bits.append(f"{esc(g.get('areaSft'))} sft")
        if g.get("unitRate") is not None and _f(g.get("unitRate")) > 0:
            g_bits.append(f"₹{esc(round(_f(g.get('unitRate')), 2))}/sft")
        inter = ln.get("interlocks") if isinstance(ln.get("interlocks"), Mapping) else {}
        inter_note = ""
        if inter:
            inter_note = (
                f"<p class=muted style=margin:.25rem 0 0>Interlocks: slim {esc(inter.get('slim'))}"
                f" · renf {esc(inter.get('renf'))}"
                f" · mesh slim {esc(inter.get('meshSlim'))}"
                f" · glass reducer {esc(inter.get('glassReducerPcs'))} pcs"
                f" ({esc(inter.get('rule'))})</p>"
            )
        waste_note = ""
        if ln.get("wastageM") is not None:
            waste_note = (
                f" · wastage {esc(round(_f(ln.get('wastageM')), 3))} m"
                + (f" ({esc(ln.get('wastagePercent'))}%)" if ln.get("wastagePercent") is not None else "")
            )
        rows_html.append(
            f"""<section class="line">
  <h3>{esc(ln.get('serial') or '')} {esc(ln.get('product'))}
    <span class="muted">{esc(ln.get('width'))}×{esc(ln.get('height'))} mm · qty {esc(ln.get('qty'))}
    · {esc(ln.get('colour'))}{(' · ' + esc(ln.get('location'))) if ln.get('location') else ''}{waste_note}</span></h3>
  <div class="cols">
    <div><h4>Sections used</h4><ul>{mats}</ul>{inter_note}</div>
    <div><h4>Hardware</h4><ul>{hws}</ul></div>
    <div><h4>Glass</h4><p>{' · '.join(g_bits) if g_bits else '—'}</p></div>
  </div>
</section>"""
        )

    def summary_table(title: str, items: Sequence[Mapping[str, Any]], qty_key: str = "qty") -> str:
        body = "".join(
            f"<tr><td>{esc(it.get('name'))}</td>"
            f"<td class=num>{esc(round(_f(it.get(qty_key)), 3) if it.get(qty_key) is not None else '')}</td>"
            f"<td>{esc(it.get('unit'))}</td>"
            f"<td>{esc(it.get('sides') or '')}</td>"
            f"<td>{esc(it.get('stock') or '')}</td>"
            f"<td class=num>{esc(round(_f(it.get('weightKg')), 3) if it.get('weightKg') is not None else '')}</td>"
            f"<td class=num>{esc(round(_f(it.get('wastageM')), 3) if it.get('wastageM') is not None else '')}</td></tr>"
            for it in items
        ) or "<tr><td colspan=7 class=muted>None</td></tr>"
        return (
            f"<h2>{esc(title)}</h2><table><thead><tr>"
            f"<th>Name</th><th>Pcs / qty</th><th>Unit</th><th>Sides</th>"
            f"<th>Section stock</th><th>Weight kg</th><th>Wastage m</th>"
            f"</tr></thead><tbody>{body}</tbody></table>"
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Materials &amp; hardware — {esc(pack.get('customer'))}</title>
<style>
  body{{font-family:Segoe UI,system-ui,sans-serif;margin:1.5rem;color:#1a1a1a;font-size:14px}}
  h1{{font-size:1.35rem;margin:0 0 .35rem}}
  h2{{font-size:1.05rem;margin:1.2rem 0 .4rem;border-bottom:1px solid #ccc;padding-bottom:.2rem}}
  h3{{font-size:.95rem;margin:.8rem 0 .35rem}}
  h4{{font-size:.8rem;margin:.2rem 0;text-transform:uppercase;letter-spacing:.04em;color:#555}}
  .meta{{color:#444;margin-bottom:1rem;line-height:1.5}}
  .muted{{color:#777;font-weight:400;font-size:.85em}}
  .cols{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem}}
  ul{{margin:.2rem 0 .5rem;padding-left:1.1rem}}
  table{{border-collapse:collapse;width:100%;margin-bottom:1rem}}
  th,td{{border:1px solid #ddd;padding:.35rem .5rem;text-align:left}}
  th{{background:#f4f4f4}}
  td.num{{text-align:right}}
  .line{{border:1px solid #e5e5e5;border-radius:8px;padding:.6rem .8rem;margin:.6rem 0}}
  @media print{{body{{margin:.8rem}} .noprint{{display:none}}}}
  @media(max-width:720px){{.cols{{grid-template-columns:1fr}}}}
</style></head><body>
<button class="noprint" onclick="window.print()" style="float:right;padding:.4rem .8rem;cursor:pointer">Print</button>
<h1>Materials &amp; hardware list</h1>
<div class="meta">
  <div><strong>Customer:</strong> {esc(pack.get('customer'))}</div>
  <div><strong>Date:</strong> {esc(pack.get('date'))}</div>
  <div><strong>Colour:</strong> {esc(pack.get('colour'))}</div>
  {('<div><strong>Project:</strong> ' + esc(pack.get('projectName')) + '</div>') if pack.get('projectName') else ''}
  <div class="muted">{esc(pack.get('lineCount'))} product line(s) on quote</div>
</div>
{summary_table('Materials (catalogue names)', pack.get('materialsSummary') or [])}
{summary_table('Hardware (catalogue names)', pack.get('hardwareSummary') or [])}
{summary_table('Glass', pack.get('glassSummary') or [], qty_key='areaSft')}
<h2>Per product</h2>
{''.join(rows_html) or '<p class=muted>No lines on quote.</p>'}
</body></html>"""
