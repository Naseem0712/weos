"""Quote copy suggestions — standard terms + product descriptions.

Reads uploaded quotes AND quotes generated/saved in WEOS, groups descriptions
and terms by product, and suggests in that same pattern.

Suggestions only. The operator reads, keeps, or edits before generating the PDF.
Never overwrites production products or saved quotes by itself.
"""

from __future__ import annotations

from typing import Any, Mapping

STANDARD_TERMS = (
    "1. Specs & sizes may differ 7–9 mm after site measurement.\n"
    "2. Pricing Ex-Works unless noted. GST extra as applicable.\n"
    "3. Payment as agreed. Order confirmation required.\n"
    "4. Delivery typically 3+ weeks from confirmation.\n"
    "5. Quotation valid 15 days.\n"
    "6. Warranty: profile manufacturing defects as per policy."
)

_PRODUCT_BLURBS = {
    "sliding": "Aluminium sliding {name} as per drawing — powder-coated finish, complete with rollers, handles and wool pile. Glass as specified. Sizes ±7–9 mm after site measure.",
    "windows": "Aluminium window {name} as per drawing — powder-coated, hardware complete, glass as specified. Site measurement before fabrication.",
    "casement": "Aluminium casement {name} as per drawing — friction stays / hinges, handles and locks as specified. Glass as quoted. Sizes ±7–9 mm after site measure.",
    "casements": "Aluminium casement {name} as per drawing — friction stays / hinges, handles and locks as specified. Glass as quoted. Sizes ±7–9 mm after site measure.",
    "door": "Aluminium door {name} as per drawing — powder-coated, lock and closer as specified. Glass / panel as quoted.",
    "fold": "Fold & sliding {name} as per drawing — bottom rollers, top guide, flush bolts and handles as specified. Glass as quoted.",
    "telescopic": "Telescopic sliding {name} as per drawing — multi-track, rollers and handles as specified. Glass as quoted.",
    "synchron": "Synchron / 2+2 sliding {name} as per drawing — linked shutters, rollers and handles as specified. Glass as quoted.",
    "style": "Style / slide door {name} as per drawing — floor spring or track as specified. Glass as quoted.",
    "railing": "Glass railing {name} as per drawing — sections, toughened glass and accessories as specified. Site measure before fabrication.",
    "staircase_railing": "Staircase glass railing {name} as per drawing — side/step mount as specified, toughened glass and accessories complete.",
    "shower_partition": "Shower partition {name} as per drawing — toughened glass, hardware and seals as specified. Site measure before fabrication.",
    "bathroom_ventilator": "Bathroom ventilator {name} as per drawing — aluminium frame, glass as specified, complete with hardware.",
    "pergolas": "Pergola {name} as per drawing — aluminium sections as specified. Site measure before fabrication.",
    "louvers": "Louvers {name} as per drawing — aluminium blades, frame and hardware as specified.",
}

_SOURCE_RANK = {
    "generated": 0,
    "observed": 0,
    "learned": 1,
    "company": 2,
    "catalogue": 3,
    "standard": 4,
}


def _norm_key(text: str, n: int = 200) -> str:
    return " ".join(str(text or "").lower().split())[:n]


def _needles(product_id: str | None, product_type: str = "", product_name: str = "") -> list[str]:
    out: list[str] = []
    for n in (product_id, product_type, product_name):
        s = str(n or "").strip().lower().replace("_", " ")
        if s and s not in out:
            out.append(s)
            compact = s.replace(" ", "")
            if compact != s:
                out.append(compact)
    return out


def _blob_hit(blob: str, needles: list[str]) -> bool:
    if not needles:
        return False
    low = (blob or "").lower()
    return any(n and n in low for n in needles)


def _useful_copy(text: str, *, min_len: int = 18, skip_names: list[str] | None = None) -> str:
    t = " ".join(str(text or "").split()).strip()
    if len(t) < min_len:
        return ""
    low = t.lower()
    for n in skip_names or []:
        if n and low == str(n).strip().lower():
            return ""
    return t


