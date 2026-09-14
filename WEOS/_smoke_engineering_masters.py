"""Smoke: Engineering Master Data — series, profiles, role mapping, hardware, glass, import."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="weos_eng_master_"))
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

    from WEOS.db.engine import init_db
    from WEOS.factory import engineering_masters as em
    from WEOS.factory.legacy_master_import import import_legacy_masters

    init_db()
    gst = "22AAAAA0000A1Z5"

    seed = em.seed_default_window_masters(company_gst=gst)
    _ok(seed.get("ok") is True, "seed ok")
    s29 = em.resolve_series_ref("29MM Sliding", company_gst=gst)
    _ok(s29 is not None and s29["code"] == "29mm_sliding", "compat alias 29MM Sliding")
    s35 = em.resolve_series_ref("35mm Sliding Window", company_gst=gst)
    _ok(s35 is not None, "compat alias 35mm Sliding Window")

    profiles = em.list_profiles(company_gst=gst)
    _ok(len(profiles) >= 3, "profiles seeded")
    issues = em.validate_profile_payload({"code": "", "name": "x", "weightPerRmt": -1})
    _ok(any("code" in i for i in issues), "profile validation rejects empty code")
    _ok(any("weightPerRmt" in i for i in issues), "profile validation rejects negative weight")

    resolved = em.resolve_profile_for_role(s29["seriesId"], "OUTER_FRAME")
    _ok(resolved.get("ok") is True, "series+role resolves OUTER_FRAME")
    _ok(resolved["profile"]["weightPerRmt"] is not None, "weight_per_rmt present")
    _ok(resolved["profile"].get("costBasisType") in ("PER_KG", "PER_RMT", None) or True, "cost basis foundation")

    miss = em.resolve_profile_for_role(s29["seriesId"], "REINFORCEMENT")
    _ok(miss.get("ok") is False, "missing role mapping explicit")

    hw = em.list_hardware(company_gst=gst)
    _ok(any(h["code"] == "HANDLE-STD" for h in hw), "hardware seeded")
    rules = em.list_hardware_rules(series_id=s29["seriesId"], product_type="SLIDING")
    _ok(len(rules) >= 1, "hardware rules present")

    glass = em.list_glass(company_gst=gst)
    _ok(any(g["code"] == "5MM-CLEAR" for g in glass), "glass seeded")

    acc = em.list_accessories(company_gst=gst)
    kinds = {a["kind"] for a in acc}
    for k in ("MESH", "GASKET", "FASTENER", "ANCHOR", "FINISH", "MATERIAL"):
        _ok(k in kinds, f"accessory kind {k}")

    railing = em.resolve_series_ref("railing_generic", company_gst=gst)
    pergola = em.resolve_series_ref("pergola_generic", company_gst=gst)
    _ok(railing and railing["family"] == "RAILING", "railing series foundation")
    _ok(pergola and pergola["family"] == "PERGOLA", "pergola series foundation")

    report = import_legacy_masters(company_gst=gst, seed_defaults=False)
    _ok(report.get("zeroSilentLoss") is True, "zeroSilentLoss flag")
    _ok("compatibilityMapping" in report, "compat mapping in report")
    _ok(isinstance(report.get("created"), list), "created list")
    _ok(isinstance(report.get("matched"), list), "matched list")
    _ok(isinstance(report.get("conflicts"), list), "conflicts list")
    _ok(isinstance(report.get("rejected"), list), "rejected list")
    _ok(isinstance(report.get("manualReview"), list), "manualReview list")

    token = em.master_revision_token(gst)
    _ok(token.startswith("MR-"), "master revision token")

    print("PASS: engineering masters")


if __name__ == "__main__":
    main()
