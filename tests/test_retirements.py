import re
from datetime import date, datetime, timedelta, timezone

import pytest

from llm_preflight import retirements
from llm_preflight.retirements import (
    ANTHROPIC_DEPRECATIONS_URL,
    GEMINI_DEPRECATIONS_URL,
    GEMINI_MODEL_REDIRECTS,
    OPENAI_DEPRECATIONS_URL,
    PUBLIC_RETIREMENTS,
    RETIREMENT_PROVIDERS,
    retirement_report,
    retirement_verdict,
    snapshot_summary,
    unique_next_commands,
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
    ("openai", "gpt-aged-30"): {
        "status": "active",
        "as_of": "2026-09-09",
        "source_url": URL,
    },
    ("openai", "gpt-aged-31"): {
        "status": "active",
        "as_of": "2026-09-08",
        "source_url": URL,
    },
    ("openai", "gpt-unlisted-successor"): {
        "status": "deprecated",
        "retirement_date": "2027-04-01",
        "replacement": "gpt-without-a-row",
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
    assert "anthropic, gemini, openai" in verdict["next_step"]
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
    assert "no single replacement recorded" in verdict["next_step"]


def test_retired_row_without_replacement_says_so(table):
    verdict = retirement_verdict("openai", "gpt-no-replacement", TODAY)
    assert verdict["status"] == "retired"
    assert "replacement" not in verdict
    assert (
        "no single replacement recorded; read the page, choose one and preflight it"
        in verdict["next_step"]
    )
    assert "next_command" not in verdict


def test_stale_row_is_inconclusive_and_points_at_the_page(table):
    verdict = retirement_verdict("openai", "gpt-old-row", TODAY)
    assert verdict["status"] == "stale"
    assert verdict["decision"] == "inconclusive"
    assert "older than 30 days" in verdict["reason"]
    assert "update llm-preflight or review" in verdict["next_step"]


def test_row_aged_exactly_the_window_is_not_stale_and_one_day_more_is(table):
    assert (TODAY - date(2026, 9, 9)).days == 30
    assert retirement_verdict("openai", "gpt-aged-30", TODAY)["status"] == "active"
    assert (TODAY - date(2026, 9, 8)).days == 31
    verdict = retirement_verdict("openai", "gpt-aged-31", TODAY)
    assert verdict["status"] == "stale"
    assert verdict["decision"] == "inconclusive"


def test_replacement_without_a_row_of_its_own_is_unknown_not_active(table):
    verdict = retirement_verdict("openai", "gpt-unlisted-successor", TODAY)
    assert verdict["replacement"] == "gpt-without-a-row"
    assert verdict["replacement_status"] == "unknown"
    assert "is itself" not in verdict["next_step"]


def test_stale_row_with_a_past_date_is_still_retired(table):
    verdict = retirement_verdict("openai", "gpt-old-row-retired", TODAY)
    assert verdict["status"] == "retired"
    assert verdict["decision"] == "fail"
    assert "older than 30 days" in verdict["reason"]


def test_stale_reasons_do_not_change_from_one_day_to_the_next(table):
    models = [
        {"provider": "openai", "model": "gpt-old-row"},
        {"provider": "openai", "model": "gpt-old-row-retired"},
    ]
    assert retirement_report(models, date(2026, 11, 20)) == retirement_report(
        models, date(2026, 11, 21)
    )


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


def test_unique_next_commands_keeps_first_seen_order_and_skips_verdicts_without_one():
    verdicts = [
        {"status": "retired", "next_command": "first"},
        {"status": "active"},
        {"status": "retiring", "next_command": "second"},
        {"status": "retired", "next_command": "first"},
    ]
    assert unique_next_commands(verdicts) == ["first", "second"]
    assert unique_next_commands([]) == []


def test_routed_prefix_resolves_to_the_catalogue_id(table):
    verdict = retirement_verdict("openai", "openai/gpt-gone", TODAY)
    assert verdict["status"] == "retired"
    assert "--models openai:gpt-gone,openai:gpt-new" in verdict["next_command"]


def test_every_snapshot_row_is_well_formed():
    assert PUBLIC_RETIREMENTS, "snapshot must not be empty"
    from llm_preflight.retirements import GEMINI_DEPRECATIONS_URL

    for (provider, model), row in PUBLIC_RETIREMENTS.items():
        assert provider in RETIREMENT_PROVIDERS, model
        assert _provider_for(model) == provider, model
        assert _MODEL_PREFIX.match(model), model
        assert row["status"] in {"active", "deprecated", "retired"}, model
        date.fromisoformat(row["as_of"])
        assert (
            row["source_url"]
            in {
                "anthropic": {ANTHROPIC_DEPRECATIONS_URL},
                "openai": {OPENAI_DEPRECATIONS_URL},
                "gemini": {
                    GEMINI_DEPRECATIONS_URL,
                    "https://aistudio.google.com/docs/models/gemini-4-argon",
                },
            }[provider]
        ), model
        assert set(row) <= {
            "status",
            "retirement_date",
            "replacement",
            "as_of",
            "source_url",
            "redirected",
            "routes_to",
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
        "as_of": "2026-11-04",
        "source_url": ANTHROPIC_DEPRECATIONS_URL,
    }
    assert PUBLIC_RETIREMENTS[("anthropic", "claude-mythos-preview")] == {
        "status": "deprecated",
        "as_of": "2026-11-04",
        "source_url": ANTHROPIC_DEPRECATIONS_URL,
    }
    assert PUBLIC_RETIREMENTS[("anthropic", "claude-sonnet-5-5")]["status"] == "active"
    assert PUBLIC_RETIREMENTS[("openai", "gpt-5.4-cyber")] == {
        "status": "deprecated",
        "retirement_date": "2026-10-01",
        "as_of": "2026-11-04",
        "source_url": OPENAI_DEPRECATIONS_URL,
    }
    assert PUBLIC_RETIREMENTS[("openai", "gpt-5.5-cyber-preview")] == {
        "status": "deprecated",
        "retirement_date": "2027-02-01",
        "as_of": "2026-11-12",
        "source_url": OPENAI_DEPRECATIONS_URL,
    }
    assert PUBLIC_RETIREMENTS[("openai", "gpt-5.1")] == {
        "status": "deprecated",
        "retirement_date": "2027-04-01",
        "replacement": "gpt-6-sol",
        "as_of": "2026-11-04",
        "source_url": OPENAI_DEPRECATIONS_URL,
    }
    assert PUBLIC_RETIREMENTS[("openai", "gpt-4-1106-preview")] == {
        "status": "deprecated",
        "retirement_date": "2026-10-23",
        "replacement": "gpt-5.6-sol",
        "as_of": "2026-11-04",
        "source_url": OPENAI_DEPRECATIONS_URL,
    }
    assert "replacement" not in PUBLIC_RETIREMENTS[("openai", "o1-pro")]
    # o3's only dated snapshot retires 2026-12-11, so it is not a replacement.
    assert "replacement" not in PUBLIC_RETIREMENTS[("openai", "o1-preview")]
    assert PUBLIC_RETIREMENTS[("anthropic", "claude-fable-5-2")] == {
        "status": "active",
        "as_of": "2026-11-09",
        "source_url": ANTHROPIC_DEPRECATIONS_URL,
    }
    providers = {provider for provider, _ in PUBLIC_RETIREMENTS}
    assert providers == {"anthropic", "gemini", "openai"}
    assert sum(1 for p, _ in PUBLIC_RETIREMENTS if p == "anthropic") == 38
    assert sum(1 for p, _ in PUBLIC_RETIREMENTS if p == "openai") == 76
    assert sum(1 for p, _ in PUBLIC_RETIREMENTS if p == "gemini") == 6


@pytest.mark.parametrize("model", ["claude-fable-5-2", "claude-mythos-5-2"])
def test_claude_5_2_rows_are_active_and_dated_per_row(model):
    assert PUBLIC_RETIREMENTS[("anthropic", model)] == {
        "status": "active",
        "as_of": "2026-11-09",
        "source_url": ANTHROPIC_DEPRECATIONS_URL,
    }


def test_gpt_5_5_cyber_preview_is_retiring_without_replacement():
    model = "gpt-5.5-cyber-preview"
    row = PUBLIC_RETIREMENTS[("openai", model)]
    assert row["as_of"] == "2026-11-12"
    assert row["source_url"] == OPENAI_DEPRECATIONS_URL
    now = retirement_verdict("openai", model, date(2026, 11, 12))
    assert (now["status"], now["decision"]) == ("retiring", "inconclusive")
    assert "replacement" not in now
    assert (
        retirement_verdict("openai", model, date(2026, 12, 12))["status"] == "retiring"
    )
    last = retirement_verdict("openai", model, date(2027, 2, 1))
    assert (last["status"], last["decision"]) == ("retired", "fail")
    assert retirement_verdict("openai", model, date(2026, 12, 13))["status"] == "stale"
    assert retirement_verdict("openai", "gpt-5.5", date(2026, 11, 12))["status"] == (
        "unknown"
    )


def test_gemini_3_1_flash_lite_retires_on_2027_05_07():
    assert PUBLIC_RETIREMENTS[("gemini", "gemini-3.1-flash-lite")] == {
        "status": "deprecated",
        "retirement_date": "2027-05-07",
        "replacement": "gemini-3.5-flash-lite",
        "as_of": "2026-11-04",
        "source_url": GEMINI_DEPRECATIONS_URL,
    }
    now = retirement_verdict("gemini", "gemini-3.1-flash-lite", date(2026, 11, 4))
    assert (now["status"], now["decision"]) == ("retiring", "inconclusive")
    assert now["replacement"] == "gemini-3.5-flash-lite"
    after = retirement_verdict("gemini", "gemini-3.1-flash-lite", date(2027, 5, 7))
    assert after["status"] == "retired"
    assert after["decision"] == "fail"


def test_gemini_alias_rows_are_active_and_carry_their_route():
    for model, route in GEMINI_MODEL_REDIRECTS.items():
        row = PUBLIC_RETIREMENTS[("gemini", model)]
        assert row["status"] == "active"
        assert row["redirected"] is True
        assert row["routes_to"] == route
        assert "replacement" not in row
        assert row["as_of"] == "2026-11-04"
    assert ("gemini", "gemini-3.1-pro-preview") not in PUBLIC_RETIREMENTS


def test_snapshot_summary_reports_coverage_and_dates():
    summary = snapshot_summary()
    assert summary["providers"] == ["anthropic", "gemini", "openai"]
    assert summary["rows"] == len(PUBLIC_RETIREMENTS)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", summary["oldest_as_of"])
    assert summary["oldest_as_of"] <= summary["newest_as_of"]


def test_snapshot_valid_until_is_oldest_row_plus_window(table):
    summary = snapshot_summary()
    oldest = date.fromisoformat(summary["oldest_as_of"])
    assert (
        summary["valid_until"]
        == (oldest + timedelta(days=retirements.DEFAULT_MAX_AGE_DAYS)).isoformat()
    )
    # Last valid day: one day later the row is stale.
    on_limit = date.fromisoformat(summary["valid_until"])
    assert retirement_verdict("openai", "gpt-old-row", on_limit)["status"] != "stale"
    day_after = on_limit + timedelta(days=1)
    assert retirement_verdict("openai", "gpt-old-row", day_after)["status"] == "stale"


def test_report_valid_until_comes_from_the_selected_rows_only(table):
    selected = retirement_report([{"provider": "openai", "model": "gpt-new"}], TODAY)
    row_date = date.fromisoformat(TABLE[("openai", "gpt-new")]["as_of"])
    expected = (row_date + timedelta(days=retirements.DEFAULT_MAX_AGE_DAYS)).isoformat()
    assert selected["snapshot"]["valid_until"] == expected
    unknown = retirement_report([{"provider": "mock", "model": "local"}], TODAY)
    assert "valid_until" not in unknown["snapshot"]


def test_report_valid_until_ignores_retired_rows(monkeypatch):
    def row(status, as_of, **extra):
        return {"status": status, "as_of": as_of, "source_url": URL, **extra}

    monkeypatch.setattr(
        retirements,
        "PUBLIC_RETIREMENTS",
        {
            ("openai", "gpt-gone"): row(
                "deprecated", "2026-10-01", retirement_date="2026-10-02"
            ),
            ("openai", "gpt-new"): row("active", "2026-10-06"),
        },
    )
    gone = {"provider": "openai", "model": "gpt-gone"}
    new = {"provider": "openai", "model": "gpt-new"}
    only_retired = retirement_report([gone], TODAY)
    assert only_retired["models"][0]["status"] == "retired"
    assert "valid_until" not in only_retired["snapshot"]
    mixed = retirement_report([gone, new], TODAY)
    assert mixed["snapshot"]["valid_until"] == "2026-11-05"


def test_expiry_notice_says_1_day_not_1_days():
    notice = retirements.expiry_notice({"valid_until": "2026-12-04"}, date(2026, 12, 3))
    assert "(1 day left)" in notice


def test_expiry_notice_appears_7_days_before_and_not_8():
    snapshot = {"valid_until": "2026-12-04"}
    assert "valid until 2026-12-04" in retirements.expiry_notice(
        snapshot, date(2026, 11, 27)
    )
    assert retirements.expiry_notice(snapshot, date(2026, 11, 26)) is None
    assert "0 days left" in retirements.expiry_notice(snapshot, date(2026, 12, 4))
    assert retirements.expiry_notice(snapshot, date(2026, 12, 5)) is None


def test_worst_decision_orders_fail_over_inconclusive_over_pass():
    assert worst_decision(["pass", "inconclusive", "fail"]) == "fail"
    assert worst_decision(["pass", "none", "inconclusive"]) == "inconclusive"
    assert worst_decision(["none", "pass"]) == "pass"
    assert worst_decision([]) == "none"
    assert worst_decision(["none"]) == "none"


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
        "alias_unmapped": 0,
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
    assert report["snapshot"]["providers"] == ["anthropic", "gemini", "openai"]


def test_retirement_report_is_inconclusive_without_a_retired_model(table):
    report = retirement_report([{"provider": "openai", "model": "gpt-going"}], TODAY)
    assert report["decision"] == "inconclusive"


def test_retirement_report_reports_none_on_unknown_only(table):
    report = retirement_report([{"provider": "mock", "model": "local"}], TODAY)
    assert report["decision"] == "none"
    assert report["next_commands"] == []


def test_today_utc_reads_the_utc_calendar_date_like_the_pricing_snapshot(
    monkeypatch,
):
    seen = []

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            seen.append(tz)
            return datetime(2026, 10, 9, 23, 30, tzinfo=timezone.utc)

    monkeypatch.setattr(retirements, "datetime", _Clock)

    assert retirements.today_utc() == date(2026, 10, 9)
    assert seen == [timezone.utc]


def test_no_recorded_replacement_is_itself_deprecated_or_retired():
    # A next command must never compare against a model that is going away;
    # such rows are recorded without a replacement.
    chained = sorted(
        (provider, model, row["replacement"])
        for (provider, model), row in PUBLIC_RETIREMENTS.items()
        if "replacement" in row
        and PUBLIC_RETIREMENTS.get((provider, row["replacement"]), {}).get("status")
        in {"deprecated", "retired"}
    )
    assert chained == []


def test_release_retirement_review_date_and_exact_freshness_boundary():
    summary = snapshot_summary()
    assert summary["oldest_as_of"] == "2026-11-04"
    assert summary["newest_as_of"] == "2026-11-12"
    assert (
        retirement_verdict("anthropic", "claude-sonnet-5-5", date(2026, 12, 4))[
            "decision"
        ]
        == "pass"
    )
    assert (
        retirement_verdict("anthropic", "claude-sonnet-5-5", date(2026, 12, 5))[
            "decision"
        ]
        == "inconclusive"
    )
    assert (
        retirement_verdict("anthropic", "claude-3-haiku-20240307", date(2026, 12, 5))[
            "decision"
        ]
        == "fail"
    )


def _alias_row(status, retirement_date=None, replacement=None, as_of="2026-10-01"):
    row = {"status": status, "as_of": as_of, "source_url": URL}
    if retirement_date:
        row["retirement_date"] = retirement_date
    if replacement:
        row["replacement"] = replacement
    return row


ALIAS_TABLE = {
    ("anthropic", "claude-opus-4-1-20250805"): _alias_row(
        "retired", "2026-08-05", "claude-opus-new"
    ),
    ("anthropic", "claude-sonnet-4-20250514"): _alias_row(
        "retired", "2026-06-15", "claude-sonnet-new"
    ),
    ("anthropic", "claude-3-7-sonnet-20250219"): _alias_row(
        "retired", "2026-02-19", "claude-sonnet-new"
    ),
    ("anthropic", "claude-split-20250101"): _alias_row("retired", "2026-01-01"),
    ("anthropic", "claude-split-20250201"): _alias_row("active"),
    ("anthropic", "claude-datesplit-20250101"): _alias_row("retired", "2026-01-01"),
    ("anthropic", "claude-datesplit-20250201"): _alias_row("retired", "2026-02-01"),
    ("anthropic", "claude-replsplit-20250101"): _alias_row(
        "retired", "2026-01-01", "a"
    ),
    ("anthropic", "claude-replsplit-20250201"): _alias_row(
        "retired", "2026-01-01", "b"
    ),
    ("anthropic", "claude-aged-20250101"): _alias_row("active"),
    ("anthropic", "claude-aged-20250201"): _alias_row("active", as_of="2026-08-01"),
    ("anthropic", "claude-twin-20250101"): _alias_row("retired", "2026-01-01"),
    ("anthropic", "claude-twin-20250201"): _alias_row("retired", "2026-01-01"),
    ("openai", "gpt-4o"): _alias_row("deprecated", "2027-01-14", "gpt-new"),
    ("openai", "gpt-4o-2024-08-06"): _alias_row("deprecated", "2027-02-01", "gpt-new"),
    ("openai", "gpt-4"): _alias_row("deprecated", "2026-10-01", "gpt-new"),
    ("openai", "gpt-5-2025-08-07"): _alias_row("deprecated", "2026-12-11"),
    ("openai", "gpt-5-mini-2025-08-07"): _alias_row("deprecated", "2026-12-11"),
    ("openai", "o3-2025-04-16"): _alias_row("deprecated", "2026-12-11"),
    ("openai", "o3-mini-2025-01-31"): _alias_row("deprecated", "2026-10-23"),
}
ALIAS_TODAY = date(2026, 10, 9)


@pytest.fixture
def alias_table(monkeypatch):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", ALIAS_TABLE)


@pytest.mark.parametrize(
    ("model", "matched", "replacement"),
    [
        ("claude-opus-4-1", "claude-opus-4-1-20250805", "claude-opus-new"),
        ("claude-sonnet-4-0", "claude-sonnet-4-20250514", "claude-sonnet-new"),
        ("claude-3-7-sonnet-latest", "claude-3-7-sonnet-20250219", "claude-sonnet-new"),
        ("Claude-Opus-4-1", "claude-opus-4-1-20250805", "claude-opus-new"),
        ("claude-twin", "claude-twin-20250101", None),
    ],
)
def test_anthropic_alias_resolves_to_dated_row_verdict(
    alias_table, model, matched, replacement
):
    verdict = retirement_verdict("anthropic", model, ALIAS_TODAY)
    assert verdict["status"] == "retired"
    assert verdict["decision"] == "fail"
    assert verdict["matched_id"] == matched
    assert verdict.get("replacement") == replacement


def test_alias_with_agreeing_rows_reviewed_on_different_days_is_stale(alias_table):
    verdict = retirement_verdict("anthropic", "claude-aged", ALIAS_TODAY)
    assert verdict["matched_id"] == "claude-aged-20250201"
    assert verdict["status"] == "stale"
    assert verdict["decision"] == "inconclusive"


def test_alias_next_command_names_the_alias_the_user_wrote(alias_table):
    verdict = retirement_verdict("anthropic", "claude-opus-4-1", ALIAS_TODAY)
    assert (
        "anthropic:claude-opus-4-1,anthropic:claude-opus-new"
        in (verdict["next_command"])
    )


def test_model_id_case_variant_resolves_to_row(alias_table):
    verdict = retirement_verdict("openai", "GPT-4", ALIAS_TODAY)
    assert verdict["status"] == "retired"
    assert "matched_id" not in verdict


def test_explicit_alias_row_wins_over_stem(alias_table):
    verdict = retirement_verdict("openai", "gpt-4o", ALIAS_TODAY)
    assert verdict["status"] == "retiring"
    assert verdict["retirement_date"] == "2027-01-14"
    assert "matched_id" not in verdict


@pytest.mark.parametrize(
    "stem", ["claude-split", "claude-datesplit", "claude-replsplit"]
)
def test_anthropic_alias_with_disagreeing_rows_is_alias_unmapped(alias_table, stem):
    verdict = retirement_verdict("anthropic", stem, ALIAS_TODAY)
    assert verdict["status"] == "alias_unmapped"
    assert verdict["decision"] == "inconclusive"
    assert verdict["alias_candidates"] == [
        f"{stem}-20250101",
        f"{stem}-20250201",
    ]
    assert "retirement_date" not in verdict


@pytest.mark.parametrize(
    ("model", "candidates"),
    [
        ("gpt-5", ["gpt-5-2025-08-07"]),
        ("o3", ["o3-2025-04-16"]),
        ("O3", ["o3-2025-04-16"]),
    ],
)
def test_openai_alias_without_own_row_is_alias_unmapped(alias_table, model, candidates):
    verdict = retirement_verdict("openai", model, ALIAS_TODAY)
    assert verdict["status"] == "alias_unmapped"
    assert verdict["decision"] == "inconclusive"
    assert verdict["alias_candidates"] == candidates


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("openai", "gpt-nothing"),
        ("openai", "o3-pro"),
        ("anthropic", "claude-nothing-latest"),
        ("anthropic", "claude-opus"),
        ("gemini", "gpt-5"),
        (None, "claude-opus-4-1"),
    ],
)
def test_unrelated_id_stays_unknown(alias_table, provider, model):
    verdict = retirement_verdict(provider, model, ALIAS_TODAY)
    assert verdict["status"] == "unknown"
    assert verdict["decision"] == "none"


def test_report_summary_counts_alias_unmapped(alias_table):
    report = retirement_report([{"provider": "openai", "model": "gpt-5"}], ALIAS_TODAY)
    assert report["summary"]["alias_unmapped"] == 1
    assert report["decision"] == "inconclusive"


def test_snapshot_valid_until_uses_oldest_of_rows_reviewed_on_different_days(
    monkeypatch,
):
    def row(as_of):
        return {"status": "active", "as_of": as_of, "source_url": URL}

    monkeypatch.setattr(
        retirements,
        "PUBLIC_RETIREMENTS",
        {
            ("openai", "gpt-older"): row("2026-10-01"),
            ("openai", "gpt-newer"): row("2026-10-06"),
        },
    )
    report = retirement_report(
        [
            {"provider": "openai", "model": "gpt-newer"},
            {"provider": "openai", "model": "gpt-older"},
        ],
        TODAY,
    )
    oldest = date.fromisoformat("2026-10-01")
    expected = (oldest + timedelta(days=retirements.DEFAULT_MAX_AGE_DAYS)).isoformat()
    assert report["snapshot"]["valid_until"] == expected
