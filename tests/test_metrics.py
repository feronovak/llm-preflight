import pytest

from llm_preflight.metrics import percentile, stats, summarize


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4, 5], 0.95) == 4.8
    assert percentile([], 0.5) is None


def test_summary_excludes_failed_latency_but_preserves_unknown_request_cost():
    samples = [
        {
            "ok": True,
            "latency_seconds": 2,
            "ttft_seconds": 0.5,
            "output_tokens_per_second": 10,
            "input_tokens": 100,
            "output_tokens": 20,
        },
        {
            "ok": False,
            "latency_seconds": 1,
            "ttft_seconds": None,
            "output_tokens_per_second": None,
            "input_tokens": None,
            "output_tokens": None,
        },
    ]
    result = summarize(
        samples, {"input_cost_per_million": 1, "output_cost_per_million": 2}
    )
    assert result["success_rate"] == 0.5
    assert result["latency_seconds"]["mean"] == 2
    assert result["estimated_cost_usd"] is None
    assert result["priced_cost_usd"] == pytest.approx(0.00014)
    assert result["cost_coverage"] == {
        "known_requests": 1,
        "missing_usage_requests": 1,
        "missing_price_requests": 0,
        "unobserved_retry_requests": 0,
    }


@pytest.mark.parametrize("missing_field", ["input_tokens", "output_tokens"])
@pytest.mark.parametrize(
    "value", [None, -1, True, "10", 1.5, float("nan"), float("inf")]
)
def test_summary_does_not_price_missing_or_invalid_usage(missing_field, value):
    sample = {
        "ok": True,
        "input_tokens": 100,
        "output_tokens": 20,
        missing_field: value,
    }
    result = summarize(
        [sample], {"input_cost_per_million": 1, "output_cost_per_million": 2}
    )
    assert result["estimated_cost_usd"] is None
    assert result["priced_cost_usd"] is None
    assert result["cost_coverage"]["missing_usage_requests"] == 1
    assert result["usage_coverage"][missing_field] == 0


def test_reported_zero_usage_is_known_cost():
    result = summarize(
        [{"ok": True, "input_tokens": 0, "output_tokens": 0}],
        {"input_cost_per_million": 1, "output_cost_per_million": 2},
    )
    assert result["estimated_cost_usd"] == 0
    assert result["priced_cost_usd"] == 0
    assert result["cost_coverage"]["known_requests"] == 1
    assert result["usage_coverage"] == {"input_tokens": 1, "output_tokens": 1}


def test_summary_counts_billable_tokens_for_validation_failures():
    samples = [
        {
            "ok": False,
            "latency_seconds": 1,
            "ttft_seconds": 0.1,
            "output_tokens_per_second": 2,
            "input_tokens": 10,
            "output_tokens": 5,
            "error": "response did not match regex",
        }
    ]

    result = summarize(
        samples, {"input_cost_per_million": 1, "output_cost_per_million": 2}
    )

    assert result["successful"] == 0
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 5
    assert result["estimated_cost_usd"] == pytest.approx(0.00002)


def test_summary_uses_cached_input_and_per_request_pricing_tiers():
    samples = [
        {
            "ok": True,
            "latency_seconds": 1,
            "ttft_seconds": 0.1,
            "output_tokens_per_second": 2,
            "input_tokens": 100,
            "cached_input_tokens": 80,
            "output_tokens": 10,
        },
        {
            "ok": True,
            "latency_seconds": 1,
            "ttft_seconds": 0.1,
            "output_tokens_per_second": 2,
            "input_tokens": 201,
            "output_tokens": 10,
        },
    ]
    model = {
        "input_cost_per_million": 1,
        "output_cost_per_million": 2,
        "cached_input_cost_per_million": 0.25,
        "pricing_tiers": [
            {
                "up_to_input_tokens": 200,
                "input_cost_per_million": 1,
                "output_cost_per_million": 2,
                "cached_input_cost_per_million": 0.25,
            },
            {
                "input_cost_per_million": 4,
                "output_cost_per_million": 8,
                "cached_input_cost_per_million": 1,
            },
        ],
    }

    result = summarize(samples, model)

    assert result["cached_input_tokens"] == 80
    assert result["estimated_cost_usd"] == pytest.approx(0.000944)


def test_summary_records_retry_accounting_and_failure_categories():
    samples = [
        {
            "ok": True,
            "latency_seconds": 1,
            "ttft_seconds": 0.1,
            "output_tokens_per_second": 2,
            "input_tokens": 10,
            "output_tokens": 5,
            "retry_count": 1,
            "retry_reasons": ["rate_limit"],
        },
        {
            "ok": False,
            "latency_seconds": 1,
            "ttft_seconds": None,
            "output_tokens_per_second": None,
            "input_tokens": None,
            "output_tokens": None,
            "retry_count": 2,
            "retry_reasons": ["timeout", "timeout"],
            "failure_category": "timeout",
            "error": "timed out",
        },
    ]

    result = summarize(samples, {})

    assert result["retry_count"] == 3
    assert result["retry_reasons"] == {"rate_limit": 1, "timeout": 2}
    assert result["failure_categories"] == {"timeout": 1}


def test_retry_without_attempt_usage_cannot_substantiate_complete_spend():
    result = summarize(
        [
            {
                "ok": True,
                "input_tokens": 100,
                "output_tokens": 20,
                "retry_count": 1,
                "retry_reasons": ["timeout"],
            }
        ],
        {"input_cost_per_million": 1, "output_cost_per_million": 2},
    )
    assert result["estimated_cost_usd"] is None
    assert result["priced_cost_usd"] == pytest.approx(0.00014)
    assert result["cost_coverage"]["unobserved_retry_requests"] == 1


def test_summary_adds_failure_diagnosis_hints():
    samples = [
        {
            "ok": False,
            "latency_seconds": 1,
            "ttft_seconds": 0.1,
            "output_tokens_per_second": 2,
            "input_tokens": 10,
            "output_tokens": 5,
            "error": "response did not match regex",
            "response_preview": "No Markdown fences or commentary? Yes, I must output only JSON.",
        },
        {
            "ok": False,
            "latency_seconds": 1,
            "ttft_seconds": 0.1,
            "output_tokens_per_second": 2,
            "input_tokens": 10,
            "output_tokens": 0,
            "error": "unsupported parameter: response_format",
        },
    ]

    result = summarize(samples, {})

    assert result["failure_hints"] == [
        "reasoning or commentary appeared before the expected answer",
        "provider rejected an unsupported request parameter",
    ]


def test_stats():
    assert stats([1, 3])["mean"] == 2
