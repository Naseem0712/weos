"""JSON export — full manufacturing package for one opening."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from WEOS.factory.job_types import JobResult


def export_json(job: JobResult, path: str | Path, *, indent: int = 2) -> Path:
    path = Path(path)
    payload: dict[str, Any] = job.manufacturing_dict()
    # Include light drawing summary (not every vertex — keep file useful)
    payload["drawing_summary"] = {
        "product_type": job.drawing.product_type,
        "polyline_count": len(job.drawing.polylines),
        "segment_count": len(job.drawing.segments),
        "dimension_count": len(job.drawing.dimensions),
        "parameters": job.drawing.parameters,
    }
    path.write_text(json.dumps(payload, indent=indent), encoding="utf-8")
    return path

