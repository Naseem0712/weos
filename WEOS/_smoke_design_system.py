"""UX Batch C — WEOS Application Design System foundation (static markers / no regression)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBSITE = ROOT / "WEOS" / "website"
DS = WEBSITE / "design-system"
INDEX = WEBSITE / "index.html"


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    tokens = DS / "tokens.css"
    components = DS / "components.css"
    js = DS / "weos-ds.js"

    _ok(tokens.is_file(), "tokens.css present")
    _ok(components.is_file(), "components.css present")
    _ok(js.is_file(), "weos-ds.js present")

    tok = tokens.read_text(encoding="utf-8")
    comp = components.read_text(encoding="utf-8")
    script = js.read_text(encoding="utf-8")
    index = INDEX.read_text(encoding="utf-8")

    # Token markers
    for needle in (
        "--weos-color-primary:",
        "--weos-color-accent:",
        "--weos-text-xs:",
        "--weos-text-2xl:",
        "--weos-space-1:",
        "--weos-space-8:",
        "--weos-radius-sm:",
        "--weos-radius-pill:",
        "--weos-toolbar-h:",
        "--weos-sidepanel-w:",
        "#0a5a48",
        "#b45324",
    ):
        _ok(needle in tok, f"token {needle.strip(':')}")

    # Anti purple / AI-slop defaults in DS tokens
    _ok("#7c3aed" not in tok.lower() and "purple" not in tok.lower(), "no purple AI-slop tokens")

    # Component class markers
    for cls in (
        ".weos-ds-card",
        ".weos-ds-btn",
        ".weos-ds-btn--secondary",
        ".weos-ds-btn--ghost",
        ".weos-ds-input",
        ".weos-ds-pill",
        ".weos-ds-tabs",
        ".weos-ds-tab",
        ".weos-ds-modal",
        ".weos-ds-sidepanel",
        ".weos-ds-toolbar",
        ".weos-ds-table",
        ".weos-ds-state",
        ".weos-ds-spinner",
        ".weos-ds-prop-section",
    ):
        _ok(cls in comp, f"component {cls}")

    # JS helpers
    for fn in (
        "WEOSDesignSystem",
        "openModal",
        "closeModal",
        "openSidePanel",
        "closeSidePanel",
        "bindTabs",
        'batch = "UX-C"',
        'version = "0.1.0"',
    ):
        _ok(fn in script, f"js {fn}")

    # Progressive SPA integration (not a blind rewrite)
    _ok('/static/design-system/tokens.css' in index, "index links tokens.css")
    _ok('/static/design-system/components.css' in index, "index links components.css")
    _ok('/static/design-system/weos-ds.js' in index, "index loads weos-ds.js")

    # Regression: engineering / money / PDF / UC surfaces must remain
    for marker, label in (
        ("WEOS_UNIVERSAL_CANVAS", "UC flag"),
        ("/static/canvas/adapters.js", "adapters script"),
        ("/static/canvas/property_panel.js", "property panel script"),
        ("/static/canvas/universal_canvas.js", "universal canvas script"),
        ("setPdfViewerState", "PDF viewer UX"),
        ("pdf-viewer-bar", "PDF viewer bar"),
        ("Preparing Quotation PDF", "PDF preparing state"),
        ("savePill", "save durability pill"),
        ("function api(", "api helper"),
    ):
        _ok(marker in index, f"regression {label}")

    # Must not have wiped legacy button language
    _ok(".btn{" in index or ".btn," in index, "legacy .btn styles retained")
    _ok("--green:" in index, "legacy brand green retained")

    print("PASS: WEOS application design system foundation")


if __name__ == "__main__":
    main()
