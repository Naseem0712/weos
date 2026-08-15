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

    print("SMOKE_MASTER_LEDGER_OK")


if __name__ == "__main__":
    main()
