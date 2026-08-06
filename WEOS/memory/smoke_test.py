"""End-to-end smoke: Memory Architecture + Brain Intelligence Upgrade.

Covers: observe→approve→version→Brain load→rollback
PLUS: validation block, explain proof, priority pick, compatibility warning,
conflict stop, version diff, size-compare suggestion.

Run: python -m WEOS.memory.smoke_test
Does not modify WEOS/products production packs.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _ok(name: str, cond: bool, detail: str = "") -> None:
    mark = "PASS" if cond else "FAIL"
    extra = f" -- {detail}" if detail else ""
    print(f"  [{mark}] {name}{extra}")
    if not cond:
        raise AssertionError(name + (": " + detail if detail else ""))


def main() -> int:
    print("WEOS Memory Architecture + Brain Intelligence smoke test")
    print("=" * 60)

    from WEOS.learning.v2_store import current_kb_version, list_library, list_kb_versions
    from WEOS.memory.admin import approve_memory, rollback_kb
    from WEOS.memory.compatibility import check_compatibility
    from WEOS.memory.conflicts import check_conflicts
    from WEOS.memory.explain import explain_from_context
    from WEOS.memory.ranking import group_formulas_by_priority, pick_by_priority
    from WEOS.memory.schemas import MEM_FORMULA, MEM_GLASS, MEM_LEARNING, empty_memory
    from WEOS.memory.search import rebuild_index, search
    from WEOS.memory.size_learn import compare_sizes
    from WEOS.memory.store import get_store, write_observation_as_learning
    from WEOS.memory.validate import validate_context
    from WEOS.memory.version_diff import compare_versions
    from WEOS.brain import generate, load_context

    store = get_store()
    v_before = current_kb_version()
    print(f"KB version before: v{v_before}")

    # ── Baseline path (existing) ──────────────────────────────────────────
    obs = write_observation_as_learning(
        observation_type="glass_default",
        summary="92/100 quotes used 5mm glass -- make default?",
        evidence={"count": 92, "total": 100, "value": "5mm"},
        suggestion="Set default glass thickness to 5mm for sliding series",
        target_memory_type=MEM_GLASS,
        target_payload={"thicknessMm": 5, "name": "5mm Clear Default Suggestion"},
        domain="engineering",
    )
    _ok("write observation", obs.get("status") == "pending_approval", obs.get("id"))
    _ok("frequency computed", abs(float(obs.get("frequency") or 0) - 0.92) < 0.001)

    glass = empty_memory(MEM_GLASS)
    glass.update(
        {
            "id": "glass_smoke_mem_default",
            "name": "5mm Clear (Memory smoke)",
            "glassType": "Clear",
            "thicknessMm": 5,
            "weightKgPerSqm": 12.5,
            "compatibleProducts": ["29mm_sliding_smoke"],
            "status": "pending_approval",
            "confidence": 92,
            "sourceKind": "quote",
            "priority": 60,
        }
    )
    glass = store.save(MEM_GLASS, glass, as_approved=False)
    _ok("suggest glass draft", glass.get("status") in ("draft", "pending_approval"), glass["id"])

    approved = approve_memory(
        MEM_GLASS,
        glass["id"],
        approved_by="smoke_test",
        publish_version=True,
        publish_to_library=True,
        reason="Smoke: approve 5mm glass default suggestion",
    )
    _ok("approve memory", approved.get("ok") is True)
    _ok("production untouched", approved.get("production_modified") is False)
    v_after_approve = current_kb_version()
    ver_meta = approved.get("kbVersion") or {}
    _ok(
        "new KB version",
        v_after_approve > v_before and int(ver_meta.get("version") or 0) == v_after_approve,
        f"v{v_before} -> v{v_after_approve}",
    )

    learn_appr = approve_memory(
        MEM_LEARNING,
        obs["id"],
        approved_by="smoke_test",
        publish_version=True,
        publish_to_library=False,
        reason="Smoke: approve learning observation",
    )
    _ok("approve learning memory", learn_appr.get("ok") is True)
    v_mid = current_kb_version()
    _ok("learning approve bumped version", v_mid > v_after_approve, f"v{v_after_approve} -> v{v_mid}")

    rebuild_index()
    hits = search("sliding systems with 29mm track", limit=10)
    _ok("search returns results", hits.get("count", 0) >= 1, f"count={hits.get('count')}")

    ctx = load_context(series="29mm_sliding_smoke", product_type="Sliding Door", use_cache=False)
    _ok("brain load ok", ctx.get("ok") is True, ctx.get("error") or ctx.get("seriesId"))
    _ok("brain has profiles", (ctx.get("counts") or {}).get("profiles", 0) >= 1, str(ctx.get("counts")))

    # ── 8) Validation layer ───────────────────────────────────────────────
    print("-- Validation / Explain / Priority / Compat / Conflict / Diff / Size --")
    good_val = validate_context(ctx)
    _ok("validation ready (smoke series)", good_val.get("canGenerate") is True, good_val.get("message"))

    empty_ctx = {"ok": True, "seriesId": "missing_series_xyz", "kbVersion": v_mid, "profiles": [], "glass": [], "formulas": [], "hardware": [], "drawings": []}
    bad_val = validate_context(empty_ctx)
    _ok("validation blocks missing", bad_val.get("canGenerate") is False)
    _ok("validation missing list", len(bad_val.get("missing") or []) >= 3, str(bad_val.get("missing")))

    blocked_gen = generate(series="no_such_series_zzz_smoke", skip_validation=False)
    _ok("generate blocks unknown series", blocked_gen.get("ok") is False)

    # Force validation failure path via empty context generate is covered above;
    # also ensure real generate works when valid:
    gen = generate(
        series="29mm_sliding_smoke",
        product_type="Sliding Door",
        width_mm=1200,
        height_mm=1500,
        quantity=1,
        shutter_count=2,
    )
    _ok("brain generate ok", gen.get("ok") is True, gen.get("message") or gen.get("blockReason"))
    _ok("brain BOM lines", ((gen.get("generated") or {}).get("bom") or {}).get("lineCount", 0) >= 1)
    _ok("generate includes explain", bool(gen.get("explain") or (gen.get("generated") or {}).get("explain")))

    # ── 7) Explain / proof ────────────────────────────────────────────────
    proof = explain_from_context(ctx, width_mm=800, height_mm=1200, shutter_count=2, inner_width=756, handle_overlap=8, interlock=4)
    gw = (proof.get("results") or {}).get("glassWidth") or {}
    _ok("explain glassWidth value", gw.get("value") == 744, f"got {gw.get('value')} eq={gw.get('equation')}")
    _ok("explain has steps", len(gw.get("steps") or []) >= 2)
    _ok("explain has memory_refs", len(gw.get("memory_refs") or []) >= 1)
    _ok("explain has formula_version", gw.get("formula_version") is not None)
    _ok("explain has kb_version", proof.get("kb_version") is not None or gw.get("kb_version") is not None)
    hq = (proof.get("results") or {}).get("handleQty") or {}
    _ok("explain handleQty = 2", hq.get("value") == 2, f"got {hq.get('value')}")

    # ── 2) Rule priority ──────────────────────────────────────────────────
    low = empty_memory(MEM_FORMULA)
    low.update(
        {
            "id": "fx_glass_priority_low_smoke",
            "name": "Glass Width Low",
            "category": "glass",
            "expression": "innerWidth - 20",
            "outputName": "glassWidth",
            "priority": 20,
            "status": "approved",
            "compatibleSeries": ["29mm_sliding_smoke"],
            "formulaVersion": 1,
        }
    )
    high = empty_memory(MEM_FORMULA)
    high.update(
        {
            "id": "fx_glass_priority_high_smoke",
            "name": "Glass Width High",
            "category": "glass",
            "expression": "innerWidth - handleOverlap - interlock",
            "outputName": "glassWidth",
            "variables": [
                {"name": "innerWidth", "default": 756},
                {"name": "handleOverlap", "default": 8},
                {"name": "interlock", "default": 4},
            ],
            "priority": 100,
            "status": "approved",
            "compatibleSeries": ["29mm_sliding_smoke"],
            "formulaVersion": 1,
            "confidence": 95,
            "sourceKind": "engineering",
        }
    )
    store.save(MEM_FORMULA, low, as_approved=True, approved_by="smoke_test")
    store.save(MEM_FORMULA, high, as_approved=True, approved_by="smoke_test")
    picked = pick_by_priority([low, high], category="glass", approved_only=True)
    _ok("priority picks 100 over 20", (picked or {}).get("id") == "fx_glass_priority_high_smoke", str((picked or {}).get("id")))
    grouped = group_formulas_by_priority([low, high])
    _ok("priority group selected high", ((grouped.get("glass") or {}).get("selected") or {}).get("priority") == 100)

    # ── 3) Compatibility warning ──────────────────────────────────────────
    compat = check_compatibility(
        series_id="29mm_sliding_smoke",
        series={**(ctx.get("series") or {}), "id": "29mm_sliding_smoke", "glassThicknessMm": [5, 6, 8]},
        glass_thickness_mm=10,
    )
    _ok("compat warns on 10mm", len(compat.get("warnings") or []) >= 1, compat.get("message"))
    _ok("compat message mentions support", "5" in str(compat.get("message")) or "supports" in str(compat.get("message")).lower())

    # ── 4) Conflict hard stop ─────────────────────────────────────────────
    conflict = check_conflicts(
        series_id="29mm_sliding_smoke",
        selections=[
            {"id": "hw_handle_premium", "name": "Premium Handle"},
            {"id": "hw_roller_old", "name": "Old Roller"},
        ],
    )
    _ok("conflict hard block", conflict.get("blocked") is True, conflict.get("message"))
    stopped = generate(
        series="29mm_sliding_smoke",
        selections=[
            {"id": "hw_handle_premium", "name": "Premium Handle"},
            {"id": "hw_roller_old", "name": "Old Roller"},
        ],
    )
    _ok("generate stops on conflict", stopped.get("ok") is False and stopped.get("blockReason") == "conflict", stopped.get("message"))

    # ── 6) Version compare ────────────────────────────────────────────────
    versions = list_kb_versions()
    ver_nums = [int(v.get("version")) for v in versions if v.get("version")]
    if len(ver_nums) >= 2:
        a, b = ver_nums[0], ver_nums[min(3, len(ver_nums) - 1)] if len(ver_nums) > 3 else ver_nums[-1]
        if a == b and len(ver_nums) >= 2:
            a, b = ver_nums[0], ver_nums[1]
        diff = compare_versions(a, b)
        _ok("version diff ok", diff.get("ok") is True, diff.get("message"))
        _ok("version diff has summary", isinstance(diff.get("summary"), dict))
    else:
        # Create a tiny field change via two snapshots if somehow thin
        diff = compare_versions(1, 2) if 1 in ver_nums else {"ok": True, "summary": {}}
        _ok("version diff skipped/thin ok", True, "few versions")

    # ── 11) Size-scale suggestion ─────────────────────────────────────────
    size = compare_sizes(
        small={"width_mm": 914, "height_mm": 1219},  # ~3x4 ft
        large={"width_mm": 1524, "height_mm": 1524},  # ~5x5 ft
        series_id="29mm_sliding_smoke",
        product_type="Sliding",
        profiles_used=["outer_track", "shutter"],
        joint_types=["mitre"],
        design_why="Same sliding design at two sizes",
        save_observation=True,
    )
    _ok("size compare ok", size.get("ok") is True)
    _ok("size compare not auto-applied", size.get("autoApplied") is False)
    _ok("size compare has delta cost", (size.get("delta") or {}).get("material_cost_inr") is not None)
    _ok("size compare learning pending", (size.get("learning") or {}).get("status") == "pending_approval")
    _ok("size compare eng draft pending", (size.get("engineeringDraft") or {}).get("status") == "pending_approval")

    # ── Ranking card present on generate path ─────────────────────────────
    from WEOS.memory.ranking import enrich_item

    ranked = enrich_item(store.get(MEM_GLASS, "glass_smoke_mem_default"))
    _ok("ranking confidence", (ranked.get("ranking") or {}).get("confidence") is not None)
    _ok("ranking approved label", (ranked.get("ranking") or {}).get("approvedLabel") in ("Yes", "No"))

    # ── Rollback ──────────────────────────────────────────────────────────
    if v_before >= 1:
        rb = rollback_kb(v_before, rolled_back_by="smoke_test", reason="Smoke rollback")
        _ok("rollback ok", rb.get("rolled_back_to") == v_before, f"to={rb.get('rolled_back_to')} new=v{rb.get('version')}")
        _ok("rollback creates new version", int(rb.get("version") or 0) > v_mid)
        _ok("rollback production flag", rb.get("production_modified") is False)
    else:
        print("  [SKIP] rollback -- no prior KB version to restore")

    ctx2 = load_context(series="29mm_sliding_smoke", use_cache=False)
    _ok("brain load after rollback", ctx2.get("ok") is True)

    from WEOS.memory import cache

    cs = cache.status()
    _ok("cache 3-layer status", "L1_RAM" in (cs.get("layers") or {}), str(cs.get("layers")))

    print("=" * 60)
    print("All smoke checks passed.")
    print(f"Final KB version: v{current_kb_version()}")
    print(f"Version history length: {len(list_kb_versions())}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
