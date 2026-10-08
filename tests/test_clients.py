import hashlib
import io
import json
import urllib.error

import pytest

from llm_preflight.client import (
    MAX_RESPONSE_BYTES,
    AnthropicClient,
    GeminiClient,
    OpenAICompatibleClient,
    OpenAIResponsesClient,
    _retry_delay,
    create_client,
)


def test_openai_responses_adapter_uses_minimal_safe_probe_request():
    client = create_client(
        {"provider": "openai", "model": "gpt-test", "adapter": "openai_responses"},
        10,
    )

    assert isinstance(client, OpenAIResponsesClient)
    assert client.endpoint() == "https://api.openai.com/v1/responses"
    assert client.body("Reply with OK.", {"max_output_tokens": 32}) == {
        "model": "gpt-test",
        "input": "Reply with OK.",
        "max_output_tokens": 32,
        "store": False,
    }


def test_openai_responses_adapter_preserves_system_prompt_for_contract_checks():
    client = create_client(
        {"provider": "openai", "model": "gpt-test", "adapter": "openai_responses"},
        10,
    )

    body = client.body(
        "A customer was charged twice. Route the ticket.",
        {
            "system_prompt": "Return only the support queue label.",
            "max_output_tokens": 128,
        },
    )

    assert body["input"] == "A customer was charged twice. Route the ticket."
    assert body["instructions"] == "Return only the support queue label."


@pytest.fixture(autouse=True)
def _resolve_provider_hosts_to_a_public_address(monkeypatch):
    """Keep unit fixtures independent from the machine's DNS configuration."""
    monkeypatch.setattr(
        "llm_preflight.security.socket.getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(
        "llm_preflight.client.open_public_url",
        lambda request, timeout: urllib.request.urlopen(request, timeout),
    )


def test_factory_applies_openai_defaults():
    client = create_client({"provider": "openai", "model": "model-a"}, 10)
    assert isinstance(client, OpenAICompatibleClient)
    assert client.model["base_url"] == "https://api.openai.com/v1"
    assert client.model["api_key_env"] == "OPENAI_API_KEY"
    body = client.body("hello", {"max_output_tokens": 1})
    assert body["max_completion_tokens"] == 1
    assert "max_tokens" not in body


@pytest.mark.parametrize(
    "provider", ["openai", "gemini", "openrouter", "xai", "deepseek", "qwen"]
)
def test_non_anthropic_clients_apply_the_safe_default_output_limit(provider):
    client = create_client({"provider": provider, "model": "model-a"}, 10)

    body = client.body("hello", {})

    if provider == "gemini":
        assert body["generationConfig"]["maxOutputTokens"] == 256
    else:
        parameter = client.model.get("max_tokens_parameter", "max_tokens")
        assert body[parameter] == 256


def test_runtime_url_validation_failure_becomes_a_normal_api_failure(monkeypatch):
    client = OpenAICompatibleClient(
        {
            "provider": "openai_compatible",
            "model": "broken",
            "base_url": "https://api.example.test/v1",
        },
        10,
    )
    monkeypatch.setattr(
        "llm_preflight.client.require_http_url",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("URL host could not be resolved: 'api.example.test'")
        ),
    )

    result = client.run("Reply with ok.", {"retry": {"max_attempts": 1}})

    assert result["ok"] is False
    assert result["failure_category"] == "provider_error"


@pytest.mark.parametrize(
    "model",
    [
        "gpt-5.5",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
        "gpt-5.6-sol",
        "gpt-6-astra",
        "gpt-6.1-sol",
        "gpt-6-sol",
        "gpt-6-luna",
    ],
)
def test_current_gpt_models_omit_unsupported_temperature(model):
    client = create_client({"provider": "openai", "model": model}, 10)
    body = client.body("hello", {"temperature": 0, "max_output_tokens": 16})
    assert "temperature" not in body

    older = create_client({"provider": "openai", "model": "gpt-5.4-mini"}, 10)
    assert older.body("hello", {"temperature": 0})["temperature"] == 0


