"""Deal / package quotes — commercial lines without a WEOS drawing.

A project may hold 1–20 package quotes. Each quote has item amounts plus a
GST mode (include / exclude / off). Project value is the sum of quote
``projectValue`` figures (agreed payable), never mixed with another job.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Sequence

MAX_QUOTES = 40
MAX_ITEMS = 120
MAX_ATTACHMENTS = 12

CATEGORIES: tuple[tuple[str, str], ...] = (
    ("window", "Windows"),
    ("casement", "Casement windows"),
    ("ventilator", "Vents"),
    ("louver", "Louvers"),
    ("railing", "Railings"),
    ("iron_fabrication", "Iron fabrication"),
    ("gate", "Gates"),
    ("grill", "Grills"),
    ("pergola", "Pergola"),
    ("other", "Other"),
)

_CAT_IDS = {c[0] for c in CATEGORIES}
_CAT_LABEL = dict(CATEGORIES)

UNITS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "window": ("pcs", "sft", "rft"),
    "casement": ("pcs", "sft"),
    "ventilator": ("pcs", "sft"),
    "louver": ("pcs", "sft"),
    "railing": ("rft", "sft", "pcs"),
    "iron_fabrication": ("kg", "sft", "pcs"),
    "gate": ("pcs", "sft"),
    "grill": ("pcs", "sft", "rft"),
    "pergola": ("sft", "pcs"),
    "other": ("pcs", "sft", "kg", "rft"),
}
KNOWN_UNITS = ("pcs", "sft", "rft", "kg", "mtr", "nos")

GST_MODES = ("exclude", "include", "off")
DEFAULT_GST_PERCENT = 18.0


def _money(n: Any) -> float:
    try:
        if n is None or n == "":
            return 0.0
        return round(float(n), 2)
    except (TypeError, ValueError):
        return 0.0


def _qty(n: Any) -> float | None:
    try:
        if n is None or n == "":
            return None
        v = float(n)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _slug_id(value: Any, prefix: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", "", str(value or "")).strip()
    if raw:
        return raw[:24]
    import secrets

    return prefix + secrets.token_hex(4)


def _norm_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def quote_stage_key(raw: Mapping[str, Any] | None) -> str:
    """Stable sheet/stage identity — not the shared PI / quote number."""
    if not isinstance(raw, Mapping):
        return ""
    sheet = _norm_key(raw.get("sheetName") or raw.get("sourceSheet"))
    sheet = re.sub(r"\s*-\s*35\s*mm.*$", "", sheet).strip(" -")
    note = _norm_key(raw.get("note") or raw.get("title") or raw.get("stageKey"))
    note = re.sub(r"\s*-\s*35\s*mm.*$", "", note).strip(" -")
    key = sheet or note
    if key and key not in {"to", "-", "—"}:
        return key[:80]
    notes = [_norm_key(it.get("note")) for it in (raw.get("items") or [])[:4] if isinstance(it, Mapping)]
    return "|".join(n for n in notes if n)[:80]


def quote_fingerprint(raw: Mapping[str, Any] | None) -> str:
    """Content hash of a package quote (items + totals + stage). Same Excel twice → same hash."""
    if not isinstance(raw, Mapping):
        return ""
    rows: list[list[Any]] = []
    for it in raw.get("items") or []:
        if not isinstance(it, Mapping):
            continue
        rows.append(
            [
                _norm_key(it.get("category")),
                round(float(it.get("qty") or 0), 2),
                _norm_key(it.get("size")),
                _norm_key(it.get("unit")),
                round(float(it.get("rate") or 0), 2),
                round(float(it.get("amount") or 0), 2),
                _norm_key(it.get("note")),
            ]
        )
    rows.sort(key=lambda r: (r[6], r[5], r[0]))
    payload = {
        "stage": quote_stage_key(raw),
        "items": rows,
        "gst": round(float(raw.get("gstAmount") or 0), 2),
        "value": round(float(raw.get("projectValue") or raw.get("totalGrand") or 0), 2),
    }
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def _copy_quote_identity(dst: dict[str, Any], src: Mapping[str, Any]) -> None:
    for key in ("sheetName", "sourceFile", "sourceFileSha256", "sourceSheet"):
        if src.get(key) and not dst.get(key):
            dst[key] = src.get(key)
    dst["stageKey"] = quote_stage_key(dst) or quote_stage_key(src)
    dst["importFingerprint"] = quote_fingerprint(dst)


def attachment_kind(filename: Any, hint: Any = None) -> str:
    h = str(hint or "").strip().lower().replace("-", "_")
    if h in {"photo", "image", "pic", "photos"}:
        return "photo"
    if h in {"quote", "quote_pdf", "pdf", "quotation"}:
        return "quote_pdf"
    name = str(filename or "").strip().lower()
    if name.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return "photo"
    return "quote_pdf"


def attachment_blob_key(project_id: str, quote_id: str, file_id: str) -> str:
    return f"package_quote_file:{project_id}:{quote_id}:{file_id}"


def normalize_attachment(
    raw: Mapping[str, Any] | None,
    *,
    project_id: str | None = None,
    quote_id: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    fname = str(raw.get("filename") or raw.get("name") or "").strip()
    if not fname and not raw.get("key") and not raw.get("id"):
        return None
    fid = str(raw.get("id") or "").strip() or _slug_id(None, "pf")
    kind = attachment_kind(fname, raw.get("kind") or raw.get("type"))
    pid = str(project_id or raw.get("projectId") or "").strip()
    qid = str(quote_id or raw.get("quoteId") or "").strip()
    key = str(raw.get("key") or "").strip() or (
        attachment_blob_key(pid, qid, fid) if pid and qid else None
    )
    url = str(raw.get("url") or "").strip() or None
    if not url and pid and qid:
        url = f"/api/projects/{pid}/package-quotes/{qid}/files/{fid}"
    return {
        "id": fid[:24],
        "kind": kind,
        "filename": fname or ("photo" if kind == "photo" else "quote"),
        "key": key,
        "contentType": str(raw.get("contentType") or "").strip() or None,
        "url": url,
    }


def normalize_attachments(
    raw: Any,
    *,
    project_id: str | None = None,
    quote_id: str | None = None,
    attachment_name: str | None = None,
    attachment_key: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for row in raw[:MAX_ATTACHMENTS]:
            att = normalize_attachment(
                row if isinstance(row, Mapping) else None,
                project_id=project_id,
                quote_id=quote_id,
            )
            if not att or att["id"] in seen:
                continue
            seen.add(att["id"])
            out.append(att)
    name = str(attachment_name or "").strip()
    if name and not any(a.get("filename") == name for a in out):
        legacy = normalize_attachment(
            {
                "id": "legacy",
                "kind": "quote_pdf",
                "filename": name,
                "key": attachment_key,
                "url": (
                    f"/api/projects/{project_id}/package-quotes/{quote_id}/file"
                    if project_id and quote_id
                    else None
                ),
            },
            project_id=project_id,
            quote_id=quote_id,
        )
        if legacy:
            out.insert(0, legacy)
    return out[:MAX_ATTACHMENTS]


def store_package_file(
    *,
    project_id: str,
    quote_id: str,
    raw: bytes,
    filename: str,
    content_type: str | None,
    kind_hint: str | None = None,
) -> dict[str, Any]:
    fid = _slug_id(None, "pf")
    kind = attachment_kind(filename, kind_hint)
    key = attachment_blob_key(project_id, quote_id, fid)
    stored = False
    try:
        from WEOS.db.durable_store import put_blob

        stored = bool(
            put_blob(
                key,
                kind="package_quote_file",
                raw=raw,
                content_type=content_type or "application/octet-stream",
                filename=filename,
                payload={"projectId": project_id, "quoteId": quote_id, "fileId": fid, "kind": kind},
            )
        )
    except Exception:
        stored = False
    if not stored:
        from WEOS.paths import data_dir

        dest = data_dir() / "package_quotes" / project_id
        dest.mkdir(parents=True, exist_ok=True)
        (dest / f"{quote_id}_{fid}.bin").write_bytes(raw)
        (dest / f"{quote_id}_{fid}.name.txt").write_text(filename, encoding="utf-8")
        (dest / f"{quote_id}_{fid}.kind.txt").write_text(kind, encoding="utf-8")
    return {
        "id": fid,
        "kind": kind,
        "filename": filename,
        "key": key,
        "contentType": content_type,
        "url": f"/api/projects/{project_id}/package-quotes/{quote_id}/files/{fid}",
    }


def load_package_file(project_id: str, quote_id: str, file_id: str | None = None) -> tuple[bytes | None, str | None, str | None]:
    keys = []
    if file_id:
        keys.append(attachment_blob_key(project_id, quote_id, file_id))
    keys.append(f"package_quote_file:{project_id}:{quote_id}")
    try:
        from WEOS.db.durable_store import get_blob

        for key in keys:
            raw, ctype, fname = get_blob(key)
            if raw is not None:
                return raw, ctype, fname
    except Exception:
        pass
    from WEOS.paths import data_dir

    folder = data_dir() / "package_quotes" / project_id
    names = []
    if file_id:
        names.append(f"{quote_id}_{file_id}.bin")
    names.append(f"{quote_id}.bin")
    for name in names:
        p = folder / name
        if p.is_file():
            fname = name.replace(".bin", "")
            np = folder / (p.stem + ".name.txt")
            if np.is_file():
                fname = np.read_text(encoding="utf-8").strip() or fname
            return p.read_bytes(), "application/octet-stream", fname
    return None, None, None


def category_id(raw: Any) -> str:
    key = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "windows": "window",
        "casements": "casement",
        "casement_windows": "casement",
        "vent": "ventilator",
        "vents": "ventilator",
        "bathroom_ventilator": "ventilator",
        "louvers": "louver",
        "louvres": "louver",
        "louvre": "louver",
        "railings": "railing",
        "iron": "iron_fabrication",
        "fabrication": "iron_fabrication",
        "ms": "iron_fabrication",
        "gates": "gate",
        "grills": "grill",
        "grilles": "grill",
        "pergolas": "pergola",
    }
    key = aliases.get(key, key)
    return key if key in _CAT_IDS else "other"


def compute_gst_split(
    items_total: float,
    *,
    gst_mode: str = "exclude",
    gst_percent: float = DEFAULT_GST_PERCENT,
) -> dict[str, Any]:
    """Split entered item amounts into taxable / GST / project value."""
    subtotal = round(max(0.0, _money(items_total)), 2)
    mode = str(gst_mode or "exclude").strip().lower()
    if mode not in GST_MODES:
        mode = "exclude"
    try:
        pct = float(gst_percent if gst_percent is not None else DEFAULT_GST_PERCENT)
    except (TypeError, ValueError):
        pct = DEFAULT_GST_PERCENT
    if pct < 0:
        pct = 0.0
    if mode == "off" or pct == 0:
        return {
            "gstMode": "off" if mode == "off" else mode,
            "gstPercent": 0.0 if mode == "off" else round(pct, 2),
            "itemsSubtotal": subtotal,
            "totalTaxable": subtotal,
            "gstAmount": 0.0,
            "totalGrand": subtotal,
            "projectValue": subtotal,
        }
    if mode == "include":
        grand = subtotal
        gst_amt = round(grand * pct / (100.0 + pct), 2) if pct else 0.0
        taxable = round(grand - gst_amt, 2)
        return {
            "gstMode": "include",
            "gstPercent": round(pct, 2),
            "itemsSubtotal": subtotal,
            "totalTaxable": taxable,
            "gstAmount": gst_amt,
            "totalGrand": grand,
            "projectValue": grand,
        }
    taxable = subtotal
    gst_amt = round(taxable * pct / 100.0, 2)
    grand = round(taxable + gst_amt, 2)
    return {
        "gstMode": "exclude",
        "gstPercent": round(pct, 2),
        "itemsSubtotal": subtotal,
        "totalTaxable": taxable,
        "gstAmount": gst_amt,
        "totalGrand": grand,
        "projectValue": grand,
    }


def normalize_package_item(raw: Mapping[str, Any] | None, *, index: int = 0) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    amount = _money(raw.get("amount") or raw.get("value") or raw.get("total"))
    cat = category_id(raw.get("category") or raw.get("kind") or raw.get("type"))
    allowed_units = UNITS_BY_CATEGORY.get(cat) or ("pcs",)
    unit = str(raw.get("unit") or allowed_units[0]).strip().lower()
    if unit not in allowed_units:
        unit = unit if unit in KNOWN_UNITS else allowed_units[0]
    item_id = str(raw.get("id") or "").strip() or _slug_id(None, "pi")
    qty = _qty(raw.get("qty") or raw.get("quantity") or raw.get("count"))
    size = str(raw.get("size") or raw.get("sizeText") or "").strip() or None
    note = str(raw.get("note") or raw.get("label") or "").strip() or None
    rate = _money(raw.get("rate")) if raw.get("rate") not in (None, "") else None
    if amount <= 0 and not qty and not size and not note:
        return None
    out = {
        "id": item_id[:24],
        "category": cat,
        "categoryLabel": _CAT_LABEL.get(cat, "Other"),
        "qty": qty,
        "size": size,
        "unit": unit,
        "amount": amount,
        "note": note,
        "sort": index,
    }
    if rate and rate > 0:
        out["rate"] = rate
    return out


def normalize_package_quote(
    raw: Mapping[str, Any] | None,
    *,
    index: int = 0,
    project_id: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    items_in = raw.get("items") or raw.get("lines") or []
    items: list[dict[str, Any]] = []
    if isinstance(items_in, list):
        for i, row in enumerate(items_in[:MAX_ITEMS]):
            it = normalize_package_item(row if isinstance(row, Mapping) else None, index=i)
            if it:
                items.append(it)
    if not items:
        return None
    qid = str(raw.get("id") or "").strip() or _slug_id(None, "pq")
    pid = str(project_id or raw.get("projectId") or "").strip() or None
    split = compute_gst_split(
        sum(_money(it.get("amount")) for it in items),
        gst_mode=str(raw.get("gstMode") or raw.get("gst") or "exclude"),
        gst_percent=raw.get("gstPercent") if raw.get("gstPercent") is not None else DEFAULT_GST_PERCENT,
    )
    # Imported quotes keep the sheet's GST / grand when provided.
    imp_gst = _money(raw.get("gstAmount")) if raw.get("gstAmount") not in (None, "") else None
    imp_grand = _money(raw.get("projectValue") or raw.get("totalGrand")) if (
        raw.get("projectValue") not in (None, "") or raw.get("totalGrand") not in (None, "")
    ) else None
    if imp_grand and imp_grand > 0:
        split["projectValue"] = imp_grand
        split["totalGrand"] = imp_grand
        if imp_gst is not None:
            split["gstAmount"] = imp_gst
            split["totalTaxable"] = round(max(0.0, imp_grand - imp_gst), 2)
    quote_no = str(raw.get("quotationId") or raw.get("quoteNumber") or raw.get("quoteNo") or "").strip() or None
    atts = normalize_attachments(
        raw.get("attachments"),
        project_id=pid,
        quote_id=qid,
        attachment_name=str(raw.get("attachmentName") or "").strip() or None,
        attachment_key=str(raw.get("attachmentKey") or "").strip() or None,
    )
    first = next((a for a in atts if a.get("kind") == "quote_pdf"), atts[0] if atts else None)
    out = {
        "id": qid[:24],
        "index": index,
        "quotationId": quote_no,
        "note": str(raw.get("note") or "").strip() or None,
        "items": items,
        "attachments": atts,
        "attachmentName": (first or {}).get("filename") or (str(raw.get("attachmentName") or "").strip() or None),
        "attachmentKey": (first or {}).get("key") or (str(raw.get("attachmentKey") or "").strip() or None),
        **split,
    }
    if raw.get("sheetName") or raw.get("sourceSheet"):
        out["sheetName"] = str(raw.get("sheetName") or raw.get("sourceSheet") or "").strip() or None
    if raw.get("sourceFile"):
        out["sourceFile"] = str(raw.get("sourceFile")).strip() or None
    if raw.get("sourceFileSha256"):
        out["sourceFileSha256"] = str(raw.get("sourceFileSha256")).strip() or None
    _copy_quote_identity(out, raw)
    return out


def collapse_duplicate_package_quotes(quotes: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Drop exact duplicate stages (same fingerprint) and same-sheet copies.

    Shared PI / quote numbers (e.g. 24/25AB291 on every sheet) are ignored —
    identity is the sheet/stage plus line items, not the quote number.
    """
    if not quotes:
        return []
    kept: list[dict[str, Any]] = []
    seen_fp: set[str] = set()
    by_stage: dict[str, int] = {}
    for row in quotes:
        q = dict(row) if isinstance(row, Mapping) else None
        if not q:
            continue
        fp = str(q.get("importFingerprint") or quote_fingerprint(q) or "")
        sk = str(q.get("stageKey") or quote_stage_key(q) or "")
        if fp and fp in seen_fp:
            continue
        if sk and sk in by_stage:
            prev = kept[by_stage[sk]]
            prev_n = len(prev.get("items") or [])
            new_n = len(q.get("items") or [])
            prev_val = _money(prev.get("projectValue") or prev.get("totalGrand"))
            new_val = _money(q.get("projectValue") or q.get("totalGrand"))
            # Same stage already on the job: keep the richer copy, never both.
            if new_n > prev_n or (new_n == prev_n and abs(new_val - prev_val) > 0.05 and new_val > 0):
                atts = list(prev.get("attachments") or [])
                qid = prev.get("id")
                kept[by_stage[sk]] = q
                kept[by_stage[sk]]["id"] = qid
                if atts and not q.get("attachments"):
                    kept[by_stage[sk]]["attachments"] = atts
            continue
        if fp:
            seen_fp.add(fp)
        if sk:
            by_stage[sk] = len(kept)
        kept.append(q)
    for i, q in enumerate(kept):
        q["index"] = i
    return kept[:MAX_QUOTES]


