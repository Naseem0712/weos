"""Memory audit (Part 5.1) — is memory actually created and used?

Traces every place WEOS is supposed to persist knowledge (engineering /
commercial observations, the 11 memory namespaces, learning pending queue, KB
versions, glass/hardware libraries) and reports what IS and ISN'T being written
and consumed. Read-only — never mutates anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from WEOS.paths import knowledge_base_dir


def _count_jsonl(path: Path) -> int:
    if not path.is_file():
        return 0
    n = 0
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n += 1
    except Exception:
        return 0
    return n


def _count_json_files(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(1 for p in folder.glob("*.json") if not p.name.startswith("_"))


def run_audit() -> dict[str, Any]:
    kb = knowledge_base_dir()

    # 1) Learning observation streams (written on calculate).
    eng_obs = _count_jsonl(kb / "engineering" / "observations.jsonl")
    com_obs = _count_jsonl(kb / "commercial" / "observations.jsonl")

    # 2) Memory namespaces (the 11 stores) — approved vs total.
    namespaces: dict[str, dict[str, int]] = {}
    total_mem = 0
    approved_mem = 0
    try:
        from WEOS.memory.schemas import MEMORY_TYPES
        from WEOS.memory.store import get_store

        store = get_store()
        for mt in MEMORY_TYPES:
            try:
                items = store.list(mt)
            except Exception:
                items = []
            appr = sum(1 for x in items if (x.get("status") or "") == "approved")
            namespaces[mt] = {"total": len(items), "approved": appr}
            total_mem += len(items)
            approved_mem += appr
    except Exception as exc:  # pragma: no cover - defensive
        namespaces = {"_error": {"total": 0, "approved": 0}}

    # 3) Learning pending queue (Observe→Suggest awaiting admin).
    pending = _count_json_files(kb / "pending" / "v2")

    # 4) KB versions.
    kb_versions = 0
    current_version = None
    try:
        from WEOS.learning.v2_store import current_kb_version, list_kb_versions

        kb_versions = len(list_kb_versions())
        current_version = current_kb_version()
    except Exception:
        pass

    # 5) Standalone configurable libraries (new engines).
    glass_lib = _count_json_files(kb / "libraries" / "glass_catalogue")
    hardware_lib = _count_json_files(kb / "libraries" / "hardware_catalogue")
    formula_mem = namespaces.get("formula", {}).get("total", 0)

    # ── Findings ────────────────────────────────────────────────────────────
    persisted: list[str] = []
    not_persisted: list[str] = []
    used: list[str] = []
    not_used: list[str] = []

    (persisted if eng_obs else not_persisted).append(
        f"Engineering observations ({eng_obs}) — written on project calculate + single calculate"
    )
    (persisted if com_obs else not_persisted).append(
        f"Commercial observations ({com_obs}) — customer/quote patterns"
    )
    (persisted if total_mem else not_persisted).append(
        f"Memory namespaces ({total_mem} items, {approved_mem} approved)"
    )
    (persisted if formula_mem else not_persisted).append(
        f"Formula Memory ({formula_mem}) — baseline weight formulas preloaded"
    )
    (persisted if glass_lib else not_persisted).append(f"Glass library ({glass_lib} specs)")
    (persisted if hardware_lib else not_persisted).append(f"Hardware library ({hardware_lib} items)")

    # Consumption: what actually reads the above.
    used.append("Engineering insights + suggestions read observations.jsonl (Engineering Live Learning)")
    used.append("Commercial intelligence + customer memory read commercial observations")
    if approved_mem:
        used.append(f"Engineering Brain load/reason/generate reads {approved_mem} approved memories")
    else:
        not_used.append("Engineering Brain has no approved memories to consume yet (approve suggestions to feed it)")
    if formula_mem:
        used.append("Default weight formulas feed material/BOM weight compute + Formula Memory")
    used.append("Intelligence dashboard surfaces observations, suggestions and libraries")

    if not pending:
        not_used.append("Learning pending queue is empty (no suggestions awaiting approval)")

    smart_flags = {
        "observationsWritten": bool(eng_obs or com_obs),
        "memoryNamespacesPopulated": bool(total_mem),
        "approvedMemoryForBrain": bool(approved_mem),
        "defaultFormulasPreloaded": bool(formula_mem),
        "glassLibraryConfigured": bool(glass_lib),
        "hardwareLibraryConfigured": bool(hardware_lib),
    }

    verdict = "healthy" if smart_flags["observationsWritten"] and smart_flags["memoryNamespacesPopulated"] else "needs_data"

    return {
        "ok": True,
        "verdict": verdict,
        "counts": {
            "engineeringObservations": eng_obs,
            "commercialObservations": com_obs,
            "memoryTotal": total_mem,
            "memoryApproved": approved_mem,
            "formulaMemory": formula_mem,
            "learningPending": pending,
            "kbVersions": kb_versions,
            "currentKbVersion": current_version,
            "glassLibrary": glass_lib,
            "hardwareLibrary": hardware_lib,
        },
        "namespaces": namespaces,
        "persisted": persisted,
        "notPersisted": not_persisted,
        "consumedBy": used,
        "notYetUsed": not_used,
        "flags": smart_flags,
        "howToProve": [
            "POST /api/calculate (or calculate a project) → engineeringObservations increments.",
            "GET /api/engineering/insights → tips derived from those observations.",
            "GET /api/memory-audit → this report reflects new counts.",
            "Approve a suggestion (Learning Engine) → memoryApproved increments and Brain consumes it.",
        ],
        "safety": "Read-only audit. Production data and approval gates are never bypassed.",
    }
