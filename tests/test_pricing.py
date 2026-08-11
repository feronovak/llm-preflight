from datetime import date

import pytest

from llm_preflight.pricing import (
    apply_live_catalog_pricing,
    apply_public_pricing,
    pricing_coverage_report,
    pricing_freshness_report,
    resolve_pricing,
)


def test_live_catalog_pricing_preserves_overrides_and_marks_live_prices():
    models, changes = apply_live_catalog_pricing(
        [
            {
                "provider": "openrouter",
                "model": "a",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
            },
            {
                "provider": "openrouter",
                "model": "b",
                "input_cost_per_million": 9,
                "output_cost_per_million": 9,
                "pricing_metadata": {"source": "user override"},
            },
        ],
        [
            {
                "provider": "openrouter",
                "model": "a",
                "input_cost_per_million": 3,
                "output_cost_per_million": 4,
            },
            {
                "provider": "openrouter",
                "model": "b",
                "input_cost_per_million": 1,
                "output_cost_per_million": 1,
            },
        ],
        today=date(2026, 8, 2),
    )
    assert models[0]["pricing_metadata"]["source"] == "live catalog"
    assert models[0]["input_cost_per_million"] == 3
    assert models[1]["input_cost_per_million"] == 9
    assert changes == [
        {"provider": "openrouter", "model": "a", "before": (1, 2), "after": (3, 4)}
    ]


def test_resolve_pricing_returns_a_stable_ledger_for_the_costing_models():
    resolution = resolve_pricing([{"provider": "openai", "model": "gpt-5.4-mini"}])

    assert resolution["models"][0]["input_cost_per_million"] == 0.75
    assert resolution["ledger"][0]["source"] == "official snapshot"
    assert len(resolution["fingerprint"]) == 64
    assert (
        resolution["fingerprint"]
        == resolve_pricing([{"provider": "openai", "model": "gpt-5.4-mini"}])[
            "fingerprint"
        ]
    )


def test_public_pricing_marks_user_overrides():
    model = apply_public_pricing(
        {
            "provider": "openai",
            "model": "gpt-4.1",
            "input_cost_per_million": 99,
            "output_cost_per_million": 100,
        }
    )

    assert model["pricing_metadata"] == {"source": "user override"}


def test_public_pricing_marks_official_snapshot():
    model = apply_public_pricing({"provider": "openai", "model": "gpt-5.4-mini"})

    assert model["pricing_metadata"]["source"] == "official snapshot"
    assert model["pricing_metadata"]["confidence"] == "official"
    assert model["pricing_metadata"]["source_url"] == (
        "https://developers.openai.com/api/docs/pricing"
    )


def test_gemini_3_1_pricing_has_cache_and_long_context_tiers():
    model = apply_public_pricing(
        {"provider": "gemini", "model": "gemini-3.1-pro-preview"}
    )

    assert model["cached_input_cost_per_million"] == 0.2
    assert model["pricing_tiers"][1] == {
        "input_cost_per_million": 4.0,
        "output_cost_per_million": 18.0,
        "cached_input_cost_per_million": 0.4,
    }


def test_gemini_3_1_flash_lite_official_snapshot_pricing():
    model = apply_public_pricing(
        {"provider": "gemini", "model": "gemini-3.1-flash-lite"}
    )

    assert model["input_cost_per_million"] == 0.25
    assert model["output_cost_per_million"] == 1.5
    assert model["cached_input_cost_per_million"] == 0.025
    assert model["pricing_metadata"]["as_of"] == "2026-08-11"


@pytest.mark.parametrize(
    ("model_id", "input_price", "output_price"),
    [
        ("gpt-5.6-luna", 0.2, 1.2),
        ("gpt-5.6-terra", 2.0, 12.0),
        ("gpt-5.6-sol", 5.0, 30.0),
    ],
)
def test_gpt_5_6_official_snapshot_pricing(model_id, input_price, output_price):
    model = apply_public_pricing({"provider": "openai", "model": model_id})

    assert model["input_cost_per_million"] == input_price
    assert model["output_cost_per_million"] == output_price


