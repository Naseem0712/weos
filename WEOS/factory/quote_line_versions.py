"""Quote versions on one Window Cart project.

Saved Projects and Master Ledger read ``project.lines``. A later save can leave
that array empty while the items still sit in the undo stack, a version file,
``lastCalculation``, or the quotes table. This module puts those lines back on
the project and marks what changed versus the previous version.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

_log = logging.getLogger("weos.quote_line_versions")

_APPROVED = frozenset(
    {"confirmed", "accepted", "approved", "finalized", "ordered", "order", "won"}
)
_DROP_KEYS = ("preview", "previewSvg", "designPhoto")


def _usable(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for ln in raw:
        if not isinstance(ln, Mapping):
            continue
        if not (
            ln.get("product")
            or ln.get("productType")
            or ln.get("displayName")
            or ln.get("width")
            or ln.get("locationName")
            or ln.get("lineId")
        ):
            continue
        out.append(dict(ln))
    return out


def _loc(ln: Mapping[str, Any]) -> str:
    for key in ("locationName", "positionName"):
        val = str(ln.get(key) or "").strip()
        if val:
            return val.lower()
    opts = ln.get("options") if isinstance(ln.get("options"), Mapping) else {}
    for key in ("locationName", "positionName"):
        val = str((opts or {}).get(key) or "").strip()
        if val:
            return val.lower()
    return ""


def _num(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def line_key(ln: Mapping[str, Any]) -> str:
    prod = str(ln.get("product") or ln.get("productType") or ln.get("displayName") or "").strip().lower()
    return f"{_loc(ln)}|{prod}|{_num(ln.get('width'))}|{_num(ln.get('height'))}"


def line_signature(lines: list[Mapping[str, Any]] | None) -> str:
    parts = [f"{line_key(ln)}#{_num(ln.get('qty') or ln.get('quantity') or 1)}" for ln in (lines or [])]
    return "|".join(sorted(parts))


def slim_line(ln: Mapping[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in dict(ln).items() if k not in _DROP_KEYS}
    opts = out.get("options")
    if isinstance(opts, dict):
        out["options"] = {k: v for k, v in opts.items() if k not in _DROP_KEYS}
    return out


def _add_snap(
    bucket: list[dict[str, Any]],
    seen: set[tuple[Any, str]],
    *,
    version: Any,
    lines: Any,
    quotation_id: Any = None,
    saved_at: Any = None,
    status: Any = None,
    source: str,
) -> None:
    usable = _usable(lines)
    if not usable:
        return
    try:
        ver = int(version or 0)
    except (TypeError, ValueError):
        ver = 0
    sig = line_signature(usable)
    key = (ver, sig)
    if key in seen:
        return
    seen.add(key)
    bucket.append(
        {
            "version": ver,
            "quotationId": quotation_id,
            "savedAt": saved_at,
            "status": status,
            "lines": usable,
            "source": source,
            "signature": sig,
        }
    )


def collect_snapshots(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Older commercial states stored on the project, newest version last."""
    bucket: list[dict[str, Any]] = []
    seen: set[tuple[Any, str]] = set()
    for snap in doc.get("quoteVersions") or []:
        if not isinstance(snap, Mapping):
            continue
        _add_snap(
            bucket,
            seen,
            version=snap.get("version"),
            lines=snap.get("lines"),
            quotation_id=snap.get("quotationId"),
            saved_at=snap.get("savedAt") or snap.get("updatedAt"),
            status=snap.get("status"),
            source=str(snap.get("source") or "quoteVersions"),
        )
    for snap in doc.get("_undoStack") or []:
        if not isinstance(snap, Mapping):
            continue
        _add_snap(
            bucket,
            seen,
            version=snap.get("version"),
            lines=snap.get("lines"),
            quotation_id=doc.get("quotationId"),
            saved_at=snap.get("updatedAt"),
            status=snap.get("status"),
            source="undo",
        )
    pid = str(doc.get("projectId") or "").strip()
    if pid:
        try:
            from WEOS.paths import projects_dir

            folder = projects_dir() / "versions"
            if folder.is_dir():
                for path in sorted(folder.glob(f"{pid}_v*.json")):
                    try:
                        payload = json.loads(path.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    _add_snap(
                        bucket,
                        seen,
                        version=payload.get("version"),
                        lines=payload.get("lines"),
                        quotation_id=payload.get("quotationId"),
                        saved_at=payload.get("updatedAt"),
                        status=payload.get("status"),
                        source="version_file",
                    )
        except Exception:
            _log.debug("version file scan skipped for %s", pid, exc_info=True)
    bucket.sort(key=lambda row: int(row.get("version") or 0))
    return bucket


def _quote_store_lines(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        from WEOS.db.quote_store import get_quote_by_ref, list_versions
    except Exception:
        return []
    refs = [
        str(doc.get("quotationId") or "").strip(),
        str(doc.get("projectId") or "").strip(),
        str(doc.get("quoteId") or "").strip(),
    ]
    for ref in refs:
        if not ref:
            continue
        try:
            quote = get_quote_by_ref(ref)
        except Exception:
            quote = None
        if not isinstance(quote, dict):
            continue
        lines = _usable(quote.get("lines"))
        if lines:
            return lines
        qid = str(quote.get("quoteId") or "").strip()
        if not qid:
            continue
        try:
            versions = list_versions(qid)
        except Exception:
            versions = []
        for row in versions or []:
            snap = row.get("snapshot") if isinstance(row, dict) else None
            if isinstance(snap, dict):
                lines = _usable(snap.get("lines"))
                if lines:
                    return lines
    return []


def hydrate_commercial_lines(doc: dict[str, Any]) -> bool:
    """Fill an empty ``lines`` array from the newest stored version. Returns True if filled."""
    if _usable(doc.get("lines")):
        return False
    snaps = collect_snapshots(doc)
    calc = doc.get("lastCalculation") if isinstance(doc.get("lastCalculation"), Mapping) else {}
    calc_lines = _usable(calc.get("lines"))
    if not snaps and calc_lines:
        doc["lines"] = calc_lines
        doc["linesRecoveredFrom"] = "calculation"
        return True
    if snaps:
        best = snaps[-1]
        doc["lines"] = [dict(ln) for ln in best["lines"]]
        doc["linesRecoveredFrom"] = best.get("source") or "version"
        return True
    stored = _quote_store_lines(doc)
    if stored:
        doc["lines"] = stored
        doc["linesRecoveredFrom"] = "quote_store"
        return True
    return False


def lines_for_commercial_display(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Lines that should drive ledger money and the public scanner.

    An approved project shows the approved version. A draft shows the latest
    recovered lines.
    """
    status = str(doc.get("status") or "").strip().lower()
    approved = doc.get("approvedVersion")
    current = _usable(doc.get("lines"))
    if status in _APPROVED and approved not in (None, ""):
        try:
            want = int(approved)
        except (TypeError, ValueError):
            want = 0
        if want:
            for snap in collect_snapshots(doc):
                if int(snap.get("version") or 0) == want and snap.get("lines"):
                    return [dict(ln) for ln in snap["lines"]]
            try:
                if int(doc.get("version") or 0) == want and current:
                    return current
            except (TypeError, ValueError):
                pass
    return current


def remember_previous_version(doc: dict[str, Any], prev: Mapping[str, Any] | None) -> None:
    """Keep the previous commercial lines on the same project when they change."""
    if not isinstance(prev, Mapping):
        return
    prev_lines = _usable(prev.get("lines"))
    if not prev_lines:
        return
    cur_lines = _usable(doc.get("lines"))
    if line_signature(prev_lines) == line_signature(cur_lines):
        return
    versions = [dict(s) for s in (doc.get("quoteVersions") or []) if isinstance(s, Mapping)]
    versions.append(
        {
            "version": prev.get("version"),
            "quotationId": prev.get("quotationId") or doc.get("quotationId"),
            "savedAt": prev.get("updatedAt"),
            "status": prev.get("status"),
            "lines": [slim_line(ln) for ln in prev_lines],
            "source": "save",
        }
    )
    doc["quoteVersions"] = versions[-15:]


def pin_approved_snapshot(doc: dict[str, Any]) -> None:
    """Remember the lines that were on the project at approval time."""
    lines = _usable(doc.get("lines"))
    if not lines:
        return
    try:
        ver = int(doc.get("approvedVersion") or doc.get("version") or 1)
    except (TypeError, ValueError):
        ver = 1
    versions = [dict(s) for s in (doc.get("quoteVersions") or []) if isinstance(s, Mapping)]
    kept = []
    for snap in versions:
        try:
            if int(snap.get("version") or 0) == ver:
                continue
        except (TypeError, ValueError):
            pass
        kept.append(snap)
    kept.append(
        {
            "version": ver,
            "quotationId": doc.get("quotationId"),
            "savedAt": doc.get("updatedAt"),
            "status": "approved",
            "lines": [slim_line(ln) for ln in lines],
            "source": "approve",
        }
    )
    doc["quoteVersions"] = kept[-15:]


def _qty(ln: Mapping[str, Any]) -> float:
    return _num(ln.get("qty") if ln.get("qty") is not None else ln.get("quantity") or 1)


def _amount(ln: Mapping[str, Any]) -> float:
    try:
        from WEOS.factory.customer_line_view import customer_line_amount

        amt = customer_line_amount(ln)
        return float(amt or 0)
    except Exception:
        return 0.0


def diff_flags(
    previous: list[Mapping[str, Any]] | None,
    current: list[Mapping[str, Any]] | None,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Added keys are green. Reduced or removed keys are red."""
    prev_map: dict[str, list[Mapping[str, Any]]] = {}
    for ln in previous or []:
        if isinstance(ln, Mapping):
            prev_map.setdefault(line_key(ln), []).append(ln)
    curr_map: dict[str, list[Mapping[str, Any]]] = {}
    for ln in current or []:
        if isinstance(ln, Mapping):
            curr_map.setdefault(line_key(ln), []).append(ln)
    flags: dict[str, str] = {}
    if not prev_map:
        return flags, []
    for key, rows in curr_map.items():
        if key not in prev_map:
            flags[key] = "added"
            continue
        prev_qty = sum(_qty(ln) for ln in prev_map[key])
        cur_qty = sum(_qty(ln) for ln in rows)
        prev_amt = sum(_amount(ln) for ln in prev_map[key])
        cur_amt = sum(_amount(ln) for ln in rows)
        if cur_qty < prev_qty - 0.001 or (prev_amt > 0 and cur_amt < prev_amt - 0.5):
            flags[key] = "reduced"
    removed: list[dict[str, Any]] = []
    for key, rows in prev_map.items():
        if key in curr_map:
            continue
        for ln in rows:
            item = slim_line(ln)
            item["changeFlag"] = "removed"
            removed.append(item)
    return flags, removed


def previous_commercial_lines(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    current = _usable(doc.get("lines"))
    cur_sig = line_signature(current)
    try:
        cur_ver = int(doc.get("version") or 0)
    except (TypeError, ValueError):
        cur_ver = 0
    candidates = []
    for snap in collect_snapshots(doc):
        if snap.get("signature") == cur_sig:
            continue
        ver = int(snap.get("version") or 0)
        if cur_ver and ver > cur_ver:
            continue
        candidates.append(snap)
    if not candidates:
        return []
    candidates.sort(key=lambda row: int(row.get("version") or 0))
    return [dict(ln) for ln in candidates[-1]["lines"]]


def stamp_change_flags(doc: dict[str, Any]) -> dict[str, Any]:
    """Mark current lines added/reduced and list removed lines. In memory only."""
    flags, removed = diff_flags(previous_commercial_lines(doc), _usable(doc.get("lines")))
    for ln in doc.get("lines") or []:
        if not isinstance(ln, dict):
            continue
        flag = flags.get(line_key(ln))
        if flag:
            ln["changeFlag"] = flag
        else:
            ln.pop("changeFlag", None)
    doc["removedLines"] = removed
    return doc


def presentation_doc(doc: Mapping[str, Any]) -> dict[str, Any]:
    """Copy used by the public scanner: approved version when one is pinned."""
    out = dict(doc)
    lines = lines_for_commercial_display(doc)
    out["lines"] = [dict(ln) for ln in lines]
    if str(out.get("status") or "").strip().lower() in _APPROVED and out.get("approvedVersion"):
        try:
            out["version"] = int(out.get("approvedVersion") or out.get("version") or 1)
        except (TypeError, ValueError):
            pass
    stamp_change_flags(out)
    total = 0.0
    any_amt = False
    for ln in out.get("lines") or []:
        amt = _amount(ln)
        if amt > 0:
            total += amt
            any_amt = True
    if any_amt:
        out["grandTotal"] = round(total, 2)
        calc = dict(out.get("lastCalculation") or {}) if isinstance(out.get("lastCalculation"), Mapping) else {}
        price = dict(calc.get("price") or {}) if isinstance(calc.get("price"), Mapping) else {}
        price["total"] = round(total, 2)
        calc["price"] = price
        out["lastCalculation"] = calc
    return out


def version_quote_rows(doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extra ledger rows for older versions. The caller prices them."""
    current_sig = line_signature(lines_for_commercial_display(doc))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        approved = int(doc.get("approvedVersion") or 0)
    except (TypeError, ValueError):
        approved = 0
    status = str(doc.get("status") or "").strip().lower()
    for snap in collect_snapshots(doc):
        sig = str(snap.get("signature") or "")
        if not sig or sig == current_sig or sig in seen:
            continue
        seen.add(sig)
        ver = int(snap.get("version") or 0)
        rows.append(
            {
                "version": ver,
                "quotationId": snap.get("quotationId") or doc.get("quotationId"),
                "lines": snap.get("lines") or [],
                "status": "approved" if status in _APPROVED and approved and ver == approved else "version",
                "savedAt": snap.get("savedAt"),
            }
        )
    return rows
