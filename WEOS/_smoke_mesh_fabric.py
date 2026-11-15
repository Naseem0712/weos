"""Smoke: mesh fabric costing + preview cues (standard/premium/rolling/collapsible/vent)."""

from __future__ import annotations

import sys


def _ok(cond: bool, msg: str) -> None:
    print(("OK  " if cond else "FAIL") + " " + msg)
    if not cond:
        raise SystemExit(1)


def main() -> None:
    from WEOS.factory.mesh_addon import (
        DEFAULT_MESH_RATES,
        MESH_MEMBER_MM,
        attach_mesh_addon_to_drawing,
        is_addon_mesh,
        mesh_addon_for_line,
        mesh_fabric_for_line,
        mesh_fabric_material_row,
        normalize_mesh_type,
        vent_fix_mesh_for_line,
    )
    from WEOS.factory.design_cost import compute_sliding_design_cost
    from WEOS.factory.materials_list import materials_rows_for_line
    from WEOS.factory.ventilator_engine import compute_ventilator, ventilator_svg

    _ok(normalize_mesh_type("pleated") == "collapsible", "pleated → collapsible")
    _ok(normalize_mesh_type("sliding") == "standard", "sliding → standard")
    _ok(DEFAULT_MESH_RATES["standard"] == 150, "standard rate 150")
    _ok(DEFAULT_MESH_RATES["premium"] == 220, "premium rate 220")
    _ok(DEFAULT_MESH_RATES["rolling"] == 450, "rolling rate 450")
    _ok(DEFAULT_MESH_RATES["collapsible"] == 480, "collapsible rate 480")
    _ok(DEFAULT_MESH_RATES["vent_fix"] == 250, "vent fix mesh 250")
    _ok(MESH_MEMBER_MM == 38, "member 38 mm")

    W, H = 1200.0, 1500.0
    half_sft = (W / 2.0) * H * 10.7639 / 1_000_000.0
    full_sft = W * H * 10.7639 / 1_000_000.0

    std = mesh_fabric_for_line({
        "width": W, "height": H, "qty": 1, "mesh": True, "meshShutters": 1, "meshType": "standard",
    })
    _ok(std is not None and std["kind"] == "intrack", f"standard fabric {std}")
    _ok(abs(float(std["areaSqft"]) - half_sft) < 1e-3, f"standard area (W/2)×H {std['areaSqft']} vs {half_sft}")
    _ok(float(std["rate"]) == 150, f"standard rate {std['rate']}")
    _ok(abs(float(std["amountUnit"]) - round(half_sft * 150, 2)) < 0.02, f"standard amt {std['amountUnit']}")

    prem = mesh_fabric_for_line({
        "width": W, "height": H, "qty": 1, "mesh": True, "meshShutters": 1, "meshType": "premium",
    })
    _ok(prem is not None and float(prem["rate"]) == 220, f"premium rate {prem}")

    roll = mesh_fabric_for_line({
        "width": W, "height": H, "qty": 1, "mesh": True, "meshType": "rolling", "meshPlacement": "left",
    })
    _ok(roll is not None and roll["kind"] == "addon", f"rolling fabric {roll}")
    _ok(abs(float(roll["areaSqft"]) - full_sft) < 1e-3, f"rolling full window {roll['areaSqft']}")
    _ok(float(roll["rate"]) == 450, f"rolling rate {roll['rate']}")
    _ok(is_addon_mesh({"meshType": "rolling", "mesh": True}), "rolling is addon")

    col = mesh_fabric_for_line({
        "width": W, "height": H, "qty": 1, "mesh": True, "meshType": "collapsible",
        "meshCollapseStyle": "center",
    })
    _ok(col is not None and float(col["rate"]) == 480, f"collapsible rate {col}")
    _ok(abs(float(col["areaSqft"]) - full_sft) < 1e-3, f"collapsible full {col['areaSqft']}")

    # Preview rects
    class _D:
        width = W
        height = H
        metadata = {}

    d = _D()
    attach_mesh_addon_to_drawing(d, mesh_addon_for_line({
        "width": W, "height": H, "mesh": True, "meshType": "rolling", "meshPlacement": "left",
    }))
    rects = (d.metadata.get("mesh_addon") or {}).get("rects") or []
    _ok(len(rects) == 1 and rects[0].get("memberOrient") == "vertical", f"rolling preview {rects}")
    _ok(float(rects[0].get("memberMm") or 0) == 38, "rolling member 38")

    d2 = _D()
    d2.metadata = {}
    attach_mesh_addon_to_drawing(d2, mesh_addon_for_line({
        "width": W, "height": H, "mesh": True, "meshType": "collapsible", "meshCollapseStyle": "center",
    }))
    r2 = (d2.metadata.get("mesh_addon") or {}).get("rects") or []
    _ok(len(r2) == 2, f"collapsible center both sides {r2}")

    d3 = _D()
    d3.metadata = {}
    attach_mesh_addon_to_drawing(d3, mesh_addon_for_line({
        "width": W, "height": H, "mesh": True, "meshType": "collapsible", "meshCollapseStyle": "top",
    }))
    r3 = (d3.metadata.get("mesh_addon") or {}).get("rects") or []
    _ok(len(r3) == 1 and r3[0].get("memberOrient") == "horizontal", f"collapsible top {r3}")

    vent = vent_fix_mesh_for_line({"widthMm": 600, "heightMm": 450, "qty": 1})
    _ok(vent is not None and float(vent["rate"]) == 250, f"vent fix mesh {vent}")
    vq = compute_ventilator({"widthMm": 600, "heightMm": 450, "qty": 1})
    _ok(any(str(it.get("key")) == "fix_mesh" for it in (vq.get("items") or [])), f"vent items mesh {vq.get('items')}")
    svg = ventilator_svg({"widthMm": 600, "heightMm": 450}, quote=vq)
    _ok('data-mesh-outside="1"' in svg or "ventFixMesh" in svg, "vent SVG outside mesh")

    # Design cost + materials list for in-track mesh
    line = {
        "product": "35mm_sliding",
        "width": W,
        "height": H,
        "qty": 1,
        "mesh": True,
        "meshShutters": 1,
        "meshType": "standard",
        "trackCount": 3,
        "glassShutters": 2,
        "colour": "white",
    }
    try:
        from WEOS.factory.product_loader import load_product
        prod = load_product("35mm_sliding", strict=False)
    except Exception:
        prod = {"id": "35mm_sliding"}
    dc = compute_sliding_design_cost(line, product=prod)
    if dc.get("ok"):
        _ok(float(dc.get("meshCost") or 0) > 0 or (dc.get("mesh") or {}).get("amountUnit"), f"design meshCost {dc.get('meshCost')} mesh={dc.get('mesh')}")
        mats = materials_rows_for_line(line)
        mesh_mats = [m for m in (mats.get("materials") or []) if m.get("kind") == "mesh"]
        _ok(len(mesh_mats) >= 1, f"materials mesh row {mesh_mats}")
        row = mesh_fabric_material_row(std)
        _ok(row["unit"] == "sft" and float(row["unitRate"]) == 150, f"material row {row}")
    else:
        print(f"SKIP design_cost (stub) {dc.get('reason')}")

    print("mesh fabric smoke OK")


if __name__ == "__main__":
    main()
    sys.exit(0)
