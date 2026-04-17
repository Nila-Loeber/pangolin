"""Resolve paths to files shipped with the installed pangolin package.

Used for the bash validator, default configs, and workflow templates that
live inside the package but are needed at runtime.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def _pkg_root() -> Path:
    """Return the filesystem path of the installed `pangolin` package."""
    return Path(str(files("pangolin")))


def default_config_root() -> Path:
    """Root of the default_config/ tree shipped with the package."""
    return _pkg_root() / "default_config"


def validate_output_script() -> Path:
    """Path to the bash validator script (called by the orchestrator)."""
    return default_config_root() / "validate_output.sh"


def default_modes_yaml() -> Path:
    return default_config_root() / "modes.yml"


def default_wiki_schema() -> Path:
    return default_config_root() / "wiki_schema.md"


def default_docs_dir() -> Path:
    return default_config_root() / "docs"


def default_workflows_dir() -> Path:
    return default_config_root() / "workflows"
