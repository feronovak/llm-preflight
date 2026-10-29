"""Deterministic native text contracts for the 2.23.0 provider cohort."""

import io
import json
import urllib.error
from pathlib import Path

import pytest

from llm_preflight.client import create_client, validate_native_request_options
from llm_preflight.pricing import estimate_sample_cost

NATIVE_CASES = [
    (
        "moonshot",
        "kimi-k3.1-pro",
        "https://api.moonshot.ai/v1/chat/completions",
        "MOONSHOT_API_KEY",
        "max_tokens",
    ),
    (
        "moonshot",
        "kimi-k3.1-pro-highspeed",
        "https://api.moonshot.ai/v1/chat/completions",
        "MOONSHOT_API_KEY",
        "max_tokens",
    ),
    (
        "minimax",
        "MiniMax-M3.1-Flash",
        "https://api.minimax.io/v1/chat/completions",
        "MINIMAX_API_KEY",
        "max_completion_tokens",
    ),
    (
        "minimax",
        "MiniMax-M3",
        "https://api.minimax.io/v1/chat/completions",
        "MINIMAX_API_KEY",
        "max_completion_tokens",
    ),
    (
        "mistral",
        "mistral-large-4",
        "https://api.mistral.ai/v1/chat/completions",
        "MISTRAL_API_KEY",
        "max_tokens",
    ),
    (
        "cohere",
        "command-a-plus-05-2026",
        "https://api.cohere.com/v2/chat",
        "COHERE_API_KEY",
        "max_tokens",
    ),
]


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(
        "llm_preflight.security.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )


class Stream:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def __iter__(self):
        return iter(
            [f"data: {json.dumps(event)}\n\n".encode() for event in self.events]
        )


def events_for(provider, model, usage=True, finish="stop"):
    if provider == "cohere":
        events = [
            {
                "type": "content-delta",
                "delta": {"message": {"content": {"text": "billing"}}},
            }
        ]
        end = {"finish_reason": "COMPLETE" if finish == "stop" else "MAX_TOKENS"}
        if usage:
            end["usage"] = {
                "billed_units": {"input_tokens": 1000, "output_tokens": 120},
                "tokens": {"input_tokens": 1100, "output_tokens": 120},
            }
        return events + [{"type": "message-end", "delta": end}]
    events = [
        {
            "model": model,
            "choices": [{"delta": {"reasoning_content": "private reasoning"}}],
        },
        {"choices": [{"delta": {"content": "billing"}, "finish_reason": finish}]},
    ]
    if usage:
        events.append(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 120,
                    "prompt_tokens_details": {"cached_tokens": 800},
                },
            }
        )
    return events


@pytest.mark.parametrize("provider,model,endpoint,key_env,limit_key", NATIVE_CASES)
@pytest.mark.parametrize("usage", [True, False])
def test_native_cohort_text_transport(
    monkeypatch, provider, model, endpoint, key_env, limit_key, usage
):
    captured = []
    monkeypatch.setenv(key_env, "fixture-key")

    def transport(request, timeout):
        captured.append(request)
        return Stream(events_for(provider, model, usage))

    monkeypatch.setattr("llm_preflight.client.open_public_url", transport)
    client = create_client({"provider": provider, "model": model}, 10)
    sample = client.run(
        "I was charged twice.",
        {
            "system_prompt": "Return only the queue label.",
            "max_output_tokens": 512,
            "temperature": 0,
            "retry": {"max_attempts": 1},
        },
    )
    assert sample["ok"] is True
    assert sample["response"] == "billing"
    assert sample["input_tokens"] == (1000 if usage else None)
    assert sample["output_tokens"] == (120 if usage else None)
    assert captured[0].full_url == endpoint
    assert captured[0].get_header("Authorization") == "Bearer fixture-key"
    body = json.loads(captured[0].data)
    assert body["model"] == model
    assert body[limit_key] == 512
    assert body["messages"][0] == {
        "role": "system",
        "content": "Return only the queue label.",
    }
    assert body["stream"] is True
    if provider == "minimax":
        assert body["reasoning_split"] is True
    else:
        assert "reasoning_split" not in body
    if provider in {"minimax", "moonshot"}:
        assert "temperature" not in body
    if provider == "cohere":
        assert "stream_options" not in body
    if not usage:
        assert (
            estimate_sample_cost(
                sample, {"input_cost_per_million": 1, "output_cost_per_million": 1}
            )
            is None
        )


