"""Learning Engine V2 — orchestrator.

Upload → Extract → Pending Review → Approve → Versioned KB
Never auto-writes production products/profiles.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from WEOS.learning.models import (
    KIND_CATALOGUE_BUNDLE,
    KIND_FORMULA,
    KIND_GLASS,
    KIND_HARDWARE,
    KIND_PRODUCT_SERIES,
    KIND_PROFILE,
    KIND_QUOTATION_PATTERN,
    KIND_TEMPLATE,
    PIPELINE_SOURCES,
    STATUS_PENDING,
)
from WEOS.learning.pdf_catalogue import extract_catalogue_pdf, extract_image_stub
from WEOS.learning.profile_recognition import recognize_cross_sections
from WEOS.learning.quotation_learn import build_template_suggestion_from_quote, extract_quotation_patterns
from WEOS.learning.v2_store import (
    archive_pending_v2,
    create_pending,
    ensure_v2_dirs,
    get_library_item,
    list_kb_versions,
    list_library,
    list_pending_v2,
    load_pending,
    publish_kb_version,
    save_library_item,
    save_upload,
    write_pending,
    _now,
)


def pipeline_status() -> dict[str, Any]:
    ensure_v2_dirs()
    eng_count = 0
    com_count = 0
    try:
        from WEOS.learning.engineering_agent import agent_status as eng_status

        eng_count = eng_status().get("observationCount") or 0
    except Exception:
        pass
    try:
        from WEOS.learning.commercial_agent import agent_status as com_status

        com_count = com_status().get("observationCount") or 0
    except Exception:
        pass
    return {
        "autoWriteProduction": False,
        "flow": ["Extract", "Review", "Approve", "Knowledge Base Version", "Production (manual via Product Builder)"],
        "sources": list(PIPELINE_SOURCES),
        "pendingCount": len(list_pending_v2()),
        "kbVersion": (list_kb_versions()[-1]["version"] if list_kb_versions() else 0),
        "libraries": {
            "product_series": len(list_library("product_series")),
            "profiles": len(list_library("profiles")),
            "hardware": len(list_library("hardware")),
            "glass": len(list_library("glass")),
            "formulas": len(list_library("formulas")),
            "quotation_patterns": len(list_library("quotation_patterns")),
            "templates": len(list_library("templates")),
        },
        "liveLearning": {
            "engineeringObservations": eng_count,
            "commercialObservations": com_count,
        },
    }


def _merge_edits(payload: dict[str, Any], edits: dict[str, Any] | None) -> dict[str, Any]:
    if not edits:
        return payload
    out = copy.deepcopy(payload)
    for k, v in edits.items():
        if k == "profiles" and isinstance(v, list):
            out["profiles"] = v
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def ingest_file(
    path: str | Path,
    *,
    mode: str = "auto",
    original_filename: str | None = None,
    series_id_hint: str | None = None,
) -> dict[str, Any]:
    """
    Ingest a source file into one or more pending proposals.

    mode:
      auto | catalogue | profiles | quotation | template | formula | json
    """
    ensure_v2_dirs()
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    suf = path.suffix.lower()
    fname = original_filename or path.name
    mode_l = (mode or "auto").lower()

    if mode_l == "auto":
        if suf == ".pdf":
            # Heuristic: quotation-like filename vs catalogue
            low = fname.lower()
            if any(k in low for k in ("quote", "quotation", "mar-qt", "marqt", "offer", "estimate")):
                mode_l = "quotation"
            else:
                mode_l = "catalogue"
        elif suf in (".docx", ".doc"):
            mode_l = "quotation"
        elif suf == ".json":
            mode_l = "json"
        elif suf in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"):
            mode_l = "catalogue"
        elif suf == ".dxf":
            # Delegate to legacy propose path
            from WEOS.learning.ingest import propose

            legacy = propose(path, profile_id=series_id_hint)
            return {
                "ok": True,
                "mode": "engineering_rules_legacy",
                "proposals": [
                    {
                        "proposal_id": legacy["proposal_id"],
                        "kind": "engineering_rules",
                        "title": legacy.get("profile_id"),
                        "legacy": True,
                    }
                ],
                "message": "DXF routed to legacy engineering-rules pending queue (still requires approve).",
            }
        else:
            mode_l = "catalogue"

    created: list[dict[str, Any]] = []

    if mode_l in ("catalogue", "profiles"):
        if suf in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"):
            extraction = extract_image_stub(path)
        else:
            extraction = extract_catalogue_pdf(path)
            # Enrich with cross-section recognition
            try:
                xsec = recognize_cross_sections(path, series_id=extraction["series"]["id"])
                # Merge profiles: prefer richer entries
                by_key: dict[str, dict[str, Any]] = {}
                for p in extraction.get("profiles") or []:
                    by_key[f"{p.get('profileType')}|{p.get('pdfPageNumber')}|{p.get('profileCode')}"] = p
                for p in xsec.get("profiles") or []:
                    k = f"{p.get('profileType')}|{p.get('pdfPageNumber')}|{p.get('profileCode')}"
                    if k not in by_key:
                        by_key[k] = p
                    elif p.get("profileImage") and not by_key[k].get("profileImage"):
                        by_key[k]["profileImage"] = p["profileImage"]
                extraction["profiles"] = list(by_key.values())
                extraction["page_previews"] = xsec.get("page_previews") or []
            except Exception as exc:
                extraction.setdefault("notes", []).append(f"Cross-section pass skipped: {exc}")

        if series_id_hint:
            extraction["series"]["id"] = series_id_hint
            for p in extraction.get("profiles") or []:
                p["compatibleSeries"] = [series_id_hint]
                p["seriesId"] = series_id_hint

        series = extraction["series"]
        payload = {
            "series": series,
            "profiles": extraction.get("profiles") or [],
            "hardware": extraction.get("hardware") or [],
            "glass": extraction.get("glass") or [],
            "formulas": extraction.get("formulas") or [],
            "page_previews": extraction.get("page_previews") or [],
        }
        prop = create_pending(
            kind=KIND_CATALOGUE_BUNDLE,
            title=series.get("seriesName") or fname,
            payload=payload,
            source={"type": extraction.get("source_type"), "filename": fname, "path": str(path)},
            summary=(
                f"Detected {len(payload['profiles'])} profiles, "
                f"{len(payload['hardware'])} hardware, "
                f"{len(payload['glass'])} glass, "
                f"{len(payload['formulas'])} formulas"
            ),
            confidence=float(extraction.get("confidence") or 0.5),
            item_counts={
                "profiles": len(payload["profiles"]),
                "hardware": len(payload["hardware"]),
                "glass": len(payload["glass"]),
                "formulas": len(payload["formulas"]),
            },
            notes=list(extraction.get("notes") or []),
            match_hints=list(extraction.get("match_hints") or []),
        )
        created.append(_brief(prop))

    elif mode_l == "quotation":
        extraction = extract_quotation_patterns(path)
        pattern = extraction["pattern"]
        prop = create_pending(
            kind=KIND_QUOTATION_PATTERN,
            title=f"Quote pattern · {fname}",
            payload={
                "pattern": pattern,
                "stats": extraction.get("stats") or {},
                "suggestions": extraction.get("suggestions") or [],
            },
            source={"type": extraction.get("source_type"), "filename": fname, "path": str(path)},
            summary="; ".join((extraction.get("suggestions") or [])[:2]) or "Quotation pattern extracted",
            confidence=float(extraction.get("confidence") or 0.5),
            notes=list(extraction.get("notes") or []),
        )
        created.append(_brief(prop))

        # Optional companion template suggestion (also pending)
        tpl = build_template_suggestion_from_quote(pattern)
        tprop = create_pending(
            kind=KIND_TEMPLATE,
            title=tpl.get("name") or f"Template from {fname}",
            payload=tpl,
            source={"type": "quotation", "filename": fname, "path": str(path)},
            summary="Reusable quotation template suggestion (does not overwrite existing templates)",
            confidence=0.4,
            notes=["Suggestion only — Template Designer remains source of truth for live templates."],
        )
        created.append(_brief(tprop))

    elif mode_l == "template":
        extraction = extract_quotation_patterns(path)
        tpl = build_template_suggestion_from_quote(extraction["pattern"])
        prop = create_pending(
            kind=KIND_TEMPLATE,
            title=tpl.get("name") or fname,
            payload=tpl,
            source={"type": "upload", "filename": fname, "path": str(path)},
            summary="Template suggestion from uploaded document",
            confidence=0.4,
        )
        created.append(_brief(prop))

    elif mode_l == "json":
        data = json.loads(path.read_text(encoding="utf-8"))
        kind = data.get("kind") or KIND_CATALOGUE_BUNDLE
        title = data.get("title") or data.get("seriesName") or path.stem
        prop = create_pending(
            kind=kind if kind in (
                KIND_CATALOGUE_BUNDLE, KIND_PRODUCT_SERIES, KIND_PROFILE,
                KIND_HARDWARE, KIND_GLASS, KIND_FORMULA, KIND_QUOTATION_PATTERN, KIND_TEMPLATE,
            ) else KIND_CATALOGUE_BUNDLE,
            title=str(title),
            payload=data.get("payload") or data,
            source={"type": "json", "filename": fname, "path": str(path)},
            summary=data.get("summary") or "JSON catalogue ingest",
            confidence=float(data.get("confidence") or 0.75),
            notes=["JSON ingest — review before approve."],
        )
        created.append(_brief(prop))

    elif mode_l == "formula":
        text = path.read_text(encoding="utf-8", errors="ignore") if suf != ".pdf" else ""
        if suf == ".pdf":
            from WEOS.learning.pdf_catalogue import extract_catalogue_pdf

            extraction = extract_catalogue_pdf(path)
            formulas = extraction.get("formulas") or []
        else:
            from WEOS.learning.pdf_catalogue import extract_formulas_from_text

            formulas = extract_formulas_from_text(text, series_id=series_id_hint or "general")
        prop = create_pending(
            kind=KIND_FORMULA,
            title=f"Formulas · {fname}",
            payload={"formulas": formulas},
            source={"type": suf.lstrip("."), "filename": fname, "path": str(path)},
            summary=f"{len(formulas)} formula candidates",
            confidence=0.4,
            item_counts={"formulas": len(formulas)},
        )
        created.append(_brief(prop))

    else:
        raise ValueError(f"Unknown ingest mode: {mode}")

    return {
        "ok": True,
        "mode": mode_l,
        "source": fname,
        "proposals": created,
        "message": f"Created {len(created)} pending review item(s). Nothing written to production.",
    }


def ingest_upload_bytes(
    filename: str,
    data: bytes,
    *,
    mode: str = "auto",
    series_id_hint: str | None = None,
) -> dict[str, Any]:
    stored = save_upload(filename, data)
    return ingest_file(
        stored["path"],
        mode=mode,
        original_filename=filename,
        series_id_hint=series_id_hint,
    )


def _brief(prop: dict[str, Any]) -> dict[str, Any]:
    return {
        "proposal_id": prop["proposal_id"],
        "kind": prop["kind"],
        "title": prop.get("title"),
        "summary": prop.get("summary"),
        "confidence": prop.get("confidence"),
        "item_counts": prop.get("item_counts") or {},
    }


def get_proposal(proposal_id: str) -> dict[str, Any]:
    return load_pending(proposal_id)


def update_proposal_edits(proposal_id: str, edits: dict[str, Any]) -> dict[str, Any]:
    """Admin corrections before approve — stored on the pending doc, not production."""
    prop = load_pending(proposal_id)
    if prop.get("status") != STATUS_PENDING:
        raise ValueError("Only pending proposals can be edited")
    prop["edits"] = {**(prop.get("edits") or {}), **edits}
    # Allow replacing payload sections directly for Review UX
    if "payload" in edits and isinstance(edits["payload"], dict):
        prop["payload"] = _merge_edits(prop.get("payload") or {}, edits["payload"])
        prop["edits"].pop("payload", None)
    prop["updated_at"] = _now()
    write_pending(prop)
    return prop


def approve_proposal(
    proposal_id: str,
    *,
    approved_by: str = "admin",
    publish_version: bool = True,
) -> dict[str, Any]:
    """Approve pending → write libraries (dedupe/link) → optional KB version."""
    prop = load_pending(proposal_id)
    if prop.get("status") != STATUS_PENDING:
        # Allow legacy engineering_rules via old ingest
        if "proposed_profile" in prop:
            from WEOS.learning.ingest import approve as legacy_approve

            return legacy_approve(proposal_id, confirmed_by=approved_by)
        raise ValueError(f"Proposal status is {prop.get('status')!r}, not pending")

    kind = prop.get("kind")
    payload = _merge_edits(prop.get("payload") or {}, prop.get("edits") or {})
    results: list[dict[str, Any]] = []

    if kind == KIND_CATALOGUE_BUNDLE:
        series = payload.get("series") or {}
        if series:
            results.append({"library": "product_series", **save_library_item("product_series", series)})
        for p in payload.get("profiles") or []:
            if p.get("linkTo"):
                p["id"] = p["linkTo"]
            results.append({"library": "profiles", **save_library_item("profiles", p)})
        for h in payload.get("hardware") or []:
            results.append({"library": "hardware", **save_library_item("hardware", h)})
        for g in payload.get("glass") or []:
            results.append({"library": "glass", **save_library_item("glass", g)})
        for f in payload.get("formulas") or []:
            results.append({"library": "formulas", **save_library_item("formulas", f)})

    elif kind == KIND_PRODUCT_SERIES:
        results.append({"library": "product_series", **save_library_item("product_series", payload)})

    elif kind == KIND_PROFILE:
        results.append({"library": "profiles", **save_library_item("profiles", payload)})

    elif kind == KIND_HARDWARE:
        results.append({"library": "hardware", **save_library_item("hardware", payload)})

    elif kind == KIND_GLASS:
        results.append({"library": "glass", **save_library_item("glass", payload)})

    elif kind == KIND_FORMULA:
        for f in payload.get("formulas") or ([payload] if payload.get("expression") else []):
            results.append({"library": "formulas", **save_library_item("formulas", f)})

    elif kind == KIND_QUOTATION_PATTERN:
        pattern = payload.get("pattern") or payload
        results.append({"library": "quotation_patterns", **save_library_item("quotation_patterns", pattern)})

    elif kind == KIND_TEMPLATE:
        # Store suggestion only — never overwrite WEOS/templates
        results.append({"library": "templates", **save_library_item("templates", payload)})

    else:
        raise ValueError(f"Cannot approve kind {kind!r} via V2 (use legacy approve for engineering_rules)")

    prop["status"] = "approved"
    prop["approved_at"] = _now()
    prop["approved_by"] = approved_by
    prop["approve_results"] = [{"action": r.get("action"), "library": r.get("library"), "id": (r.get("item") or {}).get("id")} for r in results]
    archive_pending_v2(proposal_id, status="approved", proposal=prop)

    version_meta = None
    if publish_version:
        version_meta = publish_kb_version(
            reason=f"Approved {kind} proposal {proposal_id}",
            proposal_id=proposal_id,
            approved_by=approved_by,
        )

    return {
        "status": "approved",
        "proposal_id": proposal_id,
        "kind": kind,
        "results": prop["approve_results"],
        "knowledge_base_version": version_meta,
        "production_modified": False,
        "message": "Saved to Knowledge Base libraries. Production products unchanged.",
    }


def reject_proposal(proposal_id: str, *, reason: str = "", rejected_by: str = "admin") -> dict[str, Any]:
    prop = load_pending(proposal_id)
    # Legacy?
    if "proposed_profile" in prop and prop.get("kind") is None:
        from WEOS.learning.ingest import reject as legacy_reject

        return legacy_reject(proposal_id, reason=reason)
    prop["status"] = "rejected"
    prop["rejected_at"] = _now()
    prop["rejected_by"] = rejected_by
    prop["reject_reason"] = reason
    archive_pending_v2(proposal_id, status="rejected", proposal=prop)
    return {"status": "rejected", "proposal_id": proposal_id, "reason": reason}


def list_proposals(*, kind: str | None = None) -> list[dict[str, Any]]:
    items = list_pending_v2(kind=kind)
    # Also surface legacy pending (engineering rules)
    try:
        from WEOS.learning.knowledge_base import list_pending, load_pending_proposal

        for pid in list_pending():
            if pid.startswith("v2_"):
                continue
            try:
                doc = load_pending_proposal(pid)
            except Exception:
                continue
            if doc.get("status") not in (STATUS_PENDING, "pending", "pending_approval"):
                continue
            items.append(
                {
                    "proposal_id": pid,
                    "kind": "engineering_rules",
                    "status": doc.get("status"),
                    "title": doc.get("profile_id") or pid,
                    "summary": doc.get("reason") or "Legacy DXF/JSON engineering rules",
                    "confidence": None,
                    "created_at": doc.get("created_at"),
                    "source_type": doc.get("source_type"),
                    "source_name": Path(str(doc.get("source_path") or "")).name,
                    "item_counts": {"rules": len(doc.get("review") or [])},
                    "match_hints": [],
                    "legacy": True,
                }
            )
    except Exception:
        pass
    return items
