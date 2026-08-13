"""Quote-session cache + parallel PNG for PDF / Excel elevations.

Customer PDF and Excel both need a small drawing per line. Regenerating SVG
(generate_job) and rasterizing at high scale sequentially is the main delay.
This module:

* reuses slim ``preview.svg`` from calculate_line (same strokes as live canvas)
* LRU-caches SVG + PNG for the process (same quote session / worker)
* rasterizes independent lines in a small thread pool
* downscales Excel thumbnails so xlsx is not blocked on full-res PNGs
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Mapping

_log = logging.getLogger("weos.elevation_cache")

_LOCK = threading.Lock()
_SVG_CACHE: dict[str, str] = {}
_PNG_CACHE: dict[str, bytes] = {}
_MAX = 96

# A4 design cell is ~200×210 pt — 1.4–1.6× SVG scale is enough locally.
PDF_PNG_SCALE = 1.45
# Excel drawing column is ~118×78 px display — tiny thumbnail is enough.
XLSX_PNG_SCALE = 0.55
XLSX_MAX_PX = 220


def _fp(obj: Any) -> str:
    try:
        raw = json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)
    except Exception:
        raw = repr(obj)
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()


def line_export_fingerprint(line: Mapping[str, Any] | None, *, extra: str = "") -> str:
    line = line or {}
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
    photo = line.get("designPhoto") if isinstance(line.get("designPhoto"), Mapping) else None
    if not photo and isinstance(opts, Mapping):
        photo = opts.get("designPhoto") if isinstance(opts.get("designPhoto"), Mapping) else None
    rail = opts.get("railing") if isinstance(opts, Mapping) else None
    svg = str((prev or {}).get("svg") or (prev or {}).get("pdfSvg") or "")
    return _fp(
        {
            "e": extra,
            "id": line.get("lineId"),
            "p": line.get("product") or line.get("productId"),
            "pt": line.get("productType"),
            "w": line.get("width"),
            "h": line.get("height"),
            "g": line.get("glass"),
            "c": line.get("colour"),
            "sys": line.get("system"),
            "tc": line.get("trackCount"),
            "gs": line.get("glassShutters"),
            "op": line.get("opening"),
            "ss": line.get("sectionSeries"),
            "photo": (photo or {}).get("key") if isinstance(photo, Mapping) else None,
            "rail": {
                "shape": (rail or {}).get("shape") if isinstance(rail, Mapping) else None,
                "bs": (rail or {}).get("bottomSize") if isinstance(rail, Mapping) else None,
                "hs": (rail or {}).get("handrailSize") if isinstance(rail, Mapping) else None,
                "bk": (rail or {}).get("bottomKind") if isinstance(rail, Mapping) else None,
                "bar": (rail or {}).get("handrailBarLengthFt") if isinstance(rail, Mapping) else None,
                "asp": (rail or {}).get("anchorSpacingFt") if isinstance(rail, Mapping) else None,
            }
            if isinstance(rail, Mapping)
            else None,
            "slim": "canvas-print-v3",
            "svgLen": len(svg),
            "svgHead": svg[:240],
        }
    )


def _cache_get_svg(key: str) -> str | None:
    with _LOCK:
        return _SVG_CACHE.get(key)


def _cache_put_svg(key: str, svg: str) -> None:
    with _LOCK:
        if len(_SVG_CACHE) >= _MAX:
            for k in list(_SVG_CACHE.keys())[: max(8, _MAX // 8)]:
                _SVG_CACHE.pop(k, None)
        _SVG_CACHE[key] = svg


def _cache_get_png(key: str) -> bytes | None:
    with _LOCK:
        return _PNG_CACHE.get(key)


def _cache_put_png(key: str, png: bytes) -> None:
    with _LOCK:
        if len(_PNG_CACHE) >= _MAX:
            for k in list(_PNG_CACHE.keys())[: max(8, _MAX // 8)]:
                _PNG_CACHE.pop(k, None)
        _PNG_CACHE[key] = png


def svg_for_line(line: Mapping[str, Any], *, style: str = "preview") -> str | None:
    """Return elevation SVG, preferring calculate_line preview (slim canvas strokes)."""
    key = line_export_fingerprint(line, extra=f"svg-slim:{style}")
    hit = _cache_get_svg(key)
    if hit:
        return hit
    prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
    live_svg = str((prev or {}).get("svg") or "").strip()
    svg = live_svg if live_svg and "<svg" in live_svg.lower() else ""
    if not svg:
        try:
            from WEOS.factory.svg_export import elevation_svg_for_line

            # preview style = slim canvas strokes (pdf style no longer thickens)
            svg = elevation_svg_for_line(line, style="preview") or ""
        except Exception:
            _log.debug("elevation svg rebuild skipped", exc_info=True)
            svg = live_svg
    if svg:
        _cache_put_svg(key, str(svg))
        return str(svg)
    return None


def _resize_png(png: bytes, *, max_px: int) -> bytes:
    if not png or max_px <= 0:
        return png
    try:
        from PIL import Image

        im = Image.open(__import__("io").BytesIO(png))
        im.load()
        w, h = im.size
        if max(w, h) <= max_px:
            return png
        scale = max_px / float(max(w, h))
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im
        im = im.resize((nw, nh), Image.Resampling.BILINEAR)
        buf = __import__("io").BytesIO()
        im.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return png


def png_for_line(
    line: Mapping[str, Any],
    *,
    scale: float = PDF_PNG_SCALE,
    max_px: int | None = None,
) -> bytes | None:
    """PNG of photo or canvas SVG. Cached per line fingerprint + scale."""
    photo = None
    try:
        pmap = line.get("designPhoto") if isinstance(line.get("designPhoto"), Mapping) else None
        if not pmap:
            opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
            pmap = opts.get("designPhoto") if isinstance(opts.get("designPhoto"), Mapping) else None
        key = str((pmap or {}).get("key") or "").strip() if isinstance(pmap, Mapping) else ""
        if key:
            from WEOS.factory.design_photo import design_photo_bytes_by_key

            photo, _ct = design_photo_bytes_by_key(key)
    except Exception:
        photo = None
    if photo:
        key = line_export_fingerprint(line, extra=f"photo:{scale}:{max_px or 0}:{len(photo)}")
        hit = _cache_get_png(key)
        if hit:
            return hit
        out = _resize_png(photo, max_px=int(max_px or XLSX_MAX_PX)) if max_px else photo
        if max_px and len(out) > 180_000:
            out = _resize_png(out, max_px=min(int(max_px), 160))
        _cache_put_png(key, out)
        return out

    key = line_export_fingerprint(line, extra=f"png:{scale}:{max_px or 0}")
    hit = _cache_get_png(key)
    if hit:
        return hit
    svg = svg_for_line(line, style="preview")
    if not svg:
        return None
    try:
        from WEOS.factory.image_engine import svg_to_png_bytes

        png = svg_to_png_bytes(str(svg), scale=float(scale) or 1.0, allow_slow=False, max_px=1100)
        if not png:
            # Pixel-normalized SVG is small enough for svglib when Cairo is missing.
            png = svg_to_png_bytes(str(svg), scale=1.0, allow_slow=True, max_px=900)
    except Exception:
        _log.debug("svg rasterize skipped", exc_info=True)
        png = None
    if not png:
        return None
    if max_px:
        png = _resize_png(png, max_px=int(max_px))
    _cache_put_png(key, png)
    return png


def prefetch_line_pngs(
    lines: list[Any],
    *,
    scale: float = PDF_PNG_SCALE,
    max_px: int | None = None,
    max_workers: int = 4,
) -> dict[int, bytes]:
    """Rasterize independent line elevations in parallel. Returns {index: png}."""
    indexed = [(i, ln) for i, ln in enumerate(lines or []) if isinstance(ln, Mapping)]
    if not indexed:
        return {}
    out: dict[int, bytes] = {}
    workers = max(1, min(int(max_workers or 1), len(indexed), 6))
    if workers == 1 or len(indexed) == 1:
        for i, ln in indexed:
            png = png_for_line(ln, scale=scale, max_px=max_px)
            if png:
                out[i] = png
        return out

    def _one(pair: tuple[int, Mapping[str, Any]]) -> tuple[int, bytes | None]:
        i, ln = pair
        try:
            return i, png_for_line(ln, scale=scale, max_px=max_px)
        except Exception:
            _log.debug("prefetch png failed for line %s", i, exc_info=True)
            return i, None

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="weos-elev") as pool:
        futs = [pool.submit(_one, pair) for pair in indexed]
        for fut in as_completed(futs):
            try:
                i, png = fut.result()
            except Exception:
                continue
            if png:
                out[i] = png
    return out