@pytest.mark.parametrize("provider,model,endpoint,key_env,limit_key", NATIVE_CASES)
@pytest.mark.parametrize(
    "failure",
    ["truncated", "limit", "event-error", "http401", "http429", "timeout", "malformed"],
)
def test_native_cohort_failures_are_not_success(
    monkeypatch, provider, model, endpoint, key_env, limit_key, failure
):
    monkeypatch.setenv(key_env, "fixture-key")

    def transport(request, timeout):
        if failure.startswith("http"):
            raise urllib.error.HTTPError(
                endpoint,
                int(failure[4:]),
                "fixture",
                {},
                io.BytesIO(b'{"error":"access denied"}'),
            )
        if failure == "timeout":
            raise TimeoutError("fixture timeout")
        if failure == "event-error":
            return Stream([{"error": {"message": "fixture error"}}])
        if failure == "malformed":
            return Stream([{"choices": "broken"}])
        events = events_for(
            provider, model, finish="length" if failure == "limit" else "stop"
        )
        return Stream(events[:1] if failure == "truncated" else events)

    monkeypatch.setattr("llm_preflight.client.open_public_url", transport)
    sample = create_client({"provider": provider, "model": model}, 10).run(
        "hi", {"retry": {"max_attempts": 1}}
    )
    assert sample["ok"] is False
    assert sample["failure_category"] is not None
    assert sample["attempts"] == 1
    assert (
        estimate_sample_cost(
            sample, {"input_cost_per_million": 1, "output_cost_per_million": 1}
        )
        is None
    )


@pytest.mark.parametrize("provider,model,endpoint,key_env,limit_key", NATIVE_CASES)
@pytest.mark.parametrize(
    "field",
    [
        "model",
        "messages",
        "stream",
        "stream_options",
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
    ],
)
def test_native_provider_options_cannot_replace_planned_identity_or_limit(
    provider, model, endpoint, key_env, limit_key, field
):
    config = {"provider": provider, "model": model}
    options = {"provider_options": {provider: {field: "override"}}}
    with pytest.raises(ValueError, match="cannot override"):
        validate_native_request_options(config, options)
    with pytest.raises(ValueError, match="cannot override"):
        create_client(config, 10).body("hi", options)


@pytest.mark.parametrize("model", ["glm-5.3-flash", "glm-5.3-flashx"])
def test_glm_flash_reasoning_cannot_be_disabled(model):
    with pytest.raises(ValueError, match="reasoning"):
        create_client({"provider": "zai", "model": model}, 10).body(
            "hi", {"provider_options": {"zai": {"thinking": {"type": "disabled"}}}}
        )


PRICES = [
    ("zai", "glm-5.3-flash", 0.15, 0.50, 0.03, None),
    ("zai", "glm-5.3-flashx", 0.37, 1.25, 0.075, None),
    ("anthropic", "claude-mythos-5-1", 10, 50, 0.25, 12.5),
    ("moonshot", "kimi-k3.1-pro", 2, 10, 0.20, 2),
    ("moonshot", "kimi-k3.1-pro-highspeed", 4, 20, 0.20, 4),
    ("minimax", "MiniMax-M3.1-Flash", 0.15, 0.60, 0.015, None),
    ("minimax", "MiniMax-M3", 0.30, 1.20, 0.06, None),
    ("mistral", "mistral-large-4", 1.36, 4.18, 0.14, None),
    ("mistral", "mistral-large-4-0", 1.36, 4.18, 0.14, None),
    ("cohere", "command-a-plus-05-2026", 0, 0, None, None),
]


