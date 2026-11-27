"""Smoke: structural section material/shape filters + Al louver tagging."""
from __future__ import annotations

from WEOS.factory.gate_engine import compute_gate
from WEOS.factory.structural_catalogue import (
    build_structural_catalogue,
    list_structural_sections,
    material_family,
    section_facets,
)


def main() -> int:
    fails: list[str] = []
    pack = build_structural_catalogue(persist=True)
    secs = pack.get("sections") or []
    facets = pack.get("facets") or section_facets(secs)

    iron_sq = list_structural_sections(material="iron", shape="hollow_sq")
    if not iron_sq:
        fails.append("Iron + square hollow returned 0")
    for s in iron_sq:
        if material_family(s.get("material")) != "iron":
            fails.append(f"non-iron in iron filter {s.get('sectionId')}")
            break
        if str(s.get("shape")) != "hollow_sq":
            fails.append(f"non-square in square filter {s.get('sectionId')} shape={s.get('shape')}")
            break

    al_rect = list_structural_sections(material="aluminium", shape="hollow_rect")
    if not al_rect:
        fails.append("Al + rectangle hollow returned 0")
    for s in al_rect:
        if material_family(s.get("material")) != "aluminium":
            fails.append(f"non-al in al filter {s.get('sectionId')}")
            break
        if str(s.get("shape")) != "hollow_rect":
            fails.append(f"non-rect in rect filter {s.get('sectionId')}")
            break

    al_all = list_structural_sections(material="aluminium")
    al_louverish = [
        s for s in al_all
        if str(s.get("shape")) in ("louver", "oval_louver", "hollow_sq", "hollow_rect", "flat")
    ]
    if len(al_louverish) < 20:
        fails.append(f"too few Al blade-capable sections {len(al_louverish)}")

    # Tags present
    missing_tag = [s.get("sectionId") for s in secs[:50] if not s.get("materialFamily") or not s.get("shapeLabel")]
    if missing_tag:
        fails.append(f"missing tags {missing_tag[:5]}")

    # Facets
    mats = {m["id"]: m["count"] for m in (facets.get("materials") or [])}
    if mats.get("iron", 0) < 100 or mats.get("aluminium", 0) < 50:
        fails.append(f"facet counts low {mats}")

    # Al 25×25 still costs via gate pattern
    al25 = next(
        (
            s for s in al_all
            if abs(float(s.get("widthMm") or 0) - 25) < 0.6
            and abs(float(s.get("heightMm") or 0) - 25) < 0.6
            and str(s.get("shape")) == "hollow_sq"
        ),
        None,
    )
    if not al25:
        fails.append("Al 25×25 hollow_sq missing")
    else:
        q = compute_gate(
            {
                "widthFt": 4,
                "heightFt": 4,
                "bayType": "fixed_louvers",
                "foldLeft": 0,
                "foldRight": 0,
                "louverSectionId": al25["sectionId"],
                "louverPattern": [
                    {"sectionId": al25["sectionId"], "gapAfterMm": 30},
                ],
                "alRatePerBar": 1459,
                "msRatePerKg": 215,
            }
        )
        blades = [c for c in (q.get("cuts") or []) if c.get("memberRole") == "louver_blade"]
        if not blades:
            fails.append("no louver blades in BOM for Al 25×25")
        elif any(c.get("sectionId") != al25["sectionId"] for c in blades):
            fails.append("blade sectionId drift")
        nests = q.get("nests") or {}
        if al25["sectionId"] not in nests:
            fails.append("Al 25×25 not nested in cost")
        elif float((nests[al25["sectionId"]] or {}).get("usedM") or 0) <= 0:
            fails.append("Al 25×25 usedM zero")

    if fails:
        print("FAIL section picker:")
        for f in fails:
            print(" -", f)
        return 1
    print(
        f"OK section picker · total={len(secs)} iron_sq={len(iron_sq)} al_rect={len(al_rect)} "
        f"al_bladeish={len(al_louverish)} al25={al25 and al25.get('sectionId')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
