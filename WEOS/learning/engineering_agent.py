"""Engineering learning agent — profiles, hardware situations, weight/waste formulas.

Observes calculate/cart results. Never auto-writes production profiles or engines.
Suggestions one-click → pending review (KIND_FORMULA / catalogue hints).
"""

from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from WEOS.paths import knowledge_base_dir
from WEOS.learning.knowledge_base import ensure_kb_dirs
from WEOS.learning.material_formulas import (
    BASELINE_FORMULAS,
    compute_weight,
    list_baseline_formulas,
    propose_refinement_payload,
)


def engineering_dir() -> Path:
    ensure_kb_dirs()
    d = knowledge_base_dir() / "engineering"
    d.mkdir(parents=True, exist_ok=True)
    (d / "observations").mkdir(parents=True, exist_ok=True)
    return d


def observations_path() -> Path:
    return engineering_dir() / "observations.jsonl"


def insights_cache_path() -> Path:
    return engineering_dir() / "insights_cache.json"


def suggestions_cache_path() -> Path:
    return engineering_dir() / "suggestions_cache.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _size_bucket(width: float | None, height: float | None) -> str:
    try:
        w = float(width or 0)
        h = float(height or 0)
    except (TypeError, ValueError):
        return "unknown"
    area = (w * h) / 1e6  # m²
    if area < 1.0:
        return "small_<1m2"
    if area < 2.5:
        return "medium_1-2.5m2"
    if area < 4.5:
        return "large_2.5-4.5m2"
    return "xlarge_>4.5m2"


def _panel_count(line: Mapping[str, Any]) -> int | None:
    layout = line.get("layout") or line.get("layoutMeta") or {}
    for key in ("shutterCount", "panelCount", "panels", "shutters"):
        if layout.get(key) is not None:
            try:
                return int(layout[key])
            except (TypeError, ValueError):
                pass
    meta = line.get("layoutMeta") or {}
    for key in ("shutter_count", "panel_count", "shutters"):
        if meta.get(key) is not None:
            try:
                return int(meta[key])
            except (TypeError, ValueError):
                pass
    return None


def _product_family(product: str | None) -> str:
    p = (product or "unknown").lower()
    if "slid" in p:
        return "sliding"
    if "case" in p:
        return "casement"
    if "fix" in p:
        return "fixed"
    if "pergola" in p:
        return "pergola"
    if "wardrobe" in p or "ward" in p:
        return "wardrobe"
    if "shower" in p:
        return "shower"
    if "mosquito" in p or "mesh" in p:
        return "mosquito_mesh"
    return p.split("_")[0] if p else "unknown"


