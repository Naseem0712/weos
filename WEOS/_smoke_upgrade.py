"""Aggregator smoke for the unified-canvas / railing / casement / shower upgrade."""
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    mods = [
        "WEOS._smoke_easy_railing",
        "WEOS._smoke_railing_pdf",
        "WEOS._smoke_money_specs",
        "WEOS._smoke_preview_rates",
        "WEOS._smoke_shower",
    ]
    fails: list[str] = []
    for mod in mods:
        print(f"--- {mod} ---")
        r = subprocess.run([sys.executable, "-m", mod], capture_output=True, text=True)
        if r.stdout:
            print(r.stdout.rstrip())
        if r.returncode:
            if r.stderr:
                print(r.stderr.rstrip())
            fails.append(mod)
            print(f"[{mod}] FAIL rc={r.returncode}")
        else:
            print(f"[{mod}] OK")
    if fails:
        print("FAIL upgrade:", ", ".join(fails))
        return 1
    print("OK upgrade · railing + shower + money + preview")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
