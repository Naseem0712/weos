"""End-to-end smoke: observe → suggest → approve → KB version → Brain load → rollback.

Run: python -m WEOS.memory.smoke_test
Does not modify WEOS/products production packs.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# Ensure workspace root on path when run as script
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
    print("WEOS Memory Architecture smoke test")
    print("=" * 50)

    from WEOS.learning.v2_store import current_kb_version, list_library, list_kb_versions
    from WEOS.memory.admin import approve_memory, rollback_kb
    from WEOS.memory.schemas import MEM_GLASS, MEM_LEARNING, empty_memory
    from WEOS.memory.search import rebuild_index, search
    from WEOS.memory.store import get_store, write_observation_as_learning
    from WEOS.brain import generate, load_context

    store = get_store()
    v_before = current_kb_version()
    print(f"KB version before: v{v_before}")

    # 1) Write observation (Learning Memory suggestion)
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

    # 2) Suggest payload as glass draft (admin would edit)
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
        }
    )
    glass = store.save(MEM_GLASS, glass, as_approved=False)
    _ok("suggest glass draft", glass.get("status") in ("draft", "pending_approval"), glass["id"])

    # 3) Approve -> new KB version
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
        f"v{v_before} -> v{v_after_approve} meta={ver_meta.get('version')}",
    )

    # Also approve the learning observation (records resultingKbVersion)
    learn_id = obs["id"]
    learn_appr = approve_memory(
        MEM_LEARNING,
        learn_id,
        approved_by="smoke_test",
        publish_version=True,
        publish_to_library=False,
        reason="Smoke: approve learning observation",
    )
    _ok("approve learning memory", learn_appr.get("ok") is True)
    v_mid = current_kb_version()
    _ok("learning approve bumped version", v_mid > v_after_approve, f"v{v_after_approve} -> v{v_mid}")

    # 4) Search index
    rebuild_index()
    hits = search("sliding systems with 29mm track", limit=10)
    _ok("search returns results", hits.get("count", 0) >= 1, f"count={hits.get('count')}")
    glass_hits = search("5mm glass", memory_type=MEM_GLASS, limit=10)
    _ok("glass search", glass_hits.get("count", 0) >= 1)

    # 5) Brain load S29-like series
    ctx = load_context(series="29mm_sliding_smoke", product_type="Sliding Door", use_cache=False)
    _ok("brain load ok", ctx.get("ok") is True, ctx.get("error") or ctx.get("seriesId"))
    _ok("brain has profiles", (ctx.get("counts") or {}).get("profiles", 0) >= 1, str(ctx.get("counts")))

    # Also resolve S29-style alias
    ctx_s29 = load_context(series="S29", product_type="Sliding Door", use_cache=True)
    print(f"  [INFO] S29 alias resolve ok={ctx_s29.get('ok')} seriesId={ctx_s29.get('seriesId')}")

    gen = generate(
        series="29mm_sliding_smoke",
        product_type="Sliding Door",
        width_mm=1200,
        height_mm=1500,
        quantity=1,
    )
    _ok("brain generate ok", gen.get("ok") is True)
    bom = (gen.get("generated") or {}).get("bom") or {}
    _ok("brain BOM lines", bom.get("lineCount", 0) >= 1, str(bom.get("lineCount")))
    _ok("brain weight present", "weight" in (gen.get("generated") or {}))

    # 6) Rollback to version before smoke approvals
    versions = list_kb_versions()
    if v_before >= 1:
        rb = rollback_kb(v_before, rolled_back_by="smoke_test", reason="Smoke rollback")
        _ok("rollback ok", rb.get("rolled_back_to") == v_before, f"to={rb.get('rolled_back_to')} new=v{rb.get('version')}")
        _ok("rollback creates new version", int(rb.get("version") or 0) > v_mid)
        lib_glass_ids = {g.get("id") for g in list_library("glass")}
        print(f"  [INFO] glass library ids after rollback: {sorted(lib_glass_ids)}")
        _ok("rollback production flag", rb.get("production_modified") is False)
    else:
        print("  [SKIP] rollback -- no prior KB version to restore")

    # Cache invalidation implied by rollback; reload should still work
    ctx2 = load_context(series="29mm_sliding_smoke", use_cache=False)
    _ok("brain load after rollback", ctx2.get("ok") is True)

    print("=" * 50)
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
