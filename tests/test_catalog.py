import pytest

from llm_bench.catalog import discover_models, resolve_models


def test_openrouter_normalization_and_limit(monkeypatch):
    monkeypatch.setattr(
        "llm_bench.catalog._get_json",
        lambda *args, **kwargs: {
            "data": [
                {
                    "id": "vendor/reasoner",
                    "name": "Reasoner",
                    "created": 2,
                    "context_length": 1000,
                    "supported_parameters": ["reasoning", "tools"],
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["text"],
                    },
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                },
                {
                    "id": "vendor/other",
                    "name": "Other",
                    "created": 1,
                    "supported_parameters": [],
                    "pricing": {},
                },
            ]
        },
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    models = discover_models(
        {"provider": "openrouter", "include": "reason", "limit": 1}
    )
    assert [model["model"] for model in models] == ["vendor/reasoner"]
    assert models[0]["capabilities"]["reasoning"] is True
    assert models[0]["input_cost_per_million"] == 1
    assert models[0]["output_cost_per_million"] == 2


def test_gemini_filters_non_generation_models(monkeypatch):
    monkeypatch.setattr(
        "llm_bench.catalog._get_json",
        lambda *args, **kwargs: {
            "models": [
                {
                    "name": "models/gemini-test",
                    "displayName": "Gemini Test",
                    "supportedGenerationMethods": ["generateContent"],
                    "thinking": True,
                },
                {
                    "name": "models/embed-test",
                    "supportedGenerationMethods": ["embedContent"],
                },
            ]
        },
    )
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    models = discover_models({"provider": "gemini", "limit": 5})
    assert [model["model"] for model in models] == ["gemini-test"]
    assert models[0]["capabilities"]["reasoning"] is True


def test_xai_catalog_uses_native_models_endpoint_and_pricing(monkeypatch):
    captured = {}

    def fake_get_json(url, key_env, headers=None):
        captured.update(url=url, key_env=key_env)
        return {
            "data": [
                {
                    "id": "grok-4.3",
                    "created": 1,
                    "owned_by": "xai",
                }
            ]
        }

    monkeypatch.setattr("llm_bench.catalog._get_json", fake_get_json)
    monkeypatch.setenv("XAI_API_KEY", "test")
    models = discover_models({"provider": "xai", "limit": 1})
    assert captured == {
        "url": "https://api.x.ai/v1/models",
        "key_env": "XAI_API_KEY",
    }
    assert models[0]["provider"] == "xai"
    assert models[0]["model"] == "grok-4.3"
    assert models[0]["input_cost_per_million"] == 1.25
    assert models[0]["output_cost_per_million"] == 2.5


def test_resolve_deduplicates_explicit_and_discovered(monkeypatch):
    monkeypatch.setattr(
        "llm_bench.catalog.discover_models",
        lambda source: [{"provider": "openai", "model": "same"}],
    )
    models = resolve_models(
        {
            "models": [{"provider": "openai", "model": "same"}],
            "discovery": [{"provider": "openai", "limit": 1}],
        }
    )
    assert len(models) == 1


def test_resolve_adds_public_registry_pricing_and_preserves_overrides():
    models = resolve_models(
        {
            "models": [
                {"provider": "openai", "model": "gpt-5.4-mini"},
                {"provider": "gemini", "model": "gemini-3.5-flash"},
                {"provider": "anthropic", "model": "claude-opus-4-8"},
                {
                    "provider": "openai",
                    "model": "gpt-4.1",
                    "input_cost_per_million": 99,
                    "output_cost_per_million": 100,
                },
            ]
        }
    )
    assert models[0]["input_cost_per_million"] == 0.75
    assert models[0]["output_cost_per_million"] == 4.5
    assert models[1]["input_cost_per_million"] == 1.5
    assert models[1]["output_cost_per_million"] == 9
    assert models[2]["input_cost_per_million"] == 5
    assert models[2]["output_cost_per_million"] == 25
    assert models[3]["input_cost_per_million"] == 99
    assert models[3]["output_cost_per_million"] == 100


def test_catalog_rejects_non_http_base_url_before_opening(monkeypatch):
    opened = False

    def should_not_open(*args, **kwargs):
        nonlocal opened
        opened = True

    monkeypatch.setattr("urllib.request.urlopen", should_not_open)
    with pytest.raises(ValueError, match="http or https"):
        discover_models(
            {
                "provider": "openai_compatible",
                "base_url": "file:///etc",
                "limit": 1,
            }
        )
    assert opened is False
