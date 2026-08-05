"""Heuristic DXF rule extraction for two-track sliding geometry.

Extracts candidate geometry / dimensioning deltas from DIMENSION entities.
Does NOT copy DXF entities into production drawings.
Does NOT invent catalogue OCR — PDF/image hooks are stubs for later.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from learning.provenance import rule_review_row

# Known two-track geometry keys we attempt to infer from dimension clusters
_GEOMETRY_CANDIDATES = (
    "trackWidth",
    "frameWidth",
    "interlockWidth",
    "overlap",
    "glassClip",
)


def _round_mm(v: float, ndigits: int = 1) -> float:
    return round(float(v), ndigits)


def extract_dxf_dimensions(path: Path) -> list[float]:
    """Return positive measurement values from DIMENSION entities."""
    import ezdxf

    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    values: list[float] = []
    for e in msp.query("DIMENSION"):
        try:
            meas = float(e.get_measurement())
        except Exception:
            meas = getattr(e.dxf, "actual_measurement", None)
            meas = float(meas) if meas is not None else None
        if meas is None:
            continue
        if 1.0 <= meas <= 500.0:  # profile-section scale, not overall opening
            values.append(_round_mm(meas, 1))
    return values


def extract_dxf_dim_style(path: Path) -> dict[str, Any]:
    """Pull DIMASZ / DIMTXT style hints from DXF header when present."""
    import ezdxf

    doc = ezdxf.readfile(str(path))
    out: dict[str, Any] = {}
    try:
        asz = doc.header.get("$DIMASZ")
        if asz is not None:
            out["arrowSize"] = float(asz)
    except Exception:
        pass
    try:
        txt = doc.header.get("$DIMTXT")
        if txt is not None:
            out["textHeight"] = float(txt)
    except Exception:
        pass
    return out


def _guess_geometry_from_measurements(
    measurements: list[float],
    baseline: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """
    Heuristic: cluster small dimension values and map frequent sizes onto
    known geometry keys using proximity to an existing baseline (if any).
    """
    if not measurements:
        return []

    counts = Counter(measurements)
    # Prefer values that appear more than once, else unique sorted ascending
    frequent = [v for v, c in counts.most_common() if c >= 1 and v < 200]

    baseline = baseline or {
        "trackWidth": 30.0,
        "frameWidth": 65.0,
        "interlockWidth": 22.0,
        "overlap": 8.0,
        "glassClip": 10.0,
    }

    used: set[float] = set()
    rows: list[dict[str, Any]] = []

    for key in _GEOMETRY_CANDIDATES:
        target = float(baseline.get(key, 0))
        # Find closest unused measurement within 40% of target (or absolute 15 mm)
        best = None
        best_dist = 1e9
        for v in frequent:
            if v in used:
                continue
            dist = abs(v - target) if target else abs(v)
            tol = max(15.0, abs(target) * 0.4) if target else 25.0
            if dist < best_dist and dist <= tol:
                best = v
                best_dist = dist
        if best is None:
            continue
        used.add(best)
        # Confidence: higher when close to baseline or repeated in DXF
        proximity = 1.0 - min(best_dist / max(target, 1.0), 1.0) if target else 0.5
        repeats = counts[best]
        conf = 0.45 + 0.35 * proximity + min(0.15, 0.05 * (repeats - 1))
        conf = max(0.4, min(0.95, conf))
        source = "dxf_dimension_heuristic"
        action = "set" if abs(best - target) > 0.05 else "unchanged"
        if action == "unchanged":
            conf = min(conf + 0.05, 0.98)
        rows.append(
            rule_review_row(
                f"geometry.{key}",
                best,
                conf,
                source,
                existing_value=target,
                action=action if abs(best - target) > 0.05 else "confirm",
            )
        )
    return rows


def extract_rules_from_dxf(
    path: str | Path,
    *,
    profile_id_hint: str | None = None,
    baseline_geometry: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Extract candidate engineering rules from a master DXF reference.

    Returns a structured extraction package (not a production profile write).
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    measurements = extract_dxf_dimensions(path)
    dim_style = extract_dxf_dim_style(path)
    geom_rows = _guess_geometry_from_measurements(measurements, baseline_geometry)

    # Overall opening guesses: largest dimensions (not profile sections)
    import ezdxf

    doc = ezdxf.readfile(str(path))
    overall: list[float] = []
    for e in doc.modelspace().query("DIMENSION"):
        try:
            meas = float(e.get_measurement())
        except Exception:
            continue
        if meas >= 500:
            overall.append(_round_mm(meas, 1))

    series_guess = profile_id_hint or _guess_series_id(path, geom_rows)

    dim_rows: list[dict[str, Any]] = []
    for key, val in dim_style.items():
        dim_rows.append(
            rule_review_row(
                f"dimensioning.{key}",
                val,
                0.7,
                f"dxf_header:{path.name}",
                action="set",
            )
        )

    return {
        "extractor": "dxf_heuristic_v1",
        "source_path": str(path.resolve()),
        "source_type": "dxf",
        "series_guess": series_guess,
        "measurements_mm": measurements[:80],
        "overall_dims_mm": sorted(set(overall), reverse=True)[:8],
        "rules": geom_rows + dim_rows,
        "notes": [
            "Heuristic extraction from DIMENSION clusters — review before approve.",
            "Glass/hardware/brush/cut/quotation rules are not inferred from DXF geometry.",
            "PDF/image catalogue OCR is not implemented; use extract_rules_from_json or stubs.",
        ],
    }


def extract_rules_from_json(path: str | Path, *, profile_id_hint: str | None = None) -> dict[str, Any]:
    """
    Ingest a catalogue / rules JSON stub.

    Expected shapes:
      { "id": "...", "geometry": {...}, ... }  full or partial profile
      { "rules": { "geometry.trackWidth": 32, ... } }
      { "proposed_rules": [ {path, value, confidence, source}, ...] }
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    series = profile_id_hint or data.get("id") or data.get("profile_id") or path.stem

    if isinstance(data.get("proposed_rules"), list):
        for r in data["proposed_rules"]:
            rows.append(
                rule_review_row(
                    str(r["path"]),
                    r.get("value", r.get("detected_value")),
                    float(r.get("confidence", 0.7)),
                    str(r.get("source", path.name)),
                    existing_value=r.get("existing_value"),
                    action=str(r.get("action", "set")),
                )
            )
    elif isinstance(data.get("rules"), dict):
        for pth, val in data["rules"].items():
            if isinstance(val, dict) and "value" in val:
                rows.append(
                    rule_review_row(
                        str(pth),
                        val["value"],
                        float(val.get("confidence", 0.75)),
                        str(val.get("source", path.name)),
                        action="set",
                    )
                )
            else:
                rows.append(rule_review_row(str(pth), val, 0.75, path.name, action="set"))
    else:
        # Partial profile sections
        for section in ("geometry", "glass", "dimensioning", "quotation", "trackRail", "weight"):
            block = data.get(section)
            if not isinstance(block, dict):
                continue
            for k, v in block.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, (int, float, str)):
                    rows.append(
                        rule_review_row(
                            f"{section}.{k}",
                            v,
                            float(data.get("confidence", 0.8)),
                            str(data.get("source", path.name)),
                            action="set",
                        )
                    )

    return {
        "extractor": "json_catalogue_v1",
        "source_path": str(path.resolve()),
        "source_type": "json",
        "series_guess": series,
        "rules": rows,
        "notes": ["Catalogue / rules JSON ingest — review each rule before approve."],
        "raw_sections": {k: data[k] for k in data if k in ("hardware", "brush", "cutList", "bomExtras") and data[k]},
    }


