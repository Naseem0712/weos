"""WEOS Agent Orchestrator (Part 3) — the live brain of the quote builder.

Receives a live **Quote Context** (customer, product, series, W, H, qty, track
count, shutter count, selected profiles, glass, hardware, colour, calculation
result, BOM, rates, previous-quote history, approved engineering rules) and runs
after important changes: product/series select, W/H change, track/shutter
change, glass change, hardware change, colour change, BOM calc, price calc,
finalize.

It is deliberately NOT isolated: it is invoked by the FastAPI quote workflow and
its output (suggestions + explanations) is displayed in the "WEOS Agent" panel.

Responsibilities:
1. Run the live Suggestion Engine → suggestions/warnings/recommendations.
2. Record observations into the existing memory layers (Part 6/7) — observation
   only, never auto-promoting to approved rules.
3. Persist suggestions + an audit event to the quote (Part 8) when a quote_id
   is supplied and the database is available.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger("weos.agent")

# Triggers that should re-run the agent (documented for callers/UI).
TRIGGERS = (
    "product_select",
    "series_select",
    "dimension_change",
    "track_change",
    "shutter_change",
    "glass_change",
    "hardware_change",
    "colour_change",
    "bom_calc",
    "price_calc",
    "finalize",
)


def analyze(
    context: dict[str, Any],
    *,
    trigger: str = "manual",
    quote_id: str | None = None,
    persist: bool = True,
    learn: bool = True,
) -> dict[str, Any]:
    """Main entry point. Returns suggestions + explanations for the UI panel.

    ``persist`` writes suggestions/events to the quote (needs DB + quote_id).
    ``learn`` records observations into memory (Part 7).
    """
    from WEOS.agent.suggestion_engine import generate

    context = dict(context or {})
    suggestions = generate(context)

    # Enrich with the Engineering Brain's series-level checks (best-effort).
    brain_notes: list[dict[str, Any]] = []
    series = context.get("series") or context.get("sectionSeries")
    if series:
        brain_notes = _brain_checks(series, context)

    persisted: list[dict[str, Any]] = []
    if persist and quote_id:
        persisted = _persist(quote_id, suggestions, trigger)

    if learn:
        _observe(context, trigger, suggestions)

    return {
        "ok": True,
        "trigger": trigger,
        "quoteId": quote_id,
        "suggestions": persisted or suggestions,
        "brainNotes": brain_notes,
        "count": len(suggestions),
        "context": _context_echo(context),
        "message": "WEOS Agent analysed the live quote context.",
    }


def _brain_checks(series: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    try:
        from WEOS.agent.suggestion_engine import _glass_thickness_mm
        from WEOS.brain import check_series_compatibility

        glass_mm = _glass_thickness_mm(context.get("glass"))
        res = check_series_compatibility(series=series, glass_thickness_mm=glass_mm)
        if isinstance(res, dict) and res.get("warnings"):
            for w in res["warnings"]:
                msg = w.get("message") if isinstance(w, dict) else str(w)
                notes.append({"source": "brain_compatibility", "message": msg})
    except Exception as exc:  # brain optional — never break the panel
        _log.debug("brain compatibility check skipped: %s", exc)
    return notes


def _persist(quote_id: str, suggestions: list[dict[str, Any]], trigger: str) -> list[dict[str, Any]]:
    try:
        from WEOS.db.quote_store import add_event, save_suggestions

        saved = save_suggestions(quote_id, suggestions)
        add_event(quote_id, "agent_run", f"Agent ran on trigger '{trigger}'", {"trigger": trigger, "count": len(suggestions)})
        return saved
    except FileNotFoundError:
        return []
    except Exception as exc:
        _log.warning("agent could not persist suggestions for %s: %s", quote_id, exc)
        return []


def _observe(context: dict[str, Any], trigger: str, suggestions: list[dict[str, Any]]) -> None:
    """Record an observation into existing memory (never modifies approved rules)."""
    try:
        from WEOS.memory.store import write_observation_as_learning

        write_observation_as_learning(
            observation_type="quote_agent",
            summary=(
                f"Agent[{trigger}] {context.get('product') or '?'} "
                f"{context.get('width')}×{context.get('height')} "
                f"shutters={context.get('shutterCount')} glass={_glass_label(context.get('glass'))} "
                f"→ {len(suggestions)} suggestion(s)"
            ),
            evidence={
                "trigger": trigger,
                "product": context.get("product"),
                "series": context.get("series") or context.get("sectionSeries"),
                "width": context.get("width"),
                "height": context.get("height"),
                "shutterCount": context.get("shutterCount"),
                "glass": _glass_label(context.get("glass")),
                "colour": context.get("colour"),
                "suggestionKeys": [s.get("key") for s in suggestions],
            },
            suggestion="Observed live quote context — feeds candidate learning; approval still required.",
            domain="engineering",
        )
    except Exception as exc:
        _log.debug("agent observation skipped: %s", exc)


def _glass_label(glass: Any) -> Any:
    if isinstance(glass, dict):
        return glass.get("name") or glass.get("thicknessMm")
    if isinstance(glass, list) and glass:
        return _glass_label(glass[0])
    return glass


def _context_echo(context: dict[str, Any]) -> dict[str, Any]:
    keys = ("product", "series", "sectionSeries", "width", "height", "quantity", "trackCount", "shutterCount", "colour")
    return {k: context.get(k) for k in keys if context.get(k) is not None}


def status() -> dict[str, Any]:
    """Agent + suggestion-engine readiness for the health endpoint (Part 10)."""
    try:
        from WEOS.agent.suggestion_engine import generate

        sample = generate({"product": "29mm_sliding", "width": 1440, "height": 1800, "shutterCount": 2, "glass": "5mm_clear", "trackCount": 2})
        return {
            "agent": "READY",
            "suggestionEngine": "READY",
            "triggers": list(TRIGGERS),
            "sampleSuggestionCount": len(sample),
        }
    except Exception as exc:
        return {"agent": "ERROR", "suggestionEngine": "ERROR", "error": str(exc)}