@pytest.mark.parametrize("adapter", ["openai_compatible_chat", "openai_responses"])
def test_gpt_6_1_protocol_preserves_cache_reads_and_writes(monkeypatch, adapter):
    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            event = {
                "choices": [{"delta": {"content": "billing"}}],
                "usage": {
                    "prompt_tokens": 1000,
                    "prompt_tokens_details": {
                        "cached_tokens": 800,
                        "cache_write_tokens": 100,
                    },
                    "completion_tokens": 20,
                },
            }
            return iter([f"data: {json.dumps(event)}\n".encode()])

        def read(self, *args):
            return json.dumps(
                {
                    "output": [
                        {"content": [{"type": "output_text", "text": "billing"}]}
                    ],
                    "usage": {
                        "input_tokens": 1000,
                        "input_tokens_details": {
                            "cached_tokens": 800,
                            "cache_write_tokens": 100,
                        },
                        "output_tokens": 20,
                    },
                }
            ).encode()

    def transport(request, timeout):
        captured.append(json.loads(request.data))
        return Response()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", transport)
    client = create_client(
        {"provider": "openai", "model": "gpt-6.1-sol", "adapter": adapter}, 10
    )

    sample = client.run(
        "I was charged twice.",
        {
            "temperature": 0,
            "system_prompt": "Return only the queue label.",
            "max_output_tokens": 512,
            "retry": {"max_attempts": 1},
        },
    )

    assert sample["ok"] is True
    assert sample["response"] == "billing"
    assert sample["input_tokens"] == 1000
    assert sample["cached_input_tokens"] == 800
    assert sample["cache_write_input_tokens"] == 100
    assert sample["output_tokens"] == 20
    assert captured[0]["model"] == "gpt-6.1-sol"
    assert "temperature" not in captured[0]

    from llm_preflight.metrics import summarize
    from llm_preflight.pricing import apply_public_pricing

    summary = summarize([sample], apply_public_pricing(client.model))
    assert summary["cache_write_input_tokens"] == 100
    assert summary["estimated_cost_usd"] == pytest.approx(0.00073)


def test_glm_5_3_native_stream_preserves_usage_and_ignores_reasoning_text(monkeypatch):
    from llm_preflight.metrics import summarize
    from llm_preflight.pricing import apply_public_pricing

    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            events = [
                {"choices": [{"delta": {"reasoning_content": "private reasoning"}}]},
                {"choices": [{"delta": {"content": "billing"}}]},
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 1000,
                        "prompt_tokens_details": {"cached_tokens": 800},
                        "completion_tokens": 100,
                    },
                },
            ]
            return iter(
                [f"data: {json.dumps(e)}\n".encode() for e in events]
                + [b"data: [DONE]\n"]
            )

    def transport(request, timeout):
        captured.append(request)
        return Response()

    monkeypatch.setenv("ZAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", transport)
    client = create_client({"provider": "zai", "model": "glm-5.3"}, 10)
    sample = client.run(
        "Charged twice",
        {
            "temperature": 0,
            "max_output_tokens": 512,
            "system_prompt": "Return the queue",
            "provider_options": {"zai": {"reasoning_effort": "low"}},
        },
    )
    assert sample["ok"] is True
    assert sample["response"] == "billing"
    assert sample["input_tokens"] == 1000
    assert sample["cached_input_tokens"] == 800
    assert sample["output_tokens"] == 100
    assert captured[0].full_url == "https://api.z.ai/api/paas/v4/chat/completions"
    assert captured[0].get_header("Authorization") == "Bearer test"
    body = json.loads(captured[0].data)
    assert body["model"] == "glm-5.3"
    assert body["max_tokens"] == 512
    assert body["temperature"] == 0
    assert body["reasoning_effort"] == "low"
    assert body["messages"][0] == {"role": "system", "content": "Return the queue"}
    assert "stream_options" not in body
    assert summarize([sample], apply_public_pricing(client.model))[
        "estimated_cost_usd"
    ] == pytest.approx(0.000928)


