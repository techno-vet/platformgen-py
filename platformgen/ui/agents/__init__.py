"""Canonical PlatformGen UI agents package facade."""

import auger.ui.agents as _auger_agents
from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent), *list(_auger_agents.__path__)]