@pytest.mark.parametrize(
    "provider,model,input_rate,output_rate,cache_rate,write_rate", PRICES
)
def test_reviewed_native_prices_keep_cache_partitions_and_provenance(
    provider, model, input_rate, output_rate, cache_rate, write_rate
):
    from datetime import date

    from llm_preflight.pricing import apply_public_pricing, pricing_coverage_report

    priced = apply_public_pricing({"provider": provider, "model": model})
    assert priced["input_cost_per_million"] == input_rate
    assert priced["output_cost_per_million"] == output_rate
    assert priced.get("cached_input_cost_per_million") == cache_rate
    assert priced.get("cache_write_input_cost_per_million") == write_rate
    assert priced["pricing_metadata"]["as_of"] == "2026-10-26"
    assert priced["pricing_metadata"]["source_url"].startswith("https://")
    sample = {
        "input_tokens": 1000,
        "cached_input_tokens": 800 if cache_rate is not None else 0,
        "output_tokens": 100,
    }
    expected = (
        (200 * input_rate + 800 * cache_rate + 100 * output_rate) / 1e6
        if cache_rate is not None
        else (1000 * input_rate + 100 * output_rate) / 1e6
    )
    assert estimate_sample_cost(sample, priced) == pytest.approx(expected)
    if write_rate is not None:
        sample["cache_write_input_tokens"] = 100
        assert estimate_sample_cost(sample, priced) == pytest.approx(
            expected + 100 * (write_rate - input_rate) / 1e6
        )
    assert (
        pricing_coverage_report(
            [priced], today=date(2026, 11, 25), require_current_pricing=True
        )["enforcement_ok"]
        is True
    )
    assert (
        pricing_coverage_report(
            [priced], today=date(2026, 11, 26), require_current_pricing=True
        )["enforcement_ok"]
        is False
    )


@pytest.mark.parametrize(
    "total_input,input_rate,cache_rate,output_rate",
    [(512000, 0.3, 0.06, 1.2), (512001, 0.6, 0.12, 2.4)],
)
def test_minimax_m3_full_request_context_tier(
    total_input, input_rate, cache_rate, output_rate
):
    from llm_preflight.features import estimate_budget
    from llm_preflight.pricing import apply_public_pricing

    model = apply_public_pricing({"provider": "minimax", "model": "MiniMax-M3"})
    assert estimate_sample_cost(
        {
            "input_tokens": total_input,
            "cached_input_tokens": 1000,
            "output_tokens": 100,
        },
        model,
    ) == pytest.approx(
        ((total_input - 1000) * input_rate + 1000 * cache_rate + 100 * output_rate)
        / 1e6
    )
    budget = estimate_budget(
        {
            "prompt": "a" * (total_input * 4),
            "repetitions": 1,
            "warmups": 0,
            "request": {"max_output_tokens": 100, "retry": {"max_attempts": 1}},
        },
        [model],
    )
    assert budget["maximum_estimated_cost_usd"] == pytest.approx(
        (total_input * input_rate + 100 * output_rate) / 1e6
    )


@pytest.mark.parametrize("provider,model,endpoint,key_env,limit_key", NATIVE_CASES)
@pytest.mark.parametrize("persisted", [False, True])
def test_native_public_prices_never_apply_to_another_deployment(
    provider, model, endpoint, key_env, limit_key, persisted
):
    from llm_preflight.pricing import apply_public_pricing

    config = {
        "provider": provider,
        "model": model,
        "base_url": "https://private.example.test/v1",
    }
    if persisted:
        config.update(
            input_cost_per_million=1,
            output_cost_per_million=1,
            pricing_metadata={"source": "official snapshot", "as_of": "2026-10-26"},
        )
    resolved = apply_public_pricing(config)
    assert resolved.get("input_cost_per_million") is None
    assert (
        estimate_sample_cost({"input_tokens": 1000, "output_tokens": 100}, resolved)
        is None
    )
    explicit = {
        **config,
        "input_cost_per_million": 3,
        "output_cost_per_million": 5,
        "pricing_metadata": {"source": "user override", "as_of": "2026-10-26"},
    }
    assert apply_public_pricing(explicit) == explicit


@pytest.mark.parametrize("cache_field", ["num_cached_tokens", "prompt_token_details"])
def test_mistral_documented_cache_usage_aliases(cache_field):
    client = create_client({"provider": "mistral", "model": "mistral-large-4"}, 10)
    usage = {
        "prompt_tokens": 1000,
        "completion_tokens": 120,
        cache_field: 800
        if cache_field == "num_cached_tokens"
        else {"cached_tokens": 800},
    }
    _, normalized = client.parse_event({"choices": [], "usage": usage})
    assert normalized["cached_input_tokens"] == 800


