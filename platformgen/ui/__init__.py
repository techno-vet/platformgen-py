"""Canonical PlatformGen UI package facade over the legacy auger.ui package."""

import auger.ui as _auger_ui
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent), *list(_auger_ui.__path__)]