@pytest.mark.parametrize(
    "provider_options",
    [
        {"thinking": {"type": "disabled"}},
        {"reasoning_effort": "none"},
        {"reasoning_effort": "medium"},
    ],
)
def test_glm_5_3_rejects_unsupported_reasoning_before_transport(
    monkeypatch, provider_options
):
    def unexpected_transport(*args, **kwargs):
        pytest.fail("invalid GLM reasoning must fail before transport")

    monkeypatch.setenv("ZAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", unexpected_transport)
    client = create_client({"provider": "zai", "model": "glm-5.3"}, 10)
    sample = client.run(
        "hello",
        {"retry": {"max_attempts": 1}, "provider_options": {"zai": provider_options}},
    )
    assert sample["ok"] is False
    assert "reasoning" in sample["error"]


def test_glm_5_3_rejects_image_input():
    client = create_client({"provider": "zai", "model": "glm-5.3"}, 10)
    with pytest.raises(ValueError, match="text-only"):
        client.body("hello", {"input_images": [{"path": "does-not-exist.png"}]})


def test_model_can_explicitly_override_temperature_support():
    unsupported = create_client(
        {
            "provider": "openai",
            "model": "custom-no-temp",
            "capabilities": {"temperature": False},
        },
        10,
    )
    assert "temperature" not in unsupported.body("hello", {"temperature": 0.5})

    supported = create_client(
        {"provider": "openai", "model": "gpt-5.5", "supports_temperature": True},
        10,
    )
    assert supported.body("hello", {"temperature": 0.5})["temperature"] == 0.5


def test_deepseek_uses_the_openai_compatible_chat_adapter():
    client = create_client({"provider": "deepseek", "model": "deepseek-flash"}, 10)

    assert isinstance(client, OpenAICompatibleClient)
    assert client.model["base_url"] == "https://api.deepseek.com/v1"
    assert client.model["api_key_env"] == "DEEPSEEK_API_KEY"
    assert client.endpoint() == "https://api.deepseek.com/v1/chat/completions"


def test_qwen_uses_the_model_studio_compatible_chat_adapter():
    client = create_client({"provider": "qwen", "model": "qwen3.8-max"}, 10)

    assert isinstance(client, OpenAICompatibleClient)
    assert client.model["base_url"] == (
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    )
    assert client.model["api_key_env"] == "DASHSCOPE_API_KEY"


def test_typesafe_rejects_the_text_smoke_adapter():
    with pytest.raises(ValueError, match="text smoke adapter"):
        create_client({"provider": "typesafe", "model": "jev-latest"}, 10)


def test_openrouter_jev_is_refused_as_a_typed_decision_model():
    with pytest.raises(ValueError, match="text smoke adapter"):
        create_client(
            {
                "provider": "openrouter",
                "model": "typesafe/jev-latest",
                "catalog_type": "decision",
            },
            10,
        )


def test_decision_catalog_type_is_refused_regardless_of_provider():
    with pytest.raises(ValueError, match="text smoke adapter"):
        create_client(
            {
                "provider": "openai_compatible",
                "model": "custom-jev",
                "base_url": "https://example.test/v1",
                "catalog_type": "decision",
            },
            10,
        )


def test_openrouter_uses_compatible_adapter():
    client = create_client({"provider": "openrouter", "model": "vendor/model"}, 10)
    assert isinstance(client, OpenAICompatibleClient)
    assert client.model["base_url"] == "https://openrouter.ai/api/v1"
    body = client.body("hello", {"max_output_tokens": 1})
    assert body["max_tokens"] == 1
    assert "max_completion_tokens" not in body


def test_openrouter_uses_openai_multipart_content_for_local_image_inputs(tmp_path):
    image = tmp_path / "receipt.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    client = create_client({"provider": "openrouter", "model": "qwen/qwen3-vl"}, 10)

    body = client.body(
        "Read the receipt.",
        {
            "input_images": [
                {
                    "path": "receipt.png",
                    "mime_type": "image/png",
                    "width": 1,
                    "height": 1,
                    "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                }
            ],
            "_image_base_dir": str(tmp_path),
        },
    )

    assert body["messages"][-1]["content"][0] == {
        "type": "text",
        "text": "Read the receipt.",
    }
    assert body["messages"][-1]["content"][1]["type"] == "image_url"
    assert body["messages"][-1]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )


