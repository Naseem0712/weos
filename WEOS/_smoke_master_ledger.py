"""Package quote GST math + Master Ledger isolation (no cross-job leak)."""
from __future__ import annotations

from WEOS.factory.master_ledger import job_quote_rows, ledger_from_docs, match_master_query
from WEOS.factory.package_quote import compute_gst_split, normalize_package_quotes, package_money_for_doc
from WEOS.factory.project_store import cart_quote_money, live_quote_money


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    inc = compute_gst_split(118000, gst_mode="include", gst_percent=18)
    _ok(inc["projectValue"] == 118000, f"include project value 118000 got {inc['projectValue']}")
    _ok(inc["gstAmount"] == 18000, f"include GST 18000 got {inc['gstAmount']}")
    _ok(inc["totalTaxable"] == 100000, f"include taxable 100000 got {inc['totalTaxable']}")

    exc = compute_gst_split(100000, gst_mode="exclude", gst_percent=18)
    _ok(exc["projectValue"] == 118000, f"exclude value 118000 got {exc['projectValue']}")
    _ok(exc["gstAmount"] == 18000, f"exclude GST 18000 got {exc['gstAmount']}")

    off = compute_gst_split(50000, gst_mode="off", gst_percent=18)
    _ok(off["gstAmount"] == 0 and off["projectValue"] == 50000, f"GST off got {off}")

    quotes = normalize_package_quotes(
        [
            {
                "id": "pq_a",
                "quotationId": "Q-A",
                "gstMode": "exclude",
                "gstPercent": 18,
                "items": [
                    {"category": "window", "qty": 4, "size": "1200x1500", "amount": 80000},
                    {"category": "ventilator", "qty": 2, "amount": 20000},
                ],
            },
            {
                "id": "pq_b",
                "quotationId": "Q-B",
                "gstMode": "off",
                "items": [{"category": "railing", "qty": 10, "unit": "rft", "amount": 15000}],
            },
        ]
    )
    _ok(len(quotes) == 2, f"2 package quotes got {len(quotes)}")
    money = package_money_for_doc({"packageQuotes": quotes})
    _ok(money["projectValue"] == 133000, f"job value 100k+18% + 15k = 133000 got {money['projectValue']}")

    pkg_only = {
        "projectId": "PRJ-SMOKE-ISO-A",
        "customer": "Alpha",
        "customerMobile": "9876543210",
        "packageQuotes": quotes,
        "lines": [],
    }
    live = live_quote_money(pkg_only)
    _ok(live["totalGrand"] == 133000, f"live package grand 133000 got {live['totalGrand']}")
    cart = cart_quote_money(pkg_only)
    _ok(cart["totalGrand"] == 0, f"package-only cart grand 0 got {cart['totalGrand']}")

    a = {
        "projectId": "PRJ-SMOKE-ISO-A",
        "masterJobId": "PRJ-SMOKE-ISO-A",
        "customer": "Alpha",
        "customerMobile": "9876543210",
        "quotationId": "Q-A",
        "packageQuotes": quotes,
        "name": "Site A",
    }
    b = {
        "projectId": "PRJ-SMOKE-ISO-B",
        "masterJobId": "PRJ-SMOKE-ISO-B",
        "customer": "Beta",
        "customerMobile": "9123456789",
        "quotationId": "Q-B-OTHER",
        "packageQuotes": [
            {"id": "pq_z", "gstMode": "off", "items": [{"category": "gate", "amount": 999999}]}
        ],
        "name": "Site B",
    }
    _ok(match_master_query(a, "9876543210"), "search Alpha by mobile")
    _ok(not match_master_query(b, "9876543210"), "Beta must not match Alpha mobile")
    _ok(match_master_query(a, "Q-A"), "search Alpha by quote number")
    _ok(not match_master_query(b, "Q-A"), "Beta must not match Alpha quote number")
    _ok(match_master_query(b, "Beta"), "search Beta by name")

    led_a = ledger_from_docs([a])
    led_b = ledger_from_docs([b])
    _ok(led_a["totals"]["projectValue"] == 133000, "ledger A value isolated")
    _ok(led_b["totals"]["projectValue"] == 999999, "ledger B value isolated")
    ids_a = {q["id"] for q in led_a["quotes"]}
    ids_b = {q["id"] for q in led_b["quotes"]}
    _ok("pq_z" not in ids_a, "B package quote must not appear on A")
    _ok("pq_a" not in ids_b, "A package quote must not appear on B")
    _ok(led_a["totals"]["totalAdvances"] == 0, "no advances leaked onto A")
    rows = job_quote_rows([a])
    _ok(len(rows) == 2, f"A has 2 package quotes got {len(rows)}")

    empty = normalize_package_quotes([{"items": [{"category": "window"}]}])
    _ok(empty == [], "zero-amount quotes are dropped")

    att_q = normalize_package_quotes(
        [
            {
                "id": "pq_att",
                "quotationId": "OUT-1",
                "gstMode": "off",
                "items": [{"category": "window", "qty": 2, "size": "1200x1500", "amount": 25000}],
                "attachments": [
                    {"id": "pf_pdf", "kind": "quote_pdf", "filename": "outside.pdf"},
                    {"id": "pf_pic", "kind": "photo", "filename": "site.jpg"},
                ],
            }
        ],
        project_id="PRJ-SMOKE-MIX",
    )
    _ok(len(att_q) == 1 and len(att_q[0]["attachments"]) == 2, "PDF + photo attachments survive normalize")
    kinds = {a["kind"] for a in att_q[0]["attachments"]}
    _ok("quote_pdf" in kinds and "photo" in kinds, f"attachment kinds {kinds}")
    _ok("/files/pf_pdf" in str(att_q[0]["attachments"][0].get("url") or ""), "attachment URL is per-file")

    from WEOS.factory.master_ledger import _running_advances
    from WEOS.factory.package_quote import apply_package_fields

    mixed = {
        "projectId": "PRJ-SMOKE-MIX",
        "masterJobId": "PRJ-SMOKE-MIX",
        "customer": "Mixed Job",
        "customerMobile": "9000000001",
        "quotationId": "WEOS-CART-1",
        "lines": [{"id": "L1", "sellingAmount": 50000}],
        "packageQuotes": [],
        "lastCalculation": {"price": {"total": 50000, "commercialTotal": 50000}},
    }
    apply_package_fields(
        mixed,
        {"packageQuotes": att_q, "masterJobId": "PRJ-SMOKE-MIX"},
    )
    _ok(len(mixed["lines"]) == 1, "appending an outside quote must not wipe WEOS cart lines")
    _ok(mixed.get("quoteKind") == "mixed", f"mixed quoteKind got {mixed.get('quoteKind')}")
    live_m = live_quote_money(mixed)
    cart_m = cart_quote_money(mixed)
    _ok(cart_m["totalGrand"] == 59000, f"WEOS cart 50k + 18% GST = 59000 got {cart_m['totalGrand']}")
    _ok(live_m["totalGrand"] == 84000, f"cart 59k + outside 25k = 84000 got {live_m['totalGrand']}")
    led_m = ledger_from_docs([mixed])
    kinds_q = {q["kind"] for q in led_m["quotes"]}
    _ok("weos" in kinds_q and "package" in kinds_q, f"ledger shows cart + outside quotes {kinds_q}")
    _ok(led_m["totals"]["projectValue"] == 84000, f"mixed project value 84000 got {led_m['totals']['projectValue']}")
    _ok(led_m["totals"]["closingBalance"] == 84000, "closing = project value when no advances")
    _ok(led_m["totals"]["runningBalance"] == 84000, "running = project value when no advances")
    run = _running_advances(
        [{"id": 1, "amount": 10000, "paidAt": "2026-01-01"}, {"id": 2, "amount": 15000, "paidAt": "2026-02-01"}],
        84000,
    )
    _ok(run[0]["runningAdvance"] == 10000 and run[0]["balanceAfter"] == 74000, "first advance running 10k / balance 74k")
    _ok(run[1]["runningAdvance"] == 25000 and run[1]["balanceAfter"] == 59000, "second advance running 25k / closing 59k")
    att_row = next(q for q in led_m["quotes"] if q["id"] == "pq_att")
    _ok(len(att_row.get("attachments") or []) == 2, "master ledger quote row keeps PDF + photos")

    from WEOS.factory.master_ledger import customer_group_key, same_customer
    from WEOS.factory.ledger_store import _quote_parts, _status_live, is_any_quote_id

    sibling = {
        "projectId": "PRJ-SMOKE-ISO-A2",
        "masterJobId": "PRJ-SMOKE-ISO-A2",
        "customer": "ALPHA",
        "customerMobile": "+91 98765 43210",
        "quotationId": "Q-A2",
        "packageQuotes": [
            {"id": "pq_sib", "gstMode": "off", "items": [{"category": "window", "amount": 25000}]}
        ],
        "name": "Site A2",
    }
    _ok(same_customer(a, sibling), "same mobile digits = same customer even if name spelling differs")
    _ok(not same_customer(a, b), "different mobile is a different customer")
    _ok(customer_group_key(a) == customer_group_key(sibling), "group key follows last 10 mobile digits")
    combined = ledger_from_docs([a, sibling])
    ids_c = {q["id"] for q in combined["quotes"]}
    _ok("pq_a" in ids_c and "pq_sib" in ids_c, f"combined customer ledger has both quotes {ids_c}")
    _ok(combined["totals"]["projectValue"] == 158000, f"grand total 133000+25000=158000 got {combined['totals']['projectValue']}")
    _ok(is_any_quote_id("any") and is_any_quote_id("ALL") and not is_any_quote_id("pq_a"), "Any quote id")
    parts = _quote_parts({"totalTaxable": 123285.80, "totalGst": 22191.44, "totalGrand": 145477.24})
    _ok(parts["totalGrand"] == 145477.24, "quote parts keep GST-inclusive grand")
    _ok(_status_live("approved") and _status_live("draft") and not _status_live("rejected"), "live statuses")

    print("SMOKE_MASTER_LEDGER_OK")


if __name__ == "__main__":
    main()