def extract_rules_from_pdf_stub(path: str | Path, **_kwargs: Any) -> dict[str, Any]:
    """Stub for future PDF/OCR catalogue ingest — structured API, no fake OCR."""
    path = Path(path)
    return {
        "extractor": "pdf_stub",
        "source_path": str(path.resolve()),
        "source_type": "pdf",
        "series_guess": path.stem.lower().replace(" ", "_"),
        "rules": [],
        "status": "not_implemented",
        "notes": [
            "PDF/image OCR not implemented. Plug a real extractor here later.",
            "Use DXF heuristic or JSON catalogue stubs for now.",
        ],
    }


def _guess_series_id(path: Path, geom_rows: list[dict[str, Any]]) -> str:
    name = path.stem.lower().replace(" ", "_").replace("-", "_")
    for row in geom_rows:
        if row["path"] == "geometry.trackWidth":
            tw = int(round(float(row["detected_value"])))
            return f"{tw}mm_sliding"
    if "29" in name or "two_track" in name or "twotrack" in name:
        return "29mm_sliding"
    return name or "unknown_series"


def extract_from_source(
    path: str | Path,
    *,
    profile_id_hint: str | None = None,
    baseline_geometry: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Dispatch by file extension."""
    path = Path(path)
    suf = path.suffix.lower()
    if suf == ".dxf":
        return extract_rules_from_dxf(path, profile_id_hint=profile_id_hint, baseline_geometry=baseline_geometry)
    if suf == ".json":
        return extract_rules_from_json(path, profile_id_hint=profile_id_hint)
    if suf in (".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"):
        return extract_rules_from_pdf_stub(path, profile_id_hint=profile_id_hint)
    raise ValueError(f"Unsupported source type: {suf or '(none)'}")