def test_qwen_model_studio_uses_the_openai_compatible_image_protocol(tmp_path):
    image = tmp_path / "receipt.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    client = create_client(
        {
            "provider": "openai_compatible",
            "model": "qwen3-vl-plus",
            "base_url": "https://workspace.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
        },
        10,
    )
    body = client.body(
        "Read the receipt.",
        {
            "input_images": [
                {
                    "path": "receipt.png",
                    "mime_type": "image/png",
                    "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                }
            ],
            "_image_base_dir": str(tmp_path),
        },
    )

    assert client.endpoint().endswith("/compatible-mode/v1/chat/completions")
    assert body["messages"][-1]["content"][1]["type"] == "image_url"


def test_gemini_uses_inline_data_for_local_image_inputs(tmp_path):
    image = tmp_path / "receipt.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    client = create_client({"provider": "gemini", "model": "gemini-test"}, 10)

    body = client.body(
        "Read the receipt.",
        {
            "input_images": [
                {
                    "path": "receipt.png",
                    "mime_type": "image/png",
                    "width": 1,
                    "height": 1,
                    "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                }
            ],
            "_image_base_dir": str(tmp_path),
        },
    )

    assert body["contents"][0]["parts"][0] == {"text": "Read the receipt."}
    assert body["contents"][0]["parts"][1]["inlineData"]["mimeType"] == "image/png"
    assert body["contents"][0]["parts"][1]["inlineData"]["data"]


def test_image_input_fails_if_the_local_file_changes_after_validation(tmp_path):
    image = tmp_path / "receipt.png"
    original = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    image.write_bytes(original)
    client = create_client({"provider": "openrouter", "model": "qwen/qwen3-vl"}, 10)
    options = {
        "input_images": [
            {
                "path": "receipt.png",
                "mime_type": "image/png",
                "sha256": hashlib.sha256(original).hexdigest(),
            }
        ],
        "_image_base_dir": str(tmp_path),
    }
    image.write_bytes(original + b"changed")

    with pytest.raises(ValueError, match="changed after configuration was loaded"):
        client.body("Read the receipt.", options)


def test_anthropic_rejects_image_inputs_instead_of_ignoring_them(tmp_path):
    image = tmp_path / "receipt.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    client = create_client({"provider": "anthropic", "model": "claude-test"}, 10)

    with pytest.raises(ValueError, match="does not support input_images"):
        client.body(
            "Read the receipt.",
            {
                "input_images": [{"path": "receipt.png", "mime_type": "image/png"}],
                "_image_base_dir": str(tmp_path),
            },
        )


def test_openai_responses_rejects_image_inputs_instead_of_ignoring_them():
    client = create_client(
        {"provider": "openai", "model": "gpt-test", "adapter": "openai_responses"},
        10,
    )

    with pytest.raises(ValueError, match="does not support input_images"):
        client.body("Read this.", {"input_images": [{"path": "receipt.png"}]})


def test_xai_uses_the_verified_openai_compatible_image_protocol(tmp_path):
    image = tmp_path / "receipt.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + (1).to_bytes(4, "big")
        + (1).to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
    )
    client = create_client({"provider": "xai", "model": "grok-test"}, 10)

    body = client.body(
        "Read this.",
        {
            "input_images": [
                {
                    "path": "receipt.png",
                    "mime_type": "image/png",
                    "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                }
            ],
            "_image_base_dir": str(tmp_path),
        },
    )

    assert body["messages"][-1]["content"][1]["type"] == "image_url"


def test_openrouter_applies_provider_specific_options():
    client = create_client({"provider": "openrouter", "model": "vendor/model"}, 10)
    body = client.body(
        "hello",
        {
            "provider_options": {
                "gemini": {
                    "generationConfig": {"responseMimeType": "application/json"}
                },
                "openrouter": {
                    "response_format": {"type": "json_object"},
                    "include_reasoning": False,
                    "reasoning": {"enabled": False},
                },
            }
        },
    )

    assert body["response_format"] == {"type": "json_object"}
    assert body["include_reasoning"] is False
    assert body["reasoning"] == {"enabled": False}
    assert "gemini" not in body


def test_compatible_client_ignores_other_provider_options():
    client = create_client({"provider": "openai", "model": "model-a"}, 10)
    body = client.body(
        "hello",
        {
            "provider_options": {
                "gemini": {"generationConfig": {"responseMimeType": "application/json"}}
            }
        },
    )
    assert "generationConfig" not in body
    assert "gemini" not in body


def test_xai_uses_native_compatible_api_defaults():
    client = create_client({"provider": "xai", "model": "grok-4.3"}, 10)
    assert isinstance(client, OpenAICompatibleClient)
    assert client.model["base_url"] == "https://api.x.ai/v1"
    assert client.model["api_key_env"] == "XAI_API_KEY"
    assert client.headers("secret") == {"Authorization": "Bearer secret"}
    body = client.body("hello", {"max_output_tokens": 16})
    assert body["max_tokens"] == 16


def test_anthropic_request_and_events():
    client = create_client({"provider": "anthropic", "model": "claude-test"}, 10)
    assert isinstance(client, AnthropicClient)
    body = client.body(
        "hello",
        {"system_prompt": "brief", "temperature": 0, "max_output_tokens": 42},
    )
    assert body["system"] == "brief"
    assert body["max_tokens"] == 42
    text, usage = client.parse_event(
        {"delta": {"text": "hi"}, "usage": {"output_tokens": 2}}
    )
    assert text == "hi"
    assert usage["output_tokens"] == 2


def test_current_anthropic_models_omit_unsupported_temperature():
    for model in (
        "claude-sonnet-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
        "claude-fable-5",
        "claude-fable-5-1",
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-opus-5-5",
    ):
        client = create_client({"provider": "anthropic", "model": model}, 10)
        assert "temperature" not in client.body(
            "hello", {"temperature": 0, "max_output_tokens": 16}
        )


@pytest.mark.parametrize(
    ("model_id", "expected_cost"),
    [("claude-haiku-5-5", 0.000028), ("claude-sonnet-5-5", 0.00048)],
)
@pytest.mark.parametrize("written", [0, 100])
def test_anthropic_stream_preserves_total_input_and_cache_usage(
    monkeypatch, model_id, expected_cost, written
):
    from llm_preflight.metrics import summarize
    from llm_preflight.pricing import apply_public_pricing

    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            events = [
                {
                    "type": "message_start",
                    "message": {
                        "usage": {
                            "input_tokens": 100,
                            "cache_read_input_tokens": 800,
                            "cache_creation_input_tokens": written,
                            "output_tokens": 0,
                        }
                    },
                },
                {
                    "type": "content_block_delta",
                    "delta": {"type": "thinking_delta", "thinking": "internal"},
                },
                {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "billing"},
                },
                {"type": "message_delta", "usage": {"output_tokens": 20}},
            ]
            return iter(f"data: {json.dumps(event)}\n".encode() for event in events)

    def transport(request, timeout):
        captured.append(json.loads(request.data))
        return Response()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", transport)
    model = apply_public_pricing({"provider": "anthropic", "model": model_id})
    client = create_client(model, 10)

    sample = client.run(
        "I was charged twice.",
        {
            "temperature": 0,
            "max_output_tokens": 128,
            "system_prompt": "Return only the queue label.",
            "provider_options": {"anthropic": {"output_config": {"effort": "low"}}},
            "retry": {"max_attempts": 1},
        },
    )

    assert sample["ok"] is True
    assert sample["response"] == "billing"
    assert sample["input_tokens"] == 900 + written
    assert sample["cached_input_tokens"] == 800
    assert sample["cache_write_input_tokens"] == written
    assert sample["output_tokens"] == 20
    assert "temperature" not in captured[0]
    assert captured[0]["system"] == "Return only the queue label."
    assert captured[0]["output_config"] == {"effort": "low"}
    summary = summarize([sample], model)
    assert summary["input_tokens"] == 900 + written
    assert summary["cache_write_input_tokens"] == written
    if written:
        # Anthropic write prices vary by TTL; an aggregate count cannot pick one.
        assert summary["estimated_cost_usd"] is None
        assert summary["cost_coverage"]["missing_price_requests"] == 1
    else:
        assert summary["estimated_cost_usd"] == pytest.approx(expected_cost)


@pytest.mark.parametrize(
    "cache_usage",
    [
        {"cache_read_input_tokens": -1},
        {"cache_read_input_tokens": "800"},
        {"cache_creation_input_tokens": 0.5},
        {"cache_creation_input_tokens": True},
        {"cache_creation_input_tokens": None},
    ],
)
def test_anthropic_invalid_cache_usage_cannot_produce_a_cost(cache_usage):
    from llm_preflight.pricing import apply_public_pricing, estimate_sample_cost

    model = apply_public_pricing({"provider": "anthropic", "model": "claude-haiku-5-5"})
    client = create_client(model, 10)
    _, usage = client.parse_event(
        {
            "message": {
                "usage": {"input_tokens": 100, "output_tokens": 20, **cache_usage}
            }
        }
    )

    assert estimate_sample_cost(usage, model) is None


def test_gemini_request_and_events():
    client = create_client({"provider": "gemini", "model": "gemini-test"}, 10)
    assert isinstance(client, GeminiClient)
    body = client.body("hello", {"max_output_tokens": 42})
    assert body["generationConfig"]["maxOutputTokens"] == 42
    text, usage = client.parse_event(
        {
            "candidates": [{"content": {"parts": [{"text": "hi"}]}}],
            "usageMetadata": {
                "promptTokenCount": 1,
                "candidatesTokenCount": 2,
                "thoughtsTokenCount": 8,
            },
        }
    )
    assert text == "hi"
    assert usage == {"input_tokens": 1, "output_tokens": 10}


@pytest.mark.parametrize(
    "usage_metadata", [{}, {"promptTokenCount": 100}, {"thoughtsTokenCount": 8}]
)
def test_gemini_does_not_invent_missing_output_usage(usage_metadata):
    client = create_client({"provider": "gemini", "model": "gemini-test"}, 10)
    _, usage = client.parse_event({"usageMetadata": usage_metadata})
    assert usage.get("output_tokens") is None


@pytest.mark.parametrize("value", [True, -1, "2", 1.5, float("nan"), float("inf")])
def test_gemini_does_not_coerce_invalid_output_components(value):
    client = create_client({"provider": "gemini", "model": "gemini-test"}, 10)
    _, usage = client.parse_event(
        {
            "usageMetadata": {
                "promptTokenCount": 100,
                "candidatesTokenCount": value,
                "thoughtsTokenCount": 8,
            }
        }
    )
    from llm_preflight.pricing import estimate_sample_cost

    assert (
        estimate_sample_cost(
            usage, {"input_cost_per_million": 1, "output_cost_per_million": 2}
        )
        is None
    )


def test_gemini_merges_provider_specific_generation_config():
    client = create_client({"provider": "gemini", "model": "gemini-test"}, 10)
    body = client.body(
        "hello",
        {
            "temperature": 0,
            "max_output_tokens": 42,
            "provider_options": {
                "gemini": {
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "thinkingConfig": {
                            "includeThoughts": False,
                        },
                    }
                }
            },
        },
    )

    assert body["generationConfig"] == {
        "temperature": 0,
        "maxOutputTokens": 42,
        "responseMimeType": "application/json",
        "thinkingConfig": {"includeThoughts": False},
    }


