from datetime import date

import pytest

from llm_preflight import retirements
from llm_preflight.retirements import retirement_verdict

URL = "https://example.test/deprecations"
TABLE = {
    ("openai", "old-active"): {
        "status": "active",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
    ("openai", "gpt-gone"): {
        "status": "deprecated",
        "retirement_date": "2026-10-01",
        "replacement": "gpt-new",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
    ("openai", "gpt-going"): {
        "status": "deprecated",
        "retirement_date": "2027-04-01",
        "replacement": "gpt-new",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
    ("openai", "gpt-undated"): {
        "status": "deprecated",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
    ("openai", "gpt-no-replacement"): {
        "status": "retired",
        "retirement_date": "2026-09-01",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
    ("openai", "gpt-old-row"): {
        "status": "deprecated",
        "retirement_date": "2027-01-01",
        "replacement": "gpt-new",
        "as_of": "2026-01-01",
        "source_url": URL,
    },
    ("openai", "gpt-old-row-retired"): {
        "status": "deprecated",
        "retirement_date": "2026-06-01",
        "replacement": "gpt-new",
        "as_of": "2026-01-01",
        "source_url": URL,
    },
    ("openai", "gpt-chain"): {
        "status": "deprecated",
        "retirement_date": "2026-06-01",
        "replacement": "gpt-going",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
    ("openai", "gpt-new"): {
        "status": "active",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
}
TODAY = date(2026, 10, 9)


@pytest.fixture
def table(monkeypatch):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)


def test_unknown_model_is_not_a_verdict(table):
    verdict = retirement_verdict("openai", "gpt-nothing", TODAY)
    assert verdict["status"] == "unknown"
    assert verdict["decision"] == "none"
    assert "anthropic, openai" in verdict["next_step"]
    assert "next_command" not in verdict


def test_unknown_provider_is_unknown(table):
    assert retirement_verdict(None, "gpt-gone", TODAY)["status"] == "unknown"


def test_active_row_passes_with_its_evidence(table):
    verdict = retirement_verdict("openai", "old-active", TODAY)
    assert verdict["status"] == "active"
    assert verdict["decision"] == "pass"
    assert verdict["as_of"] == "2026-10-01"
    assert verdict["source_url"] == URL


def test_past_retirement_date_fails_and_prints_the_next_command(table):
    verdict = retirement_verdict("openai", "gpt-gone", TODAY)
    assert verdict["status"] == "retired"
    assert verdict["decision"] == "fail"
    assert verdict["retirement_date"] == "2026-10-01"
    assert verdict["replacement"] == "gpt-new"
    assert verdict["replacement_status"] == "active"
    assert verdict["next_command"] == (
        'llm-preflight --quick "<your prompt>" --models openai:gpt-gone,openai:gpt-new --dry-run'
    )
    assert URL in verdict["next_step"]


def test_retirement_date_equal_to_today_is_retired(table):
    verdict = retirement_verdict("openai", "gpt-gone", date(2026, 10, 1))
    assert verdict["status"] == "retired"
    assert verdict["decision"] == "fail"


def test_future_retirement_date_is_inconclusive(table):
    verdict = retirement_verdict("openai", "gpt-going", TODAY)
    assert verdict["status"] == "retiring"
    assert verdict["decision"] == "inconclusive"
    assert "2027-04-01" in verdict["reason"]


def test_deprecated_without_a_date_is_retiring(table):
    verdict = retirement_verdict("openai", "gpt-undated", TODAY)
    assert verdict["status"] == "retiring"
    assert verdict["decision"] == "inconclusive"
    assert "to be announced" in verdict["reason"]
    assert "no replacement announced" in verdict["next_step"]


def test_retired_row_without_replacement_says_so(table):
    verdict = retirement_verdict("openai", "gpt-no-replacement", TODAY)
    assert verdict["status"] == "retired"
    assert "replacement" not in verdict
    assert (
        "no replacement announced; choose one and preflight it" in verdict["next_step"]
    )
    assert "next_command" not in verdict


def test_stale_row_is_inconclusive_and_points_at_the_page(table):
    verdict = retirement_verdict("openai", "gpt-old-row", TODAY)
    assert verdict["status"] == "stale"
    assert verdict["decision"] == "inconclusive"
    assert "older than 30 days" in verdict["reason"]
    assert "update llm-preflight or review" in verdict["next_step"]


def test_stale_row_with_a_past_date_is_still_retired(table):
    verdict = retirement_verdict("openai", "gpt-old-row-retired", TODAY)
    assert verdict["status"] == "retired"
    assert verdict["decision"] == "fail"
    assert "days old" in verdict["reason"]


def test_window_is_configurable(table):
    assert (
        retirement_verdict("openai", "gpt-old-row", TODAY, max_age_days=400)["status"]
        == "retiring"
    )


def test_replacement_that_is_itself_retiring_is_named(table):
    verdict = retirement_verdict("openai", "gpt-chain", TODAY)
    assert verdict["replacement_status"] == "retiring"
    assert "gpt-going is itself retiring" in verdict["next_step"]
    assert "next_command" in verdict


def test_routed_prefix_resolves_to_the_catalogue_id(table):
    verdict = retirement_verdict("openai", "openai/gpt-gone", TODAY)
    assert verdict["status"] == "retired"
    assert "--models openai:gpt-gone,openai:gpt-new" in verdict["next_command"]
