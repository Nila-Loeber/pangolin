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


def load_modes(path: Path) -> dict[str, Mode]:
    """Load modes from modes.yml.

    Two override mechanisms (per-mode wins over global if both set):

    1. `PANGOLIN_MODELS=path/to/models.yml`: load per-mode (provider, model)
       overrides from a YAML file. Modes not listed keep modes.yml defaults.
       Useful for switching between cost/quality profiles (e.g.
       `models.test.yml` puts cheap-but-OK modes on Haiku for E2E flow
       testing while keeping triage/self-improve on Sonnet for reasoning).
       Forward-compatible with non-Anthropic providers (e.g. Scaleway).

    2. `PANGOLIN_MODEL_OVERRIDE=<model-id>`: legacy global override —
       replaces every mode's model with the same value. Coarser; kept
       for the simplest "just throw Haiku at everything" path.
    """
    import os
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
        )
    _validate_invariants(modes)
    return modes


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