def test_gemini_parser_ignores_thought_parts():
    client = create_client({"provider": "gemini", "model": "gemini-test"}, 10)

    text, usage = client.parse_event(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "Draft: I should make JSON.", "thought": True},
                            {"text": '{"questions":[]}'},
                        ]
                    }
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 1,
                "candidatesTokenCount": 8,
            },
        }
    )

    assert text == '{"questions":[]}'
    assert usage == {"input_tokens": 1, "output_tokens": 8}


def test_custom_compatible_provider():
    client = create_client(
        {
            "provider": "openai_compatible",
            "model": "local",
            "base_url": "http://localhost:1234/v1",
        },
        10,
    )
    assert client.endpoint() == "http://localhost:1234/v1/chat/completions"


@pytest.mark.parametrize(
    ("base_url", "message"),
    [
        ("file:///etc", "http or https"),
        ("https:///missing-host", "http or https"),
        ("https://user:secret@example.test/v1", "embedded credentials"),
    ],
)
def test_custom_provider_rejects_unsafe_base_url(base_url, message):
    with pytest.raises(ValueError, match=message):
        create_client(
            {
                "provider": "openai_compatible",
                "model": "local",
                "base_url": base_url,
            },
            10,
        )


def test_compatible_client_streams_text_and_usage(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"hi"}}]}\n',
                    b'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}\n',
                    b"data: [DONE]\n",
                ]
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: FakeResponse()
    )
    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"max_output_tokens": 4}
    )
    assert sample["ok"] is True
    assert sample["response"] == "hi"
    assert sample["input_tokens"] == 3
    assert sample["output_tokens"] == 1
    assert sample["error"] is None


