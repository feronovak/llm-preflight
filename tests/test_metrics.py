import pytest

from llm_bench.metrics import percentile, stats, summarize


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4, 5], 0.95) == 4.8
    assert percentile([], 0.5) is None


def test_summary_excludes_failed_samples_and_calculates_cost():
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
    assert result["estimated_cost_usd"] == pytest.approx(0.00014)


def test_stats():
    assert stats([1, 3])["mean"] == 2
