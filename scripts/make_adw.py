#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pydantic", "python-dotenv", "pyyaml", "rich"]
# ///
"""Checkout-local shim for flowie_runtime.make_adw."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from flowie_runtime.make_adw import main


if __name__ == "__main__":
    sys.exit(main())
