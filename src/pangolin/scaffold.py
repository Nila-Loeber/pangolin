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


def init_repo(
    *, force: bool = False, with_wiki: bool = False, cwd: Path | None = None
) -> int:
    """Scaffold pangolin config into `cwd` (default: current working directory).

    Ships only the thin workflow shim + user-owned wiki content. The SSoT
    runtime config (modes.yml, docs/*-agent.md) lives inside the installed
    pangolin package — `pip install pangolin@X` updates behavior atomically.

    Wiki repos may override any package default by checking in a same-named
    copy at the same relative path (see paths.resolve_config); `pangolin
    init` does not scaffold these to avoid creating silent drift.
    """
    root = (cwd or Path.cwd()).resolve()
    actions: list[str] = []

    # Single-file copies
    actions.append(_copy(paths.default_wiki_schema(), root / "wiki" / "SCHEMA.md", force=force))

    # workflows (thin shim — all behavior in the pip package)
    for src in paths.default_workflows_dir().glob("*.yml"):
        actions.append(_copy(src, root / ".github" / "workflows" / src.name, force=force))

    # Claude Code skills: atomically-deployed natural-language shortcuts the
    # owner uses against the wiki-local agent. Today: `canary-update`.
    skills_src = paths.default_claude_skills_dir()
    if skills_src.is_dir():
        for src in skills_src.rglob("SKILL.md"):
            rel = src.relative_to(skills_src)
            actions.append(_copy(src, root / ".claude" / "skills" / rel, force=force))

    # Empty directory markers
    for d in ("wiki/fragment", "notes/ideas", "drafts", "content"):
        gk = root / d / ".gitkeep"
        if not gk.exists():
            gk.parent.mkdir(parents=True, exist_ok=True)
            gk.touch()
            actions.append(f"wrote {gk}")

    # --with-wiki: seed nlkw-style wiki structure (index.md, log.md, ref/, project/, draft/)
    # TODO(pre-GA): generalize nlkw's conventions — current templates bake in a German-default
    # voice and specific directory typology. Before GA, extract convention choices into modes.yml
    # or a separate `wiki.yml` so other users can pick their own defaults.
    if with_wiki:
        for src in paths.default_wiki_dir().glob("*.md"):
            actions.append(_copy(src, root / "wiki" / src.name, force=force))
        for d in ("wiki/ref", "wiki/project", "wiki/draft"):
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
    print("  2. (optional) Customize behavior by checking in overrides:")
    print("     - modes.override.yml   — deep-merged on top of package defaults")
    print("     - docs/<name>.md       — wins over the package default for that file")
    print("  3. Open an inbox issue, then dispatch .github/workflows/agent-cycle.yml")

    return 0
