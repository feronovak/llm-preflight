from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

from .eligibility import IncompatibleCatalogTypeError, incompatible_text_smoke_reason
from .images import input_image_parts
from .pricing import valid_token_count
from .providers import PROVIDER_DEFAULTS
from .security import open_public_url, require_http_url

TokenUsage = dict[str, int | None]
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MIN_GENERATION_WINDOW_SECONDS = 0.1
DEFAULT_MAX_OUTPUT_TOKENS = 256
MAX_OBSERVED_MODEL_CHARS = 256
_QWEN_COMBINED_OUTPUT_MODELS = {
    "qwen3.8-max",
    "qwen3.8-max-0902",
    "qwen3.8-flash",
}


def _supports_temperature(model: dict[str, Any]) -> bool:
    explicit = model.get("supports_temperature")
    if explicit is not None:
        return bool(explicit)
    capabilities = model.get("capabilities", {})
    if isinstance(capabilities, dict) and "temperature" in capabilities:
        return bool(capabilities["temperature"])
    provider = model.get("provider")
    model_id = model["model"]
    if provider == "openai":
        return not (
            model_id == "gpt-5.5"
            or model_id.startswith(("gpt-5.5-", "gpt-5.6-", "gpt-6-", "gpt-6.1-"))
        )
    if provider in {"moonshot", "minimax"}:
        return False
    if provider == "anthropic":
        return model_id not in {
            "claude-sonnet-5",
            "claude-sonnet-5-5",
            "claude-haiku-5-5",
            "claude-fable-5",
            "claude-fable-5-1",
            "claude-mythos-5-1",
            "claude-opus-4-8",
            "claude-opus-5",
            "claude-opus-5-5",
        }
    return True


def _provider_options(options: dict[str, Any], provider: str) -> dict[str, Any]:
    configured = options.get("provider_options", {})
    if not isinstance(configured, dict):
        return {}
    provider_keys = set(PROVIDER_DEFAULTS) | {"openai_compatible", "all"}
    if any(key in provider_keys for key in configured):
        merged = dict(configured.get("all", {}))
        merged.update(configured.get(provider, {}))
        return merged
    return dict(configured)


