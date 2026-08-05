# Window CAD — Parametric Manufacturing Engine

Formula-driven aluminium window/door CAD. **Engineering rules live in profile JSON**
(`profiles/29mm_sliding.json`). Python never stores catalogue dimensions.

See [ARCHITECTURE.md](ARCHITECTURE.md) for module layout.

## Quick start

```bash
pip install -r requirements.txt

# One opening → DXF + SVG + JSON (BOM, glass, quote, …)
python -m app.cli --width 1440 --height 1800 --profile 29mm_sliding --outdir output --dump-bom

# Change profile sizes without editing Python
python -m app.cli --width 1440 --height 1800 --profile 29mm_sliding \
  --set trackWidth=32 --set interlockWidth=26 --set frameWidth=75 \
  --outdir output --dump-layout

python -m app.gui
python verify_two_track.py
```

## Profile series

| Id | File | Notes |
|----|------|-------|
| `29mm_sliding` | `profiles/29mm_sliding.json` | Two-track sliding (reference DXF rules) |

Future: `50mm_casement`, `slim_sliding`, `french_door`, …