def observe_engineering(
    *,
    lines: Sequence[Mapping[str, Any]],
    project_id: str | None = None,
    quotation_id: str | None = None,
    customer: str | None = None,
    source: str = "calculate",
    optimization: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Record engineering observations from calculated line results."""
    engineering_dir()
    now = _now()
    batch_id = uuid.uuid4().hex[:10]
    rows: list[dict[str, Any]] = []

    for ln in lines or []:
        product = ln.get("product") or ln.get("productId")
        opts = ln.get("options") if isinstance(ln.get("options"), dict) else {}
        glass = opts.get("glass") if opts else ln.get("glass")
        colour = opts.get("colour") if opts else ln.get("colour")
        handle = opts.get("handle") if opts else ln.get("handle")
        weight = ln.get("weight") if isinstance(ln.get("weight"), dict) else {}
        materials = ln.get("materials") or []
        hardware = ln.get("hardware") or []
        cut_list = ln.get("cutList") or []
        bom = ln.get("bom") or []
        glass_rows = ln.get("glass") if isinstance(ln.get("glass"), list) else []

        # Wall / profile thickness hints from materials or cut profiles
        thicknesses: list[float] = []
        profile_names: list[str] = []
        for m in materials:
            if not isinstance(m, dict):
                continue
            name = m.get("name") or m.get("description") or m.get("profile")
            if name:
                profile_names.append(str(name)[:80])
            for tk in ("wallThicknessMm", "thicknessMm", "thickness"):
                if m.get(tk) is not None:
                    try:
                        thicknesses.append(float(m[tk]))
                    except (TypeError, ValueError):
                        pass
        for c in cut_list:
            if isinstance(c, dict) and c.get("profile"):
                profile_names.append(str(c["profile"])[:80])

        hw_names = []
        for h in hardware:
            if isinstance(h, dict):
                hw_names.append(str(h.get("name") or h.get("description") or "?")[:80])
            else:
                hw_names.append(str(h)[:80])

        glass_thicknesses = []
        for g in glass_rows:
            if isinstance(g, dict) and g.get("thicknessMm") is not None:
                try:
                    glass_thicknesses.append(float(g["thicknessMm"]))
                except (TypeError, ValueError):
                    pass

        waste_pct = None
        if optimization and isinstance(optimization, dict):
            alu = (optimization.get("aluminium") or optimization.get("bar") or {})
            if isinstance(alu, dict) and alu.get("wastePercent") is not None:
                try:
                    waste_pct = float(alu["wastePercent"])
                except (TypeError, ValueError):
                    pass

        row = {
            "id": f"eng_{uuid.uuid4().hex[:12]}",
            "batchId": batch_id,
            "ts": now,
            "kind": "line_engineering",
            "source": source,
            "customer": (customer or "").strip() or None,
            "projectId": project_id,
            "quotationId": quotation_id,
            "product": product,
            "productFamily": _product_family(str(product) if product else None),
            "displayName": ln.get("displayName"),
            "width": ln.get("width"),
            "height": ln.get("height"),
            "qty": ln.get("qty"),
            "sizeBucket": _size_bucket(ln.get("width"), ln.get("height")),
            "panelCount": _panel_count(ln),
            "glass": glass,
            "colour": colour,
            "handle": handle,
            "glassThicknessesMm": glass_thicknesses,
            "wallThicknessesMm": thicknesses,
            "profiles": profile_names[:24],
            "hardwareNames": hw_names[:24],
            "hardwareCount": len(hw_names),
            "cutListCount": len(cut_list),
            "bomCount": len(bom),
            "weight": {
                "aluminiumKg": weight.get("aluminiumKg"),
                "glassKg": weight.get("glassKg"),
                "hardwareKg": weight.get("hardwareKg"),
                "totalKg": weight.get("totalKg"),
            },
            "wastePercentObserved": waste_pct,
            "sectionSeries": ln.get("sectionSeries"),
        }
        rows.append(row)

    if optimization:
        alu_opt = optimization.get("aluminium") if isinstance(optimization.get("aluminium"), dict) else {}
        glass_opt = optimization.get("glass") if isinstance(optimization.get("glass"), dict) else {}
        rows.append(
            {
                "id": f"eng_{uuid.uuid4().hex[:12]}",
                "batchId": batch_id,
                "ts": now,
                "kind": "optimization",
                "source": source,
                "projectId": project_id,
                "quotationId": quotation_id,
                "optimization": {
                    "aluminiumWastePercent": alu_opt.get("wastePercent", optimization.get("wastePercent")),
                    "glassWastePercent": glass_opt.get("wastePercent"),
                },
            }
        )

    path = observations_path()
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    for cache in (insights_cache_path(), suggestions_cache_path()):
        if cache.is_file():
            cache.unlink()

    return {"ok": True, "batchId": batch_id, "observed": len(rows), "domain": "engineering"}


def _read_observations(limit: int = 800) -> list[dict[str, Any]]:
    path = observations_path()
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:]


def live_stream(limit: int = 40) -> dict[str, Any]:
    """What is being learned now — recent engineering observation stream."""
    rows = _read_observations(limit=limit)
    stream = []
    for r in reversed(rows):
        if r.get("kind") == "optimization":
            stream.append(
                {
                    "ts": r.get("ts"),
                    "kind": "optimization",
                    "summary": (
                        f"Cut waste Al {r.get('optimization', {}).get('aluminiumWastePercent')}% · "
                        f"Glass {r.get('optimization', {}).get('glassWastePercent')}%"
                    ),
                }
            )
            continue
        bits = [
            str(r.get("product") or "?"),
            f"{r.get('width')}×{r.get('height')}" if r.get("width") else None,
            r.get("sizeBucket"),
            f"panels={r.get('panelCount')}" if r.get("panelCount") else None,
            f"glass={r.get('glass')}" if r.get("glass") else None,
            f"handle={r.get('handle')}" if r.get("handle") else None,
            f"hw×{r.get('hardwareCount')}" if r.get("hardwareCount") else None,
        ]
        if (r.get("weight") or {}).get("totalKg") is not None:
            bits.append(f"wt={r['weight']['totalKg']}kg")
        stream.append(
            {
                "ts": r.get("ts"),
                "kind": "line",
                "product": r.get("product"),
                "summary": " · ".join(b for b in bits if b),
                "profiles": (r.get("profiles") or [])[:4],
                "hardware": (r.get("hardwareNames") or [])[:4],
            }
        )
    return {
        "ok": True,
        "count": len(stream),
        "stream": stream[:limit],
        "status": "learning" if stream else "waiting",
        "message": "Live engineering observations from Calculate / cart — suggestions only until admin approve.",
    }


def engineering_insights(*, limit: int = 600) -> dict[str, Any]:
    rows = [r for r in _read_observations(limit=limit) if r.get("kind") != "optimization"]
    profile_by_size: dict[str, Counter[str]] = defaultdict(Counter)
    thickness_by_size: dict[str, list[float]] = defaultdict(list)
    thickness_by_design: dict[str, list[float]] = defaultdict(list)
    hw_by_situation: dict[str, Counter[str]] = defaultdict(Counter)
    design_configs: Counter[str] = Counter()
    glass_by_product: dict[str, Counter[str]] = defaultdict(Counter)
    waste_samples: list[float] = []
    weight_samples: list[dict[str, Any]] = []

    for r in rows:
        bucket = str(r.get("sizeBucket") or "unknown")
        fam = str(r.get("productFamily") or "unknown")
        product = str(r.get("product") or "unknown")
        panels = r.get("panelCount")
        situ = f"{fam}|panels={panels or '?'}|{bucket}"

        for p in r.get("profiles") or []:
            profile_by_size[bucket][str(p)] += 1
        for t in r.get("wallThicknessesMm") or []:
            thickness_by_size[bucket].append(float(t))
            thickness_by_design[fam].append(float(t))
        for h in r.get("hardwareNames") or []:
            hw_by_situation[situ][str(h)] += 1
        if r.get("handle"):
            hw_by_situation[situ][f"handle:{r['handle']}"] += 1

        cfg = f"{product}|{r.get('glass') or '-'}|{r.get('colour') or '-'}|{r.get('handle') or '-'}|p{panels or '?'}"
        design_configs[cfg] += 1
        if r.get("glass"):
            glass_by_product[product][str(r["glass"])] += 1

        if r.get("wastePercentObserved") is not None:
            try:
                waste_samples.append(float(r["wastePercentObserved"]))
            except (TypeError, ValueError):
                pass
        w = r.get("weight") or {}
        if w.get("totalKg") is not None:
            weight_samples.append(
                {
                    "product": product,
                    "size": f"{r.get('width')}×{r.get('height')}",
                    "totalKg": w.get("totalKg"),
                    "aluminiumKg": w.get("aluminiumKg"),
                    "glassKg": w.get("glassKg"),
                }
            )

    def top_map(counter_map: dict[str, Counter[str]], n: int = 3) -> dict[str, list[list[Any]]]:
        return {k: c.most_common(n) for k, c in sorted(counter_map.items()) if c}

    def avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 3) if xs else None

    tips: list[str] = []
    if design_configs:
        cfg, n = design_configs.most_common(1)[0]
        tips.append(f"Most common canvas config: {cfg} ({n}×)")
    for bucket, thicknesses in list(thickness_by_size.items())[:3]:
        a = avg(thicknesses)
        if a is not None:
            tips.append(f"Avg wall thickness for {bucket}: {a} mm")
    if waste_samples:
        tips.append(f"Observed aluminium cut waste avg: {avg(waste_samples)}%")
    if not tips:
        tips.append("Calculate projects with BOM/weight — engineering patterns will appear here.")

    result = {
        "ok": True,
        "observationCount": len(rows),
        "tips": tips,
        "profilesBySize": top_map(profile_by_size),
        "avgWallThicknessBySizeMm": {k: avg(v) for k, v in thickness_by_size.items()},
        "avgWallThicknessByDesignMm": {k: avg(v) for k, v in thickness_by_design.items()},
        "hardwareBySituation": top_map(hw_by_situation, 5),
        "designConfigurations": design_configs.most_common(12),
        "glassByProduct": top_map(glass_by_product),
        "avgWastePercent": avg(waste_samples),
        "recentWeights": weight_samples[-8:][::-1],
        "formulasKnown": len(BASELINE_FORMULAS),
        "status": "learning" if rows else "waiting",
        "message": tips[0] if tips else "Watching engineering activity…",
        "safety": "Suggestions / pending only — production profiles never auto-modified.",
    }
    insights_cache_path().write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def build_engineering_suggestions() -> dict[str, Any]:
    """Actionable suggestions (one-click → pending), never silent production overwrite."""
    insights = engineering_insights()
    suggestions: list[dict[str, Any]] = []

    # Baseline formulas always available as teachable knowledge
    for fx in list_baseline_formulas():
        suggestions.append(
            {
                "id": f"teach_{fx['key']}",
                "domain": "engineering",
                "action": "queue_formula",
                "title": f"Teach KB: {fx['name']}",
                "summary": fx.get("description") or fx.get("expression"),
                "formulaKey": fx["key"],
                "payload": propose_refinement_payload(
                    fx["key"],
                    note=f"Seed baseline formula into formulas library: {fx['name']}",
                    evidence={"source": "baseline"},
                ),
                "confidence": 0.9,
                "oneClick": True,
            }
        )

    avg_waste = insights.get("avgWastePercent")
    if avg_waste is not None and avg_waste > 0:
        suggestions.append(
            {
                "id": "refine_alu_waste",
                "domain": "engineering",
                "action": "queue_formula",
                "title": f"Update aluminium section waste default → {avg_waste}%",
                "summary": (
                    f"Observed cut waste avg {avg_waste}% from optimize runs. "
                    "Queues formula default change for admin review."
                ),
                "formulaKey": "aluminium_section",
                "payload": propose_refinement_payload(
                    "aluminium_section",
                    defaults={"wastePercent": avg_waste},
                    note=f"Learned wastePercent={avg_waste} from engineering observations",
                    evidence={"avgWastePercent": avg_waste, "samples": insights.get("observationCount")},
                ),
                "confidence": 0.65,
                "oneClick": True,
            }
        )

    # Thickness by size → engineering note suggestion
    for bucket, avg_t in (insights.get("avgWallThicknessBySizeMm") or {}).items():
        if avg_t is None:
            continue
        suggestions.append(
            {
                "id": f"thickness_{bucket}",
                "domain": "engineering",
                "action": "queue_engineering_note",
                "title": f"Size {bucket}: typical wall ≈ {avg_t} mm",
                "summary": "Record size→thickness preference as pending engineering rule note (not production).",
                "payload": {
                    "ruleType": "wall_thickness_by_size",
                    "sizeBucket": bucket,
                    "suggestedWallThicknessMm": avg_t,
                    "evidence": insights.get("profilesBySize", {}).get(bucket),
                },
                "confidence": 0.55,
                "oneClick": True,
            }
        )

    for situ, tops in list((insights.get("hardwareBySituation") or {}).items())[:8]:
        if not tops:
            continue
        name, n = tops[0]
        suggestions.append(
            {
                "id": f"hw_{abs(hash(situ)) % 10_000_000}",
                "domain": "engineering",
                "action": "queue_engineering_note",
                "title": f"Hardware for {situ}: prefer {name}",
                "summary": f"Seen {n}× — queue as situation→hardware preference for review.",
                "payload": {
                    "ruleType": "hardware_by_situation",
                    "situation": situ,
                    "preferredHardware": name,
                    "count": n,
                    "alternatives": tops[1:4],
                },
                "confidence": min(0.85, 0.4 + 0.05 * n),
                "oneClick": True,
            }
        )

    # Deduplicate teach_* if library already has them — still ok to show lightly
    out = {
        "status": "suggestions_only",
        "message": "One-click queues Pending Review — never writes production products/profiles.",
        "suggestions": suggestions[:40],
        "insightsSummary": {
            "observationCount": insights.get("observationCount"),
            "tips": insights.get("tips"),
            "avgWastePercent": avg_waste,
        },
        "formulas": list_baseline_formulas(),
    }
    suggestions_cache_path().write_text(
        json.dumps({"ts": _now(), "count": len(suggestions)}, indent=2) + "\n", encoding="utf-8"
    )
    return out


def apply_engineering_suggestion(
    suggestion: Mapping[str, Any] | None = None,
    *,
    suggestion_id: str | None = None,
    applied_by: str = "admin",
) -> dict[str, Any]:
    """One-click: create pending V2 proposal. Does NOT approve or touch production."""
    from WEOS.learning.models import KIND_FORMULA, KIND_ENGINEERING_RULES
    from WEOS.learning.v2_store import create_pending

    sug = dict(suggestion or {})
    if not sug and suggestion_id:
        for s in build_engineering_suggestions().get("suggestions") or []:
            if s.get("id") == suggestion_id:
                sug = s
                break
    if not sug:
        raise ValueError("Suggestion not found")

    action = sug.get("action") or "queue_formula"
    payload = sug.get("payload") or {}

    if action == "queue_formula":
        prop = create_pending(
            kind=KIND_FORMULA,
            title=sug.get("title") or "Formula refinement",
            payload=payload if "formulas" in payload else {"formulas": [payload]},
            source={
                "type": "engineering_live_learn",
                "suggestionId": sug.get("id"),
                "appliedBy": applied_by,
            },
            summary=sug.get("summary") or "",
            confidence=float(sug.get("confidence") or 0.5),
            notes=[
                "Queued from Engineering Live Learning one-click apply.",
                "Approve to write formulas library / KB version — production engines unchanged until Product Builder / manual sync.",
            ],
            item_counts={"formulas": len((payload.get("formulas") or [1]))},
        )
    else:
        # engineering note / rule preference
        prop = create_pending(
            kind=KIND_FORMULA,  # keep in V2 kinds; payload carries ruleType
            title=sug.get("title") or "Engineering preference",
            payload={
                "engineeringPreference": payload,
                "formulas": [],
                "note": sug.get("summary"),
            },
            source={
                "type": "engineering_live_learn",
                "suggestionId": sug.get("id"),
                "appliedBy": applied_by,
                "legacyKindHint": KIND_ENGINEERING_RULES,
            },
            summary=sug.get("summary") or "Engineering preference for review",
            confidence=float(sug.get("confidence") or 0.5),
            notes=[
                "Preference / rule suggestion only.",
                "Does not modify production profile JSON.",
            ],
        )

    return {
        "ok": True,
        "queued": True,
        "proposal_id": prop["proposal_id"],
        "kind": prop["kind"],
        "message": "Queued for Pending Review. Production not modified.",
        "proposal": {
            "proposal_id": prop["proposal_id"],
            "title": prop.get("title"),
            "status": prop.get("status"),
        },
    }


def agent_status() -> dict[str, Any]:
    rows = _read_observations(limit=30)
    return {
        "name": "Engineering Learning Agent",
        "status": "learning" if rows else "waiting",
        "observationCount": len(_read_observations(limit=5000)),
        "formulasKnown": len(BASELINE_FORMULAS),
        "lastObservation": rows[-1] if rows else None,
        "blurb": (
            "I watch profiles, wall thickness by size, hardware by panel/design, "
            "glass & cut waste — and teach weight formulas. One-click suggestions go to Pending Review only."
        ),
    }


# Re-export compute for API convenience (legacy formulas + universal engine)
from WEOS.factory import weight_engine as _weight_engine

compute_material_weight = compute_weight
calculate_material_weight = _weight_engine.calculate_material_weight
analyze_missing_weights = _weight_engine.analyze_missing_weights