@pytest.mark.parametrize("provider,model,endpoint,key_env,limit_key", NATIVE_CASES)
def test_native_null_usage_chunks_do_not_hide_later_usage(
    monkeypatch, provider, model, endpoint, key_env, limit_key
):
    monkeypatch.setenv(key_env, "fixture-key")
    events = events_for(provider, model)
    if provider != "cohere":
        events[0]["usage"] = None
    monkeypatch.setattr(
        "llm_preflight.client.open_public_url", lambda *args, **kwargs: Stream(events)
    )
    sample = create_client({"provider": provider, "model": model}, 10).run(
        "hi", {"retry": {"max_attempts": 1}}
    )
    assert sample["ok"] is True
    assert sample["input_tokens"] == 1000


@pytest.mark.parametrize("provider,model,endpoint,key_env,limit_key", NATIVE_CASES)
def test_native_malformed_content_becomes_failure(
    monkeypatch, provider, model, endpoint, key_env, limit_key
):
    monkeypatch.setenv(key_env, "fixture-key")
    event = (
        {"type": "content-delta", "delta": {"message": {"content": {"text": 42}}}}
        if provider == "cohere"
        else {"choices": [{"delta": {"content": 42}}]}
    )
    monkeypatch.setattr(
        "llm_preflight.client.open_public_url",
        lambda *args, **kwargs: Stream([event, *events_for(provider, model)[1:]]),
    )
    sample = create_client({"provider": provider, "model": model}, 10).run(
        "hi", {"retry": {"max_attempts": 1}}
    )
    assert sample["ok"] is False


def test_mistral_request_omits_undocumented_stream_options():
    body = create_client({"provider": "mistral", "model": "mistral-large-4"}, 10).body(
        "hi", {"max_output_tokens": 128}
    )
    assert "stream_options" not in body


@pytest.mark.parametrize(
    "provider,model,settings",
    [
        (
            "moonshot",
            "kimi-k3.1-pro",
            {"prompt_cache_options": {"mode": "implicit", "ttl": "1h"}},
        ),
        ("minimax", "MiniMax-M3", {"service_tier": "priority"}),
        ("openai", "gpt-6.1-terra", {"service_tier": "fast"}),
        ("openai", "gpt-6.1-terra", {"prompt_cache_retention": "12h"}),
        ("anthropic", "claude-mythos-5-1", {"thinking": {"type": "disabled"}}),
        ("anthropic", "claude-mythos-5-1", {"tool_choice": {"type": "any"}}),
        (
            "anthropic",
            "claude-fable-5-1",
            {"thinking": {"type": "enabled", "budget_tokens": 100}},
        ),
    ],
)
def test_unsupported_native_billing_and_reasoning_settings_are_refused_by_plan_and_transport(
    provider, model, settings
):
    from llm_preflight.features import estimate_budget
    from llm_preflight.pricing import apply_public_pricing

    config = {"provider": provider, "model": model}
    options = {"max_output_tokens": 512, "provider_options": {provider: settings}}
    with pytest.raises(ValueError):
        create_client(config, 10).body("hi", options)
    with pytest.raises(ValueError):
        estimate_budget(
            {"prompt": "hi", "request": options}, [apply_public_pricing(config)]
        )


@pytest.mark.parametrize(
    "event",
    [
        {"type": "content-delta", "delta": {"message": "bad"}},
        {"type": "content-delta", "delta": {"message": {"content": "bad"}}},
        {"type": "message-end", "delta": {"finish_reason": "COMPLETE", "usage": "bad"}},
        {
            "type": "message-end",
            "delta": {"finish_reason": "COMPLETE", "usage": {"billed_units": "bad"}},
        },
    ],
)
def test_cohere_malformed_nested_stream_objects_fail_safely(monkeypatch, event):
    monkeypatch.setenv("COHERE_API_KEY", "fixture-key")
    monkeypatch.setattr(
        "llm_preflight.client.open_public_url", lambda *args, **kwargs: Stream([event])
    )
    sample = create_client(
        {"provider": "cohere", "model": "command-a-plus-05-2026"}, 10
    ).run("hi", {"retry": {"max_attempts": 1}})
    assert sample["ok"] is False


