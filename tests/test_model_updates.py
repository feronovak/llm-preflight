"""Published model changes must reach the CLI's trust and cost decisions."""

import json
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

from llm_preflight import cli
from llm_preflight.pricing import (
    apply_public_pricing,
    estimate_sample_cost,
    pricing_coverage_report,
    resolve_pricing,
)
from llm_preflight.retirements import PUBLIC_RETIREMENTS, retirement_verdict

OPENAI_RETIRING = (
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o-2024-08-06",
    "gpt-4o-2024-11-20",
    "gpt-4o-mini-2024-07-18",
    "gpt-4.1-2025-04-14",
    "gpt-4.1-mini-2025-04-14",
)


@pytest.mark.parametrize("model", OPENAI_RETIRING)
def test_october_openai_snapshots_have_the_published_shutdown_boundary(model):
    before = retirement_verdict("openai", model, date(2026, 10, 14))
    assert before["status"] == "retiring"
    assert before["decision"] == "inconclusive"
    assert before["retirement_date"] == "2027-01-14"
    assert before["replacement"] == "gpt-6-luna"
    assert PUBLIC_RETIREMENTS[("openai", model)]["source_url"] == (
        "https://developers.openai.com/api/docs/deprecations"
    )
    on_shutdown = retirement_verdict("openai", model, date(2027, 1, 14))
    assert on_shutdown["status"] == "retired"
    assert on_shutdown["decision"] == "fail"


def test_older_openai_retirements_keep_their_dates_and_drop_deprecated_replacements():
    assert (
        PUBLIC_RETIREMENTS[("openai", "gpt-4o-2024-05-13")]["retirement_date"]
        == "2026-10-23"
    )
    for model in (
        "gpt-4.5-preview",
        "gpt-4-32k",
        "gpt-4-32k-0314",
        "gpt-4-32k-0613",
        "gpt-4-vision-preview",
        "gpt-4-1106-vision-preview",
    ):
        assert "replacement" not in PUBLIC_RETIREMENTS[("openai", model)]


