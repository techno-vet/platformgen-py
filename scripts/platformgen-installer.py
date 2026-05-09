#!/usr/bin/env python3
"""Bootstrap-safe entrypoint for the Python-first PlatformGen installer."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from platformgen.installer import main


if __name__ == "__main__":
    raise SystemExit(main())
