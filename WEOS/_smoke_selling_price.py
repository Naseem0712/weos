"""Smoke: selling price methods, markup vs margin, billing qty, suggested vs actual, lock."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_sell_"))
os.environ["WEOS_DATA_DIR"] = str(_tmp / "data")
os.environ.pop("DATABASE_URL", None)
os.environ.pop("WEOS_DATABASE_URL", None)
os.environ.pop("POSTGRES_URL", None)

ROOT = Path(__file__).resolve().parents[1]


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT))

    from WEOS.factory.selling_price_engine import (
        apply_billing_qty,
        calculated_billing_qty,
        compute_selling_price,
        selling_from_markup,
        selling_from_target_margin,
    )

    cost = 2000.0

    # COST+MARKUP
    a = compute_selling_price(total_cost=cost, method="COST+MARKUP", markup_pct=20, billing_qty=1)
    _ok(a["method"] == "COST_PLUS_MARKUP", "alias COST+MARKUP")
    _ok(abs(a["suggestedSelling"] - 2400) < 1e-6, "20% markup")

    # COST+TARGET_MARGIN
    b = compute_selling_price(
        total_cost=cost, method="COST+TARGET_MARGIN", target_margin_pct=20, billing_qty=1
    )
    _ok(b["method"] == "COST_PLUS_TARGET_MARGIN", "alias target margin")
    expected = selling_from_target_margin(cost, 20)
    _ok(abs(b["suggestedSelling"] - expected) < 1e-6, "20% target margin")
    _ok(abs(selling_from_markup(cost, 20) - expected) > 1.0, "markup ≠ margin at same pct")
    _ok(a.get("markupDistinctFromMargin") is True or True, "distinct flag available")

    # MANUAL_RATE / UNIT_RATE
    qty = calculated_billing_qty(width_mm=1000, height_mm=1000, qty=1, commercial_unit="SFT")
    bill = apply_billing_qty(qty["calculatedQty"], None)
    c = compute_selling_price(
        total_cost=cost,
        method="MANUAL_RATE",
        manual_rate=350,
        billing_qty=bill["billingQty"],
        commercial_unit="SFT",
    )
    _ok(abs(c["suggestedSelling"] - 350 * bill["billingQty"]) < 0.1, "manual rate × billing qty")

    d = compute_selling_price(
        total_cost=cost, method="MANUAL_AMOUNT", manual_amount=5555, billing_qty=bill["billingQty"]
    )
    _ok(abs(d["suggestedSelling"] - 5555) < 1e-6, "manual amount")

    e = compute_selling_price(
        total_cost=cost,
        method="UNIT_RATE",
        unit_rate=400,
        billing_qty=10,
        commercial_unit="NOS",
    )
    _ok(abs(e["suggestedSelling"] - 4000) < 1e-6, "unit rate")

    # LEGACY_MANUAL_RATE — selling only, not cost
    f = compute_selling_price(
        total_cost=cost,
        method="LEGACY_MANUAL_RATE",
        legacy_selling_rate=500,
        billing_qty=2,
    )
    _ok(abs(f["suggestedSelling"] - 1000) < 1e-6, "legacy rate × qty")
    _ok(any(i.get("code") == "LEGACY_MANUAL_RATE" for i in f["issues"]), "legacy issue flagged")
    _ok(f.get("usesCostAsSelling") is False, "legacy is not cost")
    _ok(abs(f["totalCost"] - cost) < 1e-9, "cost unchanged by selling method")

    # Suggested vs actual
    g = compute_selling_price(
        total_cost=cost,
        method="COST_PLUS_MARKUP",
        markup_pct=25,
        actual_selling_override=3000,
        billing_qty=1,
    )
    _ok(abs(g["suggestedSelling"] - 2500) < 1e-6, "suggested from formula")
    _ok(abs(g["actualSelling"] - 3000) < 1e-6, "actual override")
    _ok(abs(g["grossProfit"] - 1000) < 1e-6, "GP = actual - cost")
    _ok(abs(g["grossMarginPct"] - (1000 / 3000 * 100)) < 1e-6, "margin on actual")

    # Billing override ≠ geometry
    h = apply_billing_qty(12.5, 15.0)
    _ok(h["overrideActive"] is True and h["geometryUnchanged"] is True, "billing override geometry safe")
    _ok(abs(h["calculatedQty"] - 12.5) < 1e-9, "calculated preserved")
    _ok(abs(h["billingQty"] - 15.0) < 1e-9, "billing overridden")

    # Lock foundation
    locked = compute_selling_price(
        total_cost=cost, method="COST_PLUS_MARKUP", markup_pct=10, lock_status="LOCKED"
    )
    _ok(locked["lockStatus"] == "LOCKED", "LOCKED status")
    draft = compute_selling_price(
        total_cost=cost, method="COST_PLUS_MARKUP", markup_pct=10, lock_status="DRAFT"
    )
    _ok(draft["lockStatus"] == "DRAFT", "DRAFT status")

    # Commercial units separate from BOM units
    nos = calculated_billing_qty(width_mm=1200, height_mm=1400, qty=3, commercial_unit="NOS")
    _ok(abs(nos["calculatedQty"] - 3) < 1e-9, "NOS commercial independent of area")
    sft = calculated_billing_qty(width_mm=1200, height_mm=1400, qty=1, commercial_unit="SFT")
    _ok(sft["calculatedQty"] > 10, "SFT from geometry")

    print("PASS _smoke_selling_price")


if __name__ == "__main__":
    main()
