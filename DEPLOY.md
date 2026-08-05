# Deploy WEOS on Railway

## One-time setup

1. Push this repo to GitHub (`https://github.com/Naseem0712/weos.git`).
2. In [Railway](https://railway.app): **New Project → Deploy from GitHub** → select the repo.
3. Railway reads `requirements.txt` + `railway.toml` and starts:
   ```bash
   uvicorn WEOS.api.main:app --host 0.0.0.0 --port $PORT
   ```
4. Open the public URL; check `/health` and `/api/version`.

No Dockerfile or manual start command is required.

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | `8000` (local) | Listen port (Railway sets this) |
| `WEOS_HOST` | `127.0.0.1` local / `0.0.0.0` via start cmd | Bind host |
| `WEOS_PORT` | `8000` | Fallback if `PORT` unset (`run_weos.py`) |
| `WEOS_DATA_DIR` | `WEOS/` package dir | Writable root for projects + output |
| `WEOS_PROJECTS_DIR` | `$WEOS_DATA_DIR/projects` | Project JSON store |
| `WEOS_OUTPUT_DIR` | `$WEOS_DATA_DIR/output` | Calculate/export artifacts |
| `WEOS_STOCK_DIR` | `WEOS/stock` | Stock inventory JSON |
| `WEOS_KB_DIR` | `<repo>/knowledge_base` | Learning knowledge base |

For persistence across deploys, attach a Railway volume and set `WEOS_DATA_DIR` to the mount path (e.g. `/data`).

## Local parity

```bash
pip install -r requirements.txt
python run_weos.py
# or: PORT=8000 uvicorn WEOS.api.main:app --host 127.0.0.1 --port $PORT
```

## Health checks

- `GET /health` — liveness
- `GET /api/version` — app name, version, build info