def test_public_pricing_snapshot_is_reviewed_for_this_release():
    from llm_preflight.pricing import PUBLIC_PRICING, PUBLIC_PRICING_SOURCES

    assert {as_of for _, _, as_of in PUBLIC_PRICING.values()} == {"2026-08-11"}
    assert set(PUBLIC_PRICING_SOURCES) == set(PUBLIC_PRICING)
    assert all(
        source.startswith("https://") for source in PUBLIC_PRICING_SOURCES.values()
    )
    assert PUBLIC_PRICING[("openai", "gpt-5.6-terra")][:2] == (2.0, 12.0)
    assert PUBLIC_PRICING[("openai", "gpt-5.6-luna")][:2] == (0.2, 1.2)


def test_mock_fixtures_do_not_count_as_priced_billable_models():
    report = pricing_coverage_report(
        [
            {"provider": "mock", "model": "local", "response": "ok"},
            {
                "provider": "openai",
                "model": "priced",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {
                    "source": "official snapshot",
                    "as_of": "2026-08-11",
                },
            },
        ],
        today=date(2026, 8, 11),
    )

    assert report["summary"] == {
        "selected": 2,
        "billable": 1,
        "exempt": 1,
        "priced": 1,
        "undated": 0,
        "stale": 0,
        "unknown": 0,
    }


def test_pricing_freshness_report_flags_stale_public_registry_entries():
    report = pricing_freshness_report(
        [
            {
                "provider": "openai",
                "model": "gpt-4.1",
                "input_cost_per_million": 2,
                "output_cost_per_million": 8,
                "pricing_metadata": {
                    "source": "official snapshot",
                    "as_of": "2026-01-01",
                },
            }
        ],
        today=date(2026, 7, 13),
        max_age_days=30,
    )

    assert report["ok"] is False
    assert report["warnings"] == [
        {
            "model": "gpt-4.1",
            "provider": "openai",
            "severity": "warning",
            "code": "stale_pricing",
            "message": "official pricing snapshot is stale by 193 days",
            "source": "official snapshot",
            "as_of": "2026-01-01",
        }
    ]


def test_pricing_freshness_report_flags_unknown_prices():
    report = pricing_freshness_report(
        [{"provider": "openai_compatible", "model": "local"}],
        today=date(2026, 7, 13),
    )

    assert report["ok"] is False
    assert report["warnings"][0]["message"] == "pricing is unknown"


def test_pricing_freshness_report_flags_stale_openrouter_catalog_entries():
    report = pricing_freshness_report(
        [
            {
                "provider": "openrouter",
                "model": "vendor/model",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {
                    "source": "openrouter routed",
                    "as_of": "2026-01-01",
                },
            }
        ],
        today=date(2026, 8, 11),
    )

    assert (
        report["warnings"][0]["message"]
        == "openrouter routed pricing is stale by 222 days"
    )


def test_pricing_freshness_report_rejects_an_undated_price_override():
    report = pricing_freshness_report(
        [
            {
                "provider": "openai",
                "model": "custom",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {"source": "user override"},
            }
        ]
    )

    assert report["warnings"][0]["message"] == "pricing source has no as-of date"


def test_pricing_freshness_report_rejects_an_invalid_as_of_date():
    report = pricing_freshness_report(
        [
            {
                "provider": "openai",
                "model": "custom",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {
                    "source": "official snapshot",
                    "as_of": "not-a-date",
                },
            }
        ]
    )

    assert (
        report["warnings"][0]["message"] == "pricing source has an invalid as-of date"
    )


