"""Smoke: Fixed cheaper than Door/openable; hingeQty N draws N glyphs per leaf."""
from __future__ import annotations

from WEOS.factory.design_cost import compute_casement_design_cost
from WEOS.factory.pipeline import generate_job
from WEOS.factory.product_loader import load_product


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def _line(role: str, *, hinge: int = 3, product_id: str = "50mm_casement_prestige") -> dict:
    return {
        "width": 1536,
        "height": 1500,
        "qty": 1,
        "productId": product_id,
        "hingeQty": hinge,
        "sideSwingOpenHw": "hinges",
        "casementLayout": {
            "bands": [
                {
                    "heightMm": 1500,
                    "panels": [
                        {"role": "openable", "widthMm": 512, "handleSide": "right"},
                        {"role": "openable", "widthMm": 512, "handleSide": "left"},
                        {"role": role, "widthMm": 512, "handleSide": "right"},
                    ],
                }
            ]
        },
    }


def main() -> None:
    for pid in ("50mm_casement_prestige", "40mm_casement_standard"):
        p = load_product(pid, strict=False)
        door = compute_casement_design_cost(_line("openable", product_id=pid), product=p)
        fixed = compute_casement_design_cost(_line("fix", product_id=pid), product=p)
        dt = float(door.get("total") or 0)
        ft = float(fixed.get("total") or 0)
        dhw = float((door.get("breakdown") or {}).get("hardware") or 0)
        fhw = float((fixed.get("breakdown") or {}).get("hardware") or 0)
        dal = float((door.get("breakdown") or {}).get("aluminium") or 0)
        fal = float((fixed.get("breakdown") or {}).get("aluminium") or 0)
        _ok(dt > 0 and ft > 0, f"{pid} costs live door={dt:.0f} fix={ft:.0f}")
        _ok(ft < dt, f"{pid} Fixed ({ft:.0f}) < Door/openable ({dt:.0f})")
        _ok(fhw < dhw, f"{pid} Fixed HW ({fhw:.0f}) < Door HW ({dhw:.0f})")
        _ok(fal <= dal + 1.0, f"{pid} Fixed Al ({fal:.0f}) not above Door Al ({dal:.0f})")
        # Door leaf uses door section; Fixed uses glass_clip — not shutter-as-clip
        fix_uses = {
            str(x.get("use"))
            for x in (fixed.get("profiles") or [])
            if "P3" in str(x.get("remarks") or "") or "fix" in str(x.get("remarks") or "").lower()
        }
        _ok("glass_clip" in fix_uses or not fix_uses, f"{pid} Fixed P3 uses clip {fix_uses}")
        _ok("door" not in fix_uses, f"{pid} Fixed P3 must not bill door section {fix_uses}")

    # hingeQty → elevation glyphs (3 openable leaves)
    for hq in (2, 3, 4):
        job = generate_job(
            1536,
            1500,
            "50mm_casement_prestige",
            system="casement",
            casement_layout=_line("openable", hinge=hq)["casementLayout"],
            hinges_per_door=hq,
        )
        n = len((job.drawing.metadata or {}).get("hinges") or [])
        _ok(n == hq * 3, f"hingeQty {hq} → {n} glyphs (expect {hq * 3})")

    # Stay path: no hinge glyphs
    job_stay = generate_job(
        1536,
        1500,
        "50mm_casement_prestige",
        system="casement",
        casement_layout=_line("openable")["casementLayout"],
        hinges_per_door=0,
    )
    n0 = len((job_stay.drawing.metadata or {}).get("hinges") or [])
    _ok(n0 == 0, f"stay/hinges_per_door=0 → no glyphs (got {n0})")

    # BOM hinge qty scales with hingeQty
    p = load_product("50mm_casement_prestige", strict=False)
    h2 = compute_casement_design_cost(_line("openable", hinge=2), product=p)
    h4 = compute_casement_design_cost(_line("openable", hinge=4), product=p)

    def hinge_qty(d: dict) -> float:
        for h in d.get("hardware") or []:
            name = str(h.get("name") or "").lower()
            if "hinge" in name or "standerd" in name or "standard" in name:
                return float(h.get("qty") or 0)
        return 0.0

    q2, q4 = hinge_qty(h2), hinge_qty(h4)
    _ok(q2 == 6.0 and q4 == 12.0, f"BOM hinge qty 2→{q2} 4→{q4} (3 doors)")
    _ok(
        float(h4.get("total") or 0) > float(h2.get("total") or 0),
        "more hinges → higher cost",
    )
    print("ALL PASS: casement Fixed < Door + hingeQty glyphs/BOM")


if __name__ == "__main__":
    main()
