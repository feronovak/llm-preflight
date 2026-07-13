from datetime import date

from llm_bench.pricing import apply_public_pricing, pricing_freshness_report


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


def test_pricing_freshness_report_flags_stale_public_registry_entries():
    report = pricing_freshness_report(
        [
            {
                "provider": "openai",
                "model": "gpt-4.1",
                "input_cost_per_million": 2,
                "output_cost_per_million": 8,
                "pricing_metadata": {
                    "source": "public provider pricing",
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
            "message": "public provider pricing is stale by 193 days",
            "source": "public provider pricing",
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
