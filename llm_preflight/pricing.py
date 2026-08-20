from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

# Standard synchronous API rates in USD per million tokens. Provider catalogs
# do not consistently return prices, so these public rates fill that gap.
# OpenRouter prices remain dynamic and take precedence when its catalog returns
# them. Gemini 3.1 Pro uses the <=200k-input tier.
PUBLIC_PRICING: dict[tuple[str, str], tuple[float, float, str]] = {
    ("openai", "gpt-5.6-luna"): (0.2, 1.2, "2026-08-11"),
    ("openai", "gpt-5.6-terra"): (2.0, 12.0, "2026-08-11"),
    ("openai", "gpt-5.6-sol"): (5.0, 30.0, "2026-08-11"),
    ("openai", "gpt-5.5"): (5.0, 30.0, "2026-08-11"),
    ("openai", "gpt-5.4-mini"): (0.75, 4.5, "2026-08-11"),
    ("openai", "gpt-5.4-nano"): (0.2, 1.25, "2026-08-11"),
    ("openai", "gpt-4.1"): (2.0, 8.0, "2026-08-11"),
    ("openai", "gpt-4.1-mini"): (0.4, 1.6, "2026-08-11"),
    ("openai", "gpt-4.1-nano"): (0.1, 0.4, "2026-08-11"),
    ("gemini", "gemini-3.1-flash-lite"): (0.25, 1.5, "2026-08-11"),
    ("gemini", "gemini-3.1-pro-preview"): (2.0, 12.0, "2026-08-11"),
    ("gemini", "gemini-3.5-flash"): (1.5, 9.0, "2026-08-11"),
    # Introductory Sonnet 5 rate through 2026-08-31.
    ("anthropic", "claude-sonnet-5"): (2.0, 10.0, "2026-08-11"),
    ("anthropic", "claude-fable-5"): (10.0, 50.0, "2026-08-11"),
    ("anthropic", "claude-opus-4-8"): (5.0, 25.0, "2026-08-11"),
    ("xai", "grok-4.3"): (1.25, 2.5, "2026-08-11"),
}

PUBLIC_PRICING_SOURCES: dict[tuple[str, str], str] = {
    key: {
        "openai": "https://developers.openai.com/api/docs/pricing",
        "anthropic": "https://platform.claude.com/docs/en/about-claude/pricing",
        "gemini": "https://ai.google.dev/gemini-api/docs/pricing",
        "xai": "https://docs.x.ai/developers/models/grok-4.3",
    }[key[0]]
    for key in PUBLIC_PRICING
}

PUBLIC_PRICING_DETAILS: dict[tuple[str, str], dict[str, Any]] = {
    ("gemini", "gemini-3.1-flash-lite"): {
        "cached_input_cost_per_million": 0.025,
    },
    ("gemini", "gemini-3.1-pro-preview"): {
        "cached_input_cost_per_million": 0.2,
        "pricing_tiers": [
            {
                "up_to_input_tokens": 200_000,
                "input_cost_per_million": 2.0,
                "output_cost_per_million": 12.0,
                "cached_input_cost_per_million": 0.2,
            },
            {
                "input_cost_per_million": 4.0,
                "output_cost_per_million": 18.0,
                "cached_input_cost_per_million": 0.4,
            },
        ],
    },
}


def _pricing_tier(model: dict[str, Any], input_tokens: int) -> dict[str, Any]:
    tiers = model.get("pricing_tiers")
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            maximum = tier.get("up_to_input_tokens")
            if maximum is None or input_tokens <= int(maximum):
                return {**model, **tier}
    return model


def estimate_sample_cost(sample: dict[str, Any], model: dict[str, Any]) -> float | None:
    """Estimate one request using its cache hits and applicable input tier."""
    input_tokens = sample.get("input_tokens")
    output_tokens = sample.get("output_tokens")
    if input_tokens is None or output_tokens is None:
        return None
    tier = _pricing_tier(model, int(input_tokens))
    input_price = tier.get("input_cost_per_million")
    output_price = tier.get("output_cost_per_million")
    if input_price is None or output_price is None:
        return None
    cached_input = min(
        max(0, int(sample.get("cached_input_tokens") or 0)), int(input_tokens)
    )
    cached_price = tier.get("cached_input_cost_per_million", input_price)
    return (
        (int(input_tokens) - cached_input) * float(input_price) / 1_000_000
        + cached_input * float(cached_price) / 1_000_000
        + int(output_tokens) * float(output_price) / 1_000_000
    )