@pytest.mark.parametrize("provider,model,endpoint,key_env,limit_key", NATIVE_CASES)
def test_native_plan_refuses_an_incompatible_adapter(
    provider, model, endpoint, key_env, limit_key
):
    config = {"provider": provider, "model": model, "adapter": "openai_responses"}
    with pytest.raises(ValueError, match="adapter"):
        validate_native_request_options(config, {})
    with pytest.raises(ValueError, match="adapter"):
        create_client(config, 10)
    config["adapter"] = (
        "cohere_chat" if provider == "cohere" else "openai_compatible_chat"
    )
    validate_native_request_options(config, {})
    assert create_client(config, 10).body("hi", {})["model"] == model


@pytest.mark.parametrize(
    "provider,model",
    [
        ("qwen", "qwen3.8-max"),
        ("openai", "gpt-6.1-terra"),
        ("anthropic", "claude-mythos-5-1"),
        ("gemini", "gemini-4-argon"),
        ("deepseek", "deepseek-flash"),
    ],
)
def test_retained_native_snapshots_require_their_reviewed_public_deployment(
    provider, model
):
    from llm_preflight.pricing import apply_public_pricing

    config = {
        "provider": provider,
        "model": model,
        "base_url": "https://regional.example.test/v1",
    }
    assert apply_public_pricing(config).get("input_cost_per_million") is None
    explicit = {
        **config,
        "input_cost_per_million": 1,
        "output_cost_per_million": 2,
        "pricing_metadata": {"source": "user override", "as_of": "2026-10-26"},
    }
    assert apply_public_pricing(explicit) == explicit


@pytest.mark.parametrize(
    "model_id", ["deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"]
)
def test_deepseek_flash_alias_image_fixture_keeps_observed_identity_and_top_level_cache_usage(
    monkeypatch, model_id
):
    from pathlib import Path

    from llm_preflight.features import estimate_budget
    from llm_preflight.pricing import apply_public_pricing
    from llm_preflight.runner import load_config

    config = load_config(Path("examples/vision/gemini-image-to-text.json"))
    options = {
        **config["request"],
        "retry": {"max_attempts": 1},
        "_image_base_dir": config["_config_dir"],
    }
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-key")
    captured = []

    def transport(request, timeout):
        captured.append(json.loads(request.data))
        return Stream(
            [
                {
                    "model": "deepseek-v4.1-flash-1017",
                    "choices": [
                        {"delta": {"content": "billing"}, "finish_reason": "stop"}
                    ],
                },
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 1000,
                        "prompt_cache_hit_tokens": 800,
                        "prompt_cache_miss_tokens": 200,
                        "completion_tokens": 120,
                    },
                },
            ]
        )

    monkeypatch.setattr("llm_preflight.client.open_public_url", transport)
    model = apply_public_pricing({"provider": "deepseek", "model": model_id})
    sample = create_client(model, 10).run("Read the order.", options)
    assert sample["ok"] is True
    assert sample["observed_model"] == "deepseek-v4.1-flash-1017"
    assert sample["cached_input_tokens"] == 800
    assert captured[0]["model"] == model_id
    assert captured[0]["messages"][-1]["content"][1]["type"] == "image_url"
    assert estimate_sample_cost(sample, model) == pytest.approx(0.0002088)
    assert (
        estimate_budget({"prompt": "Read the order.", "request": options}, [model])[
            "maximum_estimated_cost_usd"
        ]
        is None
    )


