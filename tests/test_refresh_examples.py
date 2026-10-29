"""Every advertised new native example has bounded, complete local fixtures."""

from pathlib import Path

import pytest

from llm_preflight.catalog import resolve_models
from llm_preflight.client import create_client
from llm_preflight.contracts import check_contract
from llm_preflight.features import estimate_budget
from llm_preflight.runner import load_config, validate_config_validations

EXAMPLES = [
    ("gpt-6.1-terra", "openai", "gpt-6.1-terra"),
    ("glm-5.3-flash", "zai", "glm-5.3-flash"),
    ("glm-5.3-flashx", "zai", "glm-5.3-flashx"),
    ("kimi-k3.1-pro", "moonshot", "kimi-k3.1-pro"),
    ("kimi-k3.1-pro-highspeed", "moonshot", "kimi-k3.1-pro-highspeed"),
    ("minimax-m3.1-flash", "minimax", "MiniMax-M3.1-Flash"),
    ("minimax-m3", "minimax", "MiniMax-M3"),
    ("mistral-large-4", "mistral", "mistral-large-4"),
    ("cohere-command-a-plus", "cohere", "command-a-plus-05-2026"),
    ("mythos-5.1-restricted", "anthropic", "claude-mythos-5-1"),
]


@pytest.mark.parametrize("name,provider,model", EXAMPLES)
def test_new_native_example_has_fixtures_and_a_single_bounded_request(
    name, provider, model
):
    config = load_config(Path("examples") / f"{name}.json")
    assert config["models"][0]["provider"] == provider
    assert config["models"][0]["model"] == model
    assert config["repetitions"] == 1 and config["warmups"] == 0
    assert config["request"]["retry"]["max_attempts"] == 1
    assert config["max_requests"] == 1
    assert config["require_current_pricing"] is True
    assert config["request"]["max_output_tokens"] > 0
    validate_config_validations(config)
    contract = check_contract(config)
    assert contract["ok"] is True
    assert not contract.get("unproven_prompts")
    assert len(contract["fixtures"]) == 2
    assert {fixture["expected"] for fixture in contract["fixtures"]} == {"pass", "fail"}
    models = resolve_models(config)
    assert len(models) == 1
    body = create_client(models[0], 10).body(config["prompt"], config["request"])
    assert body["model"] == model
    budget = estimate_budget(config, models)
    assert budget["possible_requests"] == 1
    assert budget["maximum_estimated_cost_usd"] <= config["max_estimated_cost_usd"]


def test_release_freshness_checks_every_new_native_example():
    import runpy

    script = runpy.run_path("scripts/release_freshness.py")
    assert {name for name, _, _ in EXAMPLES} <= set(script["EXAMPLES"])


@pytest.mark.parametrize(
    "name", ["native-chinese-smoke", "glm-5.3-openrouter-comparison"]
)
def test_price_sensitive_example_overrides_have_been_re_reviewed(name):
    config = load_config(Path("examples") / f"{name}.json")
    dated = [
        model["pricing_metadata"]["as_of"]
        for model in config["models"]
        if "pricing_metadata" in model
    ]
    assert dated == ["2026-10-26"]