def _label(prefix: str, product: str, count: int) -> str:
    bits = [prefix]
    name = (product or "").strip()
    if name:
        bits.append(name[:36])
    if count > 1:
        bits.append(f"{count}×")
    return " · ".join(bits)


def _dedupe(rows: list[dict[str, str]], *, limit: int = 10) -> list[dict[str, str]]:
    ranked = sorted(
        rows,
        key=lambda r: (
            _SOURCE_RANK.get(str(r.get("source") or ""), 9),
            0 if r.get("productMatch") else 1,
            -int(r.get("count") or 0),
        ),
    )
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for row in ranked:
        text = str(row.get("text") or "").strip()
        if len(text) < 12:
            continue
        key = _norm_key(text, 180)
        if key in seen:
            continue
        seen.add(key)
        out.append({**row, "text": text})
        if len(out) >= limit:
            break
    return out


def _learned_terms() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    try:
        from WEOS.learning.v2_store import list_library

        for item in list_library("quotation_patterns"):
            excerpt = str(item.get("termsExcerpt") or item.get("terms") or "").strip()
            if excerpt:
                rows.append({"source": "learned", "label": "From uploaded quote", "text": excerpt})
            pay = str(item.get("paymentTerm") or "").strip()
            if pay:
                rows.append({"source": "learned", "label": "Payment term (past quotes)", "text": pay})
            war = str(item.get("warranty") or "").strip()
            if war:
                rows.append({"source": "learned", "label": "Warranty (past quotes)", "text": war})
        for item in list_library("templates"):
            sug = str(item.get("suggestedTerms") or "").strip()
            if sug:
                rows.append({"source": "learned", "label": "From uploaded template", "text": sug})
    except Exception:
        pass
    return rows


