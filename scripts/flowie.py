#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""Flowie CLI shim for source checkouts."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flowie_runtime.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
