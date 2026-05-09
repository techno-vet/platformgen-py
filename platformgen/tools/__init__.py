"""Canonical PlatformGen tools package facade."""

import auger.tools as _auger_tools
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent), *list(_auger_tools.__path__)]
