#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""Compatibility entrypoint for source checkouts.

New installs use the packaged CLI:

    flowie init

This script remains so skill instructions can run a checkout-local installer.
It delegates to the same implementation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flowie_runtime.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["init", *sys.argv[1:]]))
