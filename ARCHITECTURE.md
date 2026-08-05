# WEOS V2 — Window Engineering Operating System

**Tagline:** Design • Calculate • Manufacture • Quote

Manufacturing OS (windows, doors, pergolas, railings, facades) — **not** a calculator, **not** a CAD app.  
**API JSON is the product.** CAD/DXF optional (default OFF).

## Run

```bash
pip install -r requirements.txt
python run_weos.py
# UI:  http://127.0.0.1:8000/
# Docs: http://127.0.0.1:8000/docs
# Health: http://127.0.0.1:8000/health
# Version: http://127.0.0.1:8000/api/version
```

Cloud deploy: see [DEPLOY.md](DEPLOY.md). Start command:

```bash
uvicorn WEOS.api.main:app --host 0.0.0.0 --port $PORT
```

## Exact project APIs

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness |
| GET | `/api/version` | App name, version, build info |
| POST | `/api/projects` | Create project + cart lines |
| POST | `/api/projects/{id}/calculate` | Full calc + optimize (engines) |
| GET | `/api/projects/{id}` | Reload project |
| GET | `/api/projects/{id}/quotation` | Quotation JSON |
| GET | `/api/projects/{id}/customer-pdf` | Customer quotation PDF |
| GET | `/api/projects/{id}/factory-pdf` | Factory package PDF + QR |
| POST | `/api/projects/import` | CSV/Excel → new or existing project |

Also: `/api/dashboard`, `/api/products`, `/api/products/{id}`, `/api/preview`, undo/redo/archive/history.

## Product Library

```
WEOS/products/<id>/
  product.json          # catalogue + materials[] + formulas + pdfLayout + brand
  rules/*.json          # manufacturing source of truth (geometry, glass, hardware, …)
WEOS/templates/         # seeded PDF template JSON (WoodenMax / AllKraft)
WEOS/website/products/  # hero/section images served as /static/products/...
```

**Fully live manufacturing:** `29mm_sliding`  
**Catalogue stubs (quote via manual rate):** casement, fixed, 35mm sliding, folding, pergola, louvers, railings, ACP, fluted, perforated

### Formula Builder

Safe AST evaluator (`WEOS/factory/formula.py`) — no `eval` of Python. Materials use `quantityFormula` / `lengthFormula` / `weightFormula` with units `PC|KG|RFT|RM|SQFT|SQM|BOX|PAIR|SET`.

### Template Designer

Drag-drop blocks in the ERP UI → JSON layouts → `template_pdf` renders Customer / Factory PDFs. Brand query `?brand=woodenmax|allkraft` selects template without code changes.

### Admin APIs

| Method | Path | Purpose |
|--------|------|---------|
| GET/POST/PUT/DELETE | `/api/admin/products…` | Product Library CRUD |
| POST | `/api/formulas/validate` `/preview` | Formula Builder |
| GET/POST/PUT/DELETE | `/api/templates…` | PDF templates |
| POST | `/api/templates/preview-pdf` | Preview render |

## Engines (never duplicate)

Frontend → FastAPI → `factory/pipeline` + glass/hardware/brush/track/cutlist/weight/bom/quotation/optimize.

## ERP UI

Dashboard · Saved Projects · Window Cart · Product Library · Product Details · **Admin · Products** · **Formula Builder** · **Template Designer**.

Open: `http://127.0.0.1:8000/` — use left nav for admin tools.

## Paths & env

Runtime paths use `pathlib` via `WEOS/paths.py`. Override writable roots with `WEOS_DATA_DIR` (and optional `WEOS_PROJECTS_DIR` / `WEOS_OUTPUT_DIR`) for Railway volumes. See `DEPLOY.md`.
