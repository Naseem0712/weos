"""Smoke: 1050×970 sliding+mesh must bill Al, Coat, EPDM, Brush (rulebook v2)."""
from __future__ import annotations

import copy
import sys

from WEOS.factory.design_cost import compute_sliding_design_cost, resolve_costing_setup
from WEOS.factory.live_pricing import live_price
from WEOS.factory.product_loader import load_product


def _ok(cond: bool, msg: str) -> None:
    print(("OK  " if cond else "FAIL") + " " + msg)
    if not cond:
        raise SystemExit(1)


def main() -> None:
    pid = "25mm_eco_gulf"
    p = load_product(pid)
    line = {
        "width": 1050,
        "height": 970,
        "qty": 1,
        "product": pid,
        "productId": pid,
        "mesh": True,
        "meshShutters": 1,
        "glassShutters": 2,
        "trackCount": 2,
        "glass": "lam_6_152_6",
        "colour": "white",
        "system": "sliding",
        "options": {"mesh": True, "meshShutters": 1, "glassShutters": 2},
    }
    live = live_price(line)
    dc = live.get("designCost") or {}
    br = dc.get("breakdown") or {}
    cost = live.get("cost") or {}
    _ok(dc.get("ok") and dc.get("costEngine") == "live", f"live engine {dc.get('costEngine')}")
    _ok(float(br.get("aluminium") or 0) > 0, f"Al>0 got {br.get('aluminium')}")
    _ok(float(br.get("coating") or 0) > 0, f"Coat>0 got {br.get('coating')}")
    _ok(float(br.get("epdm") or 0) > 0, f"EPDM>0 got {br.get('epdm')}")
    _ok(float(br.get("brush") or 0) > 0, f"Brush>0 got {br.get('brush')}")
    _ok(float(br.get("glass") or 0) > 0, f"Glass lam got {br.get('glass')}")
    _ok(float(br.get("mesh") or 0) > 0, f"Mesh>0 got {br.get('mesh')}")
    _ok(float(cost.get("epdmCost") or 0) > 0, f"cost.epdmCost {cost.get('epdmCost')}")
    _ok(float(cost.get("brushCost") or 0) > 0, f"cost.brushCost {cost.get('brushCost')}")
    # Caps / guides / dust must carry catalogue seed rates (not silent ₹0)
    hw = dc.get("hardware") or []
    caps = next((h for h in hw if "interlock" in str(h.get("name") or "").lower() and "cap" in str(h.get("name") or "").lower()), None)
    guides = next((h for h in hw if "guide" in str(h.get("name") or "").lower()), None)
    dust = next((h for h in hw if "dust" in str(h.get("name") or "").lower()), None)
    _ok(caps and float(caps.get("unitRate") or 0) > 0 and float(caps.get("amount") or 0) > 0, f"caps priced {caps}")
    _ok(guides and float(guides.get("unitRate") or 0) > 0, f"guides priced {guides}")
    _ok(dust and float(dust.get("unitRate") or 0) > 0, f"dust priced {dust}")

    # Zero Excel rates but keep weights → nest Al must still recover
    setup = resolve_costing_setup(line, product=p)
    bad = copy.deepcopy(setup)

    def zero_rates(obj):
        if isinstance(obj, dict):
            if "rate" in obj and (
                "weightKgPerM" in obj
                or "weightKgPerMtr" in obj
                or "rateUnit" in obj
                or "coatingCost" in obj
            ):
                obj["rate"] = 0
            for v in obj.values():
                zero_rates(v)
        elif isinstance(obj, list):
            for v in obj:
                zero_rates(v)

    zero_rates(bad)
    d0 = compute_sliding_design_cost(line, product=p, setup=bad)
    b0 = d0.get("breakdown") or {}
    _ok(bool(d0["missingMaterialRates"]), "missing profile rates reported")
    _ok(float(b0.get("coating") or 0) > 0, f"zero-rate setup still Coat>0 got {b0.get('coating')}")
    print("SMOKE OK 1050x970 sliding+mesh Al/Coat/EPDM/Brush")


if __name__ == "__main__":
    main()
    sys.exit(0)