@pytest.mark.parametrize(
    "failure", [None, "event-error", "truncated", "limit", "http403"]
)
def test_restricted_mythos_stream_preserves_cache_and_rejects_incomplete_evidence(
    monkeypatch, failure
):
    from llm_preflight.pricing import apply_public_pricing

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fixture-key")
    events = [
        {
            "type": "message_start",
            "message": {
                "model": "claude-mythos-5-1",
                "usage": {
                    "input_tokens": 100,
                    "cache_read_input_tokens": 800,
                    "cache_creation_input_tokens": 100,
                },
            },
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "thinking_delta", "thinking": "private"},
        },
        {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "billing"},
        },
        {
            "type": "message_delta",
            "delta": {
                "stop_reason": "max_tokens" if failure == "limit" else "end_turn"
            },
            "usage": {"output_tokens": 20},
        },
        {"type": "message_stop"},
    ]

    def transport(request, timeout):
        if failure == "http403":
            raise urllib.error.HTTPError(
                request.full_url,
                403,
                "verification required",
                {},
                io.BytesIO(b'{"error":"verification required"}'),
            )
        if failure == "event-error":
            return Stream(
                [
                    {
                        "type": "error",
                        "error": {
                            "type": "permission_error",
                            "message": "verification required",
                        },
                    }
                ]
            )
        return Stream(events[:-1] if failure == "truncated" else events)

    monkeypatch.setattr("llm_preflight.client.open_public_url", transport)
    model = apply_public_pricing(
        {"provider": "anthropic", "model": "claude-mythos-5-1"}
    )
    sample = create_client(model, 10).run("hi", {"retry": {"max_attempts": 1}})
    if failure:
        assert sample["ok"] is False
        assert estimate_sample_cost(sample, model) is None
    else:
        assert sample["ok"] is True
        assert sample["response"] == "billing"
        assert sample["observed_model"] == "claude-mythos-5-1"
        assert sample["input_tokens"] == 1000
        assert sample["cached_input_tokens"] == 800
        assert sample["cache_write_input_tokens"] == 100
        assert estimate_sample_cost(sample, model) == pytest.approx(0.00345)


@pytest.mark.parametrize("model", ["glm-5.3-flash", "glm-5.3-flashx"])
@pytest.mark.parametrize("failure", [None, "event-error", "truncated", "limit"])
def test_glm_flash_native_stream_has_explicit_completion_evidence(
    monkeypatch, model, failure
):
    monkeypatch.setenv("ZAI_API_KEY", "fixture-key")
    events = [
        {
            "choices": [
                {
                    "delta": {"content": "billing"},
                    "finish_reason": "length" if failure == "limit" else "stop",
                }
            ]
        }
    ]
    if failure == "event-error":
        events = [{"error": {"message": "fixture"}}]
    if failure == "truncated":
        events = [{"choices": [{"delta": {"content": "billing"}}]}]
    monkeypatch.setattr(
        "llm_preflight.client.open_public_url", lambda *args, **kwargs: Stream(events)
    )
    sample = create_client({"provider": "zai", "model": model}, 10).run(
        "hi", {"retry": {"max_attempts": 1}}
    )
    assert sample["ok"] is (failure is None)


def test_mistral_native_reasoning_content_chunks_preserve_only_final_text(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "fixture-key")
    events = [
        {
            "model": "mistral-large-4-0",
            "choices": [
                {
                    "delta": {
                        "content": [
                            {
                                "type": "thinking",
                                "thinking": [
                                    {"type": "text", "text": "private reasoning"}
                                ],
                            }
                        ]
                    }
                }
            ],
        },
        {
            "choices": [
                {
                    "delta": {
                        "content": [
                            {"type": "text", "text": "bill"},
                            {"type": "text", "text": "ing"},
                        ]
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 800},
                "completion_tokens_details": {"reasoning_tokens": 100},
            },
        },
    ]
    monkeypatch.setattr(
        "llm_preflight.client.open_public_url", lambda *args, **kwargs: Stream(events)
    )
    sample = create_client({"provider": "mistral", "model": "mistral-large-4"}, 10).run(
        "hi", {"retry": {"max_attempts": 1}}
    )
    assert sample["ok"] is True
    assert sample["response"] == "billing"
    assert sample["observed_model"] == "mistral-large-4-0"
    assert sample["output_tokens"] == 120
    assert sample["cached_input_tokens"] == 800


@pytest.mark.parametrize(
    "chunk",
    [
        {"type": "text", "text": 42},
        {"type": "image_url", "image_url": "unexpected"},
        "bad",
    ],
)
def test_mistral_malformed_or_unsupported_content_chunks_fail(monkeypatch, chunk):
    monkeypatch.setenv("MISTRAL_API_KEY", "fixture-key")
    events = [{"choices": [{"delta": {"content": [chunk]}, "finish_reason": "stop"}]}]
    monkeypatch.setattr(
        "llm_preflight.client.open_public_url", lambda *args, **kwargs: Stream(events)
    )
    assert (
        create_client({"provider": "mistral", "model": "mistral-large-4"}, 10).run(
            "hi", {"retry": {"max_attempts": 1}}
        )["ok"]
        is False
    )


def test_terra_responses_preserves_reviewed_request_settings():
    config = json.loads(Path("examples/gpt-6.1-terra.json").read_text())
    options = config["request"]
    options["provider_options"]["openai"].update(
        {"prompt_cache_retention": "30m", "service_tier": "default"}
    )
    body = create_client(config["models"][0], 10).body(config["prompt"], options)
    assert body["reasoning"] == {"effort": "low"}
    assert body["prompt_cache_retention"] == "30m"
    assert body["service_tier"] == "default"
    assert body["max_output_tokens"] == 4096
    assert body["store"] is False
    assert body["instructions"] == options["system_prompt"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("input", "replacement prompt"),
        ("instructions", "replacement system prompt"),
        ("store", True),
        ("background", True),
        ("tools", [{"type": "web_search"}]),
        ("reasoning_effort", "low"),
    ],
)
def test_terra_responses_refuses_unsupported_options_before_plan_or_request(
    field, value
):
    from llm_preflight.cli import dry_run_plan

    model = {
        "provider": "openai",
        "model": "gpt-6.1-terra",
        "adapter": "openai_responses",
    }
    request = {"provider_options": {"openai": {field: value}}}
    with pytest.raises(ValueError, match="Responses provider_options"):
        create_client(model, 10).body("billing", request)
    with pytest.raises(ValueError, match="Responses provider_options"):
        dry_run_plan({"prompt": "billing", "models": [model], "request": request})


