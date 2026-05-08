"""Legacy Ask Auger shim forwarding to the canonical Ask Genny module."""

from .ask_genny import AskAugerPanel, AskGennyPanel

__all__ = ["AskAugerPanel", "AskGennyPanel"]
