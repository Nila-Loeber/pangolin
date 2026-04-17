"""Implementation of `pangolin init`.

Copies default config files from the installed package into the current
directory, skipping any that already exist (unless --force).
"""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from pangolin import paths


def _copy(src: Path, dst: Path, *, force: bool) -> str:
    """Copy src → dst. Return a status string for the caller to log."""
    if dst.exists() and not force:
        return f"skip  {dst} (already exists)"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return f"wrote {dst}"


def init_repo(*, force: bool = False, cwd: Path | None = None) -> int:
    """Scaffold pangolin config into `cwd` (default: current working directory)."""
    root = (cwd or Path.cwd()).resolve()
    actions: list[str] = []

    # Single-file copies
    actions.append(_copy(paths.default_modes_yaml(), root / "modes.yml", force=force))
    actions.append(_copy(paths.default_wiki_schema(), root / "wiki" / "SCHEMA.md", force=force))

    # docs/*.md
    for src in paths.default_docs_dir().glob("*.md"):
        actions.append(_copy(src, root / "docs" / src.name, force=force))

    # workflows
    for src in paths.default_workflows_dir().glob("*.yml"):
        actions.append(_copy(src, root / ".github" / "workflows" / src.name, force=force))

    # Empty directory markers
    for d in ("wiki/fragment", "notes/ideas", "drafts", "content"):
        gk = root / d / ".gitkeep"
        if not gk.exists():
            gk.parent.mkdir(parents=True, exist_ok=True)
            gk.touch()
            actions.append(f"wrote {gk}")

    # Ingest watermark (epoch)
    wm = root / ".ingest-watermark"
    if not wm.exists() or force:
        wm.write_text("1970-01-01T00:00:00Z\n")
        actions.append(f"wrote {wm}")
    else:
        actions.append(f"skip  {wm} (already exists)")

    # Print report
    for a in actions:
        print(a)

    print("\nNext steps:")
    print("  1. Set repository secrets in GitHub:")
    print("     - CLAUDE_CODE_OAUTH_TOKEN  (Claude Max subscription token)")
    print("     - ANTHROPIC_API_KEY        (fallback; can be empty if OAuth is set)")
    print("  2. Edit docs/*.md to match your domain/voice.")
    print("  3. Edit modes.yml if you need different permission profiles.")
    print("  4. Open an inbox issue, then dispatch .github/workflows/agent-cycle.yml")

    return 0
