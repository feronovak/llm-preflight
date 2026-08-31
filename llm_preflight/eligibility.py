"""Deterministic smoke eligibility for discovered provider models."""

from __future__ import annotations

from typing import Any

from .pricing import pricing_coverage_report


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
