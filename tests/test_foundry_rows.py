"""Foundry MAI rows: retirement, tier, deployment_type and the pricing route rule."""

import json
from datetime import date

import pytest

from llm_preflight import migrate, pricing, retirements
from llm_preflight.client import create_client
from llm_preflight.contracts import provenance
from llm_preflight.retirements import (
    FOUNDRY_RETIREMENTS_URL,
    PUBLIC_RETIREMENTS,
    retirement_verdict,
)

AZURE = "https://res.services.ai.azure.com/openai/v1"
MODEL = {
    "provider": "foundry",
    "model": "mai-test",
    "base_url": AZURE,
    "deployment_type": "global",
}


@pytest.fixture
def priced(monkeypatch):
    monkeypatch.setitem(
        pricing.PUBLIC_PRICING, ("foundry", "mai-test"), (1.0, 2.0, "2026-11-19")
    )
    monkeypatch.setitem(
        pricing.PUBLIC_PRICING_SOURCES, ("foundry", "mai-test"), "https://x.test/p"
    )
    monkeypatch.setitem(
        pricing.FOUNDRY_PRICED_DEPLOYMENT_TYPES,
        "mai-test",
        frozenset({"global", "regional"}),
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://res.services.ai.azure.com/openai/v1",
        "https://res.services.ai.azure.com/api/projects/p1/openai/v1/",
        "https://res.openai.azure.com/openai/v1",
    ],
)
def test_foundry_price_applies_on_azure_host_with_matching_deployment_type(priced, url):
    result = pricing.apply_public_pricing({**MODEL, "base_url": url})
    assert result["input_cost_per_million"] == 1.0
    assert result["output_cost_per_million"] == 2.0


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "https://apim.example.com/openai/v1"},
        {"base_url": "https://res.services.ai.azure.com.evil.test/openai/v1"},
        {"base_url": "https://a.b.services.ai.azure.com/openai/v1"},
        {"base_url": "https://res.openai.azure.com/api/projects/p/openai/v1"},
        {"base_url": "https://u@res.services.ai.azure.com/openai/v1"},
        {"base_url": "https://:pw@res.openai.azure.com/openai/v1"},
        {"base_url": "https://u:@res.openai.azure.com/openai/v1"},
        {"base_url": "https://res.services.ai.azure.com:8443/openai/v1"},
        {"base_url": "http://res.services.ai.azure.com/openai/v1"},
        {"deployment_type": "data_zone"},
        {"deployment_type": None},
    ],
)
def test_foundry_price_unknown_for_gateway_host_missing_or_other_deployment_type(
    priced, change
):
    model = {**MODEL, **change}
    if model["deployment_type"] is None:
        del model["deployment_type"]
    result = pricing.apply_public_pricing(model)
    assert "input_cost_per_million" not in result
    assert result["pricing_metadata"]["source"] == "unknown"


def test_foundry_without_a_row_keeps_the_model_unchanged():
    assert pricing.apply_public_pricing(MODEL) == MODEL


@pytest.mark.parametrize("value", ["", "Global", "zone", 1, None])
def test_foundry_rejects_unknown_deployment_type(value):
    with pytest.raises(ValueError, match="deployment_type"):
        create_client({**MODEL, "deployment_type": value}, 10)


@pytest.mark.parametrize("value", ["global", "data_zone", "regional"])
def test_foundry_accepts_each_deployment_type(value):
    create_client({**MODEL, "deployment_type": value}, 10)


def _routes(model):
    config = {"prompt": "hi", "models": [model]}
    return provenance(config, [model], "p")["routes_sha256"]


def test_route_fingerprint_changes_with_deployment_type():
    plain = {k: v for k, v in MODEL.items() if k != "deployment_type"}
    hashes = {
        _routes(plain),
        _routes({**plain, "deployment_type": "global"}),
        _routes({**plain, "deployment_type": "regional"}),
    }
    assert len(hashes) == 3


def test_stray_deployment_type_on_another_provider_keeps_its_hash():
    model = {
        "provider": "openai_compatible",
        "model": "x",
        "base_url": "https://x.test/v1",
    }
    assert _routes({**model, "deployment_type": "global"}) == _routes(model)


def test_mai_thinking_1_retirement_row():
    assert PUBLIC_RETIREMENTS[("foundry", "mai-thinking-1")] == {
        "status": "deprecated",
        "retirement_date": "2027-03-02",
        "as_of": "2026-11-26",
        "source_url": FOUNDRY_RETIREMENTS_URL,
    }
    now = retirement_verdict("foundry", "MAI-Thinking-1", date(2026, 11, 26))
    assert (now["status"], now["decision"]) == ("retiring", "inconclusive")
    assert "replacement" not in now
    last = retirement_verdict("foundry", "MAI-Thinking-1", date(2027, 3, 2))
    assert (last["status"], last["decision"]) == ("retired", "fail")


def test_mai_models_without_an_official_page_row_are_absent():
    assert ("foundry", "mai-code-2") not in PUBLIC_RETIREMENTS
    assert ("foundry", "mai-code-2-flash") not in PUBLIC_RETIREMENTS
    assert ("foundry", "mai-thinking-1") not in pricing.PUBLIC_PRICING


def test_migrate_foundry_replacement_does_not_inherit_deployment_or_type(
    monkeypatch, tmp_path
):
    url = "https://example.test/deprecations"
    monkeypatch.setattr(
        retirements,
        "PUBLIC_RETIREMENTS",
        {
            ("foundry", "mai-old"): {
                "status": "retired",
                "retirement_date": "2026-10-01",
                "replacement": "mai-new",
                "as_of": "2026-11-01",
                "source_url": url,
            },
            ("foundry", "mai-new"): {
                "status": "active",
                "as_of": "2026-11-01",
                "source_url": url,
            },
        },
    )
    model = {
        **MODEL,
        "model": "mai-old",
        "deployment": "prod-mai",
        "deployment_type": "regional",
    }
    path = tmp_path / "bench.json"
    path.write_text(json.dumps({"prompt": "hi", "models": [model]}), encoding="utf-8")
    entry = migrate.build_report(path, date(2026, 11, 5))["models"][0]
    assert entry["outcome"] == "route_base_url"
    assert migrate._row_for(model, entry, [model]) is None


def test_foundry_price_unknown_for_an_out_of_range_or_non_numeric_port(priced):
    for url in (
        "https://res.openai.azure.com:99999/openai/v1",
        "https://res.openai.azure.com:abc/openai/v1",
    ):
        result = pricing.apply_public_pricing({**MODEL, "base_url": url})
        assert result["pricing_metadata"]["source"] == "unknown"


def test_foundry_price_lookup_ignores_the_case_of_the_model_id(priced):
    lower = pricing.apply_public_pricing(MODEL)
    mixed = pricing.apply_public_pricing({**MODEL, "model": "MAI-Test"})
    assert lower["input_cost_per_million"] == 1.0
    assert mixed["input_cost_per_million"] == lower["input_cost_per_million"]
    assert mixed["output_cost_per_million"] == lower["output_cost_per_million"]
