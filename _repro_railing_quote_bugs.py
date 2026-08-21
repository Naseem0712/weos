"""Reproduce railing label mismatch + manual rate total bugs."""
from __future__ import annotations

from WEOS.factory.marqt_pdf import _spec_lines
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.railing_engine import compute_railing

out: list[str] = []


def p(*a):
    out.append(" ".join(str(x) for x in a))


cfg = {
    "shape": "straight",
    "lengthMm": 4958.15,
    "heightMm": 900,
    "panels": 1,
    "blocksPerGlass": 0,
    "continuousRail": True,
    "handrail": False,
    "installComponents": {
        "bottomRail": True,
        "block": False,
        "ssPillar": False,
        "handrail": False,
        "glass": True,
    },
    "mountType": "side_mount",
    "glassThicknessMm": 12,
    "rates": {
        "glassPerSqft": 200,
        "anchorPerPc": 50,
        "bottomRailPerUnit": 180,
    },
}
q = compute_railing(cfg)
p("A", q["shape"], q["panelCount"], q["widthUnit"], q["anchorCount"])
p("items", [(i["key"], i["qty"], i["rate"], i["amount"]) for i in q["items"]])
p(
    "cascade",
    "hw",
    q["costCascade"]["hardwareCost"],
    "glass",
    q["costCascade"]["glassMaterialCost"],
    "prof",
    q["costCascade"]["profileCost"],
)
p("sell", q["sellingPerUnit"], q["sellingTotal"], "direct", q["costCascade"]["directCost"])

# Stale description on cart line (user switched staircase -> straight)
cart = {
    "product": "railing",
    "productType": "railing",
    "displayName": "Railing",
    "width": 4958.15,
    "height": 900,
    "qty": 1,
    "saleUnit": "rft",
    "sellingRate": q["sellingPerUnit"],
    "description": "Railing · staircase · 4958.15 mm · 4 panels · 12mm",
    "options": {"railing": cfg, "railingQuote": q, "productType": "railing"},
}
r = calculate_line(cart)
p("desc_after_calc", r.get("description"))
specs = _spec_lines(r)
p("specs0", specs[0] if specs else None)
p("specs1", specs[1] if len(specs) > 1 else None)
p("price", r.get("price"))
p("selling", r.get("selling"))

# manualRatePerUnit override (customer sell rate) — does it drop BOM?
cfg2 = dict(cfg)
cfg2["manualRatePerUnit"] = 639.95
q2 = compute_railing(cfg2)
p("manual_sell", q2["sellingPerUnit"], q2["sellingTotal"], "cascade_total", q2["total"])
p("rft_x_rate", round(q2["widthUnit"] * 639.95, 2))
p("items_still", [(i["key"], i["amount"]) for i in q2["items"]])

# Compare with vs without anchors in rates
cfg_no = dict(cfg)
cfg_no["rates"] = {"glassPerSqft": 200, "anchorPerPc": 0, "bottomRailPerUnit": 180}
q_no = compute_railing(cfg_no)
p("with_anchors_total", q["sellingTotal"], "without", q_no["sellingTotal"], "delta", round(q["sellingTotal"] - q_no["sellingTotal"], 2))

# Stale quote vs fresh cfg (staircase quote left on straight cfg)
stair_cfg = {
    "shape": "staircase",
    "stairSteps": 12,
    "stairRiseMm": 180,
    "stairRunMm": 305,
    "panels": 4,
    "glassHeightMm": 900,
    "rates": {"glassPerSqft": 200, "anchorPerPc": 50, "blockPerPc": 100},
}
sq = compute_railing(stair_cfg)
stale_cart = {
    "product": "railing",
    "productType": "railing",
    "width": 4958.15,
    "height": 900,
    "qty": 1,
    "description": "Railing · staircase · 4958.15 mm · 4 panels · 12mm",
    "options": {
        "railing": cfg,  # straight
        "railingQuote": sq,  # stale staircase quote
        "productType": "railing",
    },
}
from WEOS.factory.marqt_pdf import _railing_cfg_and_quote

c2, q_stale = _railing_cfg_and_quote(stale_cart)
p("stale_pdf_shape", q_stale.get("shape"), "panel", q_stale.get("panelCount"), "cfg_shape", c2.get("shape"))
p("stale_specs0", _spec_lines(stale_cart)[0])
p("stale_specs1", _spec_lines(stale_cart)[1])

# productType staircase_railing with missing shape forces staircase
forced = calculate_line(
    {
        "product": "railing",
        "productType": "staircase_railing",
        "width": 4958.15,
        "height": 900,
        "qty": 1,
        "options": {"railing": {k: v for k, v in cfg.items() if k != "shape"}},
    }
)
fq = forced.get("railing") or {}
p("forced_shape", fq.get("shape"), "panels", fq.get("panelCount"), "desc", forced.get("description"))

# sellingRate on line used by PDF amount path
# Simulate: cascade total includes BOM but cart sellingRate is OLD / different
cfg3 = dict(cfg)
cfg3["rates"] = {"glassPerSqft": 200, "anchorPerPc": 50, "bottomRailPerUnit": 180, "handrailPerUnit": 0}
q3 = compute_railing(cfg3)
# User then bumps anchors to 100 but PDF uses frozen sellingRate from cart
cfg4 = dict(cfg3)
cfg4["rates"] = {**cfg3["rates"], "anchorPerPc": 100}
q4 = compute_railing(cfg4)
p("bump_anchors", q3["sellingTotal"], "->", q4["sellingTotal"], "rates", q4["sellingPerUnit"])
cart_frozen = {
    "product": "railing",
    "width": q4["lengthMm"],
    "height": 900,
    "qty": 1,
    "saleUnit": "rft",
    "sellingRate": q3["sellingPerUnit"],  # OLD rate frozen on cart
    "selling": {
        "sellingRate": q3["sellingPerUnit"],
        "billableQty": q3["widthUnit"],
        "sellingAmount": q3["sellingTotal"],
    },
    "options": {"railing": cfg4, "railingQuote": q4},
    "description": "Railing · straight · ...",
}
r4 = calculate_line(cart_frozen)
p(
    "recalc_after_bump",
    r4.get("sellingRate"),
    r4.get("commercialTotal"),
    "expected",
    q4["sellingTotal"],
)

path = "_repro_railing_quote_bugs_out.txt"
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
print("WROTE", path)
