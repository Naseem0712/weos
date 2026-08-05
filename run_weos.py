#!/usr/bin/env python3
"""Start WEOS API server.

Usage (from workspace root):
  pip install -r requirements.txt
  python run_weos.py
  # open http://127.0.0.1:8000/

Respects PORT / WEOS_PORT and WEOS_HOST / HOST from the environment
(same vars used on Railway).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from WEOS.paths import host_from_env, port_from_env

    parser = argparse.ArgumentParser(description="WEOS — Window Engineering Operating System")
    parser.add_argument("--host", default=host_from_env("127.0.0.1"))
    parser.add_argument("--port", type=int, default=port_from_env(8000))
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run("WEOS.api.main:app", host=args.host, port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