@pytest.mark.parametrize(
    "patch,success",
    [
        ({}, True),
        ({"usage": None}, True),
        (
            {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
            },
            False,
        ),
        ({"status": "failed"}, False),
        ({"status": "in_progress"}, False),
        ({"status": None}, False),
        ({"error": {"code": "server_error"}}, False),
        ({"usage": []}, False),
        ({"usage": {"input_tokens_details": []}}, False),
        ({"output_text": ["billing"]}, False),
        ({"output_text": "", "output": ["billing"]}, False),
        (
            {
                "output_text": "",
                "output": [{"content": [{"type": "output_text", "text": 123}]}],
            },
            False,
        ),
        (
            {
                "output_text": "",
                "output": [
                    {
                        "type": "message",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": "billing"}],
                    }
                ],
            },
            True,
        ),
    ],
)
def test_terra_responses_requires_complete_well_formed_evidence(
    monkeypatch, patch, success
):
    payload = {
        "status": "completed",
        "model": "gpt-6.1-terra",
        "output_text": "billing",
        "usage": {"input_tokens": 30, "output_tokens": 2},
        **patch,
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, *args):
            return json.dumps(payload).encode()

    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setattr(
        "llm_preflight.client.open_public_url", lambda *args, **kwargs: Response()
    )
    sample = create_client(
        {"provider": "openai", "model": "gpt-6.1-terra", "adapter": "openai_responses"},
        10,
    ).run("billing", {"retry": {"max_attempts": 1}})
    assert sample["ok"] is success, sample
    if success:
        assert sample["response"] == "billing"
        assert sample["input_tokens"] == (payload.get("usage") or {}).get(
            "input_tokens"
        )
    else:
        assert sample["error"]


@pytest.mark.parametrize(
    "model,allowed", [("MiniMax-M3", True), ("MiniMax-M3.1-Flash", False)]
)
def test_minimax_disabled_reasoning_support_is_model_specific(model, allowed):
    from llm_preflight.features import estimate_budget

    config = {"provider": "minimax", "model": model}
    request = {"provider_options": {"minimax": {"thinking": {"type": "disabled"}}}}
    if allowed:
        body = create_client(config, 10).body("billing", request)
        assert body["thinking"] == {"type": "disabled"}
        assert (
            estimate_budget(
                {"prompt": "billing", "models": [config], "request": request}
            )["possible_requests"]
            > 0
        )
    else:
        with pytest.raises(ValueError, match="thinking type"):
            create_client(config, 10).body("billing", request)
        with pytest.raises(ValueError, match="thinking type"):
            estimate_budget(
                {"prompt": "billing", "models": [config], "request": request}
            )