def test_pricing_coverage_reports_selected_models_and_actionable_remediation():
    report = pricing_coverage_report(
        [
            {
                "provider": "openrouter",
                "model": "vendor/model",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {
                    "source": "live catalog",
                    "as_of": "2026-08-11",
                },
            },
            {"provider": "gemini", "model": "new-model"},
            {
                "provider": "openai",
                "model": "old-model",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {
                    "source": "official snapshot",
                    "as_of": "2026-01-01",
                },
            },
        ],
        today=date(2026, 8, 11),
    )

    assert report["ok"] is False
    assert report["summary"] == {
        "selected": 3,
        "billable": 3,
        "exempt": 0,
        "priced": 1,
        "undated": 0,
        "stale": 1,
        "unknown": 1,
    }
    assert report["models"] == [
        {
            "provider": "gemini",
            "model": "new-model",
            "status": "unknown",
            "source": "unknown",
            "source_url": None,
            "as_of": None,
            "remediation": "add a reviewed direct-provider price override or update the official snapshot",
        },
        {
            "provider": "openai",
            "model": "old-model",
            "status": "stale",
            "source": "official snapshot",
            "source_url": None,
            "as_of": "2026-01-01",
            "remediation": "upgrade llm-preflight for a refreshed official snapshot or add a reviewed price override",
        },
        {
            "provider": "openrouter",
            "model": "vendor/model",
            "status": "priced",
            "source": "live catalog",
            "source_url": None,
            "as_of": "2026-08-11",
            "remediation": None,
        },
    ]


def test_pricing_coverage_reports_undated_prices_without_calling_them_stale():
    report = pricing_coverage_report(
        [
            {
                "provider": "openai",
                "model": "custom",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {"source": "user override"},
            }
        ]
    )

    assert report["ok"] is True
    assert report["enforcement_ok"] is True
    assert report["summary"] == {
        "selected": 1,
        "billable": 1,
        "exempt": 0,
        "priced": 0,
        "undated": 1,
        "stale": 0,
        "unknown": 0,
    }
    assert report["models"][0]["status"] == "undated"
    assert report["models"][0]["remediation"] == (
        "add a reviewed ISO-8601 as-of date to the pricing metadata"
    )


def test_pricing_coverage_keeps_duplicate_model_rows_independent():
    report = pricing_coverage_report(
        [
            {
                "provider": "openai_compatible",
                "model": "same-id",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {
                    "source": "user override",
                    "as_of": "2026-08-01",
                },
            },
            {"provider": "openai_compatible", "model": "same-id"},
        ],
        today=date(2026, 8, 11),
    )

    assert [entry["status"] for entry in report["models"]] == ["priced", "unknown"]
    assert report["summary"] == {
        "selected": 2,
        "billable": 2,
        "exempt": 0,
        "priced": 1,
        "undated": 0,
        "stale": 0,
        "unknown": 1,
    }


def test_pricing_coverage_marks_an_invalid_as_of_date_undated_with_a_specific_remedy():
    report = pricing_coverage_report(
        [
            {
                "provider": "openai",
                "model": "custom",
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "pricing_metadata": {
                    "source": "user override",
                    "as_of": "not-a-date",
                },
            }
        ]
    )

    assert report["models"][0]["status"] == "undated"
    assert report["warnings"][0]["code"] == "invalid_as_of"
    assert report["models"][0]["remediation"] == (
        "replace the pricing metadata as-of date with a valid ISO-8601 date"
    )


def test_current_pricing_enforcement_expires_old_user_overrides():
    models = [
        {
            "provider": "openai",
            "model": "custom",
            "input_cost_per_million": 1,
            "output_cost_per_million": 2,
            "pricing_metadata": {
                "source": "user override",
                "as_of": "2020-01-01",
            },
        }
    ]

    assert (
        pricing_coverage_report(models, today=date(2026, 8, 11))["models"][0]["status"]
        == "priced"
    )
    enforced = pricing_coverage_report(
        models, today=date(2026, 8, 11), require_current_pricing=True
    )
    assert enforced["models"][0]["status"] == "stale"
    assert enforced["enforcement_ok"] is False


def test_public_snapshot_metadata_is_refreshed_after_a_package_upgrade(monkeypatch):
    from llm_preflight import pricing

    model = {
        "provider": "openai",
        "model": "gpt-4.1",
        "input_cost_per_million": 1,
        "output_cost_per_million": 2,
        "pricing_metadata": {
            "source": "official snapshot",
            "as_of": "2026-01-01",
        },
    }
    monkeypatch.setitem(
        pricing.PUBLIC_PRICING,
        ("openai", "gpt-4.1"),
        (3, 4, "2026-08-11"),
    )

    refreshed = apply_public_pricing(model)

    assert refreshed["input_cost_per_million"] == 3
    assert refreshed["output_cost_per_million"] == 4
    assert refreshed["pricing_metadata"]["as_of"] == "2026-08-11"
