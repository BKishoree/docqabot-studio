"""Run the OpenAI stub: ``python -m studio.stub [--host H] [--port P]``.

Precedence: flag, then STUB_HOST / STUB_PORT, then 0.0.0.0 / 8001.
"""

import argparse
import os

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m studio.stub", description=__doc__)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    host = args.host or os.environ.get("STUB_HOST") or "0.0.0.0"
    port = args.port if args.port is not None else int(os.environ.get("STUB_PORT") or 8001)
    uvicorn.run("studio.stub:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
