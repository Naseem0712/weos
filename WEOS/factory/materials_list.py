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

    for p in design.get("profiles") or []:
        materials.append({
            "kind": "profile",
            "name": _str(p.get("catalogueName") or p.get("name")),
            "qty": p.get("qty"),
            "unit": p.get("unit") or "RM",
            "lengthM": p.get("lengthM") or p.get("metres"),
            "remarks": p.get("remarks") or p.get("use") or "",
        })
    # Also surface setup section names when design engine stubbed
    if not materials and isinstance(product.get("setup"), Mapping):
        try:
            from WEOS.factory.product_setup import flatten_setup_sections

            for sec in flatten_setup_sections(product["setup"]):
                nm = _str(sec.get("name"))
                if nm:
                    materials.append({
                        "kind": "profile",
                        "name": nm,
                        "qty": 1,
                        "unit": "section",
                        "remarks": _str(sec.get("use")),
                    })
        except Exception:
            pass

    for h in design.get("hardware") or []:
        hardware.append({
            "kind": "hardware",
            "name": _str(h.get("catalogueName") or h.get("name")),
            "qty": h.get("qty"),
            "unit": h.get("unit") or "PC",
            "remarks": h.get("remarks") or "",
        })
    # Line hardware from calc result
    for h in line.get("hardware") or []:
        if isinstance(h, Mapping):
            nm = _str(h.get("name") or h.get("description"))
            if nm and not any(x["name"] == nm for x in hardware):
                hardware.append({
                    "kind": "hardware",
                    "name": nm,
                    "qty": h.get("qty") or h.get("quantity"),
                    "unit": h.get("unit") or "PC",
                    "remarks": "",
                })

    glass_name = _glass_catalogue_name(line)
    g = design.get("glass") if isinstance(design.get("glass"), Mapping) else {}
    glass_row = {
        "kind": "glass",
        "name": _str(g.get("catalogueName") or g.get("name") or glass_name),
        "qty": 1,
        "unit": "sft",
        "areaSft": g.get("areaSft"),
        "remarks": "",
    }

    # Fixed partition series names
    parts = line.get("partitions") or (line.get("options") or {}).get("partitions") or []
    for p in parts if isinstance(parts, (list, tuple)) else []:
        if not isinstance(p, Mapping):
            continue
        series = _str(p.get("profileSeries") or p.get("sectionSeries") or p.get("fixedSeries"))
        if series:
            materials.append({
                "kind": "profile",
                "name": series,
                "qty": 1,
                "unit": "fix",
                "remarks": f"{_str(p.get('side'))} fix {_f(p.get('sizeMm'))} mm",
            })

    return {
        "lineId": line.get("lineId"),
        "serial": line.get("serial"),
        "product": _product_label(line),
        "productId": pid,
        "width": line.get("width"),
        "height": line.get("height"),
        "qty": line.get("qty") or 1,
        "colour": _colour_label(line),
        "location": _str(line.get("locationName") or line.get("positionName") or ""),
        "materials": materials,
        "hardware": hardware,
        "glass": glass_row,
        "costEngine": design.get("costEngine"),
        "designCost": design.get("total") if design.get("ok") else None,
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
        for m in row.get("materials") or []:
            key = _str(m.get("name")).lower()
            if not key:
                continue
            slot = mat_roll.setdefault(key, {"name": m["name"], "qty": 0.0, "unit": m.get("unit"), "remarks": []})
            slot["qty"] = _f(slot["qty"]) + _f(m.get("qty") or m.get("lengthM") or 1) * _f(row.get("qty"), 1)
            if m.get("remarks"):
                slot["remarks"].append(str(m["remarks"]))
        for h in row.get("hardware") or []:
            key = _str(h.get("name")).lower()
            if not key:
                continue
            slot = hw_roll.setdefault(key, {"name": h["name"], "qty": 0.0, "unit": h.get("unit") or "PC"})
            slot["qty"] = _f(slot["qty"]) + _f(h.get("qty")) * _f(row.get("qty"), 1)
        g = row.get("glass") or {}
        gname = _str(g.get("name"))
        if gname and gname != "—":
            slot = glass_roll.setdefault(gname.lower(), {"name": gname, "areaSft": 0.0, "unit": "sft"})
            slot["areaSft"] = _f(slot["areaSft"]) + _f(g.get("areaSft")) * _f(row.get("qty"), 1)

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
    rows_html = []
    for ln in pack.get("lines") or []:
        mats = "".join(
            f"<li>{esc(m.get('name'))}"
            f"{(' · ' + esc(m.get('qty')) + ' ' + esc(m.get('unit'))) if m.get('qty') is not None else ''}"
            f"{(' <span class=muted>(' + esc(m.get('remarks')) + ')</span>') if m.get('remarks') else ''}"
            f"</li>"
            for m in (ln.get("materials") or [])
        ) or "<li class=muted>—</li>"
        hws = "".join(
            f"<li>{esc(h.get('name'))} · {esc(h.get('qty'))} {esc(h.get('unit'))}</li>"
            for h in (ln.get("hardware") or [])
        ) or "<li class=muted>—</li>"
        g = ln.get("glass") or {}
        rows_html.append(
            f"""<section class="line">
  <h3>{esc(ln.get('serial') or '')} {esc(ln.get('product'))}
    <span class="muted">{esc(ln.get('width'))}×{esc(ln.get('height'))} mm · qty {esc(ln.get('qty'))}
    · {esc(ln.get('colour'))}{(' · ' + esc(ln.get('location'))) if ln.get('location') else ''}</span></h3>
  <div class="cols">
    <div><h4>Materials</h4><ul>{mats}</ul></div>
    <div><h4>Hardware</h4><ul>{hws}</ul></div>
    <div><h4>Glass</h4><p>{esc(g.get('name'))}
      {(' · ' + esc(g.get('areaSft')) + ' sft') if g.get('areaSft') else ''}</p></div>
  </div>
</section>"""
        )

    def summary_table(title: str, items: Sequence[Mapping[str, Any]], qty_key: str = "qty") -> str:
        body = "".join(
            f"<tr><td>{esc(it.get('name'))}</td><td class=num>{esc(round(_f(it.get(qty_key)), 3) if it.get(qty_key) is not None else '')}</td>"
            f"<td>{esc(it.get('unit'))}</td></tr>"
            for it in items
        ) or "<tr><td colspan=3 class=muted>None</td></tr>"
        return f"<h2>{esc(title)}</h2><table><thead><tr><th>Name</th><th>Qty</th><th>Unit</th></tr></thead><tbody>{body}</tbody></table>"

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
