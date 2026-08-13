"""DESIGN serial + optional location/position name (W8 · Master Bedroom)."""
from __future__ import annotations

from WEOS.factory.line_kind import design_serial_label, line_location_name
from WEOS.factory.project_engine import calculate_line


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    _ok(line_location_name({"locationName": "Kitchen"}) == "Kitchen", "locationName")
    _ok(line_location_name({"positionName": "Balcony"}) == "Balcony", "positionName alias")
    _ok(line_location_name({"options": {"locationName": "Toilet"}}) == "Toilet", "options.locationName")
    _ok(line_location_name({}) == "", "empty is blank")
    _ok(design_serial_label(7, {"locationName": "Master Bedroom"}) == "W8 · Master Bedroom", "W8 · Master Bedroom")
    _ok(design_serial_label(0, {}) == "W1", "serial only when no location")
    _ok(design_serial_label(2, {"positionName": "Kitchen"}) == "W3 · Kitchen", "W3 · Kitchen")

    vent = calculate_line({
        "product": "bathroom_ventilator",
        "productType": "bathroom_ventilator",
        "width": 600,
        "height": 450,
        "qty": 1,
        "sellingRate": 400,
        "locationName": "Toilet",
        "options": {"ventilator": {"widthMm": 600, "heightMm": 450, "sellingRate": 400}, "productType": "bathroom_ventilator"},
    })
    _ok(vent.get("locationName") == "Toilet", f"calc keeps locationName got {vent.get('locationName')}")
    _ok(design_serial_label(0, vent) == "W1 · Toilet", "calc line serial+location")
    print("SMOKE_LOCATION_SERIAL_OK")


if __name__ == "__main__":
    main()
