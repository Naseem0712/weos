"""Durable public quote share tokens + live scan record.

QR codes encode ``/q/{token}`` (also ``/scan/{token}``). The token is stable
across quote edits; scanning always reads the latest project + ledger from DB,
never a frozen PDF snapshot.

Tokens live on the project document (``shareToken``) and as a durable index
row ``quote_share:{token}`` so lookup survives redeploys.
"""

from __future__ import annotations

import html
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Mapping

_log = logging.getLogger("weos.quote_share")

TOKEN_KEY_PREFIX = "quote_share:"
OLD_DRAFT_DAYS = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_share_token() -> str:
    """URL-safe token; stable once stored on the quote/project."""
    return secrets.token_urlsafe(18)


def share_index_key(token: str) -> str:
    return f"{TOKEN_KEY_PREFIX}{(token or '').strip()}"


def _norm_gst(value: Any) -> str:
    try:
        from WEOS.factory.company_store import normalise_gstin

        return normalise_gstin(str(value or ""))
    except Exception:
        import re

        return re.sub(r"[^A-Za-z0-9]", "", str(value or "")).upper()


def ensure_project_share_token(doc: dict[str, Any], *, persist: bool = False) -> str:
    """Guarantee ``shareToken`` on a project dict. Optionally write-through."""
    token = str(doc.get("shareToken") or doc.get("quoteShareToken") or "").strip()
    if not token:
        token = new_share_token()
        doc["shareToken"] = token
        doc["quoteShareToken"] = token
        if persist and doc.get("projectId"):
            try:
                from WEOS.factory.project_store import save_project

                save_project(doc, bump_version=False, action="share_token")
            except Exception:
                _log.exception("persist share token failed for %s", doc.get("projectId"))
    else:
        doc["shareToken"] = token
        doc.setdefault("quoteShareToken", token)
    _index_share_token(token, doc)
    return token


def _index_share_token(token: str, doc: Mapping[str, Any]) -> None:
    token = (token or "").strip()
    if not token:
        return
    payload = {
        "token": token,
        "projectId": doc.get("projectId"),
        "quotationId": doc.get("quotationId") or doc.get("quoteNumber") or doc.get("quoteId"),
        "companyGst": _norm_gst(doc.get("companyGst")),
        "customer": doc.get("customer"),
        "updatedAt": _now_iso(),
    }
    try:
        from WEOS.db.durable_store import put_json

        put_json(share_index_key(token), "quote_share", payload)
    except Exception:
        _log.debug("share token index write skipped", exc_info=True)


def lookup_share_index(token: str) -> dict[str, Any] | None:
    token = (token or "").strip()
    if not token:
        return None
    try:
        from WEOS.db.durable_store import get_json

        row = get_json(share_index_key(token))
        return row if isinstance(row, dict) else None
    except Exception:
        return None


def find_project_by_share_token(token: str) -> dict[str, Any] | None:
    """Resolve a live project document from a public share token."""
    token = (token or "").strip()
    if not token:
        return None
    idx = lookup_share_index(token)
    pid = str((idx or {}).get("projectId") or "").strip()
    if pid:
        try:
            from WEOS.factory.project_store import load_project

            doc = load_project(pid)
            if str(doc.get("shareToken") or doc.get("quoteShareToken") or "").strip() == token:
                return doc
            # Token index can outlive a regenerated token — still return live doc
            # if the project id matches (scan must never die after quote update).
            if not str(doc.get("shareToken") or "").strip():
                doc["shareToken"] = token
            return doc
        except FileNotFoundError:
            pass
        except Exception:
            _log.exception("load project by share token id failed: %s", pid)

    # Scan durable + filesystem projects (dev / missing index).
    try:
        from WEOS.factory.project_store import list_projects, load_project

        for row in list_projects(include_archived=True, company_gst=None, include_unscoped=True):
            try:
                doc = load_project(str(row.get("projectId") or ""))
            except Exception:
                continue
            if str(doc.get("shareToken") or doc.get("quoteShareToken") or "").strip() == token:
                _index_share_token(token, doc)
                return doc
    except Exception:
        _log.exception("share token project scan failed")
    return None