def _learned_descriptions(product_id: str | None, product_type: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    needles = _needles(product_id, product_type)
    try:
        from WEOS.learning.v2_store import list_library

        for item in list_library("quotation_patterns"):
            src_name = str(item.get("fileName") or item.get("source") or "uploaded quote")[:40]
            for ln in item.get("productDescriptions") or []:
                text = str(ln or "").strip()
                if not text:
                    continue
                hit = _blob_hit(text, needles)
                if needles and not hit and len(rows) >= 4:
                    continue
                rows.append(
                    {
                        "source": "learned",
                        "label": f"From uploaded quote · {src_name}" if src_name else "From uploaded quote",
                        "text": text,
                        "productMatch": hit,
                    }
                )
    except Exception:
        pass
    return rows


def _collect_bucket(
    buckets: dict[str, dict[str, Any]],
    text: str,
    *,
    product: str,
    matched: bool,
    source: str,
    prefix: str,
) -> None:
    key = _norm_key(text)
    if not key:
        return
    row = buckets.get(key)
    if row is None:
        buckets[key] = {
            "text": text,
            "count": 1,
            "product": product,
            "matched": matched,
            "source": source,
            "prefix": prefix,
        }
        return
    row["count"] = int(row.get("count") or 0) + 1
    if matched:
        row["matched"] = True
    if product and not row.get("product"):
        row["product"] = product


def _rows_from_buckets(buckets: Mapping[str, Mapping[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in buckets.values():
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        count = int(row.get("count") or 1)
        prod = str(row.get("product") or "").strip()
        rows.append(
            {
                "source": str(row.get("source") or "generated"),
                "label": _label(str(row.get("prefix") or "From your quotes"), prod, count),
                "text": text,
                "count": count,
                "productMatch": bool(row.get("matched")),
            }
        )
    return rows


def _from_observations(needles: list[str], skip_names: list[str]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    desc_b: dict[str, dict[str, Any]] = {}
    terms_b: dict[str, dict[str, Any]] = {}
    try:
        from WEOS.learning.commercial_agent import _read_observations

        for row in _read_observations(limit=2500):
            prod = str(row.get("product") or row.get("productId") or "").strip()
            disp = str(row.get("displayName") or "").strip()
            desc = _useful_copy(str(row.get("description") or ""), skip_names=skip_names + [prod, disp])
            terms = _useful_copy(str(row.get("terms") or ""), min_len=24)
            blob = " ".join((prod, disp, desc)).lower()
            hit = _blob_hit(blob, needles) if needles else True
            pname = disp or prod
            if desc:
                _collect_bucket(
                    desc_b,
                    desc,
                    product=pname,
                    matched=hit,
                    source="generated",
                    prefix="From generated quotes",
                )
            if terms:
                _collect_bucket(
                    terms_b,
                    terms,
                    product=pname if hit else "",
                    matched=hit,
                    source="generated",
                    prefix="Terms from generated quotes",
                )
    except Exception:
        pass
    return _rows_from_buckets(desc_b), _rows_from_buckets(terms_b)


def _line_fields(ln: Mapping[str, Any]) -> tuple[str, str, str, str]:
    prod = str(ln.get("product") or ln.get("productId") or "").strip()
    disp = str(ln.get("displayName") or ln.get("name") or "").strip()
    ptype = str(ln.get("productType") or ln.get("category") or "").strip()
    desc = str(ln.get("description") or "").strip()
    snap = ln.get("itemSnapshot") or ln.get("item_snapshot")
    if isinstance(snap, Mapping):
        prod = prod or str(snap.get("product_id") or "").strip()
        disp = disp or str(snap.get("product_name_snapshot") or "").strip()
        ptype = ptype or str(snap.get("category_snapshot") or "").strip()
    return prod, disp, ptype, desc


def _from_saved_projects(
    needles: list[str],
    skip_names: list[str],
    gst: str | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    desc_b: dict[str, dict[str, Any]] = {}
    terms_b: dict[str, dict[str, Any]] = {}
    try:
        from WEOS.factory.project_store import list_projects

        items = list_projects(company_gst=gst or None, sort="updatedAt", order="desc", limit=25)
    except Exception:
        items = []

    for item in items[:25]:
        pid = str((item or {}).get("projectId") or "").strip()
        if not pid:
            continue
        try:
            from WEOS.factory.project_store import load_project

            doc = load_project(pid)
        except Exception:
            continue
        qid = str(doc.get("quotationId") or pid)
        cover = _useful_copy(str(doc.get("description") or ""), min_len=18)
        terms = _useful_copy(str(doc.get("terms") or ""), min_len=24)
        lines = [ln for ln in (doc.get("lines") or []) if isinstance(ln, Mapping)]
        if not lines:
            calc = doc.get("lastCalculation") if isinstance(doc.get("lastCalculation"), Mapping) else {}
            lines = [ln for ln in (calc.get("lines") or []) if isinstance(ln, Mapping)]
        any_hit = False
        for ln in lines:
            if not isinstance(ln, Mapping):
                continue
            prod, disp, ptype, raw_desc = _line_fields(ln)
            blob = " ".join((prod, disp, ptype, raw_desc)).lower()
            hit = _blob_hit(blob, needles) if needles else True
            if hit:
                any_hit = True
            desc = _useful_copy(raw_desc, skip_names=skip_names + [prod, disp])
            if desc:
                _collect_bucket(
                    desc_b,
                    desc,
                    product=disp or prod or qid,
                    matched=hit,
                    source="generated",
                    prefix="From your quotes",
                )
        if cover:
            _collect_bucket(
                desc_b,
                cover,
                product=qid,
                matched=any_hit or (not needles),
                source="generated",
                prefix="Quote cover",
            )
        if terms:
            _collect_bucket(
                terms_b,
                terms,
                product=qid,
                matched=any_hit or (not needles),
                source="generated",
                prefix="Terms from your quotes",
            )
        for pq in doc.get("packageQuotes") or []:
            if not isinstance(pq, Mapping):
                continue
            pterms = _useful_copy(str(pq.get("terms") or pq.get("note") or ""), min_len=24)
            if pterms:
                _collect_bucket(
                    terms_b,
                    pterms,
                    product=str(pq.get("quotationId") or "uploaded"),
                    matched=True,
                    source="learned",
                    prefix="From uploaded quote",
                )
            for pit in pq.get("items") or []:
                if not isinstance(pit, Mapping):
                    continue
                pdesc = _useful_copy(str(pit.get("description") or pit.get("name") or ""))
                if not pdesc:
                    continue
                hit = _blob_hit(" ".join((str(pit.get("product") or ""), str(pit.get("name") or ""), pdesc)), needles)
                _collect_bucket(
                    desc_b,
                    pdesc,
                    product=str(pit.get("name") or pit.get("product") or "uploaded"),
                    matched=hit or (not needles),
                    source="learned",
                    prefix="From uploaded quote",
                )
    return _rows_from_buckets(desc_b), _rows_from_buckets(terms_b)


def _product_meta(product_id: str | None) -> dict[str, Any]:
    if not product_id:
        return {}
    try:
        from WEOS.factory.product_loader import load_product

        p = load_product(product_id, strict=False)
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}


def _type_blurb(product: Mapping[str, Any] | None, product_id: str | None) -> str:
    p = dict(product or {})
    name = str(p.get("displayName") or p.get("name") or product_id or "item").strip()
    pt = str(p.get("productType") or p.get("category") or "").strip().lower()
    tmpl = _PRODUCT_BLURBS.get(pt) or _PRODUCT_BLURBS.get(pt.replace(" ", "_"))
    if not tmpl and product_id:
        pid = product_id.lower()
        for key, val in _PRODUCT_BLURBS.items():
            if key in pid:
                tmpl = val
                break
    if not tmpl:
        tmpl = "Supply of {name} as per enclosed drawing and specifications. Sizes ±7–9 mm after site measure."
    return tmpl.format(name=name)


def quote_copy_suggestions(
    *,
    product_id: str | None = None,
    gst: str | None = None,
) -> dict[str, Any]:
    """Company / standard / generated / uploaded terms + product description chips."""
    company: dict[str, Any] = {}
    try:
        from WEOS.factory.company_store import load_company, load_company_by_gst, normalise_gstin

        g = normalise_gstin(gst or "")
        if g:
            company = load_company_by_gst(g) or {}
        if not company:
            company = load_company() or {}
    except Exception:
        company = {}
        g = gst or ""

    prod = _product_meta(product_id)
    pt = str(prod.get("productType") or prod.get("category") or "").strip()
    pname = str(prod.get("displayName") or prod.get("name") or "").strip()
    needles = _needles(product_id, pt, pname)
    skip_names = [n for n in (product_id, pname, pt) if n]

    obs_desc, obs_terms = _from_observations(needles, skip_names)
    saved_desc, saved_terms = _from_saved_projects(needles, skip_names, g or gst)

    terms: list[dict[str, str]] = []
    co_terms = str(company.get("terms") or "").strip()
    if co_terms:
        terms.append({"source": "company", "label": "Company saved terms", "text": co_terms})
    terms.append({"source": "standard", "label": "Regular terms (always available)", "text": STANDARD_TERMS})
    terms.extend(obs_terms)
    terms.extend(saved_terms)
    terms.extend(_learned_terms())

    descriptions: list[dict[str, str]] = []
    descriptions.extend(obs_desc)
    descriptions.extend(saved_desc)
    catalogue = str(prod.get("description") or "").strip()
    if catalogue:
        descriptions.append({"source": "catalogue", "label": "Product catalogue", "text": catalogue})
    tag = str(prod.get("tagline") or "").strip()
    if tag:
        descriptions.append({"source": "catalogue", "label": "Product tagline", "text": tag})
    blurb = _type_blurb(prod, product_id)
    descriptions.append({"source": "standard", "label": "Product-wise suggestion", "text": blurb})
    descriptions.extend(_learned_descriptions(product_id, pt))

    quote_desc = ""
    name = pname
    if name:
        quote_desc = f"Supply of {name} as per enclosed design, specifications and value."
    elif str(company.get("tagline") or "").strip():
        quote_desc = str(company.get("tagline")).strip()

    return {
        "ok": True,
        "standardTerms": STANDARD_TERMS,
        "companyTerms": co_terms,
        "quoteDescription": quote_desc,
        "terms": _dedupe(terms, limit=10),
        "descriptions": _dedupe(descriptions, limit=10),
        "productId": product_id or "",
        "safety": "Suggestions only — read and edit before generating the quote. Ranked from your generated and uploaded quotes for this product.",
    }
