"""
Start the API:  python -m tracelight.api [--host 127.0.0.1] [--port 8000]

Binds to localhost by default: the app has no authentication and can read
local folders, so it must not be exposed on a network.
"""

import argparse
import logging

import uvicorn

from .app import create_app


def main() -> None:
    ap = argparse.ArgumentParser(description="Tracelight API server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
