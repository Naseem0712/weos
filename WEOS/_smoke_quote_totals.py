"""Quote TOTALS must break qty down by product type — never lump all as Windows."""
from __future__ import annotations

from WEOS.factory.line_kind import quote_qty_breakdown, totals_group_for_line
from WEOS.factory.project_engine import combine_lines, calculate_line


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    lines = [
        {"productType": "sliding", "product": "29mm_sliding", "category": "Windows", "qty": 4, "displayName": "Sliding"},
        {"productType": "door", "product": "style_door", "category": "Doors", "qty": 2, "displayName": "Door"},
        {"productType": "casements", "product": "casement_stub", "category": "Windows", "qty": 3, "displayName": "Casement"},
        {"productType": "shower_partition", "product": "shower_partition", "category": "Bathrooms", "qty": 2,
         "options": {"shower": {"widthMm": 1200, "heightMm": 2000}, "productType": "shower_partition"}},
        {"productType": "bathroom_ventilator", "product": "bathroom_ventilator", "category": "Bathrooms", "qty": 5,
         "options": {"ventilator": {"widthMm": 600, "heightMm": 450}, "productType": "bathroom_ventilator"}},
        {"productType": "railing", "product": "railings_stub", "category": "Railings", "qty": 6,
         "options": {"railing": {"shape": "straight", "lengthMm": 2400}}},
        {"productType": "staircase_railing", "product": "railings_stub", "category": "Railings", "qty": 1,
         "options": {"railing": {"shape": "staircase", "lengthMm": 3000}}},
        {"product": "louvers_stub", "productType": "louvers_stub", "category": "Facades", "qty": 2, "displayName": "Louvers"},
        {"product": "acp_stub", "productType": "acp_stub", "category": "Facades", "qty": 1, "displayName": "ACP"},
    ]
    groups = dict(quote_qty_breakdown(lines))
    print("groups:", groups)
    _ok(groups.get("Windows") == 7, f"windows=7 (4 sliding + 3 casement) got {groups.get('Windows')}")
    _ok(groups.get("Doors") == 2, f"doors=2 got {groups.get('Doors')}")
    _ok(groups.get("Showers") == 2, f"showers=2 got {groups.get('Showers')}")
    _ok(groups.get("Bathroom ventilators") == 5, f"vents=5 got {groups.get('Bathroom ventilators')}")
    _ok(groups.get("Railings") == 6, f"railings=6 got {groups.get('Railings')}")
    _ok(groups.get("Staircase railings") == 1, f"stairs=1 got {groups.get('Staircase railings')}")
    _ok(groups.get("Louvers") == 2, f"louvers=2 got {groups.get('Louvers')}")
    _ok(groups.get("ACP") == 1, f"acp=1 got {groups.get('ACP')}")
    _ok("Windows" in groups and groups["Windows"] != 26, "must not lump everything as Windows")
    _ok(totals_group_for_line(lines[3]) == "Showers", "shower line is Showers not Windows")
    _ok(totals_group_for_line(lines[4]) == "Bathroom ventilators", "ventilator is not Windows/Showers")

    calc_lines = [
        calculate_line({
            "product": "bathroom_ventilator",
            "productType": "bathroom_ventilator",
            "width": 600, "height": 450, "qty": 3,
            "sellingRate": 450,
            "options": {"ventilator": {"widthMm": 600, "heightMm": 450, "sellingRate": 450}, "productType": "bathroom_ventilator"},
        }),
        calculate_line({
            "product": "29mm_sliding",
            "productType": "sliding",
            "width": 1200, "height": 1500, "qty": 2,
            "sellingRate": 800,
        }),
    ]
    combined = combine_lines(calc_lines)
    by = {g["label"]: g["qty"] for g in combined.get("qtyByGroup") or []}
    print("combined qtyByGroup:", by)
    _ok(by.get("Bathroom ventilators") == 3, f"combined vents=3 got {by}")
    _ok(by.get("Windows") == 2, f"combined windows=2 got {by}")
    print("SMOKE_QUOTE_TOTALS_OK")


if __name__ == "__main__":
    main()