def merge_package_quotes(
    existing: Sequence[Mapping[str, Any]] | None,
    incoming: Sequence[Mapping[str, Any]] | None,
    *,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Append only new sheets; update changed sheets; skip exact duplicates."""
    base = collapse_duplicate_package_quotes(
        normalize_package_quotes(list(existing or []), project_id=project_id)
        if existing
        else []
    )
    added: list[str] = []
    skipped: list[str] = []
    updated: list[str] = []
    by_fp = {str(q.get("importFingerprint") or quote_fingerprint(q)): q for q in base}
    by_stage = {str(q.get("stageKey") or quote_stage_key(q)): q for q in base if quote_stage_key(q)}
    for row in incoming or []:
        inc = normalize_package_quote(
            row if isinstance(row, Mapping) else None,
            index=len(base),
            project_id=project_id,
        )
        if not inc:
            continue
        fp = str(inc.get("importFingerprint") or quote_fingerprint(inc))
        sk = str(inc.get("stageKey") or quote_stage_key(inc))
        label = inc.get("note") or inc.get("sheetName") or inc.get("quotationId") or inc["id"]
        if fp and fp in by_fp:
            skipped.append(str(label))
            continue
        hit = by_stage.get(sk) if sk else None
        if hit is not None:
            keep_id = hit.get("id")
            keep_atts = list(hit.get("attachments") or [])
            hit.clear()
            hit.update(inc)
            hit["id"] = keep_id
            if keep_atts and not hit.get("attachments"):
                hit["attachments"] = keep_atts
            elif keep_atts:
                seen = {a.get("id") for a in (hit.get("attachments") or []) if isinstance(a, dict)}
                extra = [a for a in keep_atts if isinstance(a, dict) and a.get("id") not in seen]
                hit["attachments"] = list(hit.get("attachments") or []) + extra
            hit["importFingerprint"] = quote_fingerprint(hit)
            hit["stageKey"] = quote_stage_key(hit)
            by_fp[str(hit.get("importFingerprint"))] = hit
            updated.append(str(label))
            continue
        if len(base) >= MAX_QUOTES:
            skipped.append(f"{label} (max {MAX_QUOTES} quotes)")
            continue
        base.append(inc)
        if fp:
            by_fp[fp] = inc
        if sk:
            by_stage[sk] = inc
        added.append(str(label))
    for i, q in enumerate(base):
        q["index"] = i
    return {
        "quotes": base,
        "added": added,
        "skipped": skipped,
        "updated": updated,
        "addedCount": len(added),
        "skippedCount": len(skipped),
        "updatedCount": len(updated),
        "quoteCount": len(base),
    }


def normalize_package_quotes(raw: Any, *, project_id: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, row in enumerate(raw[: MAX_QUOTES * 3]):
        q = normalize_package_quote(
            row if isinstance(row, Mapping) else None,
            index=i,
            project_id=project_id,
        )
        if not q:
            continue
        if q["id"] in seen:
            q["id"] = _slug_id(None, "pq")
        seen.add(q["id"])
        out.append(q)
    return collapse_duplicate_package_quotes(out)


def package_money_for_doc(doc: Mapping[str, Any] | None) -> dict[str, Any]:
    quotes = normalize_package_quotes((doc or {}).get("packageQuotes") if isinstance(doc, Mapping) else None)
    taxable = round(sum(_money(q.get("totalTaxable")) for q in quotes), 2)
    gst_amt = round(sum(_money(q.get("gstAmount")) for q in quotes), 2)
    value = round(sum(_money(q.get("projectValue")) for q in quotes), 2)
    percents = [float(q.get("gstPercent") or 0) for q in quotes if str(q.get("gstMode")) != "off"]
    return {
        "quotes": quotes,
        "quoteCount": len(quotes),
        "totalTaxable": taxable,
        "gstAmount": gst_amt,
        "totalGst": gst_amt,
        "totalGrand": value,
        "projectValue": value,
        "gstPercent": percents[0] if len(set(round(p, 2) for p in percents)) == 1 else None,
        "gstModes": sorted({str(q.get("gstMode")) for q in quotes}),
    }


def apply_package_fields(doc: dict[str, Any], payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Copy package / master-job fields from a PUT/POST body onto the project doc."""
    if not isinstance(doc, dict):
        return doc
    src = payload if isinstance(payload, Mapping) else {}
    pid = str(doc.get("projectId") or "").strip() or None
    if "packageQuotes" in src and src.get("packageQuotes") is not None:
        doc["packageQuotes"] = normalize_package_quotes(src.get("packageQuotes"), project_id=pid)
    elif isinstance(doc.get("packageQuotes"), list):
        doc["packageQuotes"] = normalize_package_quotes(doc.get("packageQuotes"), project_id=pid)
    quotes = doc.get("packageQuotes") or []
    if quotes:
        has_lines = bool(doc.get("lines"))
        doc["quoteKind"] = "mixed" if has_lines else "package"
    if src.get("quoteKind"):
        kind = str(src.get("quoteKind") or "").strip().lower()
        if kind in {"package", "cart", "mixed", "weos"}:
            doc["quoteKind"] = kind
    mid = str(src.get("masterJobId") or doc.get("masterJobId") or doc.get("projectId") or "").strip()
    if mid:
        doc["masterJobId"] = mid
    return doc