def validate_native_request_options(
    model: dict[str, Any], options: dict[str, Any]
) -> None:
    """Keep native request identity and limits aligned with the shared plan."""
    provider = str(model.get("provider") or "")
    model_id = model.get("model", "")
    strict_openai = provider == "openai" and model_id.startswith(("gpt-6-", "gpt-6.1-"))
    strict_claude = provider == "anthropic" and model_id in {
        "claude-fable-5-1",
        "claude-mythos-5-1",
    }
    if provider == "openai" and model.get("adapter") == "openai_responses":
        supported = {
            "reasoning",
            "text",
            "service_tier",
            "prompt_cache_retention",
            "prompt_cache_key",
        }
        unsupported = _provider_options(options, provider).keys() - supported
        if unsupported:
            raise ValueError(
                "Responses provider_options are unsupported: "
                + ", ".join(sorted(unsupported))
                + "; use the configured prompt and request.max_output_tokens"
            )
    if provider not in {
        "zai",
        "deepseek",
        "qwen",
        "moonshot",
        "minimax",
        "mistral",
        "cohere",
    } and not (strict_openai or strict_claude):
        return
    provider_options = _provider_options(options, provider)
    if {
        "model",
        "messages",
        "stream",
        "stream_options",
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
    } & provider_options.keys():
        raise ValueError(
            "native provider_options cannot override model, messages, streaming or "
            "token limits; use models and request.max_output_tokens"
        )
    if strict_openai:
        if provider_options.get("service_tier", "default") not in {
            "default",
            "standard",
            "auto",
        }:
            raise ValueError(
                "GPT-6 preflight supports standard service-tier pricing only"
            )
        if provider_options.get("prompt_cache_retention", "30m") != "30m":
            raise ValueError("GPT-6 preflight supports 30m cache-write pricing only")
    if strict_claude:
        thinking = provider_options.get("thinking", {"type": "adaptive"})
        if not isinstance(thinking, dict) or thinking.get("type") != "adaptive":
            raise ValueError("Fable/Mythos 5.1 require adaptive reasoning")
        choice = provider_options.get("tool_choice", {"type": "auto"})
        if not isinstance(choice, dict) or choice.get("type") not in {"auto", "none"}:
            raise ValueError("Fable/Mythos 5.1 do not support forced tool choice")
    if provider in {"moonshot", "minimax", "mistral", "cohere"}:
        expected_adapter = (
            "cohere_chat" if provider == "cohere" else "openai_compatible_chat"
        )
        if model.get("adapter") not in {None, expected_adapter}:
            raise ValueError(f"native {provider} requires adapter={expected_adapter}")
        expected_parameter = (
            "max_completion_tokens" if provider == "minimax" else "max_tokens"
        )
        if model.get("max_tokens_parameter", expected_parameter) != expected_parameter:
            raise ValueError(
                f"native {provider} requires max_tokens_parameter={expected_parameter}"
            )
        if options.get("input_images"):
            raise ValueError(
                f"the native {provider} adapter currently supports text only"
            )
        if provider_options.get("service_tier", "standard") not in {"standard", "auto"}:
            raise ValueError("native provider service_tier requires standard pricing")
        if {"tools", "documents", "connectors", "web_search"} & provider_options.keys():
            raise ValueError(
                "native text preflight does not execute tools or hosted retrieval"
            )
    if provider == "moonshot":
        cache_options = provider_options.get("prompt_cache_options", {})
        if (
            not isinstance(cache_options, dict)
            or cache_options.get("mode", "implicit") != "implicit"
            or cache_options.get("ttl", "5m") != "5m"
        ):
            raise ValueError(
                "Kimi snapshot supports implicit 5m cache-write pricing only"
            )
        if "thinking" in provider_options or provider_options.get(
            "reasoning_effort", "max"
        ) not in {"low", "high", "max"}:
            raise ValueError(
                "Kimi K3.1 requires reasoning_effort low, high, or max; remove thinking"
            )
        if {
            "temperature",
            "top_p",
            "n",
            "presence_penalty",
            "frequency_penalty",
        } & provider_options.keys():
            raise ValueError(
                "Kimi K3.1 sampling parameters are fixed; omit provider sampling options"
            )
    if provider == "minimax":
        if provider_options.get("reasoning_split", True) is not True:
            raise ValueError("MiniMax text preflight requires reasoning_split=true")
        thinking = provider_options.get("thinking", {"type": "adaptive"})
        allowed = (
            {"adaptive"}
            if model["model"] == "MiniMax-M3.1-Flash"
            else {"adaptive", "disabled"}
        )
        if not isinstance(thinking, dict) or thinking.get("type") not in allowed:
            raise ValueError("MiniMax reasoning requires a supported thinking type")
        if provider_options.get("reasoning_effort", "max") not in {
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        }:
            raise ValueError("MiniMax reasoning effort is unsupported")
    if provider == "zai" and model.get("model") in {
        "glm-5.3",
        "glm-5.3-flash",
        "glm-5.3-flashx",
    }:
        thinking = provider_options.get("thinking", {"type": "enabled"})
        if not isinstance(thinking, dict) or thinking.get("type") != "enabled":
            raise ValueError("GLM-5.3 models require enabled reasoning")
    if provider != "qwen" or model.get("model") not in _QWEN_COMBINED_OUTPUT_MODELS:
        return
    parameter = model.get("max_tokens_parameter", "max_completion_tokens")
    thinking_disabled = provider_options.get(
        "enable_thinking"
    ) is False and provider_options.get("reasoning_effort") in (None, "none")
    if parameter != "max_completion_tokens" and not (
        parameter == "max_tokens" and thinking_disabled
    ):
        raise ValueError(
            "native Qwen reasoning requires max_tokens_parameter=max_completion_tokens; "
            "max_tokens is safe only with explicitly disabled thinking"
        )


def reported_model(value: Any) -> str | None:
    """The model string a response names, or None when it names none usable.

    A non-string, empty, oversized or non-printable value is not evidence of
    which model answered, so it is dropped rather than repaired.
    """
    if (
        isinstance(value, str)
        and 0 < len(value) <= MAX_OBSERVED_MODEL_CHARS
        and value.isprintable()
    ):
        return value
    return None


def observed_model(values: Iterable[Any]) -> str | list[str] | None:
    """One reported model, the sorted distinct set when they disagree, or None.

    Values may themselves be lists, as a sample's `observed_model` is when its
    events disagreed. Absent or unusable values are skipped, never inferred.
    """
    distinct: set[str] = set()
    for value in values:
        for item in value if isinstance(value, list) else [value]:
            model = reported_model(item)
            if model is not None:
                distinct.add(model)
    if not distinct:
        return None
    return distinct.pop() if len(distinct) == 1 else sorted(distinct)


def _retry_config(options: dict[str, Any]) -> dict[str, Any]:
    configured = options.get("retry", {})
    if configured is True:
        configured = {}
    if not isinstance(configured, dict):
        configured = {}
    return {
        "max_attempts": max(1, int(configured.get("max_attempts", 2))),
        "initial_delay_seconds": max(
            0.0, float(configured.get("initial_delay_seconds", 0.25))
        ),
        "max_delay_seconds": max(0.0, float(configured.get("max_delay_seconds", 4))),
        "backoff_multiplier": max(1.0, float(configured.get("backoff_multiplier", 2))),
        "jitter_seconds": max(0.0, float(configured.get("jitter_seconds", 0.1))),
        "retry_on": set(
            configured.get(
                "retry_on",
                ["rate_limit", "timeout", "transient_provider", "network"],
            )
        ),
    }


