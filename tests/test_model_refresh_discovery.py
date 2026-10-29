"""Metadata-only discovery and literal-source coverage for new native routes."""

import json
from datetime import date
from pathlib import Path

import pytest

from llm_preflight.catalog import discover_models
from llm_preflight.source_audit import audit_source_text


@pytest.mark.parametrize(
    "provider,model,base_url",
    [
        ("moonshot", "kimi-k3.1-pro", "https://api.moonshot.ai/v1"),
        ("minimax", "MiniMax-M3.1-Flash", "https://api.minimax.io/v1"),
        ("mistral", "mistral-large-4", "https://api.mistral.ai/v1"),
    ],
)
def test_native_discovery_is_metadata_only_and_remains_a_candidate(
    monkeypatch, provider, model, base_url
):
    seen = []

    def metadata(url, key_env, headers):
        seen.append(url)
        return {"data": [{"id": model}, {"id": "unreviewed-image-model"}]}

    monkeypatch.setattr("llm_preflight.catalog._get_json", metadata)
    rows = discover_models(
        {"provider": provider, "include": "^" + model + "$", "limit": 5}
    )
    assert seen == [base_url + "/models"]
    assert len(rows) == 1
    assert rows[0]["provider"] == provider
    assert rows[0]["catalog_type"] == "text-candidate"
    assert rows[0]["capabilities"]["adapter"] == "openai_compatible_chat"
    assert rows[0]["input_cost_per_million"] >= 0


def test_cohere_discovery_paginates_filters_chat_and_keeps_billed_route(monkeypatch):
    seen = []

    def metadata(url, key_env, headers):
        seen.append(url)
        assert key_env == "COHERE_API_KEY"
        if len(seen) == 1:
            return {
                "models": [{"name": "embed-v4", "endpoints": ["embed"]}],
                "next_page_token": "next page",
            }
        return {
            "models": [
                {
                    "name": "command-a-plus-05-2026",
                    "endpoints": ["chat"],
                    "context_length": 128000,
                }
            ],
            "next_page_token": None,
        }

    monkeypatch.setattr("llm_preflight.catalog._get_json", metadata)
    rows = discover_models({"provider": "cohere", "limit": 5})
    assert len(seen) == 2
    assert seen[0].startswith("https://api.cohere.com/v1/models?")
    assert "page_token=next+page" in seen[1]
    assert [r["model"] for r in rows] == ["command-a-plus-05-2026"]
    assert rows[0]["catalog_type"] == "text-candidate"
    assert rows[0]["capabilities"]["adapter"] == "cohere_chat"


def test_cohere_discovery_refuses_repeating_pagination(monkeypatch):
    monkeypatch.setattr(
        "llm_preflight.catalog._get_json",
        lambda *args: {"models": [], "next_page_token": "repeat"},
    )
    with pytest.raises(ValueError, match="pagination"):
        discover_models({"provider": "cohere", "limit": 5})


@pytest.mark.parametrize(
    "model,provider",
    [
        ("kimi-k3.1-pro", "moonshot"),
        ("moonshot/kimi-k3.1-pro-highspeed", "moonshot"),
        ("MiniMax-M3.1-Flash", "minimax"),
        ("minimax/MiniMax-M3", "minimax"),
        ("mistral-large-4", "mistral"),
        ("mistral/mistral-large-4-0", "mistral"),
        ("command-a-plus-05-2026", "cohere"),
        ("cohere/command-a-plus-05-2026", "cohere"),
    ],
)
def test_source_audit_recognizes_new_native_cohort(model, provider):
    report = audit_source_text(
        Path("app.py"), f'MODEL = "{model}"', today=date(2026, 10, 26)
    )
    assert len(report["references"]) == 1
    reference = report["references"][0]
    assert reference["provider"] == provider
    assert reference["status"] == "pricing_known"
    assert reference["retirement"]["status"] == "unknown"


@pytest.mark.parametrize(
    "model",
    [
        "openrouter/moonshotai/kimi-k3.1-pro",
        "openrouter/mistralai/mistral-large-4",
        "openrouter/cohere/command-a-plus-05-2026",
    ],
)
def test_source_audit_does_not_borrow_native_pricing_for_explicit_routed_ids(model):
    reference = audit_source_text(Path("app.py"), f'MODEL = "{model}"')["references"][0]
    assert reference["provider"] == "openrouter"
    assert reference["status"] == "pricing_unknown"


def test_source_audit_rejects_non_model_command_words():
    report = audit_source_text(
        Path("app.py"), 'a = "command"\nb = "command-line"\nc = "mistral-"\nd = "kimi-"'
    )
    assert report["references"] == []


@pytest.mark.parametrize("provider", ["moonshot", "minimax", "mistral", "cohere"])
def test_catalog_setup_and_environment_template_include_native_provider(
    monkeypatch, tmp_path, provider
):
    import sys

    from llm_preflight import cli
    from llm_preflight.providers import PROVIDER_DEFAULTS

    workspace = tmp_path / "benchmarks"
    monkeypatch.setattr(
        sys,
        "argv",
        ["llm-preflight", "catalog", "init", str(workspace), "--providers", provider],
    )
    cli.main()
    config = json.loads((workspace / "watch.json").read_text())
    assert [source["provider"] for source in config["discovery"]] == [provider]
    assert (
        PROVIDER_DEFAULTS[provider]["api_key_env"]
        in (workspace / ".env.production").read_text()
    )
    assert (
        PROVIDER_DEFAULTS[provider]["api_key_env"] in Path(".env.example").read_text()
    )


@pytest.mark.parametrize("provider", ["moonshot", "minimax", "mistral", "cohere"])
def test_json_preset_reaches_new_native_adapters(provider):
    from llm_preflight.presets import expand_presets

    request = expand_presets({}, ["json"])
    assert request["provider_options"][provider]["response_format"] == {
        "type": "json_object"
    }


@pytest.mark.parametrize(
    "model,provider",
    [("openai/kimi-k3.1-pro", "openai"), ("mistral/command-a-plus-05-2026", "mistral")],
)
def test_explicit_native_prefix_is_not_replaced_by_a_model_family_guess(
    model, provider
):
    reference = audit_source_text(Path("app.py"), f'MODEL = "{model}"')["references"][0]
    assert reference["provider"] == provider
    assert reference["status"] == "pricing_unknown"


def test_cohere_discovery_stops_after_twenty_distinct_pages(monkeypatch):
    calls = []

    def metadata(*args):
        calls.append(args)
        return {"models": [], "next_page_token": f"page-{len(calls)}"}

    monkeypatch.setattr("llm_preflight.catalog._get_json", metadata)
    with pytest.raises(ValueError, match="20-page safety limit"):
        discover_models({"provider": "cohere", "limit": 5})
    assert len(calls) == 20
