"""Canonical PlatformGen CLI wrapper over the legacy auger CLI module."""

from auger.cli import (
    PlatformGenGroup,
    AugerGroup,
    main,
    platformgen_main,
    genny_main,
    cli_main,
)

__all__ = [
    "PlatformGenGroup",
    "AugerGroup",
    "main",
    "platformgen_main",
    "genny_main",
    "cli_main",
]
