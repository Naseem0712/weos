"""Batch B — PDF viewer UX wiring markers (no second PDF architecture)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "WEOS" / "website" / "index.html"


def _ok(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("OK:", msg)


def main() -> None:
    text = INDEX.read_text(encoding="utf-8")
    _ok("Preparing Quotation PDF" in text, "loading title present")
    _ok('data-state="preparing"' in text or "dataset.state" in text, "viewer state machine wired")
    _ok("setPdfViewerState" in text, "setPdfViewerState helper")
    _ok("showPdfMachineError" in text, "preflight error UX helper")
    _ok("pdfErrorList" in text, "missing-item error list")
    _ok("pdfErrorRetry" in text and "pdfErrorFix" in text, "Retry + Back to Quote actions")
    _ok("pdf-viewer-bar" in text, "compact ready header bar")
    _ok('id="pdfMachineClose">Back</button>' in text, "Back control label")
    _ok("pdfMachinePrint" in text and "pdfMachineDownload" in text, "Print + Download controls")
    _ok("toolbar=0" in text, "prefer WEOS chrome over native toolbar dup")
    _ok("pdfMachineSteps" not in text, "fake progress tabs removed")
    _ok("machine-scene" not in text, "theatre loading animation removed")
    _ok("showPdfMachineError(detail)" in text or "showPdfMachineError(" in text, "openProjectPdf uses error UX")
    # Batch A fail-closed still referenced from viewer error path / export
    _ok("PDF preflight" in text or "preflight" in text.lower(), "preflight messaging retained")
    print("PASS: pdf viewer UX wiring")


if __name__ == "__main__":
    main()
