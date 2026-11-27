"""Smoke: gates_privacy loads without window-section error; desc flow + rich copy."""
from __future__ import annotations

from WEOS.factory.gate_engine import compute_gate, format_gate_description, gate_customer_spec_rows
from WEOS.factory.marqt_pdf import _spec_rows
from WEOS.factory.product_loader import load_product
from WEOS.factory.structural_catalogue import build_structural_catalogue


def main() -> int:
    fails: list[str] = []
    build_structural_catalogue(persist=True)

    # --- Fix 1: product load must not raise missing/invalid sections ---
    try:
        doc = load_product("gates_privacy", strict=True)
    except ValueError as exc:
        fails.append(f"load_product strict raised: {exc}")
        doc = {}
    if "missing/invalid sections" in str(doc):
        fails.append("unexpected missing sections in doc")
    if not doc.get("_specialty") and str(doc.get("productType") or "") != "gate":
        # specialty flag OR gate type is enough
        if str(doc.get("productType") or "") != "gate":
            fails.append("gates_privacy not recognized as gate/specialty")

    q = compute_gate({
        "widthFt": 6.726,
        "heightFt": 6.463,
        "bayType": "folding_privacy",
        "foldLeft": 2,
        "foldRight": 2,
        "msRatePerKg": 215,
        "alRatePerBar": 850,
        "fabRatePerSft": 150,
        "coatingRate": 25,
        "hardwarePackageAmount": 10000,
        "finish": "white",
    })
    line = {
        "product": "gates_privacy",
        "productType": "gate",
        "category": "Gates",
        "displayName": "Gates / Privacy screens",
        "width": q.get("widthMm"),
        "height": q.get("heightMm"),
        "qty": 1,
        "saleUnit": "sqft",
        "sellingRate": 436.6,
        "commercialTotal": 18978.35,
        "options": {"gate": {}, "gateQuote": q, "productType": "gate"},
        "gate": q,
        "selling": {"sellingRate": 436.6, "sellingAmount": 18978.35, "saleUnit": "sqft"},
    }

    rows = _spec_rows(line)
    if not any(str(a) == "__FLOW__" for a, _ in rows):
        fails.append("gate spec rows missing __FLOW__ marker")
    if any(str(a).upper() == "CATEGORY" for a, _ in rows):
        fails.append("old skinny CATEGORY table still present")
    blob = " | ".join(f"{a}:{b}" for a, b in rows)
    for needle in ("WEIGHT", "SECTIONS", "HARDWARE", "FINISH", "CHARGE"):
        if needle not in blob:
            fails.append(f"rich desc missing {needle}")
    # Outer frame dims should appear somewhere
    if "75" not in blob and "frame" not in blob.lower() and "Outer" not in blob:
        fails.append(f"expected frame/section dims in desc: {blob[:240]}")
    # Not only a 2-col skinny table — flow marker + multi-field paragraphs
    labeled = [a for a, b in rows if a and a != "__FLOW__"]
    if len(labeled) < 4:
        fails.append(f"too few labeled paragraphs: {labeled}")

    desc = format_gate_description(q, {})
    if "kg" not in desc.lower() and "WEIGHT" not in desc:
        # format_gate joins with · so WEIGHT: ... kg
        if "Iron" not in desc and "Al" not in desc:
            fails.append(f"format_gate_description missing weights: {desc[:200]}")

    g_rows = gate_customer_spec_rows(q, line=line)
    if not any(a == "HARDWARE" for a, _ in g_rows):
        fails.append("gate_customer_spec_rows missing HARDWARE")

    if fails:
        print("FAIL gate preview/desc:")
        for f in fails:
            print(" -", f)
        return 1
    print(
        f"OK gate preview/desc · specialty={doc.get('_specialty')} · "
        f"flow_rows={len(rows)} · labels={[a for a,_ in rows if a and a!='__FLOW__']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
