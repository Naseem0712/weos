"""Smoke: unit-aware cost basis (PER_KG/RMT/RFT/LENGTH/PC/NOS/SFT/SQM/SET/UNIT)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_cost_basis_"))
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

    from WEOS.db.models import COST_BASIS_TYPES
    from WEOS.factory.engineering_costing import line_material_cost, quantity_for_basis
    from WEOS.factory.selling_price_engine import (
        compute_selling_price,
        markup_from_cost_selling,
        margin_from_cost_selling,
        selling_from_markup,
        selling_from_target_margin,
    )

    required = {
        "PER_KG",
        "PER_RMT",
        "PER_RFT",
        "PER_LENGTH",
        "PER_PC",
        "PER_NOS",
        "PER_SFT",
        "PER_SQM",
        "PER_SET",
        "PER_UNIT",
    }
    _ok(required.issubset(set(COST_BASIS_TYPES)), "all cost basis types defined")

    profile = {
        "category": "PROFILE",
        "quantity": 1,
        "weightKg": 2.5,
        "lengthM": 1.4,
        "requiredLengthMm": 1400,
        "costBasisType": "PER_KG",
        "costBasisValue": 220,
    }
    q, u = quantity_for_basis(profile, "PER_KG")
    _ok(abs(q - 2.5) < 1e-9 and u == "KG", "PER_KG qty")
    c = line_material_cost(profile)
    _ok(abs(c["extendedCost"] - 550.0) < 1e-6, "PER_KG extended")

    profile["costBasisType"] = "PER_RMT"
    profile["costBasisValue"] = 100
    c = line_material_cost(profile)
    _ok(abs(c["extendedCost"] - 140.0) < 1e-6, "PER_RMT extended")

    profile["costBasisType"] = "PER_LENGTH"
    c = line_material_cost(profile)
    _ok(abs(c["extendedCost"] - 140.0) < 1e-6, "PER_LENGTH alias")

    profile["costBasisType"] = "PER_RFT"
    profile["costBasisValue"] = 30
    c = line_material_cost(profile)
    expected_rft = (1400 / 304.8) * 30
    _ok(abs(c["extendedCost"] - expected_rft) < 1e-4, "PER_RFT extended")

    hw = {"category": "HARDWARE", "quantity": 4, "costBasisType": "PER_PC", "costBasisValue": 55}
    c = line_material_cost(hw)
    _ok(abs(c["extendedCost"] - 220.0) < 1e-6, "PER_PC")

    nos = {"category": "FASTENER", "quantity": 10, "costBasisType": "PER_NOS", "costBasisValue": 0.5}
    c = line_material_cost(nos)
    _ok(abs(c["extendedCost"] - 5.0) < 1e-6, "PER_NOS")

    glass = {
        "category": "GLASS",
        "quantity": 1,
        "widthMm": 1000,
        "heightMm": 1000,
        "areaSqm": 1.0,
        "deductionMode": "NOMINAL",
        "costBasisType": "PER_SQM",
        "costBasisValue": 450,
    }
    c = line_material_cost(glass)
    _ok(abs(c["extendedCost"] - 450.0) < 1e-6, "PER_SQM glass")
    _ok(c["precisionMode"] == "ESTIMATED", "NOMINAL glass → ESTIMATED not EXACT")

    glass["costBasisType"] = "PER_SFT"
    glass["costBasisValue"] = 40
    c = line_material_cost(glass)
    _ok(abs(c["extendedCost"] - 40 * 10.7639) < 0.01, "PER_SFT")

    sett = {"category": "HARDWARE", "quantity": 2, "costBasisType": "PER_SET", "costBasisValue": 120}
    c = line_material_cost(sett)
    _ok(abs(c["extendedCost"] - 240.0) < 1e-6, "PER_SET")

    stock = {
        "category": "PROFILE",
        "quantity": 1,
        "requiredLengthMm": 1400,
        "stockConsumptionMm": 5800,
        "lengthM": 1.4,
        "costBasisType": "PER_RMT",
        "costBasisValue": 100,
        "meta": {},
    }
    c = line_material_cost(stock)
    _ok(c["precisionMode"] == "ESTIMATED_STOCK", "no optimizer → ESTIMATED_STOCK")
    _ok(abs(c["extendedCost"] - 580.0) < 1e-6, "stock consumption drives ESTIMATED_STOCK qty")

    # Markup ≠ margin
    cost = 1000.0
    s_mk = selling_from_markup(cost, 25)
    s_mg = selling_from_target_margin(cost, 25)
    _ok(abs(s_mk - 1250) < 1e-9, "25% markup → 1250")
    _ok(abs(s_mg - (1000 / 0.75)) < 1e-6, "25% margin → 1333.33")
    _ok(abs(s_mk - s_mg) > 1.0, "markup ≠ margin numerically")
    sp = compute_selling_price(total_cost=cost, method="COST_PLUS_MARKUP", markup_pct=25)
    _ok(abs(sp["suggestedSelling"] - 1250) < 1e-6, "selling markup method")
    sp2 = compute_selling_price(total_cost=cost, method="COST_PLUS_TARGET_MARGIN", target_margin_pct=25)
    _ok(abs(sp2["suggestedSelling"] - round(s_mg, 4)) < 1e-6, "selling margin method")
    _ok(abs(margin_from_cost_selling(1000, 1250) - 20.0) < 1e-6, "margin of 25% markup sell is 20%")
    _ok(abs(markup_from_cost_selling(1000, s_mg) - (100 / 3)) < 0.01, "markup of 25% margin sell")

    print("PASS _smoke_cost_basis")


if __name__ == "__main__":
    main()
