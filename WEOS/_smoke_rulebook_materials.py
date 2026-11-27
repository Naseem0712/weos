"""Regression checks for fabrication quantities shared by costing and materials."""
from math import isclose

from WEOS.factory.materials_list import materials_rows_for_line


def main():
    from pathlib import Path
    from WEOS.factory.live_pricing import live_price

    for path in sorted((Path(__file__).parent / "products").glob("[0-9]*/product.json")):
        pid = path.parent.name
        amounts = []
        missing = []
        for width, height in ((1050, 970), (1550, 970), (1050, 1470)):
            line = {"product": pid, "width": width, "height": height, "glass": "8mm_toughened",
                    "glassShutters": 1 if "casement" in pid else 2}
            dc = live_price(line)["designCost"]
            assert dc and dc["ok"], (pid, width, height)
            amounts.append(dc["aluminiumCost"])
            missing.append(dc.get("missingMaterialRates"))
        if amounts[0] > 0:
            assert min(amounts[1:]) > amounts[0], (pid, amounts)
        else:
            assert all(missing) and all(v == 0 for v in amounts), (pid, amounts, missing)
        print(pid, amounts, "missing rates:", missing[0], flush=True)
    for glass_id, clip in (("8mm_toughened", "clip sg"), ("dgu_5_12_5", "clip dg")):
        line = {
            "product": "50mm_casement_prestige", "glass": glass_id, "qty": 2,
            "system": "casement", "width": 1600, "height": 1500,
            "casementLayout": {"bands": [{"heightMm": 1500, "panels": [
                {"role": "door", "widthMm": 900}, {"role": "fix", "widthMm": 700},
            ]}]},
        }
        row = materials_rows_for_line(line)
        profiles = row["materials"]
        for use, expected in (("outer_frame", 4), ("door", 4), ("mullion", 1), ("glass_clip", 8)):
            selected = [p for p in profiles if p["use"] == use]
            assert sum(p["pcs"] for p in selected) == expected, (use, selected)
            assert len({p["sectionId"] for p in selected}) == 1, selected
        assert all(p["name"].lower() == clip for p in profiles if p["use"] == "glass_clip")
        assert row["glass"]["pcs"] == 2 and len(row["glass"]["panes"]) == 2
        glass_seal = next(h for h in row["hardware"] if "gasket — glass" in h["name"].lower())
        expected = sum(4 * (p["widthMm"] + p["heightMm"]) / 1000 for p in row["glass"]["panes"])
        assert isclose(glass_seal["qty"], expected, abs_tol=.0001) and glass_seal["amount"] > 0
    fixed_case = dict(line, product="40mm_casement_standard", glass="8mm_toughened")
    row = materials_rows_for_line(fixed_case)
    assert sum(p["pcs"] for p in row["materials"] if p["use"] == "glass_clip") == 4
    assert not row["missingClip"]

    from WEOS.factory.materials_list import build_quote_materials_list
    pack = build_quote_materials_list([line])
    clips = [s for s in pack["materialsSummary"] if s["name"].lower() == "clip dg"]
    assert sum(s["qty"] for s in clips) == 16
    assert all(s["unit"] == "pcs" and s["metres"] > 0 for s in clips)
    from WEOS.factory.materials_list import materials_list_html
    assert "Total cut m" in materials_list_html(pack)
    row = materials_rows_for_line({
        "product": "35mm_gulf", "system": "sliding", "width": 1050, "height": 970,
        "trackCount": 2, "glassShutters": 2, "glass": "8mm_toughened",
    })
    assert sum(p["pcs"] for p in row["materials"] if p["use"] == "track") == 4
    rail = next(h for h in row["hardware"] if "track rail" in h["name"].lower())
    assert rail["unit"] == "RFT" and isclose(rail["qty"], 2.1 / .3048, abs_tol=.0001)
    assert rail["unitRate"] > 0
    assert all(p["heightMm"] < 970 for p in row["glass"]["panes"])


if __name__ == "__main__":
    main()
