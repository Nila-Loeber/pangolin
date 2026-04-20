"""Load and validate modes.yml configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Mode:
    name: str
    description: str
    provider: str
    model: str
    execution: str  # "container" or "direct"
    network: bool
    code_execution: bool
    allowed_tools: list[str]
    denied_tools: list[str]
    readable_paths: list[str]
    writable_paths: list[str]
    gh_cli: bool
    autonomy: str
    trust_level: str
    container_runtime: str | None = None  # "runsc" for gVisor
    quarantine_output: str | None = None
    json_schema: str | None = None
    egress: str = "tight"  # "tight" or "loose" — egress-proxy port selector


# JSON schemas for direct-execution agents (triage, summary, self-improve)
SCHEMAS = {
    "triage": {
        "type": "object",
        "properties": {
            "watermark": {"type": "string"},
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "description": "spawn|comment|label|close|label_create"},
                        "title": {"type": "string"},
                        "body": {"type": "string", "description": "Required for spawn, comment, and close actions"},
                        "labels": {"type": "array", "items": {"type": "string"}},
                        "issue": {"type": "integer"},
                        "add": {"type": "array", "items": {"type": "string"}},
                        "remove": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["action", "body"],
                },
            },
            "store_files": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        "required": ["watermark", "decisions"],
    },
    "summary": {
        "type": "object",
        "properties": {
            "comments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "issue": {"type": "integer"},
                        "body": {"type": "string"},
                    },
                    "required": ["issue", "body"],
                },
            },
        },
        "required": ["comments"],
    },
    "wiki-index": {
        "type": "object",
        "properties": {
            "index_md": {
                "type": "string",
                "description": "Complete contents of wiki/index.md",
            },
        },
        "required": ["index_md"],
    },
    "thinking": {
        "type": "object",
        "properties": {
            "writes": {
                "type": "array",
                "description": "Files to create or edit: wiki/*.md, notes/*.md, or drafts/*.md.",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "action": {"type": "string", "description": "create | edit | append"},
                    },
                    "required": ["path", "content"],
                },
            },
            "processed_issues": {
                "type": "array",
                "items": {"type": "integer"},
            },
            "skipped": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "issue": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                    "required": ["issue", "reason"],
                },
            },
        },
        "required": ["writes", "processed_issues"],
    },
    "wiki-ingest": {
        "type": "object",
        "properties": {
            "writes": {
                "type": "array",
                "description": "Wiki pages to create or edit. Allowed paths: wiki/*.md, wiki/ref/*.md, wiki/project/*.md, wiki/draft/*.md, wiki/log.md. NOT wiki/fragment/*, NOT wiki/SCHEMA.md.",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                        "action": {"type": "string", "description": "create | edit | append"},
                    },
                    "required": ["path", "content"],
                },
            },
            "new_watermark": {
                "type": "string",
                "description": "New .ingest-watermark ISO-8601 timestamp. Must be >= the max captured_at across all absorbed fragments.",
            },
            "log_entry": {
                "type": "string",
                "description": "One-line summary for wiki/log.md (host prepends the timestamp).",
            },
            "skipped_fragments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "fragment": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["fragment", "reason"],
                },
            },
        },
        "required": ["writes"],
    },
    "writing": {
        "type": "object",
        "properties": {
            "drafts": {
                "type": "array",
                "description": "Files the writing agent wants to create or edit.",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path under drafts/ or content/.",
                        },
                        "content": {
                            "type": "string",
                            "description": "Full file content. For action=edit/append the host overwrites/appends.",
                        },
                        "action": {
                            "type": "string",
                            "description": "create | edit | append. Defaults to create.",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
            "processed_issues": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Issue numbers fully handled in this run.",
            },
            "skipped": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "issue": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                    "required": ["issue", "reason"],
                },
            },
        },
        "required": ["drafts", "processed_issues"],
    },
    "research": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Short title, no colons"},
                        "source": {"type": "string", "description": "URL or clean textual citation"},
                        "date": {"type": "string", "description": "YYYY-MM-DD of the source"},
                        "summary": {"type": "string", "description": "2-4 sentences, plain text"},
                        "why_relevant": {"type": "string", "description": "1-2 sentences on relevance"},
                    },
                    "required": ["title", "source", "date", "summary", "why_relevant"],
                },
            },
        },
        "required": ["findings"],
    },
    "self-improve": {
        "type": "object",
        "properties": {
            "edits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "file": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["file", "content"],
                },
            },
            "skipped": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "issue": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                    "required": ["issue", "reason"],
                },
            },
            "processed_issues": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Issue numbers fully handled in this run.",
            },
        },
        "required": ["edits", "skipped", "processed_issues"],
    },
}


def load_modes(path: Path | None = None) -> dict[str, Mode]:
    """Load modes.

    Resolution order:
    1. If `path` is given, load from that single file (used by tests).
    2. Otherwise: load the package-shipped default (modes.yml), then deep-merge
       any `<wiki-repo>/modes.override.yml` on top. This makes behavior
       atomically upgradable — `pip install pangolin@X` updates every wiki
       without a sync step. Wikis only check in override deltas.

    Additional runtime model-selection overrides (orthogonal to the above):

    - `PANGOLIN_MODELS=path/to/models.yml`: per-mode (provider, model)
      override file. Useful for cost/quality profiles.
    - `PANGOLIN_MODEL_OVERRIDE=<model-id>`: coarse global override —
      replaces every mode's model with the same value.
    """
    import os
    from pangolin.paths import default_modes_yaml

    if path is None:
        raw = yaml.safe_load(default_modes_yaml().read_text())
        # Overlay wiki-repo override if present (optional).
        try:
            from pangolin.core import REPO
            override_path = REPO / "modes.override.yml"
            if override_path.exists():
                override = yaml.safe_load(override_path.read_text()) or {}
                _deep_merge_modes(raw, override)
        except Exception:
            # Tests may import without a git repo; swallow and use package defaults.
            pass
    else:
        raw = yaml.safe_load(path.read_text())

    # Load per-mode overrides (option 1)
    overrides: dict[str, dict] = {}
    cfg_path = os.environ.get("PANGOLIN_MODELS")
    if cfg_path:
        cfg_p = Path(cfg_path)
        if not cfg_p.is_absolute():
            cfg_p = path.parent / cfg_p
        if cfg_p.exists():
            ovr = yaml.safe_load(cfg_p.read_text()) or {}
            overrides = ovr.get("overrides", {}) or {}

    # Legacy global override (option 2)
    global_override = os.environ.get("PANGOLIN_MODEL_OVERRIDE")

    modes = {}
    for name, cfg in raw["modes"].items():
        if global_override:
            cfg["model"] = global_override
        if name in overrides:
            mo = overrides[name]
            if "provider" in mo: cfg["provider"] = mo["provider"]
            if "model" in mo:    cfg["model"]    = mo["model"]
        modes[name] = Mode(
            name=name,
            description=cfg["description"],
            provider=cfg.get("provider", "anthropic"),
            model=cfg.get("model", "claude-sonnet-4-6"),
            execution=cfg.get("execution", "container"),
            network=cfg["network"],
            code_execution=cfg["code_execution"],
            allowed_tools=cfg.get("allowed_tools", []),
            denied_tools=cfg.get("denied_tools", []),
            readable_paths=cfg["readable_paths"],
            writable_paths=cfg["writable_paths"],
            gh_cli=cfg["gh_cli"],
            autonomy=cfg["autonomy"],
            trust_level=cfg["trust_level"],
            container_runtime=cfg.get("container_runtime"),
            quarantine_output=cfg.get("quarantine_output"),
            json_schema=cfg.get("json_schema"),
            egress=cfg.get("egress", "tight"),
        )
    _validate_invariants(modes)
    return modes


def _deep_merge_modes(base: dict, override: dict) -> None:
    """Overlay `override` onto `base` in place. Structure:

        {modes: {<name>: {<field>: value, ...}, ...}}

    Per-mode: existing field values are replaced by override values; fields
    absent from override are untouched. A mode present in override but not
    base is added. A mode absent from override is unchanged.
    """
    over_modes = (override or {}).get("modes") or {}
    base_modes = base.setdefault("modes", {})
    for name, cfg in over_modes.items():
        if name in base_modes and isinstance(cfg, dict):
            base_modes[name].update(cfg)
        else:
            base_modes[name] = cfg


def _validate_invariants(modes: dict[str, Mode]):
    """Enforce security invariants at load time. Fail-closed."""
    for name, m in modes.items():
        if m.trust_level == "untrusted":
            if m.code_execution:
                raise ValueError(f"Mode '{name}': untrusted + code_execution is forbidden")
            if m.gh_cli:
                raise ValueError(f"Mode '{name}': untrusted + gh_cli is forbidden")
            if not m.quarantine_output:
                raise ValueError(f"Mode '{name}': untrusted mode must have quarantine_output")
        if m.execution == "direct" and m.allowed_tools:
            raise ValueError(f"Mode '{name}': direct execution must have empty allowed_tools")
        if m.egress not in ("tight", "loose"):
            raise ValueError(f"Mode '{name}': egress must be 'tight' or 'loose', got '{m.egress}'")
