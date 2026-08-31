import json
from pathlib import Path

from llm_preflight.catalog import resolve_models
from llm_preflight.eligibility import smoke_eligibility_report


def test_smoke_eligibility_explains_every_catalog_and_pricing_outcome():
    report = smoke_eligibility_report(
        [
            {
                "provider": "openai",
                "model": "ready",
                "catalog_type": "text-ready",
                "capabilities": {"adapter": "openai_responses"},
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {"as_of": "2026-08-31"},
            },
            {
                "provider": "openai",
                "model": "probe",
                "catalog_type": "text-candidate",
                "capabilities": {"adapter": "openai_responses"},
            },
            {"provider": "openai", "model": "image", "catalog_type": "image"},
            {
                "provider": "openai",
                "model": "unpriced",
                "catalog_type": "text-ready",
                "capabilities": {"adapter": "openai_responses"},
            },
            {
                "provider": "openai",
                "model": "adapter-missing",
                "catalog_type": "text-ready",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {"as_of": "2026-08-31"},
            },
            {"provider": "openai", "model": "catalog-unknown"},
            {
                "provider": "openai",
                "model": "undated",
                "catalog_type": "text-ready",
                "capabilities": {"adapter": "openai_responses"},
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {"source": "user override"},
            },
            {
                "provider": "openai",
                "model": "stale",
                "catalog_type": "text-ready",
                "capabilities": {"adapter": "openai_responses"},
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {
                    "source": "official snapshot",
                    "as_of": "2020-01-01",
                },
            },
        ],
        {"max_requests": 8, "max_estimated_cost_usd": 1},
    )

    assert report["summary"] == {"discovered": 8, "needs_review": 7, "eligible": 1}
    assert [entry["reason"] for entry in report["models"]] == [
        "eligible",
        "probe_required",
        "incompatible_catalog_type",
        "unknown_pricing",
        "adapter_evidence_required",
        "catalog_evidence_required",
        "undated_pricing",
        "stale_pricing",
    ]


def test_smoke_eligibility_requires_bounded_limits_after_other_evidence():
    report = smoke_eligibility_report(
        [
            {
                "provider": "openai",
                "model": "ready",
                "catalog_type": "text-ready",
                "capabilities": {"adapter": "openai_responses"},
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {"as_of": "2026-08-31"},
            }
        ],
        {"max_requests": 1},
    )

    assert report["models"][0]["reason"] == "bounded_limits_required"


def test_tracked_approved_smoke_cohort_is_fully_eligible():
    config = json.loads(Path("examples/approved-smoke.json").read_text())

    report = smoke_eligibility_report(resolve_models(config), config)

    assert report["summary"] == {"discovered": 7, "needs_review": 0, "eligible": 7}
