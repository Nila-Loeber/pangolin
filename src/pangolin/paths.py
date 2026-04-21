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


def default_wiki_dir() -> Path:
    return default_config_root() / "wiki"


def default_claude_skills_dir() -> Path:
    """Claude Code skill templates shipped with the package, scaffolded into
    each wiki repo's `.claude/skills/` by `pangolin init`."""
    return default_config_root() / "claude" / "skills"


def resolve_config(relative: str) -> Path:
    """Resolve a config path with wiki-override-wins-over-package-default.

    Runtime config (modes.yml, docs/*-agent.md, validate_output.sh) lives in
    the package so that `pip install pangolin@X` updates behavior atomically
    across every wiki repo. A wiki may still override any file by checking
    in a same-named copy at the same relative path — the wiki's copy wins.

    Raises FileNotFoundError if neither location has the file.
    """
    from pangolin.core import REPO
    wiki = REPO / relative
    if wiki.exists():
        return wiki
    pkg = default_config_root() / relative
    if pkg.exists():
        return pkg
    raise FileNotFoundError(
        f"No config at {relative!r} (tried {wiki} and {pkg})"
    )