def resolve_public_ref(ref: str) -> dict[str, Any] | None:
    """Resolve ``/q/{ref}`` — token, quote number, quote id, or project id."""
    ref = (ref or "").strip()
    if not ref:
        return None
    doc = find_project_by_share_token(ref)
    if doc:
        return doc
    try:
        from WEOS.factory.project_store import find_project_by_quotation_id, load_project

        hit = find_project_by_quotation_id(ref)
        if isinstance(hit, dict) and hit.get("projectId"):
            return load_project(str(hit["projectId"]))
        try:
            return load_project(ref)
        except FileNotFoundError:
            pass
    except Exception:
        pass
    try:
        from WEOS.db.quote_store import get_quote_by_ref

        q = get_quote_by_ref(ref)
        if isinstance(q, dict):
            pid = q.get("projectId")
            if pid:
                try:
                    from WEOS.factory.project_store import load_project

                    return load_project(str(pid))
                except Exception:
                    pass
            return {"_quoteRow": q, "projectId": q.get("projectId"), "quotationId": q.get("quoteNumber") or q.get("quoteId")}
    except Exception:
        pass
    return None


def _money(n: Any) -> float:
    try:
        if n is None or n == "":
            return 0.0
        return float(n)
    except (TypeError, ValueError):
        return 0.0


