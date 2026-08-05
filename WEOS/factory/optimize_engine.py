"""Material optimization — glass nesting, aluminium bar packing, leftover stock reuse.

Heuristics (documented):
- Bars: First-Fit Decreasing (FFD) into leftover stock first, then new stock bars.
- Glass: Shelf / guillotine-style packing onto fixed sheets (rotate allowed).
Not a full commercial nesting solver — good enough for factory planning demos.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from WEOS.paths import PACKAGE_ROOT, stock_dir

WEOS_ROOT = PACKAGE_ROOT
DEFAULT_STOCK_PATH = stock_dir() / "inventory.json"


@dataclass
class CutPiece:
    length_mm: float
    label: str = ""
    qty: int = 1


@dataclass
class GlassPiece:
    width_mm: float
    height_mm: float
    label: str = ""
    qty: int = 1
    thickness_mm: float = 5.0


def load_stock(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else DEFAULT_STOCK_PATH
    if not p.is_file():
        return {
            "glassSheets": [{"id": "GS-3660x2440", "widthMm": 3660, "heightMm": 2440}],
            "aluminiumBars": [{"id": "BAR-6500", "lengthMm": 6500}],
            "leftoverStock": [],
        }
    return json.loads(p.read_text(encoding="utf-8"))


def expand_pieces(pieces: Sequence[CutPiece]) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    for p in pieces:
        for _ in range(max(int(p.qty), 0)):
            out.append((float(p.length_mm), p.label or f"{p.length_mm:.0f}"))
    return out


def first_fit_decreasing_bars(
    pieces: Sequence[CutPiece],
    *,
    bar_length_mm: float = 6500.0,
    leftovers: Sequence[Mapping[str, Any]] | None = None,
    kerf_mm: float = 3.0,
) -> dict[str, Any]:
    """
    Pack linear cuts: sort longest-first, fill leftover stock first, then new bars.
    Returns bars used, leftover consumption, waste %, purchase list.
    """
    items = expand_pieces(pieces)
    items.sort(key=lambda x: x[0], reverse=True)

    bins: list[dict[str, Any]] = []

    # Seed bins from leftover inventory (reusable lengths)
    for lo in leftovers or []:
        length = float(lo.get("lengthMm", lo.get("length_mm", 0)))
        if length <= 0:
            continue
        bins.append(
            {
                "source": "leftover",
                "id": lo.get("id", "LO"),
                "capacity": length,
                "remaining": length,
                "cuts": [],
            }
        )

    new_bar_count_before = 0

    def place(length: float, label: str) -> None:
        need = length + kerf_mm
        # try existing bins
        for b in bins:
            if b["remaining"] >= need:
                b["remaining"] -= need
                b["cuts"].append({"lengthMm": length, "label": label})
                return
        # open new stock bar
        bins.append(
            {
                "source": "new",
                "id": f"BAR-{bar_length_mm:.0f}",
                "capacity": float(bar_length_mm),
                "remaining": float(bar_length_mm) - need,
                "cuts": [{"lengthMm": length, "label": label}],
            }
        )

    for length, label in items:
        if length > bar_length_mm:
            raise ValueError(f"Cut {length} mm exceeds bar length {bar_length_mm} mm")
        place(length, label)

    used_leftovers = [b for b in bins if b["source"] == "leftover" and b["cuts"]]
    new_bars = [b for b in bins if b["source"] == "new"]
    total_capacity = sum(b["capacity"] for b in bins if b["cuts"])
    total_used = sum(sum(c["lengthMm"] for c in b["cuts"]) for b in bins)
    waste = max(total_capacity - total_used, 0.0)
    waste_pct = (waste / total_capacity * 100.0) if total_capacity else 0.0

    purchase = []
    if new_bars:
        purchase.append(
            {
                "item": f"Aluminium bar {bar_length_mm/1000:.1f} m",
                "qty": len(new_bars),
                "unit": "bars",
                "lengthMm": bar_length_mm,
            }
        )

    return {
        "algorithm": "first_fit_decreasing",
        "kerfMm": kerf_mm,
        "barLengthMm": bar_length_mm,
        "pieceCount": len(items),
        "leftoversUsed": [
            {"id": b["id"], "capacityMm": b["capacity"], "remainingMm": round(b["remaining"], 1), "cuts": b["cuts"]}
            for b in used_leftovers
        ],
        "newBars": len(new_bars),
        "barsDetail": [
            {"source": b["source"], "id": b["id"], "remainingMm": round(b["remaining"], 1), "cuts": b["cuts"]}
            for b in bins
            if b["cuts"]
        ],
        "totalUsedMm": round(total_used, 1),
        "totalCapacityMm": round(total_capacity, 1),
        "wasteMm": round(waste, 1),
        "wastePercent": round(waste_pct, 2),
        "purchaseList": purchase,
    }


def nest_glass_shelf(
    pieces: Sequence[GlassPiece],
    *,
    sheet_w: float = 3660.0,
    sheet_h: float = 2440.0,
    gap_mm: float = 5.0,
    allow_rotate: bool = True,
) -> dict[str, Any]:
    """
    Shelf packing heuristic for rectangular glass on fixed sheets.
    Places pieces left-to-right on shelves; opens new shelf / sheet when needed.
    Limitation: not true free-form nesting; waste % is approximate but usable.
    """
    rects: list[tuple[float, float, str]] = []
    for p in pieces:
        for _ in range(max(int(p.qty), 0)):
            w, h = float(p.width_mm), float(p.height_mm)
            if allow_rotate and h > w and h <= sheet_w and w <= sheet_h:
                # prefer orientation that fits better later — keep as-is for now; rotate if needed at place
                pass
            rects.append((w, h, p.label or f"{w:.0f}x{h:.0f}"))

    rects.sort(key=lambda r: max(r[0], r[1]), reverse=True)

    sheets: list[dict[str, Any]] = []

    def new_sheet() -> dict[str, Any]:
        s = {"index": len(sheets) + 1, "placements": [], "shelves": []}
        sheets.append(s)
        return s

    def try_place(sheet: dict[str, Any], w: float, h: float, label: str) -> bool:
        orientations = [(w, h)]
        if allow_rotate and w != h:
            orientations.append((h, w))
        for ow, oh in orientations:
            if ow + gap_mm > sheet_w or oh + gap_mm > sheet_h:
                continue
            # try existing shelves
            for shelf in sheet["shelves"]:
                if oh <= shelf["height"] and shelf["x"] + ow + gap_mm <= sheet_w:
                    sheet["placements"].append(
                        {
                            "x": shelf["x"],
                            "y": shelf["y"],
                            "widthMm": ow,
                            "heightMm": oh,
                            "label": label,
                        }
                    )
                    shelf["x"] += ow + gap_mm
                    return True
            # new shelf under last
            y = 0.0
            if sheet["shelves"]:
                last = sheet["shelves"][-1]
                y = last["y"] + last["height"] + gap_mm
            if y + oh + gap_mm <= sheet_h:
                shelf = {"y": y, "height": oh, "x": 0.0}
                sheet["shelves"].append(shelf)
                sheet["placements"].append(
                    {"x": 0.0, "y": y, "widthMm": ow, "heightMm": oh, "label": label}
                )
                shelf["x"] = ow + gap_mm
                return True
        return False

    if not rects:
        return {
            "algorithm": "shelf_packing",
            "sheetSizeMm": [sheet_w, sheet_h],
            "sheetsNeeded": 0,
            "wastePercent": 0.0,
            "placements": [],
            "limitations": ["Shelf packing heuristic — not commercial nesting CAM."],
        }

    sheet = new_sheet()
    for w, h, label in rects:
        if not try_place(sheet, w, h, label):
            sheet = new_sheet()
            if not try_place(sheet, w, h, label):
                raise ValueError(f"Glass {w}x{h} does not fit sheet {sheet_w}x{sheet_h}")

    sheet_area = sheet_w * sheet_h
    used_area = sum(p["widthMm"] * p["heightMm"] for s in sheets for p in s["placements"])
    total_sheet_area = sheet_area * len(sheets)
    waste = max(total_sheet_area - used_area, 0.0)
    waste_pct = (waste / total_sheet_area * 100.0) if total_sheet_area else 0.0

    return {
        "algorithm": "shelf_packing",
        "sheetSizeMm": [sheet_w, sheet_h],
        "gapMm": gap_mm,
        "allowRotate": allow_rotate,
        "pieceCount": len(rects),
        "sheetsNeeded": len(sheets),
        "usedAreaMm2": round(used_area, 1),
        "totalSheetAreaMm2": round(total_sheet_area, 1),
        "wastePercent": round(waste_pct, 2),
        "sheets": sheets,
        "purchaseList": [
            {
                "item": f"Glass sheet {sheet_w:.0f}×{sheet_h:.0f} mm",
                "qty": len(sheets),
                "unit": "sheets",
            }
        ],
        "limitations": [
            "Shelf/guillotine-style heuristic — not true free-form nesting.",
            "Does not model breakout sequence or scoring paths.",
        ],
    }


def optimize_project_materials(
    *,
    cut_pieces: Sequence[CutPiece],
    glass_pieces: Sequence[GlassPiece],
    stock: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stock = stock or load_stock()
    bars = stock.get("aluminiumBars") or [{"lengthMm": 6500}]
    bar_len = float(bars[0].get("lengthMm", 6500))
    leftovers = [lo for lo in (stock.get("leftoverStock") or []) if lo.get("material", "aluminium") == "aluminium"]
    sheets = stock.get("glassSheets") or [{"widthMm": 3660, "heightMm": 2440}]
    sw = float(sheets[0].get("widthMm", 3660))
    sh = float(sheets[0].get("heightMm", 2440))

    bar_opt = first_fit_decreasing_bars(cut_pieces, bar_length_mm=bar_len, leftovers=leftovers)
    glass_opt = nest_glass_shelf(glass_pieces, sheet_w=sw, sheet_h=sh)

    purchase = list(bar_opt.get("purchaseList") or []) + list(glass_opt.get("purchaseList") or [])
    return {
        "aluminium": bar_opt,
        "glass": glass_opt,
        "purchaseList": purchase,
        "stockSource": str(DEFAULT_STOCK_PATH.as_posix()),
    }