def test_openai_retirement_reaches_source_audit_ci(monkeypatch, tmp_path, capsys):
    (tmp_path / "app.py").write_text('MODEL = "gpt-4.1-2025-04-14"\n')
    monkeypatch.setattr(cli, "today_utc", lambda: date(2026, 10, 14))
    monkeypatch.setattr(
        sys,
        "argv",
        ["llm-preflight", "--audit-source", str(tmp_path), "--ci", "--json"],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 3
    report = json.loads(capsys.readouterr().out)
    assert report["decision"] == "inconclusive"
    assert report["references"][0]["retirement"]["replacement"] == "gpt-6-luna"


@pytest.mark.parametrize(
    "model,replacement",
    [
        ("gemini-3.5-flash", "gemini-3.6-flash"),
        ("gemini-3.7-flash", "gemini-3.8-flash"),
    ],
)
def test_deprecated_gemini_aliases_report_redirects_without_inventing_shutdown(
    model, replacement
):
    verdict = retirement_verdict("gemini", model, date(2026, 10, 14))
    assert verdict["status"] == "retiring"
    assert verdict["decision"] == "inconclusive"
    assert verdict["replacement"] == replacement
    assert verdict["replacement_status"] == "active"
    assert "retirement_date" not in verdict
    assert "automatically route" in verdict["reason"]
    assert "not shutting down" in verdict["reason"]
    assert "to be announced" not in verdict["reason"]


@pytest.mark.parametrize(
    "model", ["gemini-4-argon", "gemini-3.6-flash", "gemini-3.8-flash"]
)
def test_current_gemini_models_have_reviewed_active_rows(model):
    verdict = retirement_verdict("gemini", model, date(2026, 10, 14))
    assert verdict["status"] == "active"
    assert verdict["decision"] == "pass"
    assert "retirement_date" not in verdict


def test_gemini_redirect_reaches_source_audit_ci(monkeypatch, tmp_path, capsys):
    (tmp_path / "app.py").write_text('MODEL = "gemini-3.5-flash"\n')
    monkeypatch.setattr(cli, "today_utc", lambda: date(2026, 10, 14))
    monkeypatch.setattr(
        sys,
        "argv",
        ["llm-preflight", "--audit-source", str(tmp_path), "--ci", "--json"],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 3
    report = json.loads(capsys.readouterr().out)
    assert report["decision"] == "inconclusive"
    assert "automatically route" in report["references"][0]["retirement"]["reason"]


def test_current_smoke_examples_choose_direct_gemini_routes():
    for name in ("approved-smoke", "cross-provider-run"):
        config = json.loads((Path("examples") / f"{name}.json").read_text())
        models = [m for m in config["models"] if m.get("provider") == "gemini"]
        assert models and all(m["model"] == "gemini-3.8-flash" for m in models)
        assert all(m.get("name", m["model"]) == "gemini-3.8-flash" for m in models)


def pricing_day(monkeypatch, day):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(day.year, day.month, day.day, tzinfo=tz)

    monkeypatch.setattr("llm_preflight.pricing.datetime", Clock)


@pytest.mark.parametrize(
    "day,rates",
    [
        (date(2026, 10, 13), (2, 10, 0.1)),
        (date(2026, 11, 30), (2, 10, 0.1)),
        (date(2026, 12, 1), (4, 20, 0.2)),
    ],
)
def test_gemini_4_pricing_switches_on_the_published_date(monkeypatch, day, rates):
    pricing_day(monkeypatch, day)
    model = apply_public_pricing({"provider": "gemini", "model": "gemini-4-argon"})
    assert (
        tuple(
            model[k]
            for k in (
                "input_cost_per_million",
                "output_cost_per_million",
                "cached_input_cost_per_million",
            )
        )
        == rates
    )
    assert model["pricing_metadata"]["as_of"] == "2026-10-26"
    assert (
        model["pricing_metadata"]["source_url"]
        == "https://ai.google.dev/gemini-api/docs/pricing"
    )
    assert estimate_sample_cost(
        {"input_tokens": 1000, "cached_input_tokens": 800, "output_tokens": 100}, model
    ) == pytest.approx((200 * rates[0] + 800 * rates[2] + 100 * rates[1]) / 1_000_000)


@pytest.mark.parametrize("model", ["gemini-3.6-flash", "gemini-3.8-flash"])
@pytest.mark.parametrize(
    "day,rates",
    [
        (date(2026, 12, 31), (0.75, 3.75, 0.075)),
        (date(2027, 1, 1), (1.5, 7.5, 0.15)),
    ],
)
def test_current_flash_routes_switch_introductory_prices(
    monkeypatch, model, day, rates
):
    pricing_day(monkeypatch, day)
    priced = apply_public_pricing({"provider": "gemini", "model": model})
    assert (
        tuple(
            priced[k]
            for k in (
                "input_cost_per_million",
                "output_cost_per_million",
                "cached_input_cost_per_million",
            )
        )
        == rates
    )


@pytest.mark.parametrize("model", ["gemini-3.5-flash", "gemini-3.7-flash"])
@pytest.mark.parametrize("persisted", [False, True])
def test_redirected_gemini_prices_are_unknown_including_persisted_official_rates(
    model, persisted
):
    config = {"provider": "gemini", "model": model}
    if persisted:
        config.update(
            input_cost_per_million=1.5,
            output_cost_per_million=9,
            cached_input_cost_per_million=0.15,
            pricing_metadata={"source": "official snapshot", "as_of": "2026-09-28"},
        )
    resolved = resolve_pricing([config])
    assert (
        pricing_coverage_report(resolved["models"], today=date(2026, 10, 13))["models"][
            0
        ]["status"]
        == "unknown"
    )
    assert (
        estimate_sample_cost(
            {"input_tokens": 1000, "output_tokens": 100}, resolved["models"][0]
        )
        is None
    )
    if persisted:
        assert config["input_cost_per_million"] == 1.5


def test_explicit_reviewed_price_override_for_redirected_gemini_is_preserved():
    config = {
        "provider": "gemini",
        "model": "gemini-3.5-flash",
        "input_cost_per_million": 0.75,
        "output_cost_per_million": 3.75,
        "pricing_metadata": {"source": "user override", "as_of": "2026-10-13"},
    }
    assert apply_public_pricing(config) == config


def test_gemini_4_example_is_a_bounded_fixture_verified_plan(snapshot_review_day):
    from llm_preflight.catalog import resolve_models
    from llm_preflight.client import create_client
    from llm_preflight.contracts import check_contract
    from llm_preflight.features import check_budget
    from llm_preflight.runner import load_config, validate_config_validations

    config = load_config(Path("examples/gemini-4-argon.json"))
    models = resolve_models(config)
    assert len(models) == 1 and models[0]["model"] == "gemini-4-argon"
    assert config["max_requests"] == 1
    assert config["repetitions"] == 1 and config["warmups"] == 0
    assert config["request"]["retry"]["max_attempts"] == 1
    assert config["request"]["max_output_tokens"] == 32768
    assert config["max_estimated_cost_usd"] == 0.35
    assert config["require_current_pricing"] is True
    validate_config_validations(config)
    assert check_contract(config)["ok"] is True
    assert (
        pricing_coverage_report(
            models, today=date(2026, 10, 26), require_current_pricing=True
        )["enforcement_ok"]
        is True
    )
    assert check_budget(config)["possible_requests"] == 1
    assert create_client(models[0], 10).body(config["prompt"], config["request"])[
        "generationConfig"
    ] == {"maxOutputTokens": 32768, "thinkingConfig": {"thinkingLevel": "LOW"}}


def test_release_freshness_covers_gemini_4_example():
    import runpy

    script = runpy.run_path("scripts/release_freshness.py")
    assert "gemini-4-argon" in script["EXAMPLES"]


@pytest.mark.parametrize(
    "model_id,input_rate,cache_rate,output_rate",
    [
        ("gpt-5.6-luna", 0.2, 0.02, 1.2),
        ("gpt-5.6-terra", 2, 0.2, 12),
        ("gpt-5.6-sol", 4, 0.4, 20),
        ("gpt-6-astra", 10, 1, 50),
        ("gpt-6-sol", 2, 0.2, 10),
        ("gpt-6-luna", 0.1, 0.01, 0.5),
    ],
)
@pytest.mark.parametrize("total_input", [272000, 272001])
@pytest.mark.parametrize("cache_write", [0, 1000])
def test_published_openai_cache_writes_use_the_full_request_context_boundary(
    model_id, input_rate, cache_rate, output_rate, total_input, cache_write
):
    model = apply_public_pricing({"provider": "openai", "model": model_id})
    sample = {
        "input_tokens": total_input,
        "cached_input_tokens": 10000,
        "cache_write_input_tokens": cache_write,
        "output_tokens": 1000,
    }
    if total_input > 272000:
        input_rate *= 2
        cache_rate *= 2
        output_rate *= 1.5
    write_rate = input_rate * 1.25
    expected = (
        (total_input - 10000 - cache_write) * input_rate
        + 10000 * cache_rate
        + cache_write * write_rate
        + 1000 * output_rate
    ) / 1_000_000
    assert estimate_sample_cost(sample, model) == pytest.approx(expected)
    assert model["pricing_metadata"]["as_of"] == "2026-10-26"


@pytest.mark.parametrize(
    "model_id,input_rate,output_rate",
    [
        ("gpt-5.6-luna", 0.2, 1.2),
        ("gpt-5.6-terra", 2, 12),
        ("gpt-5.6-sol", 4, 20),
        ("gpt-6-astra", 10, 50),
        ("gpt-6-sol", 2, 10),
        ("gpt-6-luna", 0.1, 0.5),
    ],
)
def test_published_openai_cache_write_budget_includes_premium_and_long_context(
    snapshot_review_day,
    model_id,
    input_rate,
    output_rate,
):
    from llm_preflight.features import estimate_budget

    model = apply_public_pricing({"provider": "openai", "model": model_id})
    config = {
        "prompt": "a" * 1088004,
        "repetitions": 1,
        "warmups": 0,
        "request": {"max_output_tokens": 1000, "retry": {"max_attempts": 1}},
    }
    budget = estimate_budget(config, [model])
    assert budget["maximum_estimated_cost_usd"] == pytest.approx(
        (272001 * input_rate * 2 * 1.25 + 1000 * output_rate * 1.5) / 1_000_000
    )


@pytest.mark.parametrize(
    "model,replacement",
    [("gpt-5.4-nano-2026-03-17", "gpt-6-luna"), ("gpt-5.1-2025-11-13", "gpt-6-sol")],
)
def test_october_dated_openai_ids_reach_their_announced_retirement_boundary(
    model, replacement
):
    before = retirement_verdict("openai", model, date(2027, 3, 31))
    # Expired review evidence still carries the published retirement date.
    assert before["status"] == "stale"
    assert before["retirement_date"] == "2027-04-01"
    assert before["replacement"] == replacement
    after = retirement_verdict("openai", model, date(2027, 4, 1))
    assert after["status"] == "retired"
    assert after["decision"] == "fail"


def test_current_release_refreshes_every_reviewed_snapshot_row():
    from llm_preflight.pricing import PUBLIC_PRICING

    assert {rates[2] for rates in PUBLIC_PRICING.values()} == {"2026-10-26"}
    assert {row["as_of"] for row in PUBLIC_RETIREMENTS.values()} == {"2026-10-26"}


def test_current_typesafe_catalog_snapshot_is_priced_but_not_text_callable():
    from llm_preflight.catalog import classify_catalog_model
    from llm_preflight.client import create_client

    model = classify_catalog_model(
        apply_public_pricing({"provider": "typesafe", "model": "jev-1.14.0"})
    )
    assert model["input_cost_per_million"] == 0.042
    assert model["output_cost_per_million"] == 0
    assert model["catalog_type"] == "decision"
    with pytest.raises(ValueError, match="incompatible"):
        create_client(model, 10)
