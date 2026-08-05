"""Import cart lines from CSV / Excel. AutoCAD schedule = stub."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from WEOS.paths import output_dir


def _norm_header(h: str) -> str:
    return h.strip().lower().replace(" ", "_").replace("-", "_")


_HEADER_MAP = {
    "product": "product",
    "product_id": "product",
    "series": "product",
    "profile": "product",
    "w": "width",
    "width": "width",
    "width_mm": "width",
    "h": "height",
    "height": "height",
    "height_mm": "height",
    "qty": "qty",
    "quantity": "qty",
    "qty_nos": "qty",
    "glass": "glass",
    "colour": "colour",
    "color": "colour",
    "handle": "handle",
    "category": "category",
}


def rows_to_lines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = []
    for i, row in enumerate(rows, start=1):
        mapped: dict[str, Any] = {"lineId": f"L{i:03d}"}
        for k, v in row.items():
            key = _HEADER_MAP.get(_norm_header(str(k)), None)
            if key and v not in (None, ""):
                mapped[key] = v
        if "product" not in mapped:
            mapped["product"] = "29mm_sliding"
        mapped["width"] = float(mapped.get("width") or 0)
        mapped["height"] = float(mapped.get("height") or 0)
        mapped["qty"] = int(float(mapped.get("qty") or 1))
        if mapped["width"] > 0 and mapped["height"] > 0:
            lines.append(mapped)
    return lines


def import_csv_text(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    return rows_to_lines(list(reader))


def import_csv_file(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    return import_csv_text(path.read_text(encoding="utf-8-sig"))


def import_excel_file(path: str | Path) -> list[dict[str, Any]]:
    try:
        import openpyxl
    except ImportError as exc:
        raise ImportError("openpyxl required for Excel import: pip install openpyxl") from exc
    path = Path(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h or "") for h in next(rows_iter)]
    rows = []
    for raw in rows_iter:
        row = {headers[i]: raw[i] for i in range(len(headers)) if i < len(raw)}
        rows.append(row)
    return rows_to_lines(rows)


def import_autocad_schedule_stub(path: str | Path) -> dict[str, Any]:
    """Scaffold only — plug real schedule parser later."""
    return {
        "status": "not_implemented",
        "source": str(path),
        "message": "AutoCAD schedule parser stub — use CSV/Excel import for now.",
        "lines": [],
    }


def import_bytes(filename: str, data: bytes) -> list[dict[str, Any]]:
    name = filename.lower()
    if name.endswith(".csv"):
        return import_csv_text(data.decode("utf-8-sig"))
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        tmp = output_dir() / "_import_tmp.xlsx"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        try:
            return import_excel_file(tmp)
        finally:
            tmp.unlink(missing_ok=True)
    if name.endswith(".dxf"):
        raise ValueError("DXF schedule import not implemented — use CSV/Excel")
    raise ValueError(f"Unsupported import type: {filename}")
