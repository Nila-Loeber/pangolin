"""Sandburg — owner-triggered conversational cycles for wiki repos."""

try:
    from importlib.metadata import version as _version
    __version__ = _version("sandburg")
except Exception:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
