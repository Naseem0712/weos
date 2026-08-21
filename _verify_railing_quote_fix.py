"""Verify railing label + BOM→total fixes."""
from __future__ import annotations

from WEOS.factory.marqt_pdf import _railing_cfg_and_quote, _spec_lines
from WEOS.factory.project_engine import calculate_line
from WEOS.factory.railing_engine import compute_railing

fails: list[str] = []

# A) stale description must not survive calculate_line
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
    "rates": {"glassPerSqft": 200, "anchorPerPc": 50, "bottomRailPerUnit": 0},
}
q = compute_railing(cfg)
cart = {
    "product": "railing",
    "productType": "staircase_railing",  # stale
    "displayName": "Staircase railing",
    "width": 4958.15,
    "height": 900,
    "qty": 1,
    "saleUnit": "rft",
    "sellingRate": 639.95,  # frozen cart rate — must NOT override cascade
    "description": "Railing · staircase · 4958.15 mm · 4 panels · 12mm",
    "options": {"railing": cfg, "railingQuote": q, "productType": "staircase_railing"},
}
r = calculate_line(cart)
if "staircase" in str(r.get("description") or "").lower():
    fails.append(f"stale desc kept: {r.get('description')}")
if r.get("productType") != "railing":
    fails.append(f"productType {r.get('productType')}")
if "straight" not in str(r.get("description") or ""):
    fails.append(f"desc missing straight: {r.get('description')}")
specs = _spec_lines(r)
if "staircase" in specs[0].lower():
    fails.append(f"PDF title still staircase: {specs[0]}")
if "Type = straight" not in specs[1]:
    fails.append(f"PDF type wrong: {specs[1]}")

# B) BOM anchors must flow into total; cart sellingRate must not freeze
anchor_amt = next((i["amount"] for i in q["items"] if i["key"] == "anchors"), 0)
glass_amt = next((i["amount"] for i in q["items"] if i["key"] == "glass"), 0)
if anchor_amt <= 0:
    fails.append(f"anchors missing from BOM: {[(i['key'], i['amount']) for i in q['items']]}")
expected = round(glass_amt + anchor_amt, 2)
# sellingTotal from cascade (no manual) should include anchors
if abs(q["sellingTotal"] - expected) > 1.0:
    fails.append(f"cascade total {q['sellingTotal']} != glass+anchors {expected}")
# calculate_line must ignore frozen sellingRate 639.95
if abs(float(r["commercialTotal"]) - expected) > 1.0:
    fails.append(
        f"calc total {r['commercialTotal']} ignored BOM (expected ~{expected}); "
        f"rate={r.get('sellingRate')}"
    )
# With vs without anchors
cfg0 = dict(cfg)
cfg0["rates"] = {"glassPerSqft": 200, "anchorPerPc": 0, "bottomRailPerUnit": 0}
q0 = compute_railing(cfg0)
if not (q["sellingTotal"] > q0["sellingTotal"] + 100):
    fails.append(f"anchor rate did not raise total: {q0['sellingTotal']} -> {q['sellingTotal']}")

# C) stale staircase quote on straight cfg must recompute for PDF
stair_q = compute_railing(
    {
        "shape": "staircase",
        "stairSteps": 12,
        "stairRiseMm": 180,
        "stairRunMm": 305,
        "panels": 4,
        "glassHeightMm": 900,
        "rates": {"glassPerSqft": 200, "anchorPerPc": 50, "blockPerPc": 100},
    }
)
stale = {
    "product": "railing",
    "productType": "railing",
    "width": 4958.15,
    "height": 900,
    "qty": 1,
    "description": "Railing · staircase · 4958.15 mm · 4 panels · 12mm",
    "options": {"railing": cfg, "railingQuote": stair_q, "productType": "railing"},
}
_, qfix = _railing_cfg_and_quote(stale)
if qfix.get("shape") != "straight" or int(qfix.get("panelCount") or 0) != 1:
    fails.append(f"stale quote not recomputed: shape={qfix.get('shape')} panels={qfix.get('panelCount')}")
sp = _spec_lines(stale)
if "staircase" in sp[0].lower() or "Type = staircase" in sp[1]:
    fails.append(f"stale PDF specs: {sp[:2]}")

# D) stairs path still works
scfg = {
    "shape": "staircase",
    "stairSteps": 10,
    "stairRiseMm": 180,
    "stairRunMm": 280,
    "panels": 3,
    "glassHeightMm": 900,
    "rates": {"glassPerSqft": 200, "anchorPerPc": 50, "blockPerPc": 100, "studPerPc": 80},
    "installComponents": {"bottomRail": False, "block": True, "ssPillar": False, "handrail": True, "glass": True},
}
sq = compute_railing(scfg)
sr = calculate_line(
    {
        "product": "railing",
        "productType": "staircase_railing",
        "width": sq["lengthMm"],
        "height": 900,
        "qty": 1,
        "options": {"railing": scfg},
    }
)
if sr.get("productType") != "staircase_railing":
    fails.append(f"stairs productType {sr.get('productType')}")
if "staircase" not in str(sr.get("description") or "").lower():
    fails.append(f"stairs desc {sr.get('description')}")
if float(sr.get("commercialTotal") or 0) <= 0:
    fails.append("stairs total empty")

# E) length seed from cart width (no regress ca9592e)
typed = calculate_line(
    {
        "product": "custom_balcony",
        "productType": "railing",
        "category": "Railings",
        "width": 3000,
        "height": 1000,
        "qty": 1,
    }
)
tq = typed.get("railing") or {}
if float(tq.get("lengthMm") or 0) < 2990:
    fails.append(f"width seed regress: {tq.get('lengthMm')}")

out = "PASS\n" if not fails else ("FAIL\n" + "\n".join(fails) + "\n")
open("_verify_railing_quote_fix.txt", "w", encoding="utf-8").write(out)
print(out)
raise SystemExit(1 if fails else 0)
