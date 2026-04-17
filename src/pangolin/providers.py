"""
Provider interface for LLM API calls. Provider-agnostic: Anthropic,
OpenAI-compatible (Scaleway, local), or any future provider.

Each provider implements chat() which handles the tool-call loop:
send messages → get response → if tool_use, execute tool, append result,
repeat until end_turn.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import anthropic


def _strict_schema(schema: dict) -> dict:
    """Add additionalProperties: false to all objects (required by Anthropic)."""
    schema = dict(schema)
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        if "properties" in schema:
            schema["properties"] = {
                k: _strict_schema(v) for k, v in schema["properties"].items()
            }
    if "items" in schema:
        schema["items"] = _strict_schema(schema["items"])
    return schema


@dataclass
class ToolResult:
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class ChatResult:
    text: str
    tool_calls: int
    input_tokens: int
    output_tokens: int
    stop_reason: str


class Provider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    def chat(
        self,
        system: str,
        user: str,
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int = 8192,
        json_schema: dict | None = None,
        tool_executor: Any | None = None,
    ) -> ChatResult:
        """Send a chat request, handle tool-call loop, return final result."""
        ...


class AnthropicProvider(Provider):
    """Anthropic API via the official SDK.

    Auth is auto-detected:
    - If CLAUDE_CODE_OAUTH_TOKEN is set (Claude Max subscription), use OAuth.
      Constant cost via subscription quota, no per-token billing.
    - Otherwise fall back to ANTHROPIC_API_KEY (per-token API billing).

    The `api_key=` constructor argument still works for explicit override.
    """

    def __init__(self, api_key: str | None = None):
        # Auth: fall back to ANTHROPIC_API_KEY.
        #
        # Historical note: we briefly auto-detected `CLAUDE_CODE_OAUTH_TOKEN`
        # and routed via `auth_token=`. Turns out the `/v1/messages`
        # endpoint rejects OAuth tokens with:
        #   "OAuth authentication is currently not supported"
        # OAuth subscription access is available, but only via the
        # separate `claude-agent-sdk` Python package (not the regular
        # `anthropic` SDK). That requires its own Provider class — see
        # Epic 7 in BACKLOG.md. Until then, stick to API key.
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )
        self.auth_mode = "API key"

    def chat(
        self,
        system: str,
        user: str,
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int = 8192,
        json_schema: dict | None = None,
        tool_executor=None,
    ) -> ChatResult:
        model = model or "claude-sonnet-4-6"
        messages = [{"role": "user", "content": user}]
        total_in = 0
        total_out = 0
        tool_call_count = 0
        max_iterations = 50

        # Wrap the system prompt as a single text block with cache_control so
        # Anthropic caches it across iterations of the tool-call loop. The SSOT
        # is large (often >5k tokens) and identical across every iteration,
        # so the cache pays for itself after the first call. Cached tokens
        # cost ~10% of normal input rate.
        cached_system = [
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}},
        ] if system else None

        for iteration in range(max_iterations):
            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": messages,
            }
            if cached_system is not None:
                kwargs["system"] = cached_system
            if tools:
                kwargs["tools"] = tools
            if json_schema:
                # Use Anthropic Structured Outputs (beta as of 2025-11-13):
                # the schema is compiled into a grammar that constrains token
                # generation at inference time. The response is guaranteed to
                # be valid JSON matching the schema — no parser slop, no
                # missing required fields.
                #
                # Drop tools (the model has no other action to take), add the
                # beta header, set the output format. Routed via
                # client.beta.messages.create below.
                kwargs.pop("tools", None)
                kwargs["betas"] = ["structured-outputs-2025-11-13"]
                kwargs["output_format"] = {
                    "type": "json_schema",
                    "schema": _strict_schema(json_schema),
                }

            if "output_format" in kwargs:
                response = self.client.beta.messages.create(**kwargs)
            else:
                response = self.client.messages.create(**kwargs)

            total_in += response.usage.input_tokens
            total_out += response.usage.output_tokens

            # Collect text and tool_use blocks
            text_parts = []
            tool_uses = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)

            if not tool_uses or response.stop_reason == "end_turn" or not tool_executor:
                return ChatResult(
                    text="\n".join(text_parts),
                    tool_calls=tool_call_count,
                    input_tokens=total_in,
                    output_tokens=total_out,
                    stop_reason=response.stop_reason,
                )

            # Execute tool calls
            tool_results = []
            for tu in tool_uses:
                tool_call_count += 1
                result = tool_executor.execute(tu.name, tu.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result.content,
                    "is_error": result.is_error,
                })

            # Append assistant message + tool results for next turn
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        raise RuntimeError(f"Tool-call loop exceeded {max_iterations} iterations")



class OpenAICompatProvider(Provider):
    """OpenAI-compatible API (Scaleway, local servers, etc.)."""

    def __init__(self, base_url: str, api_key: str):
        # Use the openai SDK if available, fall back to anthropic with base_url
        try:
            import openai
            self.client = openai.OpenAI(base_url=base_url, api_key=api_key)
            self._backend = "openai"
        except ImportError:
            # Fall back to raw HTTP
            self._backend = "http"
            self._base_url = base_url
            self._api_key = api_key

    def chat(
        self,
        system: str,
        user: str,
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int = 8192,
        json_schema: dict | None = None,
        tool_executor=None,
    ) -> ChatResult:
        if self._backend != "openai":
            raise NotImplementedError("HTTP backend not implemented yet — pip install openai")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        # Convert Anthropic tool format to OpenAI format
        oai_tools = None
        if tools:
            oai_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                }
                for t in tools
            ]

        response = self.client.chat.completions.create(
            model=model or "qwen3.5-397b",
            messages=messages,
            tools=oai_tools,
            max_tokens=max_tokens,
        )

        choice = response.choices[0]
        return ChatResult(
            text=choice.message.content or "",
            tool_calls=0,  # TODO: implement tool-call loop for OpenAI
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            stop_reason=choice.finish_reason,
        )


def create_provider(name: str, **kwargs) -> Provider:
    """Factory function. Reads config from env if not provided."""
    if name == "anthropic":
        return AnthropicProvider(
            api_key=kwargs.get("api_key") or os.environ.get("ANTHROPIC_API_KEY"),
        )
    elif name == "scaleway":
        return OpenAICompatProvider(
            base_url=kwargs.get("base_url", "https://api.scaleway.ai/v1"),
            api_key=kwargs.get("api_key") or os.environ.get("SCW_SECRET_KEY", ""),
        )
    else:
        raise ValueError(f"Unknown provider: {name}")
