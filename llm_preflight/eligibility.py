"""Deterministic smoke eligibility for discovered provider models."""

from __future__ import annotations

from typing import Any

from .pricing import pricing_coverage_report

_TEXT_SMOKE_TYPES = {"text-ready", "text-candidate", "text-chat", "unknown"}

ELIGIBILITY_NEXT_STEPS: dict[str, str] = {
    "probe_required": (
        "run one minimal `catalog probe` request for this text candidate"
    ),
    "catalog_evidence_required": (
        "declared by hand; discover it with `catalog refresh` or keep the "
        "declared request and cost caps and review it yourself"
    ),
    "incompatible_catalog_type": (
        "not a text model; a live run refuses this catalogue type, remove it "
        "from the plan"
    ),
    "adapter_evidence_required": (
        "no compatible provider-adapter evidence is retained; do not guess a "
        "request shape"
    ),
    "unknown_pricing": "add reviewed direct-provider pricing with an as_of date",
    "undated_pricing": "add an as_of date to the reviewed pricing",
    "stale_pricing": "refresh the reviewed pricing; it is older than the freshness limit",
    "bounded_limits_required": "declare both max_requests and max_estimated_cost_usd",
}


def eligibility_next_step(entry: dict[str, Any]) -> str:
    """Return the next step for one non-eligible smoke-eligibility entry."""
    reason = entry.get("reason", "unknown")
    catalog_type = entry.get("catalog_type")
    if reason == "incompatible_catalog_type" and catalog_type in _TEXT_SMOKE_TYPES:
        return (
            f"catalogued as {catalog_type}; eligibility needs text-ready evidence "
            "from `catalog probe`; a reviewed bounded run may still proceed"
        )
    return ELIGIBILITY_NEXT_STEPS.get(reason, "review the catalogue evidence")


class IncompatibleCatalogTypeError(ValueError):
    """A model is not eligible for the generic text smoke adapter."""


def incompatible_text_smoke_reason(model: dict[str, Any]) -> str | None:
    provider = str(model.get("provider") or "")
    name = str(model.get("model") or "").casefold()
    catalog_type = model.get("catalog_type")
    if provider == "typesafe" or "jev-" in name or catalog_type == "decision":
        return "incompatible_catalog_type"
    if catalog_type and catalog_type not in _TEXT_SMOKE_TYPES:
        return "incompatible_catalog_type"
    return None


def assert_text_smoke_models(models: list[dict[str, Any]]) -> None:
    blocked = [
        f"{model.get('provider', 'openai_compatible')}:{model.get('model')}"
        for model in models
        if incompatible_text_smoke_reason(model)
    ]
    if not blocked:
        return
    raise IncompatibleCatalogTypeError(
        "typed-decision and other non-text catalogue types are incompatible "
        "with the text smoke adapter: " + ", ".join(blocked)
    )


def smoke_eligibility_report(
    models: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    """Explain which discovered models may enter a bounded paid smoke plan."""
    coverage = pricing_coverage_report(models, require_current_pricing=True)
    pricing = {
        (entry["provider"], entry["model"]): entry["status"]
        for entry in coverage["models"]
    }
    entries = []
    for model in models:
        provider = model.get("provider", "openai_compatible")
        model_id = model["model"]
        catalog_type = model.get("catalog_type", "unknown")
        adapter = (model.get("capabilities") or {}).get("adapter")
        if catalog_type == "text-candidate":
            reason = "probe_required"
        elif catalog_type == "unknown":
            reason = "catalog_evidence_required"
        elif catalog_type != "text-ready":
            reason = "incompatible_catalog_type"
        elif not adapter:
            reason = "adapter_evidence_required"
        elif pricing.get((provider, model_id)) != "priced":
            status = pricing.get((provider, model_id), "unknown")
            reason = f"{status}_pricing"
        elif (
            config.get("max_requests") is None
            or config.get("max_estimated_cost_usd") is None
        ):
            reason = "bounded_limits_required"
        else:
            reason = "eligible"
        entries.append(
            {
                "provider": provider,
                "model": model_id,
                "eligible": reason == "eligible",
                "reason": reason,
                "catalog_type": catalog_type,
            }
        )
    return {
        "summary": {
            "discovered": len(entries),
            "needs_review": sum(not entry["eligible"] for entry in entries),
            "eligible": sum(entry["eligible"] for entry in entries),
        },
        "models": entries,
    }
