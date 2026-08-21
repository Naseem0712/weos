"""Reproduce / verify railing 1mm collapse fix."""
from __future__ import annotations

import re
import sys

from WEOS.factory.project_engine import calculate_line
from WEOS.factory.railing_engine import compute_railing, railing_svg


def dim(svg: str) -> str:
    m = re.search(r"([\d.]+)\s*mm[^<\"]{0,40}([\d.]+)\s*RFT", svg or "")
    return m.group(0) if m else "NO_DIM"


def summ(svg: str) -> str:
    m = re.search(r"Railing [^<]+", svg or "")
    if m:
        return m.group(0)
    if "missing" in (svg or "").lower():
        return "ERROR_SVG"
    return "NO_SUMM"


def main() -> int:
    lines = []
    q = compute_railing({})
    svg = railing_svg({})
    lines.append(f"empty_cfg L={q.get('lengthMm')} | svg={summ(svg)} | dim={dim(svg)}")

    r = calculate_line({
        "product": "railings_stub",
        "productType": "railing",
        "category": "Railings",
        "width": 3000,
        "height": 1000,
        "qty": 1,
    })
    svg2 = (r.get("preview") or {}).get("svg", "")
    ql = (r.get("railing") or {}).get("lengthMm")
    rft = (r.get("railing") or {}).get("lengthRft")
    cfg = (r.get("options") or {}).get("railing")
    lines.append(f"typed_no_cfg qL={ql} rft={rft} cfgL={(cfg or {}).get('lengthMm')} | {summ(svg2)} | {dim(svg2)}")

    good = calculate_line({
        "product": "railing",
        "width": 3000,
        "height": 1000,
        "qty": 1,
        "options": {
            "railing": {
                "shape": "straight",
                "lengthMm": 3000,
                "heightMm": 1000,
                "panels": 3,
                "mountType": "side_mount",
            }
        },
    })
    svg3 = (good.get("preview") or {}).get("svg", "")
    lines.append(
        f"with_cfg qL={(good.get('railing') or {}).get('lengthMm')} "
        f"rft={(good.get('railing') or {}).get('lengthRft')} | {summ(svg3)} | {dim(svg3)}"
    )

    text = "\n".join(lines)
    open("_rbug.txt", "w", encoding="utf-8").write(text)
    print(text)
    ok = (
        "missing" in svg.lower()
        and float(ql or 0) >= 2990
        and float(rft or 0) >= 9.5
        and "3000" in dim(svg2)
        and "3000" in dim(svg3)
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
