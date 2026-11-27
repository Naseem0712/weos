"""Smoke: live Al/Coat must increase when W or H increases (rulebook cut × rate)."""
from __future__ import annotations

import sys

from WEOS.factory.design_cost import compute_sliding_design_cost, nest_cuts_by_section
from WEOS.factory.product_loader import load_product


def _ok(cond: bool, msg: str) -> None:
    print(("OK  " if cond else "FAIL") + " " + msg)
    if not cond:
        raise SystemExit(1)


def _line(w: float, h: float, pid: str) -> dict:
    return {
        "width": w,
        "height": h,
        "qty": 1,
        "product": pid,
        "productId": pid,
        "glassShutters": 2,
        "meshShutters": 1,
        "trackCount": 2,
        "mesh": True,
        "glass": "5mm_clear",
        "colour": "white",
        "system": "sliding",
        "options": {"mesh": True, "meshShutters": 1, "glassShutters": 2, "trackCount": 2},
    }


def main() -> None:
    # Nest still reports purchase bars for materials.
    nest = nest_cuts_by_section(
        [
            {"lengthM": 1.17, "key": "v", "stdM": 5.85, "aluminiumPerM": 100, "coatingPerM": 10},
            {"lengthM": 1.77, "key": "v", "stdM": 5.85, "aluminiumPerM": 100, "coatingPerM": 10},
        ],
        reuse=True,
        default_std_m=5.85,
        coat_full_bars=True,
    )
    _ok(nest["aluminiumCost"] == nest["purchasedMetres"] * 100, "nest purchase Al = purch×rate")
    _ok(
        abs(nest["aluminiumUsedCost"] - nest["netMetres"] * 100) < 0.02,
        f"nest used Al = net×rate {nest['aluminiumUsedCost']}",
    )

    pid = "29mm_sliding"
    p = load_product(pid, strict=False)
    a = compute_sliding_design_cost(_line(2050, 1170, pid), product=p, setup=p.get("setup"))
    b = compute_sliding_design_cost(_line(2050, 1770, pid), product=p, setup=p.get("setup"))
    c = compute_sliding_design_cost(_line(1550, 1770, pid), product=p, setup=p.get("setup"))
    al_a = float((a.get("breakdown") or {}).get("aluminium") or 0)
    al_b = float((b.get("breakdown") or {}).get("aluminium") or 0)
    al_c = float((c.get("breakdown") or {}).get("aluminium") or 0)
    coat_a = float((a.get("breakdown") or {}).get("coating") or 0)
    coat_b = float((b.get("breakdown") or {}).get("coating") or 0)
    coat_c = float((c.get("breakdown") or {}).get("coating") or 0)
    _ok(al_a > 0 and al_b > 0 and al_c > 0, f"Al>0 A={al_a} B={al_b} C={al_c}")
    _ok(al_b > al_a, f"taller H → more Al ({al_a} → {al_b})")
    _ok(al_b > al_c, f"wider W → more Al ({al_c} → {al_b})")
    _ok(al_a != al_b != al_c and al_a != al_c, f"three sizes distinct Al {al_a},{al_c},{al_b}")
    _ok(coat_b > coat_a, f"taller H → more Coat ({coat_a} → {coat_b})")
    _ok(coat_b > coat_c, f"wider W → more Coat ({coat_c} → {coat_b})")
    # Purchase may still be flat — that is materials nest, not live strip.
    purch_a = float(a.get("aluminiumPurchaseCost") or 0)
    purch_b = float(b.get("aluminiumPurchaseCost") or 0)
    _ok(purch_a >= al_a and purch_b >= al_b, f"purchase ≥ used Al purch={purch_a}/{purch_b}")
    print(f"SMOKE OK Al scales W/H: 2050×1170={al_a} 1550×1770={al_c} 2050×1770={al_b}")


if __name__ == "__main__":
    main()
    sys.exit(0)