def _classify_failure(error: str, status_code: int | None = None) -> str:
    folded = error.casefold()
    if status_code == 404:
        return "not_found"
    if "environment variable" in folded or status_code in {401, 403}:
        return "credentials"
    if "unsupported" in folded and "parameter" in folded:
        return "unsupported_parameter"
    if status_code == 429 or "rate limit" in folded or "rate limited" in folded:
        return "rate_limit"
    if status_code == 408 or "timed out" in folded or "timeout" in folded:
        return "timeout"
    if status_code is not None and 500 <= status_code <= 599:
        return "transient_provider"
    return "provider_error"


def _classify_exception(exc: Exception) -> str:
    """Classify local transport errors without relying on OS message text."""
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, OSError):
        return "network"
    return _classify_failure(str(exc))


def _retry_delay(config: dict[str, Any], retry_index: int) -> float:
    delay = config["initial_delay_seconds"] * (
        config["backoff_multiplier"] ** max(0, retry_index - 1)
    )
    delay = min(delay, config["max_delay_seconds"])
    jitter = min(config["jitter_seconds"], config["max_delay_seconds"] - delay)
    # Retry jitter is not a secret or a token. Bandit B311 flags random.uniform
    # as a cryptographic generator; without the suppression, `make audit` fails.
    return delay + random.uniform(0, jitter) if jitter else delay  # nosec B311