def test_single_chunk_response_reports_no_throughput(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    (
                        b'data: {"choices":[{"delta":{"content":"whole body at once"}}],'
                        b'"usage":{"prompt_tokens":3,"completion_tokens":140}}\n'
                    ),
                    b"data: [DONE]\n",
                ]
            )

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: FakeResponse()
    )
    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"max_output_tokens": 4}
    )
    assert sample["ok"] is True
    assert sample["output_tokens"] == 140
    assert sample["output_tokens_per_second"] is None


def test_incremental_stream_reports_throughput(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"first"}}]}\n',
                    (
                        b'data: {"choices":[{"delta":{"content":" second"}}],'
                        b'"usage":{"prompt_tokens":3,"completion_tokens":2}}\n'
                    ),
                    b"data: [DONE]\n",
                ]
            )

    ticks = iter(i * 0.5 for i in range(100))
    monkeypatch.setattr("llm_preflight.client.time.perf_counter", lambda: next(ticks))
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: FakeResponse()
    )
    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"max_output_tokens": 4}
    )
    assert sample["ok"] is True
    assert sample["output_tokens_per_second"] is not None
    assert sample["output_tokens_per_second"] > 0


def test_burst_stream_below_generation_window_reports_no_throughput(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"first"}}]}\n',
                    (
                        b'data: {"choices":[{"delta":{"content":" second"}}],'
                        b'"usage":{"prompt_tokens":3,"completion_tokens":140}}\n'
                    ),
                    b"data: [DONE]\n",
                ]
            )

    # Everything after the first token arrives within 1 ms — a terminal
    # burst, not incremental generation.
    ticks = iter([0.0, 3.0, 3.001, 3.002])
    monkeypatch.setattr("llm_preflight.client.time.perf_counter", lambda: next(ticks))
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: FakeResponse()
    )
    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"max_output_tokens": 4}
    )
    assert sample["ok"] is True
    assert sample["output_tokens_per_second"] is None