def apply_public_pricing(model: dict[str, Any]) -> dict[str, Any]:
    if (
        model.get("input_cost_per_million") is not None
        and model.get("output_cost_per_million") is not None
    ):
        metadata = model.get("pricing_metadata") or {}
        if metadata and metadata.get("source") != "official snapshot":
            return model
        # A prior pricing-refresh --write may have persisted an older bundled
        # snapshot.  Reapply the package snapshot so upgrading the package is
        # sufficient to refresh direct-provider prices.
        if metadata.get("source") != "official snapshot":
            return {**model, "pricing_metadata": {"source": "user override"}}
    key = (model.get("provider", "openai_compatible"), model["model"])
    pricing = PUBLIC_PRICING.get(key)
    if pricing is None:
        return model
    input_price, output_price, as_of = pricing
    return {
        **model,
        "input_cost_per_million": input_price,
        "output_cost_per_million": output_price,
        **PUBLIC_PRICING_DETAILS.get(key, {}),
        "pricing_metadata": {
            "source": "official snapshot",
            "confidence": "official",
            "as_of": as_of,
            "source_url": PUBLIC_PRICING_SOURCES[key],
        },
    }


def pricing_freshness_report(
    models: list[dict[str, Any]],
    today: date | None = None,
    max_age_days: int = 30,
    enforce_override_freshness: bool = False,
) -> dict[str, Any]:
    current = today or datetime.now(timezone.utc).date()
    warnings = []
    for model in models:
        classification = _classify_pricing(
            model, current, max_age_days, enforce_override_freshness
        )
        if classification["warning"] is not None:
            warnings.append(classification["warning"])
    return {"ok": not warnings, "warnings": warnings}


def pricing_coverage_report(
    models: list[dict[str, Any]],
    today: date | None = None,
    max_age_days: int = 30,
    require_current_pricing: bool = False,
) -> dict[str, Any]:
    """Describe price coverage for every selected billable model or route."""
    current = today or datetime.now(timezone.utc).date()
    entries: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for model in models:
        classification = _classify_pricing(
            model, current, max_age_days, require_current_pricing
        )
        entries.append(classification["entry"])
        if classification["warning"] is not None:
            warnings.append(classification["warning"])
    entries.sort(key=lambda entry: (entry["provider"], entry["model"]))
    billable_entries = [entry for entry in entries if not entry.get("pricing_exempt")]
    blocking_statuses = {"stale", "unknown"}
    ok = not any(entry["status"] in blocking_statuses for entry in billable_entries)
    enforcement_ok = ok and (
        not require_current_pricing
        or not any(entry["status"] == "undated" for entry in billable_entries)
    )
    return {
        "ok": ok,
        "enforcement_ok": enforcement_ok,
        "summary": {
            "selected": len(entries),
            "billable": len(billable_entries),
            "exempt": len(entries) - len(billable_entries),
            "priced": sum(entry["status"] == "priced" for entry in billable_entries),
            "undated": sum(entry["status"] == "undated" for entry in billable_entries),
            "stale": sum(entry["status"] == "stale" for entry in billable_entries),
            "unknown": sum(entry["status"] == "unknown" for entry in billable_entries),
        },
        "models": entries,
        "warnings": warnings,
    }


def _classify_pricing(
    model: dict[str, Any],
    current: date,
    max_age_days: int,
    enforce_override_freshness: bool,
) -> dict[str, Any]:
    """Classify one model without joining warnings by non-unique model IDs."""
    provider = model.get("provider", "openai_compatible")
    name = model["model"]
    metadata = model.get("pricing_metadata") or {}
    source = metadata.get("source", "unknown")
    as_of = metadata.get("as_of")
    entry = {
        "provider": provider,
        "model": name,
        "status": "priced",
        "source": source,
        "source_url": metadata.get("source_url"),
        "as_of": as_of,
        "remediation": None,
    }
    if provider == "mock":
        entry["source"] = "mock fixture"
        entry["pricing_exempt"] = True
        return {"entry": entry, "warning": None}
    if not _has_usable_pricing(model):
        return _pricing_problem(
            entry,
            "unknown",
            "unknown_pricing",
            "pricing is unknown",
            (
                "refresh the OpenRouter catalog price"
                if provider == "openrouter"
                else "add a reviewed direct-provider price override or update the official snapshot"
            ),
        )
    if not as_of:
        return _pricing_problem(
            entry,
            "undated",
            "missing_as_of",
            "pricing source has no as-of date",
            "add a reviewed ISO-8601 as-of date to the pricing metadata",
        )
    try:
        as_of_date = date.fromisoformat(as_of)
    except (TypeError, ValueError):
        return _pricing_problem(
            entry,
            "undated",
            "invalid_as_of",
            "pricing source has an invalid as-of date",
            "replace the pricing metadata as-of date with a valid ISO-8601 date",
        )
    should_expire = source in {
        "official snapshot",
        "live catalog",
        "openrouter routed",
    } or (enforce_override_freshness and source == "user override")
    age_days = (current - as_of_date).days
    if should_expire and age_days > max_age_days:
        label = (
            "official pricing snapshot"
            if source == "official snapshot"
            else f"{source} pricing"
        )
        remediation = (
            "refresh the OpenRouter catalog price"
            if provider == "openrouter"
            else (
                "refresh the reviewed user override or set a newer as-of date"
                if source == "user override"
                else "upgrade llm-preflight for a refreshed official snapshot or add a reviewed price override"
            )
        )
        return _pricing_problem(
            entry,
            "stale",
            "stale_pricing",
            f"{label} is stale by {age_days} days",
            remediation,
        )
    return {"entry": entry, "warning": None}


