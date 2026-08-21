"""Atomic-ish commit+push for GST hub changes only (PowerShell-safe)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(r"D:\Downloads\window cad model")
FILES = [
    "WEOS/api/server.py",
    "WEOS/db/models.py",
    "WEOS/factory/company_workspace.py",
    "WEOS/factory/customer_store.py",
    "WEOS/factory/ledger_pdf.py",
    "WEOS/factory/ledger_store.py",
    "WEOS/factory/project_store.py",
    "WEOS/website/index.html",
    "WEOS/_smoke_gst_hub_persist.py",
]
MSG = (
    "Persist GST company workspace across refresh with live hub KPIs and ledger PDF.\n\n"
    "Restore saved GSTIN from localStorage/sessionStorage, rehydrate hub lists from "
    "Postgres, add dashboard aggregates, mobile customer search, and improved ledger PDF sections.\n"
)
LOCK = ROOT / ".git" / "weos_gst_commit.lock"
OUT = ROOT / "_push_result.txt"


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


def main() -> int:
    lines: list[str] = []
    if LOCK.exists():
        lines.append("LOCK already held — abort")
        OUT.write_text("\n".join(lines), encoding="utf-8")
        return 2
    LOCK.write_text("gst-hub", encoding="utf-8")
    try:
        # Clear index of unrelated staged files from parallel agents.
        r = run(["git", "reset", "HEAD"])
        lines.append("reset: " + (r.stdout or r.stderr or "").strip())

        r = run(["git", "add", "--"] + FILES)
        lines.append("add exit=" + str(r.returncode))
        if r.stderr:
            lines.append(r.stderr.strip())

        r = run(["git", "diff", "--cached", "--stat"])
        lines.append("cached:\n" + (r.stdout or "").strip())
        cached = (r.stdout or "").strip()
        if not cached:
            lines.append("Nothing staged — abort")
            OUT.write_text("\n".join(lines), encoding="utf-8")
            return 1

        msg_path = ROOT / "_commit_msg_gst.txt"
        msg_path.write_text(MSG, encoding="utf-8")
        r = run(["git", "commit", "-F", str(msg_path)])
        lines.append("commit exit=" + str(r.returncode))
        lines.append((r.stdout or "").strip())
        lines.append((r.stderr or "").strip())
        if r.returncode != 0:
            OUT.write_text("\n".join(lines), encoding="utf-8")
            return r.returncode

        r = run(["git", "rev-parse", "HEAD"])
        sha = (r.stdout or "").strip()
        lines.append("HEAD=" + sha)

        r = run(["git", "push", "origin", "main"])
        lines.append("push exit=" + str(r.returncode))
        lines.append((r.stdout or "").strip())
        lines.append((r.stderr or "").strip())
        if r.returncode != 0:
            OUT.write_text("\n".join(lines), encoding="utf-8")
            return r.returncode

        r = run(["git", "status", "-sb"])
        lines.append((r.stdout or "").strip())
        lines.append("PUSH_DONE " + sha)
        OUT.write_text("\n".join(lines), encoding="utf-8")
        return 0
    finally:
        try:
            LOCK.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
