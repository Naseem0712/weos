# Bundled PDF fonts (₹ / Unicode)

`WEOS/factory/pdf_fonts.py` looks here **first** for a Unicode TrueType font so
that the Indian Rupee glyph (₹, U+20B9) prints correctly in quotation PDFs on
**any** OS — including the Railway (Linux) server, which does **not** ship the
Windows fonts (Nirmala UI / Segoe UI) the app used to depend on.

## To guarantee the ₹ symbol on every platform

Drop a ₹-capable `.ttf` in this folder. Recommended (free, redistributable):

- `DejaVuSans.ttf` (and optionally `DejaVuSans-Bold.ttf`) — has ₹, wide coverage.
  Download from https://dejavu-fonts.github.io/ or copy from a Linux box at
  `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`.
- or `NotoSans-Regular.ttf` / `LiberationSans-Regular.ttf`.

The file name must match one of the preferred names in `pdf_fonts.py`
(`DejaVuSans.ttf`, `NotoSans-Regular.ttf`, `LiberationSans-Regular.ttf`, …) or
just be any `*.ttf` — all `.ttf` files here are tried.

## If no font is bundled

The exporter still works everywhere:

1. It tries common Linux system fonts (DejaVu / Liberation / Noto).
2. Then Windows fonts (dev machines).
3. Then reportlab's own bundled Vera font.
4. If nothing has the ₹ glyph, currency prints as `Rs.` instead of a tofu box.

Export **never** crashes because of fonts.

## Alternative: install a font at the OS level on Railway

Add a Nixpacks/apt package so the system has DejaVu, e.g. in `nixpacks.toml`:

```toml
[phases.setup]
aptPkgs = ["fonts-dejavu-core"]
```

or set the env var `WEOS_RUPEE_FONT=/absolute/path/to/DejaVuSans.ttf`.