def test_client_reports_missing_key_and_http_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = create_client({"provider": "openai", "model": "model-a"}, 10)
    assert "OPENAI_API_KEY" in client.run("hello", {})["error"]

    monkeypatch.setenv("OPENAI_API_KEY", "test")

    def raise_http_error(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "rate limited",
            {},
            io.BytesIO(b'{"error":"rate limited"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", raise_http_error)
    sample = client.run("hello", {})
    assert sample["ok"] is False
    assert sample["error"] == 'HTTP 429: {"error":"rate limited"}'


def test_client_retries_retryable_http_error_and_records_attempts(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
                    b'data: {"choices":[],"usage":{"prompt_tokens":2,"completion_tokens":1}}\n',
                    b"data: [DONE]\n",
                ]
            )

    calls = 0

    def flaky_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "rate limited",
                {},
                io.BytesIO(b'{"error":"rate limited"}'),
            )
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", flaky_urlopen)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello",
        {
            "retry": {
                "max_attempts": 2,
                "initial_delay_seconds": 0,
                "jitter": False,
            }
        },
    )

    assert sample["ok"] is True
    assert sample["response"] == "ok"
    assert sample["attempts"] == 2
    assert sample["retry_count"] == 1
    assert sample["retry_reasons"] == ["rate_limit"]


def test_client_retries_rate_limit_once_by_default(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )

    calls = 0

    def flaky_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "rate limited",
                {},
                io.BytesIO(b'{"error":"rate limited"}'),
            )
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", flaky_urlopen)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {}
    )

    assert calls == 2
    assert sample["ok"] is True
    assert sample["retry_reasons"] == ["rate_limit"]


