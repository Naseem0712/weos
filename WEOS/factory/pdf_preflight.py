"""Customer PDF preflight — fail closed on incomplete commercial content.

Designed so a future immutable QuoteSnapshot can feed the same validator +
renderer pipeline as today's live cart payload (no second competing architecture).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Mapping, Sequence

_log = logging.getLogger("weos.pdf_preflight")

# Built-in / demo strings that must never silently substitute for quote terms.
_BANNED_TERM_MARKERS = (
    "demo terms",
    "warranty: 1 year manufacturing defects (demo",
)


class PdfCompletenessError(Exception):
    """Raised when a customer PDF would omit required commercial content."""

    def __init__(
        self,
        message: str,
        *,
        errors: Sequence[str] | None = None,
        missing_ids: Sequence[str] | None = None,
        status: str = "Error",
    ) -> None:
        self.errors = [str(e) for e in (errors or []) if str(e).strip()]
        self.missing_ids = [str(i) for i in (missing_ids or []) if str(i).strip()]
        self.status = status
        if self.errors and message not in self.errors:
            detail = "; ".join(self.errors[:8])
            message = f"{message}: {detail}" if message else detail
        if self.missing_ids and "missing" not in message.lower():
            message = f"{message} (missing IDs: {', '.join(self.missing_ids[:12])})"
        super().__init__(message or "PDF completeness check failed")

    def as_detail(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": str(self),
            "errors": list(self.errors),
            "missingIds": list(self.missing_ids),
        }


def line_id_of(line: Mapping[str, Any] | None) -> str:
    if not isinstance(line, Mapping):
        return ""
    return str(line.get("lineId") or line.get("id") or "").strip()


def is_manual_commercial_line(line: Mapping[str, Any] | None) -> bool:
    """Manual / commercial-only lines do not require an engineered drawing."""
    if not isinstance(line, Mapping):
        return False
    kind = str(
        line.get("itemKind")
        or line.get("manufacturingMode")
        or line.get("quoteItemKind")
        or ""
    ).strip().upper()
    if kind in ("MANUAL", "COMMERCIAL_MANUAL", "MANUAL_PRODUCT"):
        return True
    if line.get("manualProduct") or line.get("isManual") or line.get("manualOnly"):
        return True
    pt = str(line.get("productType") or line.get("product_type") or "").strip().lower()
    if pt in ("manual", "commercial", "other", "custom", "manual_product"):
        return True
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    if isinstance(opts, Mapping):
        ok = str(opts.get("itemKind") or opts.get("manufacturingMode") or "").strip().upper()
        if ok in ("MANUAL", "COMMERCIAL_MANUAL"):
            return True
        if opts.get("manualProduct") or opts.get("isManual"):
            return True
    return False


def _has_design_photo(line: Mapping[str, Any]) -> bool:
    photo = line.get("designPhoto")
    if not isinstance(photo, Mapping):
        opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
        photo = opts.get("designPhoto") if isinstance(opts, Mapping) else None
    if not isinstance(photo, Mapping):
        return False
    return bool(str(photo.get("key") or "").strip())


def _durable_svg(line: Mapping[str, Any]) -> str:
    prev = line.get("preview") if isinstance(line.get("preview"), Mapping) else {}
    svg = str((prev or {}).get("svg") or (prev or {}).get("pdfSvg") or "").strip()
    if svg and "<svg" in svg.lower():
        return svg
    return ""


def svg_content_hash(svg: str) -> str:
    raw = str(svg or "").encode("utf-8", errors="replace")
    return hashlib.sha1(raw).hexdigest() if raw else ""


def drawing_source_status(line: Mapping[str, Any]) -> tuple[str, str]:
    """Return (status, detail). status in READY|OPTIONAL|MISSING."""
    if is_manual_commercial_line(line):
        if _has_design_photo(line) or _durable_svg(line):
            return "READY", "manual-with-media"
        return "OPTIONAL", "manual-no-drawing-required"
    if _has_design_photo(line):
        return "READY", "design-photo"
    if _durable_svg(line):
        return "READY", "durable-svg"
    # Regenerable engineered geometry (engines / ReportLab schematics).
    try:
        w = float(line.get("width") or 0)
        h = float(line.get("height") or 0)
    except (TypeError, ValueError):
        w = h = 0.0
    product = str(line.get("product") or line.get("productId") or "").strip()
    if product and (w > 0 or h > 0):
        return "READY", "regenerable-geometry"
    # Specials sometimes encode size in options only.
    opts = line.get("options") if isinstance(line.get("options"), Mapping) else {}
    for nest_key in ("railing", "shower", "ventilator", "pergola"):
        nest = opts.get(nest_key) if isinstance(opts, Mapping) else None
        if not isinstance(nest, Mapping):
            continue
        try:
            nw = float(
                nest.get("widthMm")
                or nest.get("lengthMm")
                or nest.get("width")
                or 0
            )
            nh = float(
                nest.get("heightMm")
                or nest.get("depthMm")
                or nest.get("postHeightMm")
                or nest.get("height")
                or 0
            )
        except (TypeError, ValueError):
            nw = nh = 0.0
        if nw > 0 or nh > 0:
            return "READY", f"regenerable-{nest_key}"
    # Explicit pergola product without nested size must still not be silently omitted
    # when the line is identifiable as pergola with any footprint.
    try:
        from WEOS.factory.line_kind import is_pergola_cart_line

        if is_pergola_cart_line(line) and (w > 0 or h > 0 or product):
            return "READY", "regenerable-pergola"
    except Exception:
        pass
    return "MISSING", "no-photo-svg-or-geometry"


def resolve_terms_text(
    payload: Mapping[str, Any],
    *,
    template: Mapping[str, Any] | None = None,
    branding: Mapping[str, Any] | None = None,
    allow_builtin_default: bool = False,
) -> tuple[str, str]:
    """Return (terms_text, source). source: quote|template|company|builtin|none."""
    quote_terms = str(payload.get("terms") or "").strip()
    if quote_terms:
        low = quote_terms.lower()
        for ban in _BANNED_TERM_MARKERS:
            if ban in low:
                raise PdfCompletenessError(
                    "Quote terms contain banned demo/default substitute text",
                    errors=["terms_demo_substitute"],
                )
        return quote_terms, "quote"
    template = template or {}
    for b in template.get("blocks") or []:
        if isinstance(b, Mapping) and b.get("type") == "terms":
            text = str(b.get("text") or "").strip()
            if text:
                return text, "template"
    branding = branding or payload.get("branding") or template.get("branding") or {}
    if isinstance(branding, Mapping):
        company_terms = str(branding.get("terms") or "").strip()
        if company_terms:
            low = company_terms.lower()
            for ban in _BANNED_TERM_MARKERS:
                if ban in low:
                    raise PdfCompletenessError(
                        "Company terms contain banned demo substitute text",
                        errors=["terms_demo_substitute"],
                    )
            return company_terms, "company"
    if allow_builtin_default:
        return (
            "1. Specs & sizes may differ 7–9 mm after site measurement.\n"
            "2. Pricing Ex-Works unless noted. GST extra as applicable.\n"
            "3. Payment as agreed. Order confirmation required.\n"
            "4. Delivery typically 3+ weeks from confirmation.\n"
            "5. Quotation valid 15 days.\n"
            "6. Warranty: profile manufacturing defects as per policy.",
            "builtin",
        )
    return "", "none"


def _manual_field_issues(line: Mapping[str, Any]) -> list[str]:
    lid = line_id_of(line) or "?"
    issues: list[str] = []
    name = str(line.get("displayName") or line.get("name") or line.get("product") or "").strip()
    if not name:
        issues.append(f"{lid}: manual product missing name")
    try:
        qty = float(line.get("qty") or line.get("quantity") or 0)
    except (TypeError, ValueError):
        qty = 0.0
    if qty <= 0:
        issues.append(f"{lid}: manual product missing qty")
    selling = line.get("selling") if isinstance(line.get("selling"), Mapping) else {}
    rate = line.get("sellingRate")
    if rate in (None, "") and selling:
        rate = selling.get("sellingRate")
    if rate in (None, ""):
        # amount alone can still print
        amt = selling.get("sellingAmount") if selling else None
        if amt in (None, ""):
            amt = line.get("commercialTotal")
        if amt in (None, ""):
            issues.append(f"{lid}: manual product missing rate/amount")
    unit = str(line.get("saleUnit") or (selling or {}).get("saleUnit") or "").strip()
    if not unit:
        issues.append(f"{lid}: manual product missing unit")
    return issues


def preflight_customer_pdf(
    payload: Mapping[str, Any],
    *,
    expected_line_ids: Sequence[str] | None = None,
    template: Mapping[str, Any] | None = None,
    require_terms: bool = False,
    allow_builtin_terms: bool = False,
    strict_drawings: bool = True,
) -> dict[str, Any]:
    """Validate payload before Download/Print.

    Returns a READY report dict, or raises PdfCompletenessError.
    """
    errors: list[str] = []
    missing_ids: list[str] = []
    lines = [ln for ln in (payload.get("lines") or []) if isinstance(ln, Mapping)]

    if expected_line_ids is not None:
        expected = [str(x).strip() for x in expected_line_ids if str(x).strip()]
        have = {line_id_of(ln) for ln in lines}
        for eid in expected:
            if eid not in have:
                missing_ids.append(eid)
                errors.append(f"Expected line missing from PDF payload: {eid}")
        if len(lines) != len(expected):
            errors.append(
                f"Line count mismatch: expected {len(expected)} rendered {len(lines)}"
            )

    # Duplicate / blank IDs undermine determinism and merge.
    seen: set[str] = set()
    for ln in lines:
        lid = line_id_of(ln)
        if not lid:
            errors.append("Cart line missing lineId (required for PDF reliability)")
            continue
        if lid in seen:
            errors.append(f"Duplicate lineId in PDF payload: {lid}")
        seen.add(lid)

    drawing_report: list[dict[str, Any]] = []
    for ln in lines:
        lid = line_id_of(ln) or "?"
        status, detail = drawing_source_status(ln)
        drawing_report.append({"lineId": lid, "status": status, "detail": detail})
        if strict_drawings and status == "MISSING":
            missing_ids.append(lid)
            errors.append(f"Drawing unavailable for line {lid} ({detail})")
        if is_manual_commercial_line(ln):
            errors.extend(_manual_field_issues(ln))

    # Specs: every non-empty line must produce at least one structured row.
    try:
        from WEOS.factory.marqt_pdf import _spec_rows
    except Exception:
        _spec_rows = None  # type: ignore
    if _spec_rows is not None:
        for ln in lines:
            lid = line_id_of(ln) or "?"
            try:
                rows = _spec_rows(ln, audience="customer")
            except Exception as exc:
                errors.append(f"Specs build failed for line {lid}: {exc}")
                continue
            if not rows:
                errors.append(f"Specs empty for line {lid}")
            # Pergola must not be silently omitted from design summary content.
            try:
                from WEOS.factory.line_kind import is_pergola_cart_line

                if is_pergola_cart_line(ln):
                    labels = {str(a or "").upper() for a, _ in rows}
                    required = {"SIZE", "ROOF", "SIDES", "DECK"}
                    missing_labels = sorted(required - labels)
                    if missing_labels:
                        errors.append(
                            f"Pergola design summary incomplete for line {lid}: missing {', '.join(missing_labels)}"
                        )
                    summary = ln.get("designSummary")
                    if not isinstance(summary, Mapping):
                        opts = ln.get("options") if isinstance(ln.get("options"), Mapping) else {}
                        nest = opts.get("pergola") if isinstance(opts, Mapping) else None
                        summary = (nest or {}).get("designSummary") if isinstance(nest, Mapping) else None
                    if not isinstance(summary, Mapping):
                        errors.append(f"Pergola designSummary missing for line {lid}")
            except Exception as exc:
                errors.append(f"Pergola preflight check failed for line {lid}: {exc}")
            # If a description exists on the line, it must survive into NOTE or display.
            desc = str(ln.get("description") or "").strip()
            title = str(ln.get("displayName") or ln.get("product") or "").strip()
            if desc and desc != title:
                blob = " ".join(f"{a} {b}" for a, b in rows).lower()
                # soft check — description may be truncated; require some token
                token = desc.split()[0].lower() if desc.split() else ""
                if token and len(token) > 2 and token not in blob and "note" not in blob:
                    # Do not hard-fail on truncation; record warning only via log.
                    _log.debug("description token %r not obvious in specs for %s", token, lid)

    quote_desc = str(payload.get("description") or "").strip()
    # Description is optional; if present we only assert it is kept on the payload
    # (renderer cover block prints it). Empty is OK.

    terms_text, terms_source = resolve_terms_text(
        payload,
        template=template,
        branding=payload.get("branding") if isinstance(payload.get("branding"), Mapping) else None,
        allow_builtin_default=allow_builtin_terms,
    )
    if require_terms and not terms_text:
        errors.append("Terms missing — refuse silent demo/default substitute")
    if terms_text:
        low = terms_text.lower()
        for ban in _BANNED_TERM_MARKERS:
            if ban in low:
                errors.append("Terms contain banned demo substitute text")

    # Totals presence (commercial)
    try:
        commercial = 0.0
        for ln in lines:
            selling = ln.get("selling") if isinstance(ln.get("selling"), Mapping) else {}
            amt = None
            try:
                from WEOS.factory.customer_line_view import customer_line_amount

                amt = customer_line_amount(ln)
            except Exception:
                amt = selling.get("sellingAmount") if selling else None
            if amt is None:
                amt = ln.get("commercialTotal")
            if amt is None:
                amt = (ln.get("price") or {}).get("total")
            commercial += float(amt or 0)
    except Exception:
        commercial = -1.0
    if lines and commercial < 0:
        errors.append("Unable to resolve commercial totals for PDF")

    report = {
        "status": "READY" if not errors else "Error",
        "lineCount": len(lines),
        "expectedCount": len(expected_line_ids) if expected_line_ids is not None else len(lines),
        "missingIds": missing_ids,
        "errors": errors,
        "termsSource": terms_source,
        "termsPresent": bool(terms_text),
        "descriptionPresent": bool(quote_desc),
        "drawings": drawing_report,
        "commercialTotal": commercial if commercial >= 0 else None,
    }
    if errors:
        raise PdfCompletenessError(
            "PDF preflight failed",
            errors=errors,
            missing_ids=missing_ids,
            status="Error",
        )
    return report


def assert_not_minimal_pdf(pdf: bytes) -> None:
    """Reject emergency one-line minimal PDF bodies for customer exports."""
    raw = bytes(pdf or b"")
    if not raw.startswith(b"%PDF"):
        raise PdfCompletenessError(
            "Customer PDF is not a valid PDF",
            errors=["invalid_pdf"],
        )
    # Minimal builder embeds a tiny BT ... Td stream with Project/Quote/Total only.
    if len(raw) < 1200 and b"/F1 12 Tf" in raw and b"WEOS" in raw:
        raise PdfCompletenessError(
            "Customer PDF degraded to minimal stub — refused",
            errors=["minimal_pdf_refused"],
        )


def commercial_text_fingerprint(pdf: bytes) -> str:
    """Stable-ish commercial content hash (ignore binary object ids)."""
    try:
        from pypdf import PdfReader
        import io

        reader = PdfReader(io.BytesIO(pdf))
        parts: list[str] = []
        for page in reader.pages:
            t = page.extract_text() or ""
            # Drop page footers that include page numbers.
            lines_out = []
            for row in t.splitlines():
                low = row.strip().lower()
                if "computer generated document" in low:
                    continue
                if low.startswith("page ") and low[5:].strip().isdigit():
                    continue
                lines_out.append(row.rstrip())
            parts.append("\n".join(lines_out))
        blob = "\n---\n".join(parts)
    except Exception:
        blob = pdf.decode("latin-1", errors="ignore")
        # Strip fluctuating xref offsets roughly by keeping printable runs only.
        blob = "".join(ch if 32 <= ord(ch) < 127 or ch in "\n\r\t" else " " for ch in blob)
    normalized = "\n".join(line.rstrip() for line in blob.splitlines() if line.strip())
    return hashlib.sha1(normalized.encode("utf-8", errors="replace")).hexdigest()
