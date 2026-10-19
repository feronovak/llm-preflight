"""Human summaries must respect the evidence used by machine decisions."""

import copy

import pytest

from llm_preflight.cli import _starter_config
from llm_preflight.decision import build_decision
from llm_preflight.runner import console_report, report, run_benchmark, save_result


@pytest.fixture
def mock_result():
    return run_benchmark(_starter_config())


def live_fixture(mock_result):
    """Reuse deterministic sample structure; no provider request is performed."""
    result = copy.deepcopy(mock_result)
    model = result["models"][0]
    model.update(name="live-fixture", provider="openai_compatible", model="fixture")
    model["summary"]["estimated_cost_usd"] = 0.004
    result["total_estimated_cost_usd"] = result["priced_cost_usd"] = 0.004
    result["pricing_coverage"]["summary"].update(billable=1, exempt=0, priced=1)
    result["pricing_coverage"]["models"] = [
        {
            "provider": "openai_compatible",
            "model": "fixture",
            "status": "priced",
            "pricing_exempt": False,
            "remediation": "Review the provider pricing source.",
        }
    ]
    result["source_config_path"] = "/workspace/benchmark.json"
    result["decision"] = build_decision(result)
    return result


@pytest.mark.parametrize("surface", ["terminal", "markdown", "saved-summary"])
def test_mock_summary_explains_local_success_without_provider_rankings(
    mock_result, tmp_path, surface
):
    if surface == "saved-summary":
        path = save_result(mock_result, tmp_path / "results")
        rendered = path.with_suffix(".summary.md").read_text()
    else:
        rendered = (console_report if surface == "terminal" else report)(mock_result)

    assert "local mock data" in rendered.lower()
    assert "no live provider was tested" in rendered.lower()
    assert "inconclusive" in rendered
    assert "Recommended: unavailable" in rendered
    for label in ("Fastest:", "Cheapest:", "Best value:"):
        assert label not in rendered
    assert "--contract-check" in rendered and "--dry-run" in rendered
    assert "Total spent:" not in rendered
    assert "Estimated cost:" in rendered
    assert mock_result["decision"]["state"] == "inconclusive"


@pytest.mark.parametrize("warning", ["stale", "unknown", "usage", "retry", "legacy"])
def test_incomplete_live_evidence_cannot_produce_a_value_recommendation(
    mock_result, warning
):
    result = live_fixture(mock_result)
    if warning in {"stale", "unknown"}:
        result["pricing_coverage"]["models"][0]["status"] = warning
    elif warning == "legacy":
        del result["cost_coverage"]
    else:
        key = (
            "missing_usage_requests"
            if warning == "usage"
            else "unobserved_retry_requests"
        )
        result["cost_coverage"][key] = 1
        result["cost_confidence"] = "partial"
        result["total_estimated_cost_usd"] = None
    # A stale cached verdict must not override the evidence being displayed.
    assert result["decision"]["state"] == "pass"
    assert build_decision(result)["state"] == "inconclusive"

    for renderer in (console_report, report):
        rendered = renderer(result)
        assert "Recommended: unavailable" in rendered
        assert "Best value: **live-fixture**" not in rendered
        assert "Best value: live-fixture" not in rendered
        assert "Decision: pass" not in rendered
        assert "inconclusive" in rendered
        assert "llm-preflight /workspace/benchmark.json --doctor --json" in rendered
        for message in build_decision(result)["blocking_warnings"]:
            assert message in rendered


def test_mock_rows_cannot_win_a_mixed_provider_comparison(mock_result):
    result = live_fixture(mock_result)
    live_model = result["models"][0]
    live_model["summary"]["latency_seconds"].update(mean=1, p50=1, p95=1)
    result["models"].insert(0, mock_result["models"][0])
    result["pricing_coverage"]["summary"].update(selected=2, exempt=1)
    result["pricing_coverage"]["models"].insert(
        0, mock_result["pricing_coverage"]["models"][0]
    )
    assert build_decision(result)["state"] == "pass"

    for renderer in (console_report, report):
        rendered = renderer(result)
        assert "mock rows" in rendered.lower()
        for label in ("Fastest", "Cheapest", "Best value", "Recommended"):
            line = next(line for line in rendered.splitlines() if f"{label}:" in line)
            assert "live-fixture" in line
            assert "local-mock" not in line


def test_failed_candidate_does_not_hide_a_complete_passing_comparison(mock_result):
    result = live_fixture(mock_result)
    failed = copy.deepcopy(result["models"][0])
    failed["name"] = "rejected-candidate"
    failed["summary"]["valid_output_rate"] = 0
    failed["samples"][0]["valid_output"] = False
    result["models"].append(failed)
    result["total_estimated_cost_usd"] = result["priced_cost_usd"] = 0.008
    result["pricing_coverage"]["summary"].update(selected=2, billable=2, priced=2)
    result["decision"] = build_decision(result)
    assert result["decision"]["state"] == "fail"
    assert not result["decision"]["blocking_warnings"]

    for renderer in (console_report, report):
        rendered = renderer(result)
        line = next(line for line in rendered.splitlines() if "Recommended:" in line)
        assert "live-fixture" in line
        assert "rejected-candidate" not in line
        assert "Estimated cost:" in rendered
        assert "Total spent:" not in rendered


@pytest.mark.parametrize("requests", [0, 1])
def test_complete_cost_cannot_qualify_an_untested_or_failed_live_model(
    mock_result, requests
):
    result = live_fixture(mock_result)
    model = result["models"][0]
    model["summary"]["requests"] = requests
    if requests:
        model["summary"]["valid_output_rate"] = 0
        model["samples"][0]["valid_output"] = False
    else:
        # Even a stored 100% rate cannot substitute for an observed request.
        model["samples"] = []
    assert build_decision(result)["state"] == "fail"
    assert not build_decision(result)["blocking_warnings"]

    for renderer in (console_report, report):
        rendered = renderer(result)
        for label in ("Fastest", "Cheapest", "Best value", "Recommended"):
            assert f"{label}: unavailable" in rendered
        assert "Decision: pass" not in rendered
