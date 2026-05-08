"""Canonical PlatformGen package facade over the legacy auger package."""

import auger as _auger

IN_DOCKER = _auger.IN_DOCKER

# Reuse the auger package's module search path so imports like
# `platformgen.cli` and `platformgen.ui.ask_genny` resolve without a risky
# package-root move yet.
__path__ = list(_auger.__path__)

__all__ = ["IN_DOCKER"]
