"""Provider-neutral model client used by the pipeline, and its Anthropic implementation.

The pipeline only sees `LLMClient`: one JSON-schema-constrained completion per call. Tests and the offline
demo mode swap in `app.ai.fake.FakeLLM` through `app.state.llm_factory`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic
from anthropic import AsyncAnthropic

# Server-side refusal fallback, "default" routing (Claude API). Only sent for models that support it.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = frozenset({"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"})
NO_EFFORT_MODELS = frozenset({"claude-haiku-4-5"})


@dataclass
class Block:
    """A text block of the user message. ``cache`` marks a prompt-cache breakpoint after this block."""

    text: str
    cache: bool = False


@dataclass
class LLMRequest:
    stage: str
    model: str
    system: str
    blocks: list[Block]
    schema: dict[str, Any]
    effort: str = "medium"
    max_tokens: int = 32_000


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class LLMResult:
    data: dict[str, Any]
    usage: Usage
    model: str
    stop_reason: str | None = None
    request_id: str | None = None
    duration_ms: int = 0


# ---- errors -------------------------------------------------------------------------------------


@dataclass
class LLMError(Exception):
    code: str = "provider_error"
    message: str = "The AI request failed."
    usage: Usage | None = None  # set when tokens were billed before the failure
    model: str | None = None
    request_id: str | None = None
    retry_after: int | None = None
    duration_ms: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def key_rejected() -> LLMError:
    return LLMError("key_rejected", "Anthropic rejected this API key. Check it in Account → AI, or replace it.")


def _map_api_error(exc: Exception) -> LLMError:
    request_id = getattr(exc, "request_id", None)
    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        error = key_rejected()
    elif isinstance(exc, anthropic.RateLimitError):
        header = exc.response.headers.get("retry-after", "")
        error = LLMError("rate_limited", "Anthropic is rate-limiting this API key. Wait a minute and retry.",
                         retry_after=int(header) if header.isdigit() else None)
    elif isinstance(exc, anthropic.NotFoundError):
        error = LLMError("model_unavailable", "This API key can't use the selected model. Choose another model in "
                                              "Account → AI, or ask an admin.")
    elif isinstance(exc, anthropic.BadRequestError):
        text = str(getattr(exc, "message", exc)).lower()
        if "credit balance" in text or "billing" in text:
            error = LLMError("out_of_credit", "This API key's Anthropic account is out of credit. Add credit in the "
                                              "Anthropic Console, then retry.")
        else:
            error = LLMError("bad_request", f"Anthropic rejected the request: {getattr(exc, 'message', exc)}")
    elif isinstance(exc, anthropic.APIConnectionError):
        error = LLMError("provider_unavailable", "Couldn't reach Anthropic. Check the connection and retry.")
    else:
        error = LLMError("provider_unavailable", "Anthropic is temporarily unavailable. Retry in a few minutes.")
    error.request_id = request_id
    return error


class LLMClient(Protocol):
    async def verify(self) -> None:
        """Raise LLMError if the key can't be used. Must not spend tokens."""

    async def complete(self, request: LLMRequest) -> LLMResult:
        """One completion constrained to ``request.schema``; returns the parsed JSON object."""


class AnthropicLLM:
    def __init__(self, api_key: str, *, timeout: float = 180.0) -> None:
        # Always pass the key explicitly so the SDK never falls back to ambient credentials.
        self._client = AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=2)

    async def verify(self) -> None:
        try:
            await self._client.models.list(limit=1)  # a Models API call uses no tokens
        except anthropic.APIError as exc:
            raise _map_api_error(exc) from exc

    async def complete(self, request: LLMRequest) -> LLMResult:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": request.schema}}
        if request.model not in NO_EFFORT_MODELS:
            output_config["effort"] = request.effort
        kwargs: dict[str, Any] = {}
        if request.model in FALLBACK_MODELS:
            kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
        content = [
            {"type": "text", "text": b.text, **({"cache_control": {"type": "ephemeral"}} if b.cache else {})}
            for b in request.blocks
        ]
        system = [{"type": "text", "text": request.system, "cache_control": {"type": "ephemeral"}}]

        started = time.monotonic()
        try:
            async with self._client.beta.messages.stream(
                model=request.model,
                max_tokens=request.max_tokens,
                system=system,  # type: ignore[arg-type]
                messages=[{"role": "user", "content": content}],  # type: ignore[list-item]
                output_config=output_config,  # type: ignore[arg-type]
                **kwargs,
            ) as stream:
                message = await stream.get_final_message()
                request_id = stream.request_id
        except anthropic.APIError as exc:
            error = _map_api_error(exc)
            error.model = request.model
            error.duration_ms = int((time.monotonic() - started) * 1000)
            raise error from exc
        duration = int((time.monotonic() - started) * 1000)

        u = message.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read_tokens=u.cache_read_input_tokens or 0,
            cache_write_tokens=u.cache_creation_input_tokens or 0,
        )
        served = message.model or request.model
        common = {"usage": usage, "model": served, "request_id": request_id, "duration_ms": duration}
        if message.stop_reason == "refusal":
            category = getattr(message.stop_details, "category", None) if message.stop_details else None
            raise LLMError("refused", "The model declined this request. Try rephrasing your instructions.",
                           details={"category": category}, **common)
        if message.stop_reason == "max_tokens":
            raise LLMError("truncated", "The response was cut off before it finished. Retry, or shorten the posting.",
                           **common)
        text = "".join(block.text for block in message.content if block.type == "text")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise LLMError("bad_output", "The model returned malformed output. Retry.", **common) from None
        if not isinstance(data, dict):
            raise LLMError("bad_output", "The model returned an unexpected shape. Retry.", **common)
        return LLMResult(data=data, stop_reason=message.stop_reason, **common)
