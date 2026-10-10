import re
from datetime import date

import pytest

from llm_preflight import retirements
from llm_preflight.retirements import (
    ANTHROPIC_DEPRECATIONS_URL,
    OPENAI_DEPRECATIONS_URL,
    PUBLIC_RETIREMENTS,
    RETIREMENT_PROVIDERS,
    retirement_report,
    retirement_verdict,
    snapshot_summary,
    worst_decision,
)
from llm_preflight.source_audit import _MODEL_PREFIX, _provider_for

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


def test_every_snapshot_row_is_well_formed():
    assert PUBLIC_RETIREMENTS, "snapshot must not be empty"
    for (provider, model), row in PUBLIC_RETIREMENTS.items():
        assert provider in RETIREMENT_PROVIDERS, model
        assert _provider_for(model) == provider, model
        assert _MODEL_PREFIX.match(model), model
        assert row["status"] in {"active", "deprecated", "retired"}, model
        date.fromisoformat(row["as_of"])
        assert row["source_url"] in {
            ANTHROPIC_DEPRECATIONS_URL,
            OPENAI_DEPRECATIONS_URL,
        }
        assert set(row) <= {
            "status",
            "retirement_date",
            "replacement",
            "as_of",
            "source_url",
        }
        if row["status"] == "retired":
            assert "retirement_date" in row, model
        if "retirement_date" in row:
            date.fromisoformat(row["retirement_date"])
            assert row["status"] != "active", model
        if "replacement" in row:
            replacement = row["replacement"]
            assert _MODEL_PREFIX.match(replacement), model
            assert _provider_for(replacement) == provider, model
            assert replacement != model, model


def test_snapshot_pins_reviewed_rows_for_this_release():
    assert PUBLIC_RETIREMENTS[("anthropic", "claude-sonnet-4-5-20250929")] == {
        "status": "deprecated",
        "retirement_date": "2026-11-30",
        "replacement": "claude-sonnet-5-5",
        "as_of": "2026-10-09",
        "source_url": ANTHROPIC_DEPRECATIONS_URL,
    }
    assert PUBLIC_RETIREMENTS[("anthropic", "claude-mythos-preview")] == {
        "status": "deprecated",
        "as_of": "2026-10-09",
        "source_url": ANTHROPIC_DEPRECATIONS_URL,
    }
    assert PUBLIC_RETIREMENTS[("anthropic", "claude-sonnet-5-5")]["status"] == "active"
    assert PUBLIC_RETIREMENTS[("openai", "gpt-5.4-cyber")] == {
        "status": "deprecated",
        "retirement_date": "2026-10-01",
        "as_of": "2026-10-09",
        "source_url": OPENAI_DEPRECATIONS_URL,
    }
    assert PUBLIC_RETIREMENTS[("openai", "gpt-5.1")] == {
        "status": "deprecated",
        "retirement_date": "2027-04-01",
        "replacement": "gpt-6-sol",
        "as_of": "2026-10-09",
        "source_url": OPENAI_DEPRECATIONS_URL,
    }
    providers = {provider for provider, _ in PUBLIC_RETIREMENTS}
    assert providers == {"anthropic", "openai"}
    assert sum(1 for p, _ in PUBLIC_RETIREMENTS if p == "anthropic") == 36
    assert sum(1 for p, _ in PUBLIC_RETIREMENTS if p == "openai") == 64


def test_snapshot_summary_reports_coverage_and_dates():
    summary = snapshot_summary()
    assert summary["providers"] == ["anthropic", "openai"]
    assert summary["rows"] == len(PUBLIC_RETIREMENTS)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", summary["oldest_as_of"])
    assert summary["oldest_as_of"] <= summary["newest_as_of"]


def test_worst_decision_orders_fail_over_inconclusive_over_pass():
    assert worst_decision(["pass", "inconclusive", "fail"]) == "fail"
    assert worst_decision(["pass", "none", "inconclusive"]) == "inconclusive"
    assert worst_decision(["none", "pass"]) == "pass"
    assert worst_decision([]) == "pass"


def test_retirement_report_summarises_a_model_list(table):
    report = retirement_report(
        [
            {"provider": "openai", "model": "gpt-gone"},
            {"provider": "openai", "model": "gpt-going"},
            {"provider": "openai", "model": "gpt-gone"},
            {"provider": "mock", "model": "local"},
            {"provider": "openai", "model": "old-active"},
        ],
        TODAY,
    )
    assert report["decision"] == "fail"
    assert report["summary"] == {
        "retired": 2,
        "retiring": 1,
        "stale": 0,
        "active": 1,
        "unknown": 1,
    }
    assert [m["model"] for m in report["models"]] == [
        "gpt-gone",
        "gpt-going",
        "gpt-gone",
        "local",
        "old-active",
    ]
    assert report["models"][0]["status"] == "retired"
    assert report["models"][3]["status"] == "unknown"
    assert report["next_commands"] == [
        'llm-preflight --quick "<your prompt>" --models openai:gpt-gone,openai:gpt-new --dry-run',
        'llm-preflight --quick "<your prompt>" --models openai:gpt-going,openai:gpt-new --dry-run',
    ]
    assert report["snapshot"]["providers"] == ["anthropic", "openai"]


def test_retirement_report_is_inconclusive_without_a_retired_model(table):
    report = retirement_report([{"provider": "openai", "model": "gpt-going"}], TODAY)
    assert report["decision"] == "inconclusive"


def test_retirement_report_passes_on_unknown_only(table):
    report = retirement_report([{"provider": "mock", "model": "local"}], TODAY)
    assert report["decision"] == "pass"
    assert report["next_commands"] == []
