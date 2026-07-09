from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any

from .client import PROVIDER_DEFAULTS
from .pricing import apply_public_pricing
from .security import require_http_url


def _get_json(
    url: str, key_env: str | None, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    require_http_url(url)
    key = os.environ.get(key_env) if key_env else None
    if key_env and not key:
        raise ValueError(f"environment variable {key_env!r} is not set")
    request_headers = dict(headers or {})
    if key:
        request_headers.setdefault("Authorization", f"Bearer {key}")
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
        return json.load(response)


def _base(source: dict[str, Any]) -> dict[str, Any]:
    provider = source["provider"]
    return {**PROVIDER_DEFAULTS.get(provider, {}), **source}


def _openai(source: dict[str, Any]) -> list[dict[str, Any]]:
    config = _base(source)
    payload = _get_json(
        config["base_url"].rstrip("/") + "/models",
        config.get("api_key_env"),
        config.get("headers"),
    )
    return [
        {
            "name": item["id"],
            "provider": source["provider"],
            "model": item["id"],
            "created": item.get("created"),
            "owned_by": item.get("owned_by"),
            "capabilities": {"reasoning": None},
            "catalog_metadata": item,
        }
        for item in payload.get("data", [])
    ]


def _anthropic(source: dict[str, Any]) -> list[dict[str, Any]]:
    config = _base(source)
    headers = {
        "x-api-key": os.environ.get(config.get("api_key_env", ""), ""),
        "anthropic-version": config.get("api_version", "2023-06-01"),
        **config.get("headers", {}),
    }
    payload = _get_json(
        config["base_url"].rstrip("/") + "/models?limit=1000",
        config.get("api_key_env"),
        headers,
    )
    return [
        {
            "name": item.get("display_name", item["id"]),
            "provider": "anthropic",
            "model": item["id"],
            "created": item.get("created_at"),
            "capabilities": {"reasoning": None},
            "catalog_metadata": item,
        }
        for item in payload.get("data", [])
    ]


def _gemini(source: dict[str, Any]) -> list[dict[str, Any]]:
    config = _base(source)
    key = os.environ.get(config.get("api_key_env", ""))
    if not key:
        raise ValueError(
            f"environment variable {config.get('api_key_env')!r} is not set"
        )
    url = config["base_url"].rstrip("/") + "/models?pageSize=1000"
    payload = _get_json(url, None, {"x-goog-api-key": key, **config.get("headers", {})})
    result = []
    for item in payload.get("models", []):
        methods = item.get("supportedGenerationMethods", [])
        if "generateContent" not in methods:
            continue
        model_id = item["name"].removeprefix("models/")
        result.append(
            {
                "name": item.get("displayName", model_id),
                "provider": "gemini",
                "model": model_id,
                "context_length": item.get("inputTokenLimit"),
                "max_output_tokens": item.get("outputTokenLimit"),
                "capabilities": {
                    "reasoning": item.get("thinking"),
                    "methods": methods,
                },
                "catalog_metadata": item,
            }
        )
    return result


def _openrouter(source: dict[str, Any]) -> list[dict[str, Any]]:
    config = _base(source)
    query = {"output_modalities": source.get("output_modalities", "text")}
    if source.get("sort"):
        query["sort"] = source["sort"]
    if source.get("require_parameters"):
        query["supported_parameters"] = ",".join(source["require_parameters"])
    url = config["base_url"].rstrip("/") + "/models?" + urllib.parse.urlencode(query)
    payload = _get_json(url, config.get("api_key_env"), config.get("headers"))
    result = []
    for item in payload.get("data", []):
        parameters = item.get("supported_parameters") or []
        pricing = item.get("pricing") or {}
        prompt_price = _number(pricing.get("prompt"))
        completion_price = _number(pricing.get("completion"))
        architecture = item.get("architecture") or {}
        model = {
            "name": item.get("name", item["id"]),
            "provider": "openrouter",
            "model": item["id"],
            "created": item.get("created"),
            "context_length": item.get("context_length"),
            "capabilities": {
                "reasoning": "reasoning" in parameters,
                "structured_outputs": "structured_outputs" in parameters,
                "tools": "tools" in parameters,
                "input_modalities": architecture.get("input_modalities"),
                "output_modalities": architecture.get("output_modalities"),
                "supported_parameters": parameters,
            },
            "catalog_metadata": item,
        }
        if prompt_price is not None:
            model["input_cost_per_million"] = prompt_price * 1_000_000
        if completion_price is not None:
            model["output_cost_per_million"] = completion_price * 1_000_000
        result.append(model)
    return result


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


DISCOVERERS = {
    "openai": _openai,
    "openai_compatible": _openai,
    "xai": _openai,
    "anthropic": _anthropic,
    "gemini": _gemini,
    "openrouter": _openrouter,
}


def discover_models(source: dict[str, Any]) -> list[dict[str, Any]]:
    provider = source.get("provider")
    if provider not in DISCOVERERS:
        raise ValueError(f"catalog discovery is unsupported for provider {provider!r}")
    if "limit" not in source or int(source["limit"]) < 1:
        raise ValueError("every discovery source requires a positive 'limit'")
    models = DISCOVERERS[provider](source)
    include = source.get("include")
    exclude = source.get("exclude")
    if include:
        models = [model for model in models if re.search(include, model["model"], re.I)]
    if exclude:
        models = [
            model for model in models if not re.search(exclude, model["model"], re.I)
        ]
    if not source.get("sort"):
        models.sort(key=lambda model: str(model.get("created") or ""), reverse=True)
    inherited: dict[str, Any] = {
        key: source[key]
        for key in (
            "base_url",
            "api_key_env",
            "headers",
            "api_version",
        )
        if key in source
    }
    return [
        apply_public_pricing({**model, **inherited})
        for model in models[: int(source["limit"])]
    ]


def resolve_models(config: dict[str, Any]) -> list[dict[str, Any]]:
    models = list(config.get("models", []))
    for source in config.get("discovery", []):
        models.extend(discover_models(source))
    seen: set[tuple[str, str]] = set()
    unique = []
    for model in models:
        identity = (model.get("provider", "openai_compatible"), model["model"])
        if identity not in seen:
            seen.add(identity)
            unique.append(apply_public_pricing(model))
    return unique