def _has_usable_pricing(model: dict[str, Any]) -> bool:
    """Return whether direct prices or every configured tier can price a call."""
    if (
        model.get("input_cost_per_million") is not None
        and model.get("output_cost_per_million") is not None
    ):
        return True
    tiers = model.get("pricing_tiers")
    return (
        isinstance(tiers, list)
        and bool(tiers)
        and all(
            isinstance(tier, dict)
            and tier.get("input_cost_per_million") is not None
            and tier.get("output_cost_per_million") is not None
            for tier in tiers
        )
    )


def _pricing_problem(
    entry: dict[str, Any], status: str, code: str, message: str, remediation: str
) -> dict[str, Any]:
    entry["status"] = status
    entry["remediation"] = remediation
    return {
        "entry": entry,
        "warning": {
            "model": entry["model"],
            "provider": entry["provider"],
            "severity": "warning",
            "code": code,
            "message": message,
            "source": entry["source"],
            "as_of": entry["as_of"],
        },
    }


def apply_live_catalog_pricing(
    models: list[dict[str, Any]],
    catalog: list[dict[str, Any]],
    today: date | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply authoritative catalog prices without replacing explicit overrides."""
    resolution = resolve_pricing(models, {"catalog": catalog, "today": today})
    return resolution["models"], resolution["changes"]


def resolve_pricing(
    models: list[dict[str, Any]], policy: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Resolve every model through one deterministic pricing ledger.

    Callers use the returned models for both planning and result costing, and
    persist the ledger fingerprint beside their result.  ``catalog`` is an
    optional authoritative refresh input; explicit user overrides always win.
    """
    policy = policy or {}
    today = policy.get("today")
    current = (today or datetime.now(timezone.utc).date()).isoformat()
    refreshed_at = policy.get("refreshed_at") or datetime.now(timezone.utc).isoformat()
    source_url = policy.get("source_url")
    catalog = policy.get("catalog", [])
    prices = {
        (item.get("provider"), item.get("model")): item
        for item in catalog
        if item.get("input_cost_per_million") is not None
        and item.get("output_cost_per_million") is not None
    }
    updated: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []
    for model in models:
        item = dict(model)
        metadata = item.get("pricing_metadata") or {}
        key = (item.get("provider", "openai_compatible"), item.get("model"))
        live = prices.get(key)
        if metadata.get("source") != "user override" and live is not None:
            before = (
                item.get("input_cost_per_million"),
                item.get("output_cost_per_million"),
            )
            after = (live["input_cost_per_million"], live["output_cost_per_million"])
            item.update(
                input_cost_per_million=after[0], output_cost_per_million=after[1]
            )
            item["pricing_metadata"] = {
                "source": "live catalog",
                "confidence": "live",
                "as_of": current,
                "refreshed_at": refreshed_at,
                **({"source_url": source_url} if source_url else {}),
            }
            if before != after or metadata.get("source") != "live catalog":
                changes.append(
                    {
                        "provider": key[0],
                        "model": key[1],
                        "before": before,
                        "after": after,
                    }
                )
        updated.append(apply_public_pricing(item))
    ledger = [
        {
            "provider": model.get("provider", "openai_compatible"),
            "model": model["model"],
            "input_cost_per_million": model.get("input_cost_per_million"),
            "output_cost_per_million": model.get("output_cost_per_million"),
            "source": (model.get("pricing_metadata") or {}).get("source", "unknown"),
            "as_of": (model.get("pricing_metadata") or {}).get("as_of"),
            "refreshed_at": (model.get("pricing_metadata") or {}).get("refreshed_at"),
            "source_url": (model.get("pricing_metadata") or {}).get("source_url"),
            **{
                key: model[key]
                for key in (
                    "cached_input_cost_per_million",
                    "pricing_tiers",
                    "pricing_metadata",
                )
                if key in model
            },
        }
        for model in updated
    ]
    ledger.sort(key=lambda entry: (str(entry["provider"]), str(entry["model"])))
    fingerprint = hashlib.sha256(
        json.dumps(ledger, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "models": updated,
        "ledger": ledger,
        "fingerprint": fingerprint,
        "refreshed_at": refreshed_at if catalog else None,
        "changes": changes,
    }
