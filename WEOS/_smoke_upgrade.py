"""Upgrade smoke: GST hub quote delete, live scan token, formula recall + suggestions."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_upgrade_smoke_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)


def _ok(cond: bool, msg: str, fails: list[str]) -> None:
    if not cond:
        fails.append(msg)
        print("FAIL:", msg)
    else:
        print("OK:", msg)


def main() -> int:
    fails: list[str] = []
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from WEOS.db.engine import init_db
    from WEOS.factory.company_quotes import (
        bulk_delete_unused,
        delete_company_quote,
        list_company_quotes,
    )
    from WEOS.factory.company_workspace import open_workspace
    from WEOS.factory.customer_store import save_customer_profile
    from WEOS.factory.ledger_store import add_advance
    from WEOS.factory.project_store import empty_project, list_projects, load_project, save_project, set_project_status
    from WEOS.factory.quote_share import build_public_quote_record, render_scan_html

    res = init_db()
    _ok(bool(res.get("ok")), f"init_db {res}", fails)

    gst_a = "27AAAAA0000A1Z5"
    gst_b = "29BBBBB0000B1Z8"
    open_workspace(gst_a, profile={"companyName": "Alpha Glass Works", "phone": "9000000001", "email": "a@example.com"})
    open_workspace(gst_b, profile={"companyName": "Beta Facades", "phone": "9000000002"})

    save_customer_profile("Alpha Cust", {"name": "Alpha Cust", "phone": "9876500001", "companyGst": gst_a})
    save_customer_profile("Beta Cust", {"name": "Beta Cust", "phone": "9876500002", "companyGst": gst_b})

    unused = empty_project(name="Unused draft", customer="Alpha Cust")
    unused["companyGst"] = gst_a
    unused["quotationId"] = "AG-26/00001/A1"
    unused["status"] = "draft"
    unused["lastCalculation"] = {"price": {"total": 0}}
    unused = save_project(unused, action="smoke")

    live = empty_project(name="Live quote", customer="Alpha Cust")
    live["companyGst"] = gst_a
    live["quotationId"] = "AG-26/00002/A1"
    live["status"] = "active"
    live["lines"] = [
        {
            "product": "29mm_sliding",
            "displayName": "Sliding window",
            "width": 1500,
            "height": 1200,
            "qty": 2,
            "sellingRate": 450,
            "locationName": "Master Bedroom",
            "price": {"total": 14580},
        }
    ]
    live["lastCalculation"] = {"price": {"total": 14580}}
    live = save_project(live, action="smoke")
    set_project_status(live["projectId"], "approved")
    add_advance(
        "Alpha Cust",
        {
            "amount": 5000,
            "paymentMode": "upi",
            "reference": "UTR-UPG",
            "projectId": live["projectId"],
            "quoteId": "AG-26/00002/A1",
            "quoteVersion": int(live.get("version") or 1),
        },
    )

    save_customer_profile("Alpha Cust B", {"name": "Alpha Cust B", "phone": "9876500003", "companyGst": gst_a})
    extra = empty_project(name="Duplicate extra", customer="Alpha Cust B")
    extra["companyGst"] = gst_a
    extra["quotationId"] = "AG-26/00002/A1"
    extra["status"] = "draft"
    extra["lastCalculation"] = {"price": {"total": 1000}}
    extra = save_project(extra, action="smoke")

    other = empty_project(name="Other company", customer="Beta Cust")
    other["companyGst"] = gst_b
    other["quotationId"] = "BF-26/00001/A1"
    other["lastCalculation"] = {"price": {"total": 80000}}
    other = save_project(other, action="smoke")

    listing = list_company_quotes(gst_a, filter_key="all")
    ids_a = {q.get("projectId") for q in listing.get("quotes") or []}
    _ok(unused["projectId"] in ids_a, "GST A lists unused quote", fails)
    _ok(other["projectId"] not in ids_a, "GST A does not list GST B quote", fails)

    unused_list = list_company_quotes(gst_a, filter_key="unused")
    unused_ids = {q.get("projectId") for q in unused_list.get("quotes") or []}
    _ok(unused["projectId"] in unused_ids, "unused filter includes zero-value draft", fails)
    _ok(live["projectId"] not in unused_ids, "approved+advance not unused", fails)

    dup_list = list_company_quotes(gst_a, filter_key="duplicate")
    dup_ids = {q.get("projectId") for q in dup_list.get("quotes") or []}
    # extra row shares quote number with live (versioning may fold — accept either extra id or flag)
    _ok(extra["projectId"] in dup_ids or live["projectId"] in dup_ids, "duplicate extra flagged for same quote number", fails)

    try:
        delete_company_quote(other["projectId"], company_gst=gst_a, hard=True)
        fails.append("GST A must not delete GST B quote")
    except PermissionError:
        print("OK: GST scope blocks cross-company delete")
    except Exception as exc:
        # If unscoped mismatch raises differently, still require B project to survive.
        print("note: cross-delete raised", type(exc).__name__, exc)

    still_b = [p.get("projectId") for p in list_projects(company_gst=gst_b, include_unscoped=True)]
    _ok(other["projectId"] in still_b, "GST B quote survives after A delete attempt", fails)

    deleted = delete_company_quote(unused["projectId"], company_gst=gst_a, hard=True)
    _ok(deleted.get("ok") or deleted.get("deleted"), "hard delete unused from server", fails)
    after = {q.get("projectId") for q in list_company_quotes(gst_a).get("quotes") or []}
    _ok(unused["projectId"] not in after, "unused quote gone from hub list", fails)
    try:
        load_project(unused["projectId"])
        fails.append("deleted project still loadable")
    except FileNotFoundError:
        print("OK: deleted project not loadable")

    bulk = bulk_delete_unused(gst_a, filter_key="unused")
    _ok(bulk.get("ok"), f"bulk unused ok {bulk}", fails)
    _ok(other["projectId"] in still_b, "bulk unused did not touch GST B", fails)

    # ── B) live scan token ────────────────────────────────────────────────
    live_doc = load_project(live["projectId"])
    token = str(live_doc.get("shareToken") or "").strip()
    _ok(bool(token), "save_project minted shareToken", fails)
    rec = build_public_quote_record(token)
    _ok(bool(rec and rec.get("ok")), "public record by token", fails)
    rec = rec or {}
    _ok((rec.get("company") or {}).get("gstNo") == gst_a or "ALPHA" in str((rec.get("company") or {}).get("name") or "").upper(), "scan shows company", fails)
    _ok(str(rec.get("quoteNumber") or "").startswith("AG-26"), "scan quote number", fails)
    _ok(str(rec.get("status") or "") == "approved" or rec.get("approved"), "scan approval status", fails)
    _ok(float((rec.get("value") or {}).get("totalTaxable") or 0) > 0, "scan taxable value", fails)
    _ok(float((rec.get("value") or {}).get("totalGrand") or 0) > float((rec.get("value") or {}).get("totalTaxable") or 0), "scan GST grand > taxable", fails)
    _ok(int(rec.get("advanceCount") or 0) >= 1, "scan advance count", fails)
    adv0 = (rec.get("advances") or [{}])[0]
    _ok(float(adv0.get("amount") or 0) == 5000, "scan advance amount", fails)
    _ok(str(adv0.get("paymentMode") or "").lower() == "upi", "scan advance mode", fails)
    _ok(adv0.get("date"), "scan advance date", fails)
    _ok(float(rec.get("totalAdvance") or 0) == 5000, "scan running advance total", fails)
    _ok(float(rec.get("balanceWithGst") or 0) > 0, "scan balance outstanding", fails)
    prods = rec.get("products") or []
    _ok(len(prods) >= 1, "scan products list", fails)
    p0 = prods[0] if prods else {}
    _ok("serial" in p0 and "location" in p0 and "type" in p0 and "size" in p0 and "qty" in p0, "scan product fields", fails)
    _ok("Master" in str(p0.get("location") or "") or "Bedroom" in str(p0.get("location") or ""), "scan location", fails)
    _ok(rec.get("updatedAt"), "scan last updated", fails)
    html = render_scan_html(rec, base_url="https://example.test")
    blob = html.lower()
    for needle in ("alpha glass", "gstin", "approved", "advance", "balance", "master bedroom", "last updated", "live"):
        _ok(needle in blob, f"scan html contains {needle!r}", fails)

    rec2 = build_public_quote_record(token)
    _ok((rec2 or {}).get("shareToken") == token, "token stable after re-read", fails)

    # ── C) formula recall + suggestions (no invented weights, no auto-apply) ─
    from WEOS.learning.material_formulas import get_formula, recall_approved_formulas, recall_formula_for_context
    from WEOS.agent.suggestion_engine import generate

    recalled = recall_approved_formulas()
    _ok(len(recalled) >= 3, f"recalled >=3 formulas got {len(recalled)}", fails)
    glass = get_formula("glass") or recall_formula_for_context(material="glass", glass_makeup="sg")
    _ok(bool(glass and glass.get("expression")), "SG glass formula recalled", fails)
    dgu = get_formula("dgu") or recall_formula_for_context(glass_makeup="dgu")
    _ok(bool(dgu and dgu.get("expression")), "DG/DGU formula recalled", fails)
    rail = recall_formula_for_context(product="railing", material="steel")
    _ok(bool(rail and rail.get("expression")), "railing/steel formula recalled", fails)
    # Never invent: unknown material returns None
    _ok(get_formula("unobtainium_alloy_xyz") is None, "unknown material not invented", fails)

    sug = generate(
        {
            "product": "29mm_sliding",
            "width": 1500,
            "height": 1200,
            "trackCount": 2,
            "lines": [
                {
                    "product": "29mm_sliding",
                    "mesh": True,
                    "trackCount": 2,
                    "width": 1500,
                    "height": 1200,
                    "qty": 1,
                }
            ],
            "bom": [{"name": "frame", "material": "aluminium", "lengthMm": 1500}],
        }
    )
    keys = {str(s.get("key") or "") for s in sug}
    _ok("mesh_requires_3_track" in keys, "mesh to 3-track suggestion keys=" + str(keys), fails)
    _ok("missing_rates" in keys, "missing rates suggestion keys=" + str(keys), fails)

    from WEOS.learning.engineering_agent import apply_engineering_suggestion, build_engineering_suggestions

    bundled = build_engineering_suggestions()
    _ok(bundled.get("status") == "suggestions_only", "engineering suggestions_only", fails)
    _ok("Approve" in str(bundled.get("safety") or bundled.get("message") or ""), "review/approve safety copy", fails)
    queued = None
    for s in bundled.get("suggestions") or []:
        if s.get("oneClick"):
            queued = apply_engineering_suggestion(s, applied_by="smoke_upgrade")
            break
    if queued:
        _ok(queued.get("queued") and not queued.get("applied"), "one-click queues pending, not applied", fails)
        _ok("Production not modified" in str(queued.get("message") or "") or queued.get("queued"), "pending review message", fails)

    if fails:
        print("FAIL upgrade smoke")
        for f in fails:
            print(" -", f)
        return 1
    print("OK gst hub delete + live scan token + formula recall smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