def test_client_does_not_retry_non_retryable_http_error(monkeypatch):
    calls = 0

    def bad_request(request, timeout):
        nonlocal calls
        calls += 1
        raise urllib.error.HTTPError(
            request.full_url,
            400,
            "bad request",
            {},
            io.BytesIO(b'{"error":"unsupported parameter"}'),
        )

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", bad_request)

    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"retry": {"max_attempts": 3, "initial_delay_seconds": 0}}
    )

    assert calls == 1
    assert sample["ok"] is False
    assert sample["attempts"] == 1
    assert sample["retry_count"] == 0
    assert sample["failure_category"] == "unsupported_parameter"


def test_client_rejects_an_oversized_streaming_response(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter([b"data: " + b"x" * MAX_RESPONSE_BYTES])

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout: FakeResponse()
    )

    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"retry": {"max_attempts": 1}}
    )

    assert sample["ok"] is False
    assert "8 MiB safety limit" in sample["error"]


def test_retry_delay_adds_bounded_jitter(monkeypatch):
    monkeypatch.setattr("llm_preflight.client.random.uniform", lambda low, high: 0.125)

    delay = _retry_delay(
        {
            "initial_delay_seconds": 0.5,
            "max_delay_seconds": 1,
            "backoff_multiplier": 2,
            "jitter_seconds": 0.2,
        },
        1,
    )

    assert delay == 0.625


def test_openai_compatible_provider_options_are_not_sent_as_a_bogus_field():
    client = create_client(
        {
            "provider": "openai_compatible",
            "model": "local",
            "base_url": "https://example.test/v1",
        },
        10,
    )

    body = client.body(
        "hello", {"provider_options": {"openai_compatible": {"seed": 7}}}
    )

    assert body["seed"] == 7
    assert "openai_compatible" not in body


def test_gemini_honors_explicit_temperature_capability_override():
    client = create_client(
        {"provider": "gemini", "model": "gemini-test", "supports_temperature": False},
        10,
    )

    assert (
        "temperature"
        not in client.body("hello", {"temperature": 0.2})["generationConfig"]
    )


def test_statusless_malformed_stream_is_not_retried(monkeypatch):
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter([b"data: not-json\n"])

    def bad_stream(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", bad_stream)
    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"retry": {"max_attempts": 3, "initial_delay_seconds": 0}}
    )

    assert calls == 1
    assert sample["failure_category"] == "provider_error"


def test_openai_responses_honors_retry_configuration(monkeypatch):
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, *_args):
            return b'{"output_text":"ok","usage":{}}'

    def flaky(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                request.full_url, 429, "rate", {}, io.BytesIO(b"rate limited")
            )
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", flaky)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    sample = create_client(
        {"provider": "openai", "model": "model-a", "adapter": "openai_responses"}, 10
    ).run("hello", {"retry": {"max_attempts": 2, "initial_delay_seconds": 0}})

    assert calls == 2
    assert sample["retry_reasons"] == ["rate_limit"]


def test_success_latency_excludes_previous_retry_and_backoff(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter(
                [
                    b'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
                    b"data: [DONE]\n",
                ]
            )

    calls = 0

    def flaky(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise urllib.error.HTTPError(
                request.full_url, 429, "rate", {}, io.BytesIO()
            )
        return FakeResponse()

    timestamps = iter([0.0, 1.0, 10.0, 12.0, 15.0])
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", flaky)
    monkeypatch.setattr(
        "llm_preflight.client.time.perf_counter", lambda: next(timestamps)
    )
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"retry": {"max_attempts": 2, "initial_delay_seconds": 1}}
    )

    assert sample["latency_seconds"] == 5.0
    assert sample["ttft_seconds"] == 2.0


def test_transient_socket_errors_are_retried_by_exception_type(monkeypatch):
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def __iter__(self):
            return iter([b'data: {"choices":[{"delta":{"content":"ok"}}]}\n'])

    def flaky(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionRefusedError("Connection refused")
        return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("urllib.request.urlopen", flaky)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    sample = create_client({"provider": "openai", "model": "model-a"}, 10).run(
        "hello", {"retry": {"max_attempts": 2, "initial_delay_seconds": 0}}
    )

    assert calls == 2
    assert sample["retry_reasons"] == ["network"]