class ProviderClient(ABC):
    """Provider adapter contract.

    New providers only need to define endpoint/auth, request translation, and
    streamed event translation. The runner and metrics remain provider-neutral.
    """

    def __init__(self, model: dict[str, Any], timeout: float):
        self.model = model
        self.timeout = timeout

    @abstractmethod
    def endpoint(self) -> str:
        pass

    @abstractmethod
    def headers(self, api_key: str | None) -> dict[str, str]:
        pass

    @abstractmethod
    def body(self, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        pass

    @abstractmethod
    def parse_event(self, event: dict[str, Any]) -> tuple[str | None, TokenUsage]:
        """Return a text delta and any input/output token usage."""

    requires_complete_stream = False

    def terminal_event(self, event: dict[str, Any]) -> bool:
        return False

    def event_model(self, event: dict[str, Any]) -> Any:
        """The model an event says answered; OpenAI-compatible chunks name it."""
        return event.get("model")

    def run(self, prompt: str, request_options: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        key_env = self.model.get("api_key_env")
        api_key = os.environ.get(key_env) if key_env else None
        if key_env and not api_key:
            return self._failure(
                started,
                f"environment variable {key_env!r} is not set",
                attempts=1,
                retry_reasons=[],
                failure_category="credentials",
            )

        retry = _retry_config(request_options)
        retry_reasons: list[str] = []
        last_error = ""
        last_category = "provider_error"
        for attempt in range(1, retry["max_attempts"] + 1):
            attempt_started = time.perf_counter()
            first_token_at: float | None = None
            content: list[str] = []
            usage: dict[str, int] = {}
            models: list[Any] = []
            completed = False
            try:
                endpoint = self.endpoint()
                require_http_url(endpoint)
                request = urllib.request.Request(
                    endpoint,
                    data=json.dumps(self.body(prompt, request_options)).encode(),
                    headers={
                        "Content-Type": "application/json",
                        **self.headers(api_key),
                        **self.model.get("headers", {}),
                    },
                    method="POST",
                )
                with open_public_url(request, timeout=self.timeout) as response:
                    response_bytes = 0
                    for raw_line in response:
                        response_bytes += len(raw_line)
                        if response_bytes > MAX_RESPONSE_BYTES:
                            raise ValueError(
                                "provider response exceeded the 8 MiB safety limit"
                            )
                        line = raw_line.decode("utf-8", errors="replace").strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if not payload or payload == "[DONE]":
                            continue
                        event = json.loads(payload)
                        if not isinstance(event, dict):
                            raise TypeError("provider stream event must be an object")
                        text, event_usage = self.parse_event(event)
                        completed = completed or self.terminal_event(event)
                        models.append(self.event_model(event))
                        usage.update(
                            {
                                key: value
                                for key, value in event_usage.items()
                                if value is not None
                            }
                        )
                        if text is not None and not isinstance(text, str):
                            raise ValueError("provider text delta must be a string")
                        if text:
                            if first_token_at is None:
                                first_token_at = time.perf_counter()
                            content.append(text)
                    if self.requires_complete_stream and not completed:
                        raise ValueError(
                            "provider stream ended before a complete response"
                        )
            except urllib.error.HTTPError as exc:
                detail = exc.read(2000).decode("utf-8", errors="replace")
                last_error = f"HTTP {exc.code}: {detail}"
                last_category = _classify_failure(last_error, exc.code)
            except (
                OSError,
                TimeoutError,
                json.JSONDecodeError,
                ValueError,
                TypeError,
            ) as exc:
                last_error = str(exc)
                last_category = _classify_exception(exc)
            else:
                finished = time.perf_counter()
                output_tokens = usage.get("output_tokens")
                generation_seconds = (
                    finished - first_token_at if first_token_at else None
                )
                # Some providers buffer the whole body server-side and burst
                # it in one or a few chunks at the end. The post-TTFT window
                # is then transport time, not generation speed, and would
                # inflate throughput by orders of magnitude. Report a rate
                # only when the stream was observably incremental.
                throughput = (
                    output_tokens / generation_seconds
                    if valid_token_count(output_tokens)
                    and generation_seconds is not None
                    and generation_seconds >= MIN_GENERATION_WINDOW_SECONDS
                    and len(content) >= 2
                    else None
                )
                return {
                    "ok": True,
                    "latency_seconds": finished - attempt_started,
                    "ttft_seconds": first_token_at - attempt_started
                    if first_token_at
                    else None,
                    "output_tokens_per_second": throughput,
                    "input_tokens": usage.get("input_tokens"),
                    "cached_input_tokens": usage.get("cached_input_tokens"),
                    **(
                        {"cache_write_input_tokens": usage["cache_write_input_tokens"]}
                        if "cache_write_input_tokens" in usage
                        else {}
                    ),
                    "output_tokens": output_tokens,
                    "response_chars": sum(map(len, content)),
                    "response": "".join(content),
                    "observed_model": observed_model(models),
                    "error": None,
                    "attempts": attempt,
                    "retry_count": attempt - 1,
                    "retry_reasons": retry_reasons,
                    "failure_category": None,
                }

            if (
                last_category not in retry["retry_on"]
                or attempt == retry["max_attempts"]
            ):
                return self._failure(
                    started,
                    last_error,
                    attempts=attempt,
                    retry_reasons=retry_reasons,
                    failure_category=last_category,
                )
            retry_reasons.append(last_category)
            delay = _retry_delay(retry, attempt)
            if delay:
                time.sleep(delay)

        return self._failure(
            started,
            last_error,
            attempts=retry["max_attempts"],
            retry_reasons=retry_reasons,
            failure_category=last_category,
        )

    @staticmethod
    def _failure(
        started: float,
        error: str,
        attempts: int = 1,
        retry_reasons: list[str] | None = None,
        failure_category: str | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "latency_seconds": time.perf_counter() - started,
            "ttft_seconds": None,
            "output_tokens_per_second": None,
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "response_chars": 0,
            "response": "",
            "observed_model": None,
            "error": error,
            "attempts": attempts,
            "retry_count": max(0, attempts - 1),
            "retry_reasons": retry_reasons or [],
            "failure_category": failure_category or _classify_failure(error),
        }


class OpenAICompatibleClient(ProviderClient):
    def endpoint(self) -> str:
        return self.model["base_url"].rstrip("/") + "/chat/completions"

    def headers(self, api_key: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def body(self, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        validate_native_request_options(self.model, options)
        messages = []
        if options.get("system_prompt"):
            messages.append({"role": "system", "content": options["system_prompt"]})
        content: str | list[dict[str, Any]] = prompt
        image_parts = input_image_parts(options)
        if image_parts:
            content = [
                {"type": "text", "text": prompt},
                *[
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image['mime_type']};base64,{image['data']}"
                        },
                    }
                    for image in image_parts
                ],
            ]
        messages.append({"role": "user", "content": content})
        body: dict[str, Any] = {
            "model": self.model["model"],
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if "temperature" in options and _supports_temperature(self.model):
            body["temperature"] = options["temperature"]
        limit = options.get(
            "max_output_tokens", options.get("max_tokens", DEFAULT_MAX_OUTPUT_TOKENS)
        )
        parameter = self.model.get("max_tokens_parameter", "max_tokens")
        body[parameter] = limit
        body.update(
            _provider_options(options, self.model.get("provider", "openai_compatible"))
        )
        return body

    def parse_event(self, event: dict[str, Any]) -> tuple[str | None, TokenUsage]:
        usage = event.get("usage") or {}
        normalized = {
            "input_tokens": usage.get("prompt_tokens"),
            "cached_input_tokens": (usage.get("prompt_tokens_details") or {}).get(
                "cached_tokens"
            ),
            "output_tokens": usage.get("completion_tokens"),
        }
        if (
            self.model.get("provider") == "deepseek"
            and normalized["cached_input_tokens"] is None
        ):
            normalized["cached_input_tokens"] = usage.get("prompt_cache_hit_tokens")
        details = usage.get("prompt_tokens_details") or {}
        if "cache_write_tokens" in details:
            normalized["cache_write_input_tokens"] = details["cache_write_tokens"]
        choices = event.get("choices") or []
        text = (choices[0].get("delta") or {}).get("content") if choices else None
        return text, normalized


def _stream_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError("provider stream contained a malformed object")
    return value


class NativeTextClient(OpenAICompatibleClient):
    """Reviewed native Chat Completions routes with explicit completion evidence."""

    requires_complete_stream = True

    def body(self, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        body = super().body(prompt, options)
        if self.model.get("provider") == "minimax":
            body.setdefault("reasoning_split", True)
        if self.model.get("provider") == "mistral":
            body.pop("stream_options", None)
        return body

    def parse_event(self, event: dict[str, Any]) -> tuple[str | None, TokenUsage]:
        if (
            not isinstance(event, dict)
            or event.get("error")
            or event.get("type") == "error"
        ):
            raise ValueError("native provider returned an error event")
        choices = event.get("choices", [])
        if not isinstance(choices, list) or any(
            not isinstance(c, dict) for c in choices
        ):
            raise ValueError("native provider returned malformed choices")
        if any(c.get("finish_reason") not in {None, "stop"} for c in choices):
            raise ValueError("native provider did not finish a complete text response")
        if any(not isinstance(c.get("delta", {}), dict) for c in choices):
            raise ValueError("native provider returned a malformed text delta")
        if event.get("usage") is not None and not isinstance(event["usage"], dict):
            raise ValueError("native provider returned malformed usage")
        text, usage = super().parse_event(event)
        if self.model.get("provider") == "mistral" and isinstance(text, list):
            final_text = []
            for chunk in text:
                if not isinstance(chunk, dict):
                    raise TypeError("Mistral content chunk must be an object")
                kind = chunk.get("type", "text")
                if kind == "thinking":
                    continue
                if kind != "text" or not isinstance(chunk.get("text"), str):
                    raise ValueError(
                        "Mistral returned an unsupported text content chunk"
                    )
                final_text.append(chunk["text"])
            text = "".join(final_text)
        if (
            self.model.get("provider") == "mistral"
            and usage.get("cached_input_tokens") is None
        ):
            raw = event.get("usage") or {}
            usage["cached_input_tokens"] = (raw.get("prompt_token_details") or {}).get(
                "cached_tokens", raw.get("num_cached_tokens")
            )
        return text, usage

    def terminal_event(self, event: dict[str, Any]) -> bool:
        return any(c.get("finish_reason") == "stop" for c in event.get("choices", []))


class CohereClient(NativeTextClient):
    """Cohere v2 Chat SSE, normalized using billed rather than injected tokens."""

    def endpoint(self) -> str:
        return self.model["base_url"].rstrip("/") + "/chat"

    def body(self, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        body = super().body(prompt, options)
        body.pop("stream_options", None)
        return body

    def parse_event(self, event: dict[str, Any]) -> tuple[str | None, TokenUsage]:
        if (
            not isinstance(event, dict)
            or event.get("error")
            or event.get("type") == "error"
        ):
            raise ValueError("Cohere returned an error event")
        delta = event.get("delta") or {}
        if not isinstance(delta, dict):
            raise TypeError("Cohere returned a malformed delta")
        if event.get("type") == "content-delta":
            message = _stream_object(delta.get("message"))
            content = _stream_object(message.get("content"))
            return content.get("text"), {}
        if event.get("type") == "message-end":
            if delta.get("finish_reason") != "COMPLETE":
                raise ValueError("Cohere did not finish a complete text response")
            raw = _stream_object(delta.get("usage"))
            billed = _stream_object(raw.get("billed_units"))
            return None, {
                "input_tokens": billed.get("input_tokens"),
                "output_tokens": billed.get("output_tokens"),
            }
        return None, {}

    def terminal_event(self, event: dict[str, Any]) -> bool:
        return event.get("type") == "message-end"


class ZaiClient(NativeTextClient):
    """Z.ai's native Chat Completion protocol, with usage in the final event."""

    def __init__(self, model: dict[str, Any], timeout: float):
        super().__init__(model, timeout)
        self.requires_complete_stream = model["model"] in {
            "glm-5.3-flash",
            "glm-5.3-flashx",
        }

    def body(self, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        if self.model["model"] == "glm-5.3" and options.get("input_images"):
            raise ValueError("GLM-5.3 is text-only; remove input_images")
        body = super().body(prompt, options)
        body.pop("stream_options", None)
        if self.model["model"] == "glm-5.3":
            thinking = body.get("thinking", {})
            if (
                not isinstance(thinking, dict)
                or thinking.get("type", "enabled") != "enabled"
            ):
                raise ValueError("GLM-5.3 requires enabled reasoning")
            if body.get("reasoning_effort", "max") not in {"low", "high", "max"}:
                raise ValueError("GLM-5.3 reasoning effort must be low, high, or max")
        return body


class OpenAIResponsesClient(OpenAICompatibleClient):
    """OpenAI's Responses endpoint, used first for capability probes."""

    def endpoint(self) -> str:
        return self.model["base_url"].rstrip("/") + "/responses"

    def body(self, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        validate_native_request_options(self.model, options)
        if options.get("input_images"):
            raise ValueError(
                "the OpenAI Responses adapter does not support input_images"
            )
        body: dict[str, Any] = {
            "model": self.model["model"],
            "input": prompt,
            "store": False,
        }
        if options.get("system_prompt"):
            body["instructions"] = options["system_prompt"]
        limit = options.get(
            "max_output_tokens", options.get("max_tokens", DEFAULT_MAX_OUTPUT_TOKENS)
        )
        body["max_output_tokens"] = limit
        body.update(_provider_options(options, "openai"))
        return body

    def run(self, prompt: str, request_options: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        key_env = self.model.get("api_key_env")
        api_key = os.environ.get(key_env) if key_env else None
        if key_env and not api_key:
            return self._failure(
                started, f"environment variable {key_env!r} is not set"
            )
        retry = _retry_config(request_options)
        retry_reasons: list[str] = []
        last_error = ""
        last_category = "provider_error"
        for attempt in range(1, retry["max_attempts"] + 1):
            attempt_started = time.perf_counter()
            try:
                endpoint = self.endpoint()
                require_http_url(endpoint)
                request = urllib.request.Request(
                    endpoint,
                    data=json.dumps(self.body(prompt, request_options)).encode(),
                    headers={
                        "Content-Type": "application/json",
                        **self.headers(api_key),
                        **self.model.get("headers", {}),
                    },
                    method="POST",
                )
                with open_public_url(request, timeout=self.timeout) as response:
                    body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ValueError(
                        "provider response exceeded the 8 MiB safety limit"
                    )
                payload = _stream_object(json.loads(body))
                status = payload.get("status")
                requires_status = self.model.get("provider") == "openai" and self.model[
                    "model"
                ].startswith(("gpt-6-", "gpt-6.1-"))
                if payload.get("error") or (
                    status != "completed" and (status is not None or requires_status)
                ):
                    raise ValueError(
                        "Responses API did not finish a complete text response"
                    )
                usage = _stream_object(payload.get("usage"))
                input_details = _stream_object(usage.get("input_tokens_details"))
                text = payload.get("output_text")
                if text is not None and not isinstance(text, str):
                    raise TypeError("Responses API returned malformed output text")
                text = text or ""
                if not text:
                    output_items = payload.get("output", [])
                    if not isinstance(output_items, list):
                        raise TypeError("Responses API returned malformed output items")
                    for output in output_items:
                        output = _stream_object(output)
                        content_items = output.get("content", [])
                        if not isinstance(content_items, list):
                            raise TypeError("Responses API returned malformed content")
                        for content in content_items:
                            content = _stream_object(content)
                            if content.get("type") in {"output_text", "text"}:
                                chunk = content.get("text")
                                if not isinstance(chunk, str):
                                    raise TypeError(
                                        "Responses API returned malformed text"
                                    )
                                text += chunk
            except urllib.error.HTTPError as exc:
                detail = exc.read(2000).decode("utf-8", errors="replace")
                last_error = f"HTTP {exc.code}: {detail}"
                last_category = _classify_failure(last_error, exc.code)
            except (
                OSError,
                TimeoutError,
                json.JSONDecodeError,
                ValueError,
                TypeError,
            ) as exc:
                last_error = str(exc)
                last_category = _classify_exception(exc)
            else:
                finished = time.perf_counter()
                return {
                    "ok": bool(text),
                    "latency_seconds": finished - attempt_started,
                    "ttft_seconds": None,
                    "output_tokens_per_second": None,
                    "input_tokens": usage.get("input_tokens"),
                    "cached_input_tokens": input_details.get("cached_tokens"),
                    **(
                        {
                            "cache_write_input_tokens": input_details[
                                "cache_write_tokens"
                            ]
                        }
                        if "cache_write_tokens" in input_details
                        else {}
                    ),
                    "output_tokens": usage.get("output_tokens"),
                    "response_chars": len(text),
                    "response": text,
                    "observed_model": observed_model([payload.get("model")]),
                    "error": None if text else "Responses API returned no text output",
                    "attempts": attempt,
                    "retry_count": attempt - 1,
                    "retry_reasons": retry_reasons,
                    "failure_category": None if text else "provider_error",
                }
            if (
                last_category not in retry["retry_on"]
                or attempt == retry["max_attempts"]
            ):
                return self._failure(
                    started, last_error, attempt, retry_reasons, last_category
                )
            retry_reasons.append(last_category)
            delay = _retry_delay(retry, attempt)
            if delay:
                time.sleep(delay)
        return self._failure(
            started, last_error, retry["max_attempts"], retry_reasons, last_category
        )


class AnthropicClient(ProviderClient):
    def __init__(self, model: dict[str, Any], timeout: float):
        super().__init__(model, timeout)
        self.requires_complete_stream = model["model"] in {
            "claude-fable-5-1",
            "claude-mythos-5-1",
        }

    def terminal_event(self, event: dict[str, Any]) -> bool:
        return event.get("type") == "message_stop"

    def endpoint(self) -> str:
        return self.model["base_url"].rstrip("/") + "/messages"

    def headers(self, api_key: str | None) -> dict[str, str]:
        return {
            "x-api-key": api_key or "",
            "anthropic-version": self.model.get("api_version", "2023-06-01"),
        }

    def body(self, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        validate_native_request_options(self.model, options)
        if options.get("input_images"):
            raise ValueError("the Anthropic adapter does not support input_images")
        body: dict[str, Any] = {
            "model": self.model["model"],
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "max_tokens": options.get(
                "max_output_tokens", options.get("max_tokens", 256)
            ),
        }
        if "temperature" in options and _supports_temperature(self.model):
            body["temperature"] = options["temperature"]
        if options.get("system_prompt"):
            body["system"] = options["system_prompt"]
        body.update(_provider_options(options, "anthropic"))
        return body

    def parse_event(self, event: dict[str, Any]) -> tuple[str | None, TokenUsage]:
        if event.get("type") == "error":
            raise ValueError("Anthropic returned a provider error event")
        if self.requires_complete_stream and event.get("type") == "message_delta":
            reason = (event.get("delta") or {}).get("stop_reason")
            if reason not in {None, "end_turn", "stop_sequence"}:
                raise ValueError("Anthropic did not finish a complete text response")
        usage = event.get("usage") or (event.get("message") or {}).get("usage") or {}
        # Anthropic's input count excludes both cache reads and writes; our
        # normalized count includes them for partition costing and price bands.
        uncached = usage.get("input_tokens")
        cached = usage.get("cache_read_input_tokens", 0)
        written = usage.get("cache_creation_input_tokens", 0)
        total_input = (
            int(uncached) + int(cached) + int(written)
            if valid_token_count(uncached)
            and valid_token_count(cached)
            and valid_token_count(written)
            else None
        )
        normalized = {
            "input_tokens": total_input,
            "cached_input_tokens": usage.get("cache_read_input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }
        if "cache_creation_input_tokens" in usage:
            normalized["cache_write_input_tokens"] = usage[
                "cache_creation_input_tokens"
            ]
        delta = event.get("delta") or {}
        return delta.get("text"), normalized

    def event_model(self, event: dict[str, Any]) -> Any:
        """Only `message_start` names the model, inside its message."""
        message = event.get("message")
        return message.get("model") if isinstance(message, dict) else None


class GeminiClient(ProviderClient):
    def endpoint(self) -> str:
        model = self.model["model"]
        return (
            self.model["base_url"].rstrip("/")
            + f"/models/{model}:streamGenerateContent?alt=sse"
        )

    def headers(self, api_key: str | None) -> dict[str, str]:
        return {"x-goog-api-key": api_key or ""}

    def body(self, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        parts: list[dict[str, Any]] = [{"text": prompt}]
        parts.extend(
            {
                "inlineData": {
                    "mimeType": image["mime_type"],
                    "data": image["data"],
                }
            }
            for image in input_image_parts(options)
        )
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {},
        }
        generation = body["generationConfig"]
        if "temperature" in options and _supports_temperature(self.model):
            generation["temperature"] = options["temperature"]
        limit = options.get(
            "max_output_tokens", options.get("max_tokens", DEFAULT_MAX_OUTPUT_TOKENS)
        )
        generation["maxOutputTokens"] = limit
        if options.get("system_prompt"):
            body["systemInstruction"] = {"parts": [{"text": options["system_prompt"]}]}
        provider_options = _provider_options(options, "gemini")
        provider_generation = provider_options.pop("generationConfig", {})
        if provider_generation.get("maxOutputTokens", limit) != limit:
            raise ValueError(
                "set request.max_output_tokens instead of overriding "
                "generationConfig.maxOutputTokens; it must match the planned budget"
            )
        generation.update(provider_generation)
        if self.model["model"] == "gemini-4-argon":
            for parameter in ("temperature", "topP", "topK"):
                generation.pop(parameter, None)
            if limit > 65_536:
                raise ValueError(
                    "Gemini 4 synchronous output is limited to 65536 tokens"
                )
            if "cachedContent" in provider_options:
                raise ValueError("Gemini 4 supports implicit caching only")
            thinking = generation.get("thinkingConfig", {})
            if not isinstance(thinking, dict):
                raise ValueError("Gemini 4 thinkingConfig must be an object")
            if thinking.get("thinkingLevel", "MEDIUM") not in ("LOW", "MEDIUM", "HIGH"):
                raise ValueError("Gemini 4 thinkingLevel must be LOW, MEDIUM, HIGH")
        body.update(provider_options)
        return body

    def parse_event(self, event: dict[str, Any]) -> tuple[str | None, TokenUsage]:
        usage = event.get("usageMetadata") or {}
        output_tokens = usage.get("candidatesTokenCount")
        thoughts = usage.get("thoughtsTokenCount", 0)
        if valid_token_count(output_tokens):
            # An omitted optional reasoning count means no reported reasoning.
            # Explicit malformed components remain invalid evidence, without coercion.
            output_tokens = (
                int(output_tokens) + int(thoughts)
                if valid_token_count(thoughts)
                else thoughts
            )
        normalized = {
            "input_tokens": usage.get("promptTokenCount"),
            "output_tokens": output_tokens,
        }
        if usage.get("cachedContentTokenCount") is not None:
            normalized["cached_input_tokens"] = usage["cachedContentTokenCount"]
        candidates = event.get("candidates") or []
        parts = (
            ((candidates[0].get("content") or {}).get("parts") or [])
            if candidates
            else []
        )
        text = (
            "".join(part.get("text", "") for part in parts if not part.get("thought"))
            or None
        )
        return text, normalized

    def event_model(self, event: dict[str, Any]) -> Any:
        """Each chunk names the serving model version."""
        return event.get("modelVersion")


class MockClient(ProviderClient):
    def endpoint(self) -> str:
        return self.model["base_url"]

    def headers(self, api_key: str | None) -> dict[str, str]:
        return {}

    def body(self, prompt: str, options: dict[str, Any]) -> dict[str, Any]:
        return {"prompt": prompt, **options}

    def parse_event(self, event: dict[str, Any]) -> tuple[str | None, TokenUsage]:
        return event.get("text"), event.get("usage", {})

    def run(self, prompt: str, request_options: dict[str, Any]) -> dict[str, Any]:
        input_image_parts(request_options)
        response = str(
            self.model.get("response", request_options.get("response", "ok"))
        )
        input_tokens = max(1, len(prompt.split()))
        output_tokens = max(1, len(response.split()))
        return {
            "ok": True,
            "latency_seconds": float(self.model.get("latency_seconds", 0.001)),
            "ttft_seconds": float(self.model.get("ttft_seconds", 0.001)),
            "output_tokens_per_second": output_tokens
            / float(self.model.get("latency_seconds", 0.001)),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "response_chars": len(response),
            "response": response,
            # The mock is not a provider; it reports no model.
            "observed_model": None,
            "error": None,
        }


def create_client(model: dict[str, Any], timeout: float) -> ProviderClient:
    provider = model.get("provider", "openai_compatible")
    defaults = PROVIDER_DEFAULTS.get(provider, {})
    resolved = {**defaults, **model}
    if provider == "qwen" and resolved.get("model") in _QWEN_COMBINED_OUTPUT_MODELS:
        # Model Studio's max_tokens excludes reasoning on these models.
        resolved.setdefault("max_tokens_parameter", "max_completion_tokens")
    if "base_url" not in resolved:
        raise ValueError(
            f"model {model.get('name', model.get('model'))!r} requires base_url "
            f"for provider {provider!r}"
        )
    require_http_url(resolved["base_url"], resolve_host=False)
    if provider in {"moonshot", "minimax", "mistral", "cohere"}:
        validate_native_request_options(resolved, {})
    adapters: dict[str, Any] = {
        "openai": OpenAICompatibleClient,
        "openrouter": OpenAICompatibleClient,
        "xai": OpenAICompatibleClient,
        "openai_compatible": OpenAICompatibleClient,
        "deepseek": OpenAICompatibleClient,
        "qwen": OpenAICompatibleClient,
        "zai": ZaiClient,
        "moonshot": NativeTextClient,
        "minimax": NativeTextClient,
        "mistral": NativeTextClient,
        "cohere": CohereClient,
        "anthropic": AnthropicClient,
        "gemini": GeminiClient,
        "mock": MockClient,
    }
    if incompatible_text_smoke_reason(resolved):
        raise IncompatibleCatalogTypeError(
            "typed-decision and other non-text catalogue types are incompatible "
            "with the text smoke adapter"
        )
    try:
        adapter = (
            OpenAIResponsesClient
            if resolved.get("adapter") == "openai_responses"
            else adapters[provider]
        )
    except KeyError as exc:
        raise ValueError(
            f"unsupported provider {provider!r}; choose {', '.join(sorted(adapters))}"
        ) from exc
    return adapter(resolved, timeout)