def _customer_safe_products(lines: list[Any] | None, *, doc: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Customer-facing line list — no factory BOM / purchase rates."""
    from WEOS.factory.customer_line_view import public_product_row, public_products_from_doc

    if isinstance(doc, Mapping):
        rows = public_products_from_doc(doc)
        if rows:
            return rows
    out: list[dict[str, Any]] = []
    for i, ln in enumerate(lines or []):
        if not isinstance(ln, dict):
            continue
        out.append(public_product_row(i, ln))
    return out


def _advances_for_project(customer: str, project_id: str | None, quote_id: str | None) -> list[dict[str, Any]]:
    if not customer:
        return []
    try:
        from WEOS.factory.ledger_store import list_advances

        rows = list_advances(customer)
    except Exception:
        return []
    pid = str(project_id or "").strip()
    qid = str(quote_id or "").strip().upper()
    matched: list[dict[str, Any]] = []
    for a in rows:
        ap = str(a.get("projectId") or "").strip()
        aq = str(a.get("quoteId") or "").strip().upper()
        if pid and ap == pid:
            matched.append(a)
        elif qid and aq and aq == qid:
            matched.append(a)
        elif not pid and not qid:
            matched.append(a)
    # If none linked to this quote, still show customer advances that name this quote.
    if not matched and (pid or qid):
        return []
    # Chronological for running total
    matched.sort(key=lambda r: str(r.get("paidAt") or r.get("createdAt") or ""))
    running = 0.0
    out = []
    for i, a in enumerate(matched, 1):
        amt = round(_money(a.get("amount")), 2)
        running = round(running + amt, 2)
        out.append(
            {
                "n": i,
                "id": a.get("id"),
                "amount": amt,
                "paymentMode": a.get("paymentMode") or a.get("mode") or "—",
                "date": a.get("paidAt") or a.get("createdAt"),
                "reference": a.get("reference") or "",
                "quoteVersion": a.get("quoteVersion"),
                "runningTotal": running,
            }
        )
    return out


def build_public_quote_record(ref: str) -> dict[str, Any] | None:
    """Live customer/project record for the public scan page."""
    doc = resolve_public_ref(ref)
    quote_row = None
    if isinstance(doc, dict) and doc.get("_quoteRow"):
        quote_row = doc.get("_quoteRow")
        doc = {k: v for k, v in doc.items() if k != "_quoteRow"}
        if not doc.get("lines") and isinstance(quote_row, dict):
            doc["lines"] = quote_row.get("lines") or []
            doc["quotationId"] = doc.get("quotationId") or quote_row.get("quoteNumber")
            doc["status"] = doc.get("status") or quote_row.get("status")
            doc["version"] = doc.get("version") or quote_row.get("version")
            doc["grandTotal"] = doc.get("grandTotal") or quote_row.get("grandTotal")
            doc["customer"] = doc.get("customer") or (
                (quote_row.get("customer") or {}).get("name")
                if isinstance(quote_row.get("customer"), dict)
                else quote_row.get("customer")
            )
            doc["updatedAt"] = doc.get("updatedAt") or quote_row.get("updatedAt")
    if not doc:
        return None

    token = ensure_project_share_token(doc, persist=bool(doc.get("projectId")))
    gst = _norm_gst(doc.get("companyGst"))
    company: dict[str, Any] = {}
    try:
        from WEOS.factory.company_store import load_company, load_company_by_gst

        if gst:
            company = dict(load_company_by_gst(gst) or {})
        if not company:
            company = dict(load_company() or {})
    except Exception:
        company = {}

    customer_name = str(doc.get("customer") or "").strip()
    customer_profile: dict[str, Any] = {}
    try:
        if customer_name:
            from WEOS.factory.customer_store import load_customer_profile

            customer_profile = dict(load_customer_profile(customer_name) or {})
    except Exception:
        customer_profile = {}

    calc = doc.get("lastCalculation") if isinstance(doc.get("lastCalculation"), dict) else {}
    price = (calc.get("price") or {}) if isinstance(calc, dict) else {}
    commercial = _money(price.get("total") if price.get("total") is not None else doc.get("grandTotal"))
    from WEOS.factory.ledger_store import quote_money_parts

    money = quote_money_parts(commercial)
    qid = str(doc.get("quotationId") or doc.get("quoteNumber") or doc.get("quoteId") or "").strip()
    pid = str(doc.get("projectId") or "").strip()
    advances = _advances_for_project(customer_name, pid or None, qid or None)
    total_adv = round(sum(_money(a.get("amount")) for a in advances), 2)
    taxable = money["totalTaxable"]
    grand = money["totalGrand"]
    balance = round(taxable - total_adv, 2)
    balance_gst = round(grand - total_adv, 2)

    versions: list[dict[str, Any]] = []
    try:
        from WEOS.factory.customer_store import _project_versions

        if pid:
            versions = list(_project_versions(pid) or [])
    except Exception:
        versions = []
    version_count = max(int(doc.get("version") or 1), len(versions) + 1)

    status = str(doc.get("status") or "draft").strip().lower() or "draft"
    products = _customer_safe_products(list(doc.get("lines") or []), doc=doc)
    from WEOS.factory.customer_line_view import totals_by_type
    from WEOS.factory.ledger_store import CONFIRMED_STATUSES
    from WEOS.factory.project_pack import public_pack_payload

    approved = status in CONFIRMED_STATUSES or bool(advances)
    type_totals = totals_by_type(list(doc.get("lines") or []))
    pack = public_pack_payload(doc, share_token=token, approved=approved)
    ledger_html = f"/q/{token}/ledger" if token else None
    all_pdf = f"/api/public/quote/{token}/all.pdf" if token else None

    return {
        "ok": True,
        "live": True,
        "shareToken": token,
        "scanPath": f"/q/{token}",
        "scanAltPath": f"/scan/{token}",
        "projectId": pid or None,
        "quoteNumber": qid or pid or token,
        "version": int(doc.get("version") or 1),
        "versionCount": version_count,
        "versions": [
            {
                "version": v.get("version"),
                "updatedAt": v.get("updatedAt") or v.get("savedAt"),
                "grandTotal": v.get("grandTotal"),
            }
            for v in versions[-12:]
        ],
        "status": status,
        "approvalStatus": status,
        "approved": approved,
        "customer": {
            "name": customer_name or customer_profile.get("name") or "—",
            "phone": doc.get("customerMobile") or customer_profile.get("phone") or "",
            "gstNo": doc.get("customerGst") or customer_profile.get("gstNo") or "",
            "address": doc.get("customerAddress") or customer_profile.get("address") or "",
        },
        "company": {
            "name": company.get("companyName") or company.get("name") or "",
            "gstNo": company.get("gstNo") or gst or "",
            "phone": company.get("phone") or "",
            "email": company.get("email") or "",
            "address": company.get("address") or "",
            "website": company.get("website") or "",
        },
        "value": {
            "totalTaxable": taxable,
            "totalGst": money["totalGst"],
            "gstPercent": money["gstPercent"],
            "totalGrand": grand,
        },
        "advances": advances,
        "advanceCount": len(advances),
        "totalAdvance": total_adv,
        "balance": balance,
        "balanceWithGst": balance_gst,
        "products": products,
        "productCount": len(products),
        "typeTotals": type_totals,
        "pack": pack,
        "createdAt": doc.get("createdAt"),
        "updatedAt": doc.get("updatedAt") or _now_iso(),
        "customerPdfUrl": f"/api/projects/{pid}/customer-pdf" if pid else None,
        "ledgerPdfUrl": f"/api/customers/{customer_name}/ledger.pdf" if customer_name else None,
        "ledgerHtmlUrl": ledger_html,
        "allPdfUrl": all_pdf,
    }


def public_quote_url(payload: Mapping[str, Any], *, base: str = "") -> str:
    token = str(
        payload.get("shareToken")
        or payload.get("quoteShareToken")
        or payload.get("quoteRef")
        or payload.get("quoteId")
        or payload.get("quoteNumber")
        or payload.get("quotationId")
        or payload.get("projectId")
        or ""
    ).strip()
    from urllib.parse import quote as _urlquote

    ref = _urlquote(token or "WEOS", safe="")
    b = (base or "").rstrip("/")
    return f"{b}/q/{ref}" if b else f"/q/{ref}"


def render_scan_html(record: Mapping[str, Any], *, base_url: str = "") -> str:
    """Self-contained public HTML — no login. Always reflects ``record`` (live DB)."""
    co = record.get("company") or {}
    cust = record.get("customer") or {}
    val = record.get("value") or {}
    status = str(record.get("status") or "draft")
    approved = bool(record.get("approved"))
    badge = "Approved" if approved else status.replace("_", " ").title()
    badge_bg = "#0a5a48" if approved else ("#b45324" if status in ("draft", "unused") else "#334155")

    def inr(n: Any) -> str:
        try:
            return f"₹{float(n or 0):,.2f}"
        except (TypeError, ValueError):
            return "₹—"

    def esc(x: Any) -> str:
        return html.escape("" if x is None else str(x))

    def fmt_dt(iso: Any) -> str:
        if not iso:
            return "—"
        text = str(iso)
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt.strftime("%d %b %Y, %I:%M %p")
        except Exception:
            return esc(text[:19].replace("T", " "))

    adv_rows = ""
    for a in record.get("advances") or []:
        adv_rows += (
            f"<tr><td>{esc(a.get('n'))}</td><td>{inr(a.get('amount'))}</td>"
            f"<td>{esc(a.get('paymentMode'))}</td><td>{fmt_dt(a.get('date'))}</td>"
            f"<td>{inr(a.get('runningTotal'))}</td></tr>"
        )
    if not adv_rows:
        adv_rows = '<tr><td colspan="5" class="muted">No advances recorded yet</td></tr>'

    prod_rows = ""
    for p in record.get("products") or []:
        amt = inr(p.get("amount")) if p.get("amount") is not None else "—"
        loc = p.get("location") or p.get("locationName") or p.get("positionName") or "—"
        extra = " · ".join(
            x
            for x in (
                "" if not p.get("glass") or str(p.get("glass")) == "—" else str(p.get("glass")),
                "" if not p.get("colour") or str(p.get("colour")) == "—" else str(p.get("colour")),
            )
            if x
        )
        type_cell = esc(p.get("type"))
        if extra:
            type_cell += f'<div class="muted" style="font-size:.72rem">{esc(extra)}</div>'
        prod_rows += (
            f"<tr><td>{esc(p.get('serial'))}</td><td>{esc(loc)}</td>"
            f"<td>{type_cell}</td><td>{esc(p.get('size'))}</td>"
            f"<td>{esc(p.get('qty'))}</td><td>{amt}</td></tr>"
        )
    if not prod_rows:
        prod_rows = '<tr><td colspan="6" class="muted">No products on this quote</td></tr>'

    type_tot_html = ""
    for trow in record.get("typeTotals") or []:
        type_tot_html += (
            f"<div class='muted' style='margin:.15rem 0'>{esc(trow.get('type'))} × {esc(trow.get('qty'))}"
            f" · {inr(trow.get('amount'))}</div>"
        )

    pack = record.get("pack") or {}
    pack_html = ""
    if approved:
        upd_html = ""
        for u in pack.get("updates") or []:
            upd_html += (
                f"<div class='item'><div class='muted'>{fmt_dt(u.get('date') or u.get('createdAt'))}</div>"
                f"<div>{esc(u.get('text') or u.get('note') or '')}</div></div>"
            )
        if not upd_html:
            upd_html = '<p class="muted">No process updates yet</p>'
        doc_html = ""
        labels = {"bill": "Bill", "warranty": "Warranty card", "challan": "Delivery challan"}
        for d in pack.get("documents") or []:
            href = esc(d.get("url") or "#")
            if base_url and href.startswith("/"):
                href = base_url.rstrip("/") + href
            kind = labels.get(str(d.get("kind") or ""), str(d.get("kind") or "File").title())
            note = esc(d.get("note") or d.get("filename") or kind)
            ct = str(d.get("contentType") or "")
            thumb = ""
            if ct.startswith("image/"):
                thumb = f'<a href="{href}" target="_blank" rel="noopener"><img src="{href}" alt="" style="max-height:72px;max-width:110px;border-radius:8px;border:1px solid var(--line);object-fit:cover"/></a>'
            doc_html += (
                f'<div class="item" style="display:flex;gap:.6rem;align-items:center;flex-wrap:wrap">'
                f"{thumb}<div><strong>{esc(kind)}</strong>"
                f'<div class="muted">{fmt_dt(d.get("date") or d.get("createdAt"))} · {note}</div>'
                f'<a class="btn ghost" href="{href}" target="_blank" rel="noopener">Open / download</a></div></div>'
            )
        if not doc_html:
            doc_html = '<p class="muted">No bills, warranty cards, or delivery challans yet</p>'
        photo_html = ""
        for ph in pack.get("photos") or []:
            href = esc(ph.get("url") or "#")
            if base_url and href.startswith("/"):
                href = base_url.rstrip("/") + href
            cap = esc(ph.get("note") or ph.get("filename") or "Photo")
            photo_html += (
                f'<a href="{href}" target="_blank" rel="noopener" style="display:inline-block;margin:.2rem">'
                f'<img src="{href}" alt="{cap}" style="max-height:140px;max-width:180px;border-radius:10px;border:1px solid var(--line);object-fit:cover"/>'
                f'<div class="muted" style="font-size:.72rem">{fmt_dt(ph.get("date") or ph.get("createdAt"))} · {cap}</div></a>'
            )
        if not photo_html:
            photo_html = '<p class="muted">No process photos yet</p>'
        pack_html = f"""
  <div class="card">
    <h2>Process updates</h2>
    {upd_html}
  </div>
  <div class="card">
    <h2>Bills / warranty / delivery challan</h2>
    {doc_html}
  </div>
  <div class="card">
    <h2>Process photos</h2>
    {photo_html}
  </div>"""
    else:
        pack_html = """
  <div class="card">
    <h2>Process pack</h2>
    <p class="muted">Available after approval</p>
  </div>"""

    ver_bits = []
    for v in record.get("versions") or []:
        ver_bits.append(f"v{esc(v.get('version'))}")
    if not ver_bits:
        ver_bits.append(f"v{esc(record.get('version') or 1)}")
    versions_txt = ", ".join(ver_bits)
    if int(record.get("versionCount") or 1) > 1:
        versions_txt += f" · {esc(record.get('versionCount'))} versions"

    pdf_url = record.get("customerPdfUrl") or ""
    led_url = record.get("ledgerPdfUrl") or ""
    all_url = record.get("allPdfUrl") or ""
    led_html = record.get("ledgerHtmlUrl") or ""
    if base_url:
        b = base_url.rstrip("/")
        if pdf_url and pdf_url.startswith("/"):
            pdf_url = b + pdf_url
        if led_url and led_url.startswith("/"):
            led_url = b + led_url
        if all_url and all_url.startswith("/"):
            all_url = b + all_url
        if led_html and led_html.startswith("/"):
            led_html = b + led_html

    links = []
    if all_url:
        links.append(f'<a class="btn" href="{esc(all_url)}" target="_blank" rel="noopener">Download all (A4 PDF)</a>')
    if pdf_url:
        links.append(f'<a class="btn ghost" href="{esc(pdf_url)}" target="_blank" rel="noopener">Customer PDF</a>')
    if led_url:
        links.append(f'<a class="btn ghost" href="{esc(led_url)}" target="_blank" rel="noopener">Ledger PDF</a>')
    if led_html:
        links.append(f'<a class="btn ghost" href="{esc(led_html)}" target="_blank" rel="noopener">Ledger</a>')
    links_html = " ".join(links) if links else ""

    co_name = esc(co.get("name") or "WEOS")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<meta name="robots" content="noindex"/>
<title>Quote {esc(record.get('quoteNumber'))} · {co_name}</title>
<style>
:root{{--ink:#141410;--muted:#5c584f;--bg:#e8e3d8;--card:#fffdf9;--line:rgba(20,20,16,.12);--green:#0a5a48}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:var(--ink);
  background:radial-gradient(ellipse 80% 50% at 0% -10%,#c9e5db,transparent 55%),
             radial-gradient(ellipse 60% 40% at 100% 0%,#efd6c2,transparent 50%),var(--bg)}}
.wrap{{max-width:820px;margin:0 auto;padding:1.1rem 1rem 2.5rem}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1rem 1.1rem;margin-bottom:.85rem;
  box-shadow:0 10px 40px rgba(20,20,16,.06)}}
h1{{font-size:1.35rem;margin:.15rem 0 .25rem}}
h2{{font-size:.95rem;margin:0 0 .55rem}}
.muted{{color:var(--muted);font-size:.82rem}}
.badge{{display:inline-block;background:{badge_bg};color:#fff;border-radius:999px;padding:.18rem .65rem;font-size:.75rem;font-weight:600}}
.kpis{{display:flex;flex-wrap:wrap;gap:.6rem}}
.kpi{{flex:1;min-width:140px;background:#f7f4ee;border-radius:10px;padding:.55rem .7rem}}
.kpi .l{{font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}}
.kpi .v{{font-size:1.05rem;font-weight:650;margin-top:.15rem}}
table{{width:100%;border-collapse:collapse;font-size:.85rem}}
th,td{{text-align:left;padding:.4rem .35rem;border-bottom:1px solid var(--line);vertical-align:top}}
th{{font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}}
.btn{{display:inline-block;background:var(--green);color:#f4faf7;text-decoration:none;border-radius:10px;
  padding:.45rem .75rem;font-weight:600;font-size:.85rem;margin:.15rem .25rem 0 0}}
.btn.ghost{{background:transparent;color:var(--green);border:1px solid var(--green)}}
.item{{padding:.45rem 0;border-bottom:1px solid var(--line)}}
.item:last-child{{border-bottom:0}}
.foot{{margin-top:.8rem;font-size:.75rem;color:var(--muted)}}
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="muted">Live quote · powered by WEOS</div>
    <h1>{co_name}</h1>
    <div class="muted">GSTIN {esc(co.get('gstNo') or '—')}
      {(' · ' + esc(co.get('phone'))) if co.get('phone') else ''}
      {(' · ' + esc(co.get('email'))) if co.get('email') else ''}
    </div>
    {f"<div class='muted' style='margin-top:.25rem'>{esc(co.get('address'))}</div>" if co.get('address') else ""}
  </div>
  <div class="card">
    <div class="row" style="display:flex;justify-content:space-between;gap:.6rem;flex-wrap:wrap;align-items:center">
      <div>
        <div class="muted">Quote number</div>
        <strong style="font-size:1.15rem">{esc(record.get('quoteNumber'))}</strong>
        <div class="muted" style="margin-top:.2rem">Versions: {versions_txt}</div>
      </div>
      <span class="badge">{esc(badge)}</span>
    </div>
    <div class="muted" style="margin-top:.45rem">Customer: {esc(cust.get('name'))}
      {(' · ' + esc(cust.get('phone'))) if cust.get('phone') else ''}
    </div>
    <div class="kpis" style="margin-top:.7rem">
      <div class="kpi"><div class="l">Taxable</div><div class="v">{inr(val.get('totalTaxable'))}</div></div>
      <div class="kpi"><div class="l">GST {esc(val.get('gstPercent') or 18)}%</div><div class="v">{inr(val.get('totalGst'))}</div></div>
      <div class="kpi"><div class="l">Grand (w/ GST)</div><div class="v">{inr(val.get('totalGrand'))}</div></div>
      <div class="kpi"><div class="l">Advance ({esc(record.get('advanceCount') or 0)}×)</div><div class="v">{inr(record.get('totalAdvance'))}</div></div>
      <div class="kpi"><div class="l">Balance outstanding</div><div class="v">{inr(record.get('balanceWithGst'))}</div></div>
    </div>
    {f'<div style="margin-top:.75rem">{links_html}</div>' if links_html else ''}
  </div>
  <div class="card">
    <h2>Advances</h2>
    <table>
      <thead><tr><th>#</th><th>Amount</th><th>Mode</th><th>Date</th><th>Running total</th></tr></thead>
      <tbody>{adv_rows}</tbody>
    </table>
  </div>
  <div class="card">
    <h2>Products</h2>
    <table>
      <thead><tr><th>Serial</th><th>Location</th><th>Type</th><th>Size</th><th>Qty</th><th>Amount</th></tr></thead>
      <tbody>{prod_rows}</tbody>
    </table>
    {f'<div style="margin-top:.55rem">{type_tot_html}</div>' if type_tot_html else ''}
  </div>
  {pack_html}
  <p class="foot">Last updated {fmt_dt(record.get('updatedAt'))}. This page always loads the live project from the company database — not a PDF snapshot.</p>
</div>
</body>
</html>"""
